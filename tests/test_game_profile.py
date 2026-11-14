"""The game profile seam holds: a second game is described in nx2/game_profile.py and nowhere else, a dump is matched
to its profile by main's build id, an unknown or unmeasured game is patched and hooked by nothing, and the committed C
view of the profile is the one the profile emits.

What this guards, and why each check is here rather than left to review:

1. **The profile is chosen by main's build id.** Ocarina's build gets Ocarina's profile, a second game's build (a
   profile made up for this check) gets its own, and a build no profile knows gets NONE -- never Ocarina's by default,
   because Ocarina's patches and return addresses on another game are C after the wrong instruction and a module
   captured from a random call.
2. **A profile with no patches installs none, and Ocarina's patch modules leave out every site whose word differs.**
   The modules run for real against a fake image, so the skip path itself is exercised.
3. **No game is named outside the profile.** nx2/lift.py imports no game's module; host/nn_vi.c, host/hos_thread.c,
   host/nvn_native.c, the renderer and make_game.py carry none of Ocarina's offsets, return addresses, program keys or
   build id as literals.
6. **game/ travels with the sources**: the AppImage's tools, the Windows package and the source stamp (Lakitu 029287fa).
4. **A profile is whole or empty where half would be unsafe:** one that names the graphics module's return address
   names every offset the runtime reads in it.
5. **game/game_profile.h is what nx2/game_profile.py emits**, and every profile's header compiles with the guard the
   runtime puts on it.

Every check asserts first that it is looking at something (the files are read and hold the markers searched for, the
fake image really holds the words), so it cannot pass by finding nothing.

python -I -B tests/test_game_profile.py [--cc gcc]
"""
import argparse
import contextlib
import importlib
import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import game_profile  # noqa: E402

RUN_ALL_ARGS = ["--cc", "gcc"]
FAILURES = []


def check(cond, what):
    if not cond:
        FAILURES.append(what)
    return bool(cond)


class FakeLifter(object):
    """What a patch module touches: the dict of C to run after a guest instruction."""

    def __init__(self):
        self.after = {}


class FakeImage(object):
    """A guest image whose every word is `word`: none of the instructions a patch was written for."""

    def __init__(self, word=0):
        self.value = word
        self.asked = 0

    def word(self, pc):
        self.asked += 1
        return self.value


def check_choice():
    oot, none = game_profile.GAMES["oot"], game_profile.GAMES["none"]
    # (a second game, made up here: the engine has one profile, Ocarina's, and the choice must already tell games apart)
    other = game_profile.Profile("other", "a second game", build_id="9ede03836568bcd34434dfc29bc61e0451dbbe3e",
                                 main_base=0x80020000)
    game_profile.GAMES["other"] = other
    try:
        check(game_profile.for_build(oot.build_id) is oot, "Ocarina's build id does not choose Ocarina's profile")
        check(game_profile.for_build(oot.build_id[:8]) is oot, "the 8-digit prefix the docs quote does not choose Ocarina")
        check(game_profile.for_build(other.build_id) is other, "a second game's build id does not choose its profile")
        check(game_profile.for_build("0123456789abcdef0123456789abcdef01234567") is none,
              "a build no profile knows does not get the empty profile")
        check(game_profile.for_build("e0f3") is none, "four digits are taken as a build id")
        check(game_profile.active({}, build_id=other.build_id) is other, "a lift of another dump does not get its profile")
        check(game_profile.active({}, build_id="ffffffff") is none, "a lift of an unknown dump gets a profile with patches")
        check(game_profile.active({}) is game_profile.GAMES[game_profile.DEFAULT], "no dump does not mean the default")
        check(game_profile.active({"HOOKSHOT_GAME": "other"}, build_id=oot.build_id) is other,
              "HOOKSHOT_GAME does not override")
    finally:
        del game_profile.GAMES["other"]
    try:
        game_profile.active({"HOOKSHOT_GAME": "nope"})
        check(False, "an unknown HOOKSHOT_GAME is accepted")
    except SystemExit:
        pass
    ids = [p.build_id for p in game_profile.GAMES.values() if p.build_id]
    check(len(ids) == len(set(ids)) and all(re.fullmatch(r"[0-9a-f]{40}", b) for b in ids),
          "a profile's build id is not main's whole 40-digit build id, or two profiles share one")
    check([p.key for p, _ in game_profile.known_builds()] == ["oot", "mkw"], "make_game.py's known builds are not Ocarina's and Mario Kart World 1.0.0's (Lakitu)")


def check_wholeness():
    for p in game_profile.GAMES.values():
        if p.hooks.gfx_clock is not None:
            check(all(v is not None for v in p.gfx[:5]) and p.gfx.controller_words and p.gfx.controller_rate_words,
                  "%s: names the graphics module's return address but not every offset read in it" % p.key)
        if p.patch_modules or p.code_patch_module or p.hooks != game_profile.EMPTY_HOOKS:
            check(p.build_id and p.main_base is not None,
                  "%s: patches or hooks a game without saying which build and where main is" % p.key)
        check(isinstance(p.account_users, int) and 1 <= p.account_users <= 8, "%s: account_users is not 1..8" % p.key)
        check(p.npad_players == "auto" or (isinstance(p.npad_players, int) and 1 <= p.npad_players <= 8),
              "%s: npad_players is not 1..8 or auto" % p.key)
    none = game_profile.GAMES["none"]
    check(not none.patch_modules and none.code_patch_module is None and none.hooks == game_profile.EMPTY_HOOKS and
          none.gfx == game_profile.EMPTY_GFX and none.upscale == game_profile.EMPTY_UPSCALE and not none.build_id,
          "the empty profile claims a patch, an offset, a hook, a key or a build")


def check_patches():
    none = game_profile.GAMES["none"]
    lifter = FakeLifter()
    with contextlib.redirect_stdout(io.StringIO()):
        n = game_profile.install_patches(lifter, FakeImage(), none, "")
    check(n == 0 and not lifter.after, "a profile with no patch modules installed C")
    oot = game_profile.GAMES["oot"]
    check(oot.patch_modules, "Ocarina's profile has no patch modules to check")
    for p in game_profile.GAMES.values():
        for name in p.patch_modules + ((p.code_patch_module,) if p.code_patch_module else ()):
            check(game_profile.load_module(name).__name__ == name, "%s: %s does not load as itself" % (p.key, name))
    for name in oot.patch_modules:
        module = importlib.import_module(name)
        check(callable(getattr(module, "install", None)), "%s has no install()" % name)
    image, lifter, out = FakeImage(0), FakeLifter(), io.StringIO()
    with contextlib.redirect_stdout(out):
        n = game_profile.install_patches(lifter, image, oot, oot.build_id)
    check(image.asked > 0, "Ocarina's patch modules never looked at the image, so the word check was not exercised")
    check(n == 0 and not lifter.after, "Ocarina's patch modules wrote C after instructions that are not theirs")
    module = importlib.import_module(oot.code_patch_module)
    check(callable(getattr(module, "patch_file", None)) and getattr(module, "LIFE_BUILD_ID", "") == oot.build_id,
          "Ocarina's code patch module is not the one chunks.edit_c applies, or its build is not the profile's")


def read(rel, *markers):
    text = (ROOT / rel).read_text(encoding="utf-8")
    for m in markers:
        check(m in text, "%s: no %r, so the check below would look at nothing" % (rel, m))
    return text


def code_only(text):
    """C or Python without its comments, for the literal checks: a comment may say what Ocarina's value was."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return re.sub(r"(?m)^\s*#(?!include|define|if|endif|else|elif|error|ifdef|ifndef).*$", "", text)


def check_no_literals():
    lift = read("nx2/lift.py", "game_profile")
    check(not re.search(r"^\s*(import|from)\s+oot_\w+", lift, re.M), "nx2/lift.py imports a game's module by name")
    chunks = code_only(read("nx2/chunks.py", "def edit_c("))
    check("import oot_patches" not in chunks, "nx2/chunks.py imports Ocarina's code patches by name")
    vi = code_only(read("host/nn_vi.c", "GAME_GFX_FRAME_LIMITER"))
    for lit in ("0xfc)", "0x2c8)", "0x231)", "0x232)", "0x270 +"):
        check("mod + " + lit not in vi, "host/nn_vi.c reads the graphics module at Ocarina's %s again" % lit)
    thread = code_only(read("host/hos_thread.c", "GAME_LR_GFX_CLOCK"))
    for lit in ("0x8348c770", "0x80590520"):
        check(lit not in thread, "host/hos_thread.c recognises Ocarina's %s again" % lit)
    nvn = code_only(read("host/nvn_native.c", "GAME_LR_PRESENT_EVENTS"))
    for lit in ("0x805904a0", "0x80590530"):
        check(lit not in nvn, "host/nvn_native.c recognises Ocarina's %s again" % lit)
    for rel in ("gpu/vk/vk_draw.cpp", "gpu/vk/vk_shader.cpp"):
        src = code_only(read(rel, "game_profile.h"))
        for lit in ("fd029a317a9a4b94", "9dc98871eb7fc101"):
            check(lit not in src, "%s names Ocarina's program %s outside a comment" % (rel, lit))
    main_c = code_only(read("host/hos_main.c", "GAME_SAVES_DIR"))
    saves = main_c[main_c.index("static const char *saves_dir(const char *beside) {"):]
    check('"/" GAME_SAVES_DIR' in saves[:saves.index("\n}\n")],
          "host/hos_main.c's saves folder is not the game profile's: two games would share one")
    make = read("nx2/make_game.py", "game_profile")
    check(not re.search(r"""^BUILD_ID\s*=\s*["']""", make, re.M), "nx2/make_game.py has its own supported build again")


def check_headers(cc):
    proc = subprocess.run([sys.executable, "-I", str(ROOT / "nx2" / "game_profile.py"), "--check-header"],
                          capture_output=True, text=True)
    check(proc.returncode == 0, "game/game_profile.h is not what nx2/game_profile.py emits: " + proc.stdout.strip())
    guard = read("host/game_profile_check.h", "#error")
    with tempfile.TemporaryDirectory(prefix="game-profile-") as tmp:
        for key, p in game_profile.GAMES.items():
            folder = os.path.join(tmp, key)
            game_profile.write_header(folder, p)
            text = Path(folder, "game_profile.h").read_text(encoding="utf-8")
            check(("#define GAME_PROFILE_KEY \"%s\"" % key) in text, "%s's header does not name its profile" % key)
            src = Path(tmp, key + ".c")
            src.write_text('#include "game_profile.h"\n' + guard + "\n"
                           "static const unsigned long long ev[] = GAME_LR_PRESENT_EVENTS;\n"
                           "static const unsigned long long gk[] = GAME_GAMEPLAY_NETWORK_KEYS;\n"
                           "static const unsigned cw[] = GAME_GFX_CONTROLLER_WORDS, rw[] = GAME_GFX_CONTROLLER_RATE_WORDS;\n"
                           "int main(void) { return (int)(sizeof ev + sizeof gk + sizeof cw + sizeof rw) * 0 + "
                           "GAME_NPAD_PLAYERS * 0 + GAME_ACCOUNT_USERS * 0; }\n", encoding="utf-8")
            r = subprocess.run([cc, "-std=c11", "-Wall", "-Werror", "-fsyntax-only", "-I" + folder, str(src)],
                               capture_output=True, text=True)
            check(r.returncode == 0, "%s's header does not compile with the runtime's guard: %s" % (key, r.stderr[-400:]))
            check(('#define GAME_SAVES_DIR "%s"' % ("hookshot" if key == "oot" else "hookshot-" + key)) in text,
                  "%s's saves would not be in a folder of their own" % key)
            if key == "none":
                check("#define GAME_HAVE_LR_GFX_CLOCK 0" in text and "#define GAME_HAVE_BUILD_ID 0" in text and
                      "#define GAME_NPAD_PLAYERS 1" in text and "#define GAME_ACCOUNT_USERS 1" in text,
                      "the empty profile's header hooks a graphics module, names a build or changes the defaults")
        # the guard has to be able to fail: a profile with the module's address and none of its offsets
        bad = game_profile.Profile("bad", "half", build_id="0" * 40, main_base=0x80020000,
                                   hooks=game_profile.Hooks(gfx_clock=0x80000004, present_poll=None, present_events=()))
        folder = os.path.join(tmp, "bad")
        game_profile.write_header(folder, bad)
        src = Path(tmp, "bad.c")
        src.write_text('#include "game_profile.h"\n' + guard + "\nint main(void) { return 0; }\n", encoding="utf-8")
        r = subprocess.run([cc, "-std=c11", "-fsyntax-only", "-I" + folder, str(src)], capture_output=True, text=True)
        check(r.returncode != 0, "the runtime's guard compiles a profile that has the module's address but no offsets")


def check_game_folder_travels():
    """game/ goes wherever the runtime's sources go: into the AppImage's tools, the Windows release package and the
    source stamp (nx2/version.py). Each of the three once left it out in a fork, so a player's build could not find
    game_profile.h, or a profile change did not change the build's source id (Lakitu 029287fa)."""
    appimage = (ROOT / "scripts" / "linux" / "appimage.sh").read_text(encoding="utf-8")
    check(re.search(r"^cp -a [^\n]*\bnx2\b[^\n]*\bgame\b[^\n]*\"\$T/\"$", appimage, re.M),
          "scripts/linux/appimage.sh does not copy game/ into the AppImage's tools")
    parts = (ROOT / "scripts" / "release_parts.py").read_text(encoding="utf-8")
    check(re.search(r'tracked\("game", "gpu", "host", "nx2"', parts),
          "scripts/release_parts.py does not package game/ with the Windows tools")
    import version
    check("game" in version.SOURCES, "nx2/version.py's source stamp does not read game/")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    check_choice()
    check_wholeness()
    check_patches()
    check_no_literals()
    check_headers(a.cc)
    check_game_folder_travels()
    for f in FAILURES:
        print("FAIL: " + f)
    if FAILURES:
        sys.exit(1)
    print("PASS: game profiles: chosen by build id, whole or empty, no game named outside them, header in step")


if __name__ == "__main__":
    main()
