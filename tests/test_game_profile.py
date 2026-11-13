"""The game profile seam holds: a patch site is only patched when the game has the instruction it was written for,
the lift driver names no game, and the committed C view of the profile is the one the profile emits.

What this guards, and why each check is here rather than left to review:

1. **A site whose instruction word differs is skipped, not patched.** This is the whole safety story of a game
   profile. The profile may be wrong about an address -- aimed at the wrong build, or at another game entirely --
   and the result has to be a feature that is off, never C written after an instruction that is not the one the
   patch was written for. The check runs each profile's real patch modules against a fake image, so it exercises
   the skip path itself; it does not read the source and hope.
2. **nx2/lift.py imports no game's modules by name.** The driver asks the profile which modules to install. If
   someone puts `import oot_wide` back, adding a second game means editing the driver again, which is the thing
   the seam exists to stop.
3. **game/game_profile.h is what nx2/game_profile.py emits.** The header is generated and committed so a build
   needs no generation step; that only works while the two cannot drift.
4. **The Mario Kart World profile holds no invented numbers**, and a profile that claims patch sites also says
   which build it is for.

This test has to be able to fail. Every check below asserts first that it is looking at something: that the
fixture image really does hold the expected words, that a module really does install sites when they match, that
the files it reads are non-empty and contain the markers it searches for. A source scan that passes because it
found nothing is worse than no test.

python -I -B tests/test_game_profile.py
"""
import contextlib
import importlib
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import game_profile  # noqa: E402

FAILURES = []


def check(cond, what):
    if not cond:
        FAILURES.append(what)
    return bool(cond)


class FakeLifter(object):
    """Only what install_sites touches: the dict of C to run after a guest instruction."""

    def __init__(self):
        self.after = {}


class FakeImage(object):
    """A guest image that holds exactly the words it is given, and nothing at any other address."""

    class _Main(object):
        name = "main"

        def __init__(self, base):
            self.base = base

    def __init__(self, base, words):
        self.modules = [FakeImage._Main(base)]
        self.words = dict(words)
        self.asked = []

    def word(self, pc):
        self.asked.append(pc)
        if pc not in self.words:
            raise IndexError("%#x is not in this image" % pc)
        return self.words[pc]


def sites_of(module, main_base):
    """A patch module's sites as (offset, word) pairs, however it spells its table.

    A module may hold its sites as a tuple or build them from main's base (one of Ocarina's writes absolute
    vtable addresses into its C). Both shapes are accepted; a module with neither is a failure, because then
    this test would have nothing to check and would pass by looking at nothing.
    """
    table = None
    if callable(getattr(module, "sites", None)):
        table = module.sites(main_base)
    elif isinstance(getattr(module, "SITES", None), tuple):
        table = module.SITES
    if not table:
        return None
    out = []
    for site in table:
        if len(site) < 2 or not isinstance(site[0], int):
            return None
        words = game_profile.site_words(site[1])
        if not words or not all(isinstance(w, int) for w in words):
            return None
        out.append((site[0], words))
    return out


def image_words(base, pairs, flip=()):
    """The words an image holds for these sites: each site's consecutive words, the ones in flip changed."""
    out = {}
    for k, (off, words) in enumerate(pairs):
        for i, w in enumerate(words):
            out[base + off + 4 * i] = w ^ 0xffffffff if flip == "all" or (k, i) in flip else w
    return out


def install(module, lifter, img, profile):
    """The module installed as the lift installs it (nx2/game_profile.py install_module), for the profile's build."""
    return game_profile.install_module(module, lifter, img, profile, build_id=profile.build_id)


def check_patch_modules(profile):
    """Each of the profile's patch modules, against an image that holds the words and one that does not."""
    if not profile.patch_modules:
        return 0
    checked = 0
    for name in profile.patch_modules:
        module = importlib.import_module(name)
        pairs = sites_of(module, profile.main_base)
        if not check(pairs, "%s: %s has no readable site table, so nothing about it could be checked"
                            % (profile.key, name)):
            continue
        if not check(all(0 <= w <= 0xffffffff for _, words in pairs for w in words),
                     "%s: %s has a site whose expected value is not a 32-bit instruction word" % (profile.key, name)):
            continue

        # (1a) the image holds every word the module expects: every site goes in
        good = FakeImage(profile.main_base, image_words(profile.main_base, pairs))
        lifter = FakeLifter()
        with contextlib.redirect_stdout(io.StringIO()):
            n = install(module, lifter, good, profile)
        if not check(n == len(pairs) and len(lifter.after) > 0,
                     "%s: %s installed %d of %d sites on an image that holds every expected word"
                     % (profile.key, name, n, len(pairs))):
            continue
        # the fixture really did exercise the word check (otherwise 1b below proves nothing)
        if not check(good.asked, "%s: %s never read an instruction word: its sites are not checked at all"
                                 % (profile.key, name)):
            continue

        # (1b) every word differs: nothing is patched, and each skipped site is said out loud
        flipped = FakeImage(profile.main_base, image_words(profile.main_base, pairs, flip="all"))
        lifter = FakeLifter()
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            n = install(module, lifter, flipped, profile)
        check(n == 0 and not lifter.after,
              "%s: %s patched %d sites on an image where every word differs: a profile aimed at the wrong build "
              "would corrupt the game" % (profile.key, name, n))
        check(said.getvalue().count("left out") == len(pairs),
              "%s: %s did not log every site it left out (%d of %d said)"
              % (profile.key, name, said.getvalue().count("left out"), len(pairs)))

        # (1c) one word differs: that site alone is left out, the rest still go in
        if len(pairs) > 1:
            words = image_words(profile.main_base, pairs, flip={(0, 0)})
            first = profile.main_base + pairs[0][0]
            lifter = FakeLifter()
            with contextlib.redirect_stdout(io.StringIO()):
                n = install(module, lifter, FakeImage(profile.main_base, words), profile)
            check(n == len(pairs) - 1 and first not in lifter.after,
                  "%s: %s did not leave out the one site whose word differs (installed %d of %d)"
                  % (profile.key, name, n, len(pairs)))
        # (1e) a site that needs several consecutive words: its last word alone differs, and it is still left out
        multi = [k for k, (_, words) in enumerate(pairs) if len(words) > 1]
        for k in multi:
            words = image_words(profile.main_base, pairs, flip={(k, len(pairs[k][1]) - 1)})
            lifter = FakeLifter()
            with contextlib.redirect_stdout(io.StringIO()):
                n = install(module, lifter, FakeImage(profile.main_base, words), profile)
            check(n == len(pairs) - 1 and profile.main_base + pairs[k][0] not in lifter.after,
                  "%s: %s patched a site whose last needed word differs" % (profile.key, name))

        # (1d) an address that is not in the image at all is left out, not raised through
        lifter = FakeLifter()
        with contextlib.redirect_stdout(io.StringIO()):
            n = install(module, lifter, FakeImage(profile.main_base, {}), profile)
        check(n == 0 and not lifter.after,
              "%s: %s patched %d sites on an image that holds no instruction at any of them"
              % (profile.key, name, n))
        checked += 1
    return checked


def check_no_main_base_patches_nothing():
    """A profile with no main base cannot place an offset, so it patches nothing rather than patching from 0."""
    nowhere = game_profile.Profile(key="test", game="a game with no addresses known")
    lifter = FakeLifter()
    n = game_profile.install_sites(lifter, FakeImage(0, {}), nowhere,
                                   ((0x10, 0xd503201f, "/* would be wrong */"),), "test", log=lambda *a: None)
    check(n == 0 and not lifter.after,
          "install_sites patched a site for a profile with no main base, which would place it at an offset from 0")


def check_lift_names_no_game():
    """nx2/lift.py goes through the profile and imports no game's modules by name."""
    text = (ROOT / "nx2" / "lift.py").read_text(encoding="utf-8")
    if not check(len(text) > 2000, "nx2/lift.py is missing or far too short to be the lift driver"):
        return
    # the positive marker first: without it this check could pass on a file that does nothing at all
    check("game_profile" in text, "nx2/lift.py does not mention game_profile: it is not going through the seam")
    check(re.search(r"game_profile\.install_patches\(", text),
          "nx2/lift.py does not call game_profile.install_patches()")
    check(re.search(r"game_profile\.code_patches\(", text),
          "nx2/lift.py does not ask game_profile.code_patches() which module edits the lifted C")

    # every module any profile names, plus anything that looks like a game module, must not be imported here
    named = {m for p in game_profile.GAMES.values() for m in p.patch_modules}
    named |= {p.code_patch_module for p in game_profile.GAMES.values() if p.code_patch_module}
    if not check(named, "no profile names a patch module, so this check would scan for nothing"):
        return
    # (nx2/chunks.py edits the lifted C for the lift: it takes the code patch module's name from the profile too)
    chunks = (ROOT / "nx2" / "chunks.py").read_text(encoding="utf-8")
    check("def edit_c(" in chunks and "patches=" in chunks,
          "nx2/chunks.py edit_c does not take the code patch module from its caller")
    for where, body in (("nx2/lift.py", text), ("nx2/chunks.py", chunks)):
        for module in sorted(named):
            check(not re.search(r"^\s*(?:import|from)\s+%s\b" % re.escape(module), body, re.M),
                  "%s imports %s by name: the game's modules come from the profile" % (where, module))
        # and the general shape, for a game whose prefix no profile lists yet
        stray = re.findall(r"^\s*import\s+([a-z0-9]+_(?:wide|camera|occlusion|patches|fov|jitter))\b", body, re.M)
        check(not stray, "%s imports game patch modules by name: %s" % (where, ", ".join(stray)))


def check_header_matches():
    """game/game_profile.h is what nx2/game_profile.py emits for the active profile."""
    path = Path(game_profile.header_path())
    if not check(path.is_file(), "game/game_profile.h is missing: run python -I nx2/game_profile.py --emit-header"):
        return
    have = path.read_text(encoding="utf-8")
    want = game_profile.emit_header(game_profile.active())
    if not check(len(want) > 500 and "GAME_PROFILE_H" in want, "emit_header() produced no usable header"):
        return
    check(have == want,
          "game/game_profile.h is not what nx2/game_profile.py emits: run python -I nx2/game_profile.py --emit-header")


def check_build_uses_the_active_header():
    """nx2/build.py compiles against the active profile's header: game/ for the committed one, otherwise that
    profile's header written under the work folder. A HOOKSHOT_GAME=mkw build with the committed (oot) header would
    put Ocarina's graphics-module offsets into a Mario Kart World runtime."""
    import os
    import tempfile
    import build
    saved = os.environ.get("HOOKSHOT_GAME")
    try:
        with tempfile.TemporaryDirectory(prefix="game-profile-") as work, contextlib.redirect_stdout(io.StringIO()):
            os.environ.pop("HOOKSHOT_GAME", None)
            committed = game_profile.active()
            check(build.active_game_dir(work) == build.GAME, "the default profile's build does not use game/")
            other = next(k for k in game_profile.GAMES if k != committed.key)
            os.environ["HOOKSHOT_GAME"] = other
            folder = build.active_game_dir(work)
            path = Path(folder) / "game_profile.h"
            check(Path(folder) != Path(build.GAME) and path.is_file()
                  and path.read_text(encoding="utf-8") == game_profile.emit_header(game_profile.GAMES[other]),
                  "a HOOKSHOT_GAME=%s build does not compile against the %s profile's header" % (other, other))
    finally:
        if saved is None:
            os.environ.pop("HOOKSHOT_GAME", None)
        else:
            os.environ["HOOKSHOT_GAME"] = saved


def check_game_folder_travels():
    """game/ goes wherever the runtime's sources go: into the AppImage's tools, the Windows release package and the
    source stamp (nx2/version.py). Each of the three once left it out, so a player's build could not find
    game_profile.h, or a profile change did not change the build's source id."""
    appimage = (ROOT / "scripts" / "linux" / "appimage.sh").read_text(encoding="utf-8")
    check(re.search(r"^cp -a [^\n]*\bnx2\b[^\n]*\bgame\b[^\n]*\"\$T/\"$", appimage, re.M),
          "scripts/linux/appimage.sh does not copy game/ into the AppImage's tools")
    parts = (ROOT / "scripts" / "release_parts.py").read_text(encoding="utf-8")
    check(re.search(r'tracked\("game", "gpu", "host", "nx2"', parts),
          "scripts/release_parts.py does not package game/ with the Windows tools")
    import version
    check("game" in version.SOURCES, "nx2/version.py's source stamp does not read game/")


def check_profiles_are_honest():
    """No profile holds a value it cannot have measured, and one with patch sites says which build it is for."""
    if not check(len(game_profile.GAMES) >= 2, "there is only one game profile, so the seam has nothing to prove"):
        return
    for key, p in game_profile.GAMES.items():
        claims = bool(p.patch_modules or p.code_patch_module or p.gfx.frame_limiter is not None
                      or p.gfx.nominal_fps is not None or p.upscale.taau or p.upscale.gameplay)
        if claims:
            # a profile that patches or paces a game has to say which game build it was measured on, or there is
            # no way to tell whether its addresses apply to the dump in front of it
            check(p.main_base is not None, "the %s profile claims game-specific values but has no main base" % key)
            check(p.build_id, "the %s profile claims game-specific values but does not say which build" % key)
            check(p.program_id, "the %s profile claims game-specific values but no program id" % key)
        else:
            # an empty profile must be empty all the way: a half-filled one is the dangerous state
            check(p.main_base is None, "the %s profile names no patches but has a main base" % key)
            check(p.gfx == game_profile.EMPTY_GFX,
                  "the %s profile names no patches but has graphics-module offsets" % key)
            check(p.upscale == game_profile.EMPTY_UPSCALE,
                  "the %s profile names no patches but has upscale program keys" % key)
    check("mkw" in game_profile.GAMES, "there is no mkw profile")
    # (the identity it does hold: Mario Kart World 1.0.0, checked against a dump, and mkw-recomp's row for that build)
    mkw = game_profile.GAMES.get("mkw")
    if mkw:
        check(mkw.program_id == "0400C3F00006E000" and mkw.version == 0,
              "the mkw profile's title is not Mario Kart World's base game (0400C3F00006E000 v0)")
        check(mkw.build_id and mkw.build_id.startswith("9e244438") and len(mkw.build_id) >= 16,
              "the mkw profile's build is not 1.0.0's main (9e244438c3d8ef1c)")
        text = game_profile.emit_header(mkw)
        check("#define GAME_HAVE_VERSION 1" in text and "#define GAME_VERSION 0" in text,
              "version 0 is emitted as an unknown version")
    mkw = game_profile.GAMES.get("mkw")
    if mkw:
        check(mkw.main_base is None and not mkw.patch_modules and mkw.gfx == game_profile.EMPTY_GFX
              and mkw.upscale == game_profile.EMPTY_UPSCALE,
              "the mkw profile holds values, and nothing of Mario Kart World has been measured here")


def check_c_reads_the_profile():
    """The runtime and the renderer take these from the profile, not from literals of their own."""
    cases = [
        (Path("host") / "nn_vi.c", ("GAME_GFX_FRAME_LIMITER", "GAME_GFX_NOMINAL_FPS", "GAME_GFX_VRR_GATE"),
         (r"mod \+ 0xfc\b", r"mod \+ 0x2c8\b", r"mod \+ 0x231\b", r"mod \+ 0x232\b", r"mod \+ 0x270 \+")),
        (Path("gpu") / "vk" / "vk_draw.cpp", ("GAME_UPSCALE_TAAU_KEYS", "GAME_GAMEPLAY_NETWORK_KEYS"),
         (r'"fd029a317a9a4b94"', r"0xfd029a317a9a4b94ull")),
        (Path("gpu") / "vk" / "vk_shader.cpp", ("GAME_NETWORK_KEEP_KEYS",),
         (r'"fd029a317a9a4b94,9dc98871eb7fc101"',)),
    ]
    for rel, wanted, forbidden in cases:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if not check(len(text) > 1000, "%s is missing or too short to be the real file" % rel):
            continue
        for macro in wanted:
            check(macro in text, "%s does not read %s from the game profile" % (rel, macro))
        for pattern in forbidden:
            hits = [line.strip() for line in text.splitlines()
                    if re.search(pattern, line) and not line.lstrip().startswith(("//", "*", "/*", "#"))]
            check(not hits, "%s still has the game's value as a literal: %s" % (rel, hits[:2]))


def main():
    checked = sum(check_patch_modules(p) for p in game_profile.GAMES.values())
    check(checked > 0, "no profile's patch modules were checked, so check 1 proved nothing")
    check_no_main_base_patches_nothing()
    check_lift_names_no_game()
    check_header_matches()
    check_build_uses_the_active_header()
    check_game_folder_travels()
    check_profiles_are_honest()
    check_c_reads_the_profile()
    if FAILURES:
        for f in FAILURES:
            print("FAIL: %s" % f)
        raise SystemExit(1)
    print("game profile: %d patch module(s) checked, the seam holds" % checked)


if __name__ == "__main__":
    main()
