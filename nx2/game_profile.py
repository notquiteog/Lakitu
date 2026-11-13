"""The game profile: the one place that says which game a build is for, and which addresses, offsets and keys are
that game's rather than the engine's.

This repository is a static recompiler with a game-shaped hole in it. The lifter, the Horizon runtime and the Vulkan
back end are general; a handful of things are not, and before this file they were written as literals wherever they
were needed: patch sites at fixed addresses of one build of one game, offsets into one game's graphics module, and
one game's shader program keys. Retargeting meant finding them all, which is exactly the work this file exists to
stop repeating.

What belongs here
  - the game's identity (program id, version, build id) as the dump reports it;
  - the base address of its `main` module in the lifted image, which every patch offset is relative to;
  - which lift patch modules apply to it, by profile rather than by `import` in lift.py;
  - the offsets into its graphics module that the runtime's frame pacing reads;
  - the shader program keys the renderer treats specially.

What does not belong here: anything that is true of every Switch 2 title (the process code base 0x80000000, the NVN2
procs, the SASS translator), and the C text a patch writes, which lives with the patch.

An unknown value is None, never a plausible-looking number. A None switches its feature off: the runtime skips a
pacing field it has no offset for and says so once, and a game with no patch modules is lifted without patches. A
wrong address, by contrast, is a crash or silent corruption in someone's game, so a guess is worse than nothing.

Every patch site still carries the instruction word the game has at it, and install_sites() below refuses to patch a
site whose word differs: that check is what makes a profile safe to be wrong about. It is the reason a site is given
as (offset, word, C) and not as (offset, C).

Which profile a build uses: HOOKSHOT_GAME=<key>, default "oot".

    python -I nx2/game_profile.py                 # what the profiles hold
    python -I nx2/game_profile.py --emit-header   # rewrite game/game_profile.h from this file
    python -I nx2/game_profile.py --check-header  # the committed header still matches (tests/test_game_profile.py)
"""
import argparse
import collections
import importlib
import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = os.path.join(HERE, "..", "game", "game_profile.h")

# The project's own name, which is not game data: it names the window, the AppImage and the builder. One constant so
# that renaming the project is a one-line change rather than a sweep through the tree.
PROJECT = "Lakitu"

# The offsets into the game's graphics module that host/nn_vi.c reads. They are offsets into one game's engine object,
# found by reading that game's code; nothing about them generalizes, so a profile that does not know one says None and
# the runtime leaves that field alone.
Gfx = collections.namedtuple("Gfx", "frame_limiter nominal_fps vrr_mode vrr_gate controller controller_words "
                                    "controller_rate_words")
EMPTY_GFX = Gfx(frame_limiter=None, nominal_fps=None, vrr_mode=None, vrr_gate=None, controller=None,
                controller_words=(), controller_rate_words=())

# The shader program keys the renderer treats specially. A key is the 64-bit hash of a program's SASS, so it is
# per-game and per-build; the renderer takes prefixes, as its RX_VK_* overrides do.
#   taau:         programs the compute stand-in replaces (gpu/vk/vk_draw.cpp taau_key)
#   gameplay:     networks that are never dropped when the movie networks turn out slow (gameplay_network)
#   network_keep: cooperative-matrix programs kept on cards that run them in software (gpu/vk/vk_shader.cpp)
#   trace:        programs an upscaler backend may be handed (upscale_trace_key)
Upscale = collections.namedtuple("Upscale", "taau gameplay network_keep trace")
EMPTY_UPSCALE = Upscale(taau=(), gameplay=(), network_keep=(), trace=())


class Profile(object):
    """One game. Everything optional is None or empty when the profile does not know it yet."""

    def __init__(self, key, game, program_id=None, version=None, build_id=None, main_base=None,
                 patch_modules=(), code_patch_module=None, gfx=EMPTY_GFX, upscale=EMPTY_UPSCALE, notes=""):
        self.key = key                                # HOOKSHOT_GAME=<this>
        self.game = game                              # the game's name, for logs and the window
        self.program_id = program_id                  # as nx2/dump.py --set reports it
        self.version = version
        self.build_id = build_id                      # main's build id, the prefix the docs quote
        self.main_base = main_base                    # main's base in the lifted image; patch offsets are from it
        self.patch_modules = tuple(patch_modules)     # nx2 modules with install(lifter, img), in order
        self.code_patch_module = code_patch_module    # an nx2 module with apply(gen), run after the C is written
        self.gfx = gfx
        self.upscale = upscale
        self.notes = notes

    def __repr__(self):
        return "<Profile %s: %s>" % (self.key, self.game)


OOT = Profile(
    key="oot",
    game="The Legend of Zelda: Ocarina of Time",
    program_id="0400486024DEC000",
    version=131072,                 # the update; base v65536
    build_id="e0f3ccfaf50065ae4ea01eb5aeb13b1a45da3348",
    # main sits after rtld in Eden's layout (nx2/image.py), which for this dump's rtld is 0x20000 bytes.
    main_base=0x80020000,
    patch_modules=("oot_wide", "oot_fov", "oot_jitter", "oot_occlusion"),
    code_patch_module="oot_patches",
    gfx=Gfx(
        frame_limiter=0xfc,         # int: the rate f_8042cd20 sleeps to
        nominal_fps=0x2c8,          # int: the nominal rate the engine steps game time by (60 / it)
        vrr_mode=0x231,             # byte: logged beside the gate; 1 in every run seen
        vrr_gate=0x232,             # byte: f_804fc0f0 stores a rate into +0xfc only while this is set
        controller=0x270,           # the adaptive controller's object, the words below are offsets inside it
        # the words HOS_FPS_LOG prints, which is how they were identified: all four read 60 in a 60 fps run
        controller_words=(0x58, 0x28, 0x2c, 0x30),
        # the ones HOS_FPS_FORCE raises. Not +0x30, and not the nominal rate above: the experiment that raised
        # those changed game speed as well (host/nn_vi.c says why), so the profile keeps the two lists apart.
        controller_rate_words=(0x58, 0x28, 0x2c),
    ),
    upscale=Upscale(
        taau=("fd029a317a9a4b94",),
        gameplay=(0xfd029a317a9a4b94, 0x9dc98871eb7fc101),
        network_keep=("fd029a317a9a4b94", "9dc98871eb7fc101"),
        trace=("fd029a317a9a4b94",),
    ),
    notes="The game this engine was retargeted to; every value here was measured on the dump.",
)

MKW = Profile(
    key="mkw",
    game="Mario Kart World",
    # Everything below is None or empty on purpose. There is no Mario Kart World dump on the machine this profile was
    # written on, so nothing here could be measured, and a number that looks right is worse than no number: the
    # lifter would write C after an instruction that is not the one the patch was written for, and the runtime would
    # read a pacing field out of the middle of some other object. Each comment says what the value is and how it
    # would be found.
    #
    #   program_id / version / build_id: `python -I nx2/dump.py --dump <exefs+romfs> --set` prints all three, and
    #       prints them again on every lift, so the profile can be filled in from the first run against the dump.
    program_id=None,
    version=None,
    build_id=None,
    #   main_base: main's base in the lifted image. Eden's layout (nx2/image.py) puts rtld first, so this is
    #       0x80000000 + rtld's page-aligned image size, which is this dump's rtld, not Ocarina's. lift.py prints it
    #       on the "image:" line as main@<base>+<size>; install_sites() below also reads it off the image and warns
    #       when the profile disagrees, so it can be checked rather than trusted.
    main_base=None,
    #   patch_modules: none yet. Each of Ocarina's (nx2/oot_wide.py, nx2/oot_fov.py, nx2/oot_jitter.py,
    #       nx2/oot_occlusion.py) is a table of addresses in Ocarina's main, so none of them can be reused; a Mario
    #       Kart World widescreen, lens or jitter patch is a new module, found the same way theirs were (the
    #       instruction that loads the picture size, the projection update, the view's projection load, the
    #       occlusion-query flag) and named here once it exists.
    patch_modules=(),
    #   code_patch_module: the equivalent of nx2/oot_patches.py, which rewrites named lifted functions
    #       (f_80b1e140 and friends). Those names are Ocarina's addresses; a Mario Kart World module would be new.
    code_patch_module=None,
    #   gfx: offsets into the graphics module (host/nn_vi.c's hos_gfx_module). Ocarina's were found by reading the
    #       function that sleeps to the frame limiter and the one that writes it. The same search in Mario Kart
    #       World's main gives this game's. Until then the frame limiter is left alone and game time steps whole
    #       frames, which is how the game ships.
    #
    #       Note that Mario Kart World already has a frame pacer the runtime knows (host/nn_vi.c hos_mkw_pacer,
    #       inherited from mkw-recomp), reached through nvn_native.c rather than through these offsets. It is not
    #       the same mechanism and does not fill these in.
    gfx=EMPTY_GFX,
    #   upscale: program keys. These are hashes of this game's own shader programs, so they can only come from a run:
    #       RX_VK_SHADER_CENSUS / nx2/shader_census.py list the programs a boot compiles, and a cooperative-matrix
    #       program that resolves the scene is the candidate. With none named, the renderer treats no program
    #       specially: no stand-in, nothing handed to an upscaler backend, and cooperative-matrix programs are left
    #       out on cards that would run them in software, which is the existing behaviour for an unlisted key.
    upscale=EMPTY_UPSCALE,
    notes="Scaffolding only: nothing here has been measured, because there is no dump to measure it on.",
)

GAMES = collections.OrderedDict((p.key, p) for p in (OOT, MKW))

# Ocarina stays the default because it is the only game that can be lifted today: its dump, its addresses and its
# measurements are the ones that exist, and a build that quietly switched to an empty profile would lose widescreen,
# the camera publish and the real-time frame step without saying so. HOOKSHOT_GAME=mkw selects the other one.
DEFAULT = "oot"


def active(env=None):
    """The profile this build is for: HOOKSHOT_GAME, or DEFAULT."""
    env = os.environ if env is None else env
    key = (env.get("HOOKSHOT_GAME") or DEFAULT).strip().lower()
    if key not in GAMES:
        raise SystemExit("HOOKSHOT_GAME=%s: no such game profile (have %s)" % (key, ", ".join(GAMES)))
    return GAMES[key]


# ---- patch sites ----

def module_base(img, name="main"):
    """The base the image actually loaded a module at, or None when the image does not say."""
    for m in getattr(img, "modules", ()):
        if getattr(m, "name", None) == name:
            return getattr(m, "base", None)
    return None


def site_word(img, pc):
    """The instruction word at pc, or None when the address is not in the image."""
    try:
        return img.word(pc)
    except Exception:
        return None


def site_words(word):
    """A site's expected instruction words: one word, or a tuple of consecutive ones the site needs together."""
    return tuple(word) if isinstance(word, (tuple, list)) else (word,)


def install_sites(lifter, img, profile, sites, what, log=print):
    """Install each site's C after the game's instruction at it, and return how many went in.

    sites is ((offset from main, the instruction word expected there, the C to add), ...), or a function of main's
    base returning that, for a patch whose C text holds absolute addresses of its own. The word may be a tuple of the
    consecutive words the site needs (a patch that relies on the two instructions after its own as well, as
    nx2/oot_fov.py's does); every one of them is checked, and the C goes after the first. A site whose word is not
    the expected one is logged and left out: that is the whole safety story of a game profile, because it is what
    turns "this profile is for another build" from a corrupted game into a feature that is off. A profile with no
    main base patches nothing at all, for the same reason.

    The C is appended where a site already has some, so two patch modules can share a site, in the order the profile
    lists them.
    """
    base = profile.main_base
    if base is None:
        log("%s: the %s profile has no main base: nothing patched" % (what, profile.key))
        return 0
    sites = sites(base) if callable(sites) else sites
    loaded = module_base(img, "main")
    if loaded is not None and loaded != base:
        # Not fatal: the word check below is what actually protects the patch, and this says which number to fix.
        log("%s: the %s profile's main base is %#x but the image loaded main at %#x"
            % (what, profile.key, base, loaded))
    n = 0
    for off, word, text in sites:
        pc = base + off
        wrong = None
        for i, want in enumerate(site_words(word)):
            have = site_word(img, pc + 4 * i)
            if have != want:
                wrong = (off + 4 * i, have, want)
                break
        if wrong:
            log("%s: main+%#x holds %s, not %08x: left out"
                % (what, wrong[0], "?" if wrong[1] is None else "%08x" % wrong[1], wrong[2]))
            continue
        lifter.after[pc] = (lifter.after[pc] + "\n" + text) if pc in lifter.after else text
        n += 1
    log("%s: %d of %d sites" % (what, n, len(sites)))
    return n


def load_module(name):
    """A game's patch module by the name its profile holds. This file is the one place the lift imports a module by a
    name made at run time; nx2/make_game.py lift_sources takes every profile's modules into the lift's cache key
    because its walk of import statements cannot see these (tests/test_lift_cache.py)."""
    return importlib.import_module(name)


def install_module(module, lifter, img, profile, build_id=None):
    """One patch module's install(lifter, img, ...), handed what its signature asks for: build_id (main's build id
    as the image holds it, for a module gated on one build, as nx2/oot_fov.py is) and profile."""
    params = inspect.signature(module.install).parameters
    kw = {}
    if "build_id" in params:
        kw["build_id"] = build_id or ""
    if "profile" in params:
        kw["profile"] = profile
    return module.install(lifter, img, **kw)


def install_patches(lifter, img, profile=None, build_id=None, log=print):
    """Install the active profile's lift patch modules, in the order the profile lists them.

    lift.py calls this instead of importing a game's modules by name, which is the point: adding a game is a profile
    entry and a new module, not an edit to the lift driver. build_id is main's build id as the image holds it
    (install_module hands it to the modules that ask for it).
    """
    profile = active() if profile is None else profile
    if not profile.patch_modules:
        log("patches: the %s profile has no lift patch modules" % profile.key)
        return 0
    return sum(install_module(load_module(name), lifter, img, profile, build_id)
               for name in profile.patch_modules)


def code_patches(profile=None, main_build=None, standalone=False):
    """(module name or None, supported): what nx2/chunks.py edit_c runs over the lifted C, after it has been written.

    main_build is the build id the image really holds, and standalone says whether this is the standalone lift.
    A code patch module may hold patches that apply only to the one build it was written against and are unsafe on
    any other (Ocarina's player-state and output-size edits, gated on nx2/oot_patches.py's LIFE_BUILD_ID). The module
    owns that constant; supported is true only when the image holds exactly that build in a standalone lift, so another
    build of the same game still gets the module's other patches and not those. A module without such a constant is
    never "supported" in that sense. A profile without a code patch module gets (None, False): edit_c then makes only
    the engine's own edits.
    """
    profile = active() if profile is None else profile
    if not profile.code_patch_module:
        return None, False
    module = load_module(profile.code_patch_module)
    gate = getattr(module, "LIFE_BUILD_ID", None)
    return profile.code_patch_module, bool(standalone and gate is not None and main_build == gate)


# ---- the C view of the profile ----
#
# host/ and gpu/ cannot import Python, so the profile is emitted as a header. It is generated and committed, so that
# a build needs no generation step and a diff shows what a profile change does to the C; tests/test_game_profile.py
# fails when the committed header no longer matches this file, so the two cannot drift.

def _keys(prefixes):
    """The renderer takes key prefixes as a comma-separated list; empty means it treats no program specially."""
    return ",".join(prefixes)


def _init(fmt, values):
    """A C array initializer. Empty is written as one zero, because `{ }` is not C and the count beside it is 0."""
    return "{ %s }" % (", ".join(fmt % v for v in values) if values else "0")


def emit_header(profile=None):
    p = active() if profile is None else profile
    out = []
    w = out.append
    w("/* The game profile, as C. GENERATED by nx2/game_profile.py --emit-header: do not edit.")
    w(" *")
    w(" * Edit nx2/game_profile.py and run `python -I nx2/game_profile.py --emit-header`. The committed copy is")
    w(" * checked against that file by tests/test_game_profile.py, so an edit here fails the suite.")
    w(" *")
    w(" * A GAME_HAVE_<x> of 0 means this profile does not know that value. The code it guards must then leave the")
    w(" * thing alone rather than guess: an unknown offset is a feature that is off, not a number to invent. */")
    w("#ifndef GAME_PROFILE_H")
    w("#define GAME_PROFILE_H")
    w("")
    w("/* the project, which is not game data: the window's name, the AppImage's and the builder's.")
    w(" * GAME_PROJECT_W is the same name for the Win32 wide-string calls (MessageBoxW and friends). */")
    w('#define GAME_PROJECT "%s"' % PROJECT)
    w('#define GAME_PROJECT_W L"%s"' % PROJECT)
    w("")
    w('#define GAME_PROFILE_KEY "%s"' % p.key)
    w('#define GAME_NAME "%s"' % p.game)
    w('#define GAME_PROGRAM_ID "%s"' % (p.program_id or ""))
    w("#define GAME_HAVE_PROGRAM_ID %d" % (1 if p.program_id else 0))
    w("#define GAME_VERSION %d" % (p.version or 0))
    w("#define GAME_HAVE_VERSION %d" % (1 if p.version else 0))
    w("")
    w("/* main's base in the lifted image; every patch offset in the profile is relative to it */")
    w("#define GAME_MAIN_BASE 0x%xull" % (p.main_base or 0))
    w("#define GAME_HAVE_MAIN_BASE %d" % (1 if p.main_base is not None else 0))
    w("")
    w("/* offsets into the game's graphics module (host/nn_vi.c's hos_gfx_module) */")
    for name, value in (("FRAME_LIMITER", p.gfx.frame_limiter), ("NOMINAL_FPS", p.gfx.nominal_fps),
                        ("VRR_MODE", p.gfx.vrr_mode), ("VRR_GATE", p.gfx.vrr_gate),
                        ("CONTROLLER", p.gfx.controller)):
        w("#define GAME_GFX_%s 0x%x" % (name, value or 0))
        w("#define GAME_GFX_HAVE_%s %d" % (name, 1 if value is not None else 0))
    # (an empty initializer is not C, so an empty list is one zero with a count of 0: the loops over it do nothing)
    w("#define GAME_GFX_CONTROLLER_WORDS %s" % _init("0x%x", p.gfx.controller_words))
    w("#define GAME_GFX_CONTROLLER_WORD_COUNT %d" % len(p.gfx.controller_words))
    w("#define GAME_GFX_CONTROLLER_RATE_WORDS %s" % _init("0x%x", p.gfx.controller_rate_words))
    w("#define GAME_GFX_CONTROLLER_RATE_WORD_COUNT %d" % len(p.gfx.controller_rate_words))
    w("")
    w("/* shader program keys this game's renderer treats specially; empty: none of them */")
    w('#define GAME_UPSCALE_TAAU_KEYS "%s"' % _keys(p.upscale.taau))
    w('#define GAME_UPSCALE_TRACE_KEYS "%s"' % _keys(p.upscale.trace))
    w('#define GAME_NETWORK_KEEP_KEYS "%s"' % _keys(p.upscale.network_keep))
    w("#define GAME_GAMEPLAY_NETWORK_KEYS %s" % _init("0x%016xull", p.upscale.gameplay))
    w("#define GAME_GAMEPLAY_NETWORK_KEY_COUNT %d" % len(p.upscale.gameplay))
    w("")
    w("#endif /* GAME_PROFILE_H */")
    return "\n".join(out) + "\n"


def header_path():
    return os.path.normpath(HEADER)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--emit-header", action="store_true", help="rewrite game/game_profile.h from this file")
    p.add_argument("--check-header", action="store_true", help="exit 1 when the committed header does not match")
    p.add_argument("--game", help="a profile key, instead of HOOKSHOT_GAME")
    a = p.parse_args(argv)
    profile = GAMES[a.game] if a.game else active()
    if a.emit_header or a.check_header:
        text = emit_header(profile)
        path = header_path()
        if a.check_header:
            with open(path, encoding="utf-8", newline="") as f:
                have = f.read()
            if have != text:
                print("%s is not what nx2/game_profile.py emits: run python -I nx2/game_profile.py --emit-header"
                      % path)
                return 1
            print("%s matches nx2/game_profile.py" % path)
            return 0
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("wrote %s for the %s profile" % (path, profile.key))
        return 0
    for key, prof in GAMES.items():
        print("%s%s: %s" % ("* " if prof is profile else "  ", key, prof.game))
        print("    program %s, version %s, build %s" % (prof.program_id, prof.version, prof.build_id))
        print("    main base %s" % ("%#x" % prof.main_base if prof.main_base is not None else None))
        print("    lift patches %s, code patches %s" % (prof.patch_modules or None, prof.code_patch_module))
        print("    graphics module %s" % (prof.gfx,))
        print("    upscale keys %s" % (prof.upscale,))
        print("    %s" % prof.notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
