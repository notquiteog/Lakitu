"""The game profile: the one place that says which game a build is for, and which addresses, offsets and keys are
that game's rather than the engine's.

The lifter, the Horizon runtime and the Vulkan back end are general; a handful of things are not, and before this file
they were written as literals wherever they were needed: patch modules for one build of one game, offsets into one
game's graphics module, the return addresses the runtime recognised that game's calls by, one game's shader program
keys, and the one build make_game.py accepted. This is the seam the engine's forks for other games (Lakitu: Mario Kart
World, Dragoon: Kirby Air Riders) built and converged on, so that a second game is a profile and its own patch modules,
not an edit to the engine (docs/one-engine.md):

  - the game is chosen by the build id of the dump's main (for_build), as host/hos_main.c's hos_game_is_mkw() always
    did; HOOKSHOT_GAME=<key> only overrides it, and a build no profile knows gets NONE, which patches nothing;
  - the return addresses the runtime recognises are the profile's (Hooks), and are recognised only in the build the
    profile is for (host/hos_main.c hos_game_profile_live);
  - the renderer is built once for every game, so it is handed the game's program keys at run time (HOOKSHOT_PROFILE_*);
  - every profile's patch modules are roots of the lift's cache key (nx2/make_game.py lift_sources), and load_module is
    the one place they are imported by name.

What belongs here: the game's identity (program id, version, main's build id) as nx2/dump.py reports it; the base of
its main in the lifted image; which lift patch modules and which code patch module apply; the offsets into its
graphics module the frame pacing reads; the return addresses the runtime recognises; the shader program keys the
renderer treats specially; its default player count. What does not: anything true of every Switch 2 title, and the C
text a patch writes, which lives with the patch.

An unknown value is None, never a plausible-looking number. None switches its feature off: the runtime never captures
a graphics module it has no return address for and skips a pacing field it has no offset for, saying so once; a game
with no patch modules is lifted without patches. A wrong address, by contrast, is silent corruption in someone's game.
Every lift patch module also checks the instruction word at each of its sites and leaves a site out when it differs,
so a profile aimed at the wrong build turns its patches off rather than writing C after the wrong instruction.

Which profile: HOOKSHOT_GAME=<key> if set; else the profile whose build id the dump's main has (for_build); else, with
no build id to go by (a build or a check without a dump), DEFAULT. A dump whose build no profile knows gets NONE, which
patches nothing and hooks nothing: lifting an unknown game must not apply Ocarina's patches to it.

    python -I nx2/game_profile.py                       # what the profiles hold
    python -I nx2/game_profile.py --emit-header         # rewrite game/game_profile.h (DEFAULT's) from this file
    python -I nx2/game_profile.py --check-header        # the committed header still matches (tests/test_game_profile.py)
    python -I nx2/game_profile.py --emit-header --game oot --out <dir>   # one game's header, as a lift writes it
"""
import argparse
import collections
import importlib
import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = os.path.join(HERE, "..", "game", "game_profile.h")

# The project's own name, which is not game data: it names the release files (scripts/product_name.sh). A fork's
# rename is this one line.
PROJECT = "Lakitu"

# The offsets into the game's graphics module that host/nn_vi.c reads.
Gfx = collections.namedtuple("Gfx", "frame_limiter nominal_fps vrr_mode vrr_gate controller controller_words "
                                    "controller_rate_words")
EMPTY_GFX = Gfx(frame_limiter=None, nominal_fps=None, vrr_mode=None, vrr_gate=None, controller=None,
                controller_words=(), controller_rate_words=())

# The shader program keys the renderer treats specially. A key is the 64-bit hash of a program's
# SASS, so it is per game and per build; the renderer takes prefixes, as its RX_VK_* overrides do.
#   taau:         programs the compute stand-in replaces (gpu/vk/vk_draw.cpp taau_key, RX_VK_TAAU_KEYS)
#   gameplay:     networks treated as the game's own upscale, never dropped when the movie networks are slow
#   network_keep: cooperative-matrix programs kept on cards that run them in software (gpu/vk/vk_shader.cpp)
Upscale = collections.namedtuple("Upscale", "taau gameplay network_keep")
EMPTY_UPSCALE = Upscale(taau=(), gameplay=(), network_keep=())

# Return addresses the runtime recognises a call of the game's by. Each is the address after a bl in the
# game's main, so it is one build's and nothing else's: on another game the same number is some unrelated call.
#   gfx_clock:      after the graphics module's frame-end GetSystemTick; x19 there is the module (host/hos_thread.c).
#                   Without it no module is captured and nn_vi.c's real-time step and frame-limiter work stay off.
#   present_poll:   after the SleepThread of the present's GPU-event poll (HOS_PRESENT_POLL, HOS_SLEEP_LOG, and the
#                   frame-time breakdown's poll share: host/hos_thread.c)
#   present_events: the nvnEventGetValue calls of that poll (HOS_PRESENT_NOWAIT: host/nvn_native.c)
Hooks = collections.namedtuple("Hooks", "gfx_clock present_poll present_events")
EMPTY_HOOKS = Hooks(gfx_clock=None, present_poll=None, present_events=())


class Profile(object):
    """One game. Everything optional is None or empty when the profile does not know it yet."""

    def __init__(self, key, game, program_id=None, version=None, build_id=None, main_base=None,
                 patch_modules=(), code_patch_module=None, gfx=EMPTY_GFX, upscale=EMPTY_UPSCALE, hooks=EMPTY_HOOKS,
                 npad_players=1, account_users=1, notes=""):
        self.key = key                                # HOOKSHOT_GAME=<this>
        self.game = game                              # the game's name, for logs
        self.program_id = program_id                  # as nx2/dump.py reports it
        self.version = version                        # the update's version number (the .nup title's)
        self.build_id = build_id                      # main's whole build id: for_build() and make_game.py's gate
        self.main_base = main_base                    # main's base in the lifted image
        self.patch_modules = tuple(patch_modules)     # nx2 modules with install(lifter, img[, build_id]), in order
        self.code_patch_module = code_patch_module    # the nx2 module whose patches chunks.edit_c applies to the C
        self.gfx = gfx
        self.upscale = upscale
        self.hooks = hooks
        # 1..8, or "auto": one per attached controller. The default player count for the forks' multi-player input
        # (Dragoon's HOS_NPAD_PLAYERS); nothing in this engine reads it yet, Ocarina's one pad being the only input here
        self.npad_players = npad_players
        self.account_users = account_users            # the console's users (nn::account), 1..8
        self.notes = notes

    def __repr__(self):
        return "<Profile %s: %s>" % (self.key, self.game)


OOT = Profile(
    key="oot",
    game="The Legend of Zelda: Ocarina of Time",
    program_id="0400486024DEC000",
    version=131072,                 # the update; base v65536
    build_id="e0f3ccfaf50065ae4ea01eb5aeb13b1a45da3348",
    main_base=0x80020000,           # after rtld's 0x20000 bytes in Eden's layout (nx2/image.py)
    # (the order lift.py has always installed them in: two modules may add C at one site, in this order)
    patch_modules=("oot_wide", "oot_fov", "oot_jitter", "oot_occlusion"),
    code_patch_module="oot_patches",
    gfx=Gfx(
        frame_limiter=0xfc,         # int: the rate f_8042cd20 sleeps to
        nominal_fps=0x2c8,          # int: the nominal rate the engine steps game time by (60 / it)
        vrr_mode=0x231,             # byte: logged beside the gate; 1 in every run seen
        vrr_gate=0x232,             # byte: f_804fc0f0 stores a rate into +0xfc only while this is set
        controller=0x270,           # the adaptive controller's object; the words below are offsets inside it
        controller_words=(0x58, 0x28, 0x2c, 0x30),       # what HOS_FPS_LOG prints: all four read 60 at 60 fps
        controller_rate_words=(0x58, 0x28, 0x2c),        # what HOS_FPS_FORCE raises (not +0x30, not nominal_fps)
    ),
    upscale=Upscale(
        taau=("fd029a317a9a4b94",),
        gameplay=(0xfd029a317a9a4b94, 0x9dc98871eb7fc101),
        # (9dc98871 resolves the dynamic-resolution scene to 2048x1152; left out, the 3D picture is black under the HUD)
        network_keep=("fd029a317a9a4b94", "9dc98871eb7fc101"),
    ),
    hooks=Hooks(
        gfx_clock=0x8348c770,       # main+0x346c770: after the bl of the graphics module's frame-end GetSystemTick
        present_poll=0x80590520,    # the SleepThread in 0x80590500's `while (nvnEventGetValue(e) != 1)` loop
        present_events=(0x805904a0, 0x80590530),
    ),
    npad_players=1,                 # Ocarina reads Npad No.1 alone, with every device merged into it
    account_users=1,                # one user, "Player": the one there always was
    notes="The game this engine was retargeted to; every value here was measured on its dump.",
)

# (Lakitu) Mario Kart World 1.0.0. Only what was measured on the dump is filled in; everything else is None or empty, so
# the code it would guard stays off (a wrong address is a crash or silent corruption, a None is a feature left off).
#   program_id / version / build_id: `nx2/make_game.py --check` on the 1.0.0 dump (title 0400c3f00006e000 v0, main
#       9e244438...); the same build id and RomFS count (205,660 files) are mkw-recomp's 1.0.0 row
#       (adriadam10/mkw-recomp@5ff4fbb, recomp/versions.py, MIT, Copyright (c) 2026 Adria). 1.8.0 (main d00e4f39...) is
#       another executable with other addresses, and not this profile's.
#   main_base: the lift's "image:" line, main@0x80020000 (rtld's 0x20000 bytes first in Eden's layout, as Ocarina's).
#   patch_modules / code_patch_module: none yet. Ocarina's are tables of its own addresses; a Mario Kart World
#       widescreen, lens or jitter patch is a new module, found the same way.
#   gfx / hooks: unknown. The graphics module's offsets and the frame-end, present-poll return addresses are found
#       by reading this build's code as they were for Ocarina; until then the runtime's pacing work stays off.
#   upscale: program keys come from a run (RX_VK_SHADER_CENSUS / nx2/shader_census.py); none named, none special.
MKW = Profile(
    key="mkw",
    game="Mario Kart World",
    program_id="0400C3F00006E000",
    version=0,                      # the base game, as the dump's title reports it: 1.0.0
    build_id="9e244438c3d8ef1c703a6a85ef99c4f000000000",   # (main's build id, as the lift reads it)
    main_base=0x80020000,
    npad_players=1,
    account_users=1,
    notes="Identity and main's base, checked against a 1.0.0 dump; no other address, offset or key measured yet.",
)

# The profile for a dump whose build no profile knows: nothing patched, nothing hooked, one player.
NONE = Profile(key="none", game="an unknown game",
               notes="No profile knows this build: lifted without patches, and the runtime recognises nothing in it.")

GAMES = collections.OrderedDict((p.key, p) for p in (OOT, MKW, NONE))

# Ocarina stays the default where there is no dump to go by (the committed header, the game-free checks), because it
# is the only game whose values have been measured and checked by running it.
DEFAULT = "oot"


def for_build(build_id):
    """The profile whose build id is main's (a prefix of 8 or more hex digits matches, as the docs quote them), or
    NONE when no profile knows that build."""
    bid = (build_id or "").strip().lower()
    if len(bid) >= 8:
        for p in GAMES.values():
            if p.build_id and (p.build_id.startswith(bid) or bid.startswith(p.build_id)):
                return p
    return NONE


def active(env=None, build_id=None):
    """The profile this lift or build is for: HOOKSHOT_GAME, else the one for main's build id, else DEFAULT."""
    env = os.environ if env is None else env
    key = (env.get("HOOKSHOT_GAME") or "").strip().lower()
    if key:
        if key not in GAMES:
            raise SystemExit("HOOKSHOT_GAME=%s: no such game profile (have %s)" % (key, ", ".join(GAMES)))
        return GAMES[key]
    if build_id:
        return for_build(build_id)
    return GAMES[DEFAULT]


def known_builds():
    """The build ids make_game.py accepts, as (profile, the 8-digit prefix the messages quote)"""
    return [(p, p.build_id[:8]) for p in GAMES.values() if p.build_id]


# ---- the lift ----

def load_module(name):
    """A game's patch module by the name its profile holds. This is the one place the lift imports a module by a name made
    at run time; nx2/make_game.py lift_sources takes every profile's modules into the lift's cache key, because its walk
    of import statements cannot see these (tests/test_lift_cache.py)."""
    return importlib.import_module(name)


def install_patches(lifter, img, profile, build_id="", log=print):
    """The profile's lift patch modules, in its order; lift.py names no game's module itself. A module's install
    takes (lifter, img), or (lifter, img, build_id) when it gates on the build as nx2/oot_fov.py does."""
    if not profile.patch_modules:
        log("patches: the %s profile has no lift patch modules" % profile.key)
        return 0
    total = 0
    for name in profile.patch_modules:
        install = load_module(name).install
        n = len(inspect.signature(install).parameters)
        total += (install(lifter, img, build_id) if n >= 3 else install(lifter, img)) or 0
    return total


# ---- the C view ----
#
# host/ and gpu/ cannot import Python, so a profile is emitted as game_profile.h. DEFAULT's is committed in game/, so a
# build or a check with no dump needs no generation step (tests/test_game_profile.py fails when it drifts). A lift of a
# dump writes its own profile's header beside the lifted C (<work>/sa/game/game_profile.h), and nx2/build.py puts that
# folder ahead of game/, so the runtime and the renderer are compiled for the game they will run.

def _keys(prefixes):
    return ",".join(prefixes)


def _init(fmt, values):
    """A C array initializer. Empty is one zero, because `{ }` is not C and the count beside it is 0."""
    return "{ %s }" % (", ".join(fmt % v for v in values) if values else "0")


def saves_dir(profile):
    """The saves' folder name under $XDG_DATA_HOME on Linux: Ocarina's "hookshot", where its players' saves have always
    been; any other game's "hookshot-<key>". The save folder holds save/<user id>/ with the game's own files in it and
    nothing that says which game wrote them, so two games sharing one would read, and overwrite, each other's
    (DK Bananza fork, 4f417fd7)."""
    return "hookshot" if profile.key == "oot" else "hookshot-" + profile.key


def emit_header(profile=None):
    p = GAMES[DEFAULT] if profile is None else profile
    out = []
    w = out.append
    w("/* The game profile, as C. GENERATED by nx2/game_profile.py --emit-header: do not edit.")
    w(" *")
    w(" * Edit nx2/game_profile.py and run `python -I nx2/game_profile.py --emit-header`. The committed copy is")
    w(" * checked against that file by tests/test_game_profile.py, so an edit here fails the suite. A lift writes the")
    w(" * dump's own profile beside its C, and the build reads that one first.")
    w(" *")
    w(" * A GAME_HAVE_<x> of 0 means this profile does not know that value. The code it guards must then leave the")
    w(" * thing alone rather than guess: an unknown offset is a feature that is off, not a number to invent. */")
    w("#ifndef GAME_PROFILE_H")
    w("#define GAME_PROFILE_H")
    w("")
    w("/* the project, which is not game data. GAME_PROJECT_W is the same name for the Win32 wide-string calls. */")
    w('#define GAME_PROJECT "%s"' % PROJECT)
    w('#define GAME_PROJECT_W L"%s"' % PROJECT)
    w("")
    w('#define GAME_PROFILE_KEY "%s"' % p.key)
    w('#define GAME_NAME "%s"' % p.game)
    w('#define GAME_PROGRAM_ID "%s"' % (p.program_id or ""))
    w("#define GAME_HAVE_PROGRAM_ID %d" % (1 if p.program_id else 0))
    w("#define GAME_VERSION %d" % (p.version or 0))
    w("#define GAME_HAVE_VERSION %d" % (1 if p.version else 0))
    w("/* main's build id: the runtime checks the image it runs against it before it recognises any address */")
    w('#define GAME_BUILD_ID "%s"' % (p.build_id or ""))
    w("#define GAME_HAVE_BUILD_ID %d" % (1 if p.build_id else 0))
    w("")
    w("/* main's base in the lifted image */")
    w("#define GAME_MAIN_BASE 0x%xull" % (p.main_base or 0))
    w("#define GAME_HAVE_MAIN_BASE %d" % (1 if p.main_base is not None else 0))
    w("")
    w("/* offsets into the game's graphics module (host/nn_vi.c's hos_gfx_module) */")
    for name, value in (("FRAME_LIMITER", p.gfx.frame_limiter), ("NOMINAL_FPS", p.gfx.nominal_fps),
                        ("VRR_MODE", p.gfx.vrr_mode), ("VRR_GATE", p.gfx.vrr_gate),
                        ("CONTROLLER", p.gfx.controller)):
        w("#define GAME_GFX_%s 0x%x" % (name, value or 0))
        w("#define GAME_GFX_HAVE_%s %d" % (name, 1 if value is not None else 0))
    w("#define GAME_GFX_CONTROLLER_WORDS %s" % _init("0x%x", p.gfx.controller_words))
    w("#define GAME_GFX_CONTROLLER_WORD_COUNT %d" % len(p.gfx.controller_words))
    w("#define GAME_GFX_CONTROLLER_RATE_WORDS %s" % _init("0x%x", p.gfx.controller_rate_words))
    w("#define GAME_GFX_CONTROLLER_RATE_WORD_COUNT %d" % len(p.gfx.controller_rate_words))
    w("")
    w("/* return addresses the runtime recognises the game's calls by (host/hos_thread.c, host/nvn_native.c) */")
    w("#define GAME_LR_GFX_CLOCK 0x%xull" % (p.hooks.gfx_clock or 0))
    w("#define GAME_HAVE_LR_GFX_CLOCK %d" % (1 if p.hooks.gfx_clock is not None else 0))
    w("#define GAME_LR_PRESENT_POLL 0x%xull" % (p.hooks.present_poll or 0))
    w("#define GAME_HAVE_LR_PRESENT_POLL %d" % (1 if p.hooks.present_poll is not None else 0))
    w("#define GAME_LR_PRESENT_EVENTS %s" % _init("0x%xull", p.hooks.present_events))
    w("#define GAME_LR_PRESENT_EVENT_COUNT %d" % len(p.hooks.present_events))
    w("")
    w("/* shader program keys this game's renderer treats specially; empty: none of them */")
    w('#define GAME_UPSCALE_TAAU_KEYS "%s"' % _keys(p.upscale.taau))
    w('#define GAME_NETWORK_KEEP_KEYS "%s"' % _keys(p.upscale.network_keep))
    w("#define GAME_GAMEPLAY_NETWORK_KEYS %s" % _init("0x%016xull", p.upscale.gameplay))
    w("#define GAME_GAMEPLAY_NETWORK_KEY_COUNT %d" % len(p.upscale.gameplay))
    w("")
    w("/* Npads served when HOS_NPAD_PLAYERS is unset: a count, or -1 for one per attached controller */")
    w("#define GAME_NPAD_PLAYERS %d" % (-1 if p.npad_players == "auto" else int(p.npad_players)))
    w("")
    w("/* the saves' folder on Linux, under $XDG_DATA_HOME (host/hos_main.c saves_dir): Ocarina's stays where its")
    w("   players' saves are, every other game has its own, so no two games ever write one save folder */")
    w('#define GAME_SAVES_DIR "%s"' % saves_dir(p))
    w("")
    w("/* the console's users (nn::account) when HOS_ACCOUNT_USERS is unset: host/nn_applet.c */")
    w("#define GAME_ACCOUNT_USERS %d" % int(p.account_users))
    w("")
    w("#endif /* GAME_PROFILE_H */")
    return "\n".join(out) + "\n"


def write_header(folder, profile):
    """The profile's header into folder/game_profile.h (a lift's <work>/sa/game), only when it changes, so a build
    after an unchanged lift does not rebuild the runtime for nothing. Returns the path."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "game_profile.h")
    text = emit_header(profile)
    try:
        with open(path, encoding="utf-8", newline="") as f:
            if f.read() == text:
                return path
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def header_path():
    return os.path.normpath(HEADER)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--emit-header", action="store_true", help="write game_profile.h (game/'s, or --out's)")
    p.add_argument("--check-header", action="store_true", help="exit 1 when the committed header does not match")
    p.add_argument("--game", help="a profile key (default: %s for the committed header)" % DEFAULT)
    p.add_argument("--build-id", help="choose the profile by main's build id, as a lift does")
    p.add_argument("--out", help="with --emit-header: the folder to write into instead of game/")
    a = p.parse_args(argv)
    if a.game:
        if a.game not in GAMES:
            p.error("no profile %r (have %s)" % (a.game, ", ".join(GAMES)))
        profile = GAMES[a.game]
    elif a.build_id:
        profile = for_build(a.build_id)
    else:
        profile = GAMES[DEFAULT]
    if a.check_header:
        text = emit_header(GAMES[DEFAULT])
        with open(header_path(), encoding="utf-8", newline="") as f:
            have = f.read()
        if have != text:
            print("%s is not what nx2/game_profile.py emits: run python -I nx2/game_profile.py --emit-header"
                  % header_path())
            return 1
        print("%s matches nx2/game_profile.py" % header_path())
        return 0
    if a.emit_header:
        if a.out:
            print("wrote %s for the %s profile" % (write_header(a.out, profile), profile.key))
            return 0
        if profile.key != DEFAULT:
            p.error("game/game_profile.h is %s's; write another game's with --out <folder>" % DEFAULT)
        with open(header_path(), "w", encoding="utf-8", newline="\n") as f:
            f.write(emit_header(profile))
        print("wrote %s for the %s profile" % (header_path(), profile.key))
        return 0
    for key, prof in GAMES.items():
        print("%s%s: %s" % ("* " if prof is profile else "  ", key, prof.game))
        print("    program %s, version %s, build %s" % (prof.program_id, prof.version, prof.build_id))
        print("    main base %s" % ("%#x" % prof.main_base if prof.main_base is not None else None))
        print("    lift patches %s, code patches %s" % (prof.patch_modules or None, prof.code_patch_module))
        print("    graphics module %s" % (prof.gfx,))
        print("    hooks %s" % (prof.hooks,))
        print("    upscale keys %s" % (prof.upscale,))
        print("    npad players %s, users %s" % (prof.npad_players, prof.account_users))
        print("    %s" % prof.notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
