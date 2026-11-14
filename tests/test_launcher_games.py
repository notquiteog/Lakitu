"""One launcher entry and one builder for several games (docs/one-engine.md, step 4): each game has its own game
folder, work folder and saves, and the default game's (Ocarina's) do not move. Game-free.

The rule, nx2/game_folders.py: the default game keeps <base>, another game gets <base>-<key>. Checked here in every
place that applies it, since a launcher tile that starts one folder while the builder built another is a game that
"is not built":
  - nx2/game_folders.py itself (folder, launcher_games);
  - recomplauncher.json: no games[] while one game is in the release (RecompLauncher's schema wants two or more), and
    the default game's saves in launcher_games() are exactly the entry's top-level saves, so nothing moves;
  - nx2/make_game.py --prepare without --out: the copy's game decides its game and work folder;
  - Play: builder/linux/hookshot-launch (run) and builder/setup/setup.c play_target (cut out and compiled), and that
    setup.c's default key is the profile's.

    python -I -B tests/test_launcher_games.py [--cc gcc]
"""
import argparse
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]
RUN_ALL_SKIP = {"windows": "runs a POSIX shell script and gcc: checked on Linux"}

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import game_folders  # noqa: E402
import game_profile  # noqa: E402

CC = "gcc"
DEFAULT = game_profile.DEFAULT


def other_profile(key="zz"):
    """A second game for the checks: no profile but the default one is in the release yet"""
    return game_profile.Profile(key=key, game="Another Game", program_id="0400000000000000", version=0,
                                build_id="0123456789abcdef")


class Rule(unittest.TestCase):
    def test_the_default_game_keeps_its_folder(self):
        self.assertEqual(game_folders.folder("/home/p/Games/Hookshot", DEFAULT), "/home/p/Games/Hookshot")
        self.assertEqual(game_folders.folder("/home/p/Games/Hookshot/", DEFAULT), "/home/p/Games/Hookshot")

    def test_another_game_sits_beside_it(self):
        self.assertEqual(game_folders.folder("/home/p/Games/Hookshot", "mkw"), "/home/p/Games/Hookshot-mkw")
        self.assertEqual(game_folders.folder("C:\\Games\\Hookshot\\", "kar"), "C:\\Games\\Hookshot-kar")

    def test_a_key_is_a_key(self):
        for bad in ("", "MKW", "../x", "a" * 17, "a-b", None):
            with self.assertRaises(ValueError):
                game_folders.folder("/x", bad)


class LauncherEntry(unittest.TestCase):
    def setUp(self):
        self.entry = json.loads((ROOT / "recomplauncher.json").read_text(encoding="utf-8"))

    def test_one_game_has_no_games_list(self):
        released = game_folders.released()
        self.assertTrue(released and released[0].key == DEFAULT)
        if len(released) < 2:
            self.assertIsNone(game_folders.launcher_games())
            self.assertNotIn("games", self.entry, "games[] with one game: the schema wants two or more")
        else:
            self.assertEqual(self.entry.get("games"), game_folders.launcher_games(),
                             "recomplauncher.json games[] is not what nx2/game_folders.py gives the released profiles")

    def test_two_games_each_their_own_and_the_default_unmoved(self):
        default = game_profile.GAMES[DEFAULT]
        games = game_folders.launcher_games([default, other_profile()])
        self.assertEqual([g["id"] for g in games], [DEFAULT, "zz"])
        for g in games:
            self.assertRegex(g["id"], r"^[a-z0-9]{1,16}$")   # (RecompLauncher's games[].id)
            self.assertEqual(set(g), {"id", "name", "args", "saves"})
            self.assertEqual(g["args"], ["--game", g["id"]])
        self.assertEqual(games[0]["saves"], self.entry["saves"],
                         "the default game's saves in games[] are not the entry's own: they would move")
        self.assertEqual(games[1]["saves"], ["{local}/%s" % game_profile.saves_dir(other_profile()),
                                             "{home}/Games/Hookshot-zz/user"])
        self.assertNotEqual(games[0]["saves"], games[1]["saves"])
        # (and the default game's folder is still the one start.args and the folders name)
        self.assertIn("{home}/Games/Hookshot", self.entry["start"]["args"])


class Prepare(unittest.TestCase):
    def load(self):
        spec = importlib.util.spec_from_file_location("make_game_launcher_games", ROOT / "nx2" / "make_game.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def run_for(self, profile, work_given=False):
        mg = self.load()
        with tempfile.TemporaryDirectory(prefix="launcher-games-") as tmp:
            default_work = os.path.join(tmp, "hookshot-builder")
            work = os.path.join(tmp, "mine") if work_given else default_work
            a = types.SimpleNamespace(out=os.path.join(tmp, "Games", "Hookshot"), work=work, default_work=default_work,
                                      nup="copy.nup", exefs=None)
            mg.dump_build_id = lambda a, work: "0123456789abcdef"
            mg.supported_build = lambda bid: profile
            mg.game_folders_for_dump(a)
            return (os.path.relpath(a.out, tmp), os.path.relpath(a.work, tmp),
                    os.path.isdir(a.work) if a.work != default_work else None)

    def test_the_default_game_builds_where_it_always_did(self):
        self.assertEqual(self.run_for(game_profile.GAMES[DEFAULT])[:2], (os.path.join("Games", "Hookshot"), "hookshot-builder"))

    def test_another_game_gets_its_own_game_and_work_folders(self):
        out, work, made = self.run_for(other_profile())
        self.assertEqual((out, work, made), (os.path.join("Games", "Hookshot-zz"), "hookshot-builder-zz", True))

    def test_a_work_folder_given_is_kept(self):
        self.assertEqual(self.run_for(other_profile(), work_given=True)[1], "mine")

    def test_a_copy_no_profile_knows_is_left_to_the_check(self):
        self.assertEqual(self.run_for(None)[:2], (os.path.join("Games", "Hookshot"), "hookshot-builder"))

    def test_main_asks_only_without_out(self):
        source = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
        self.assertIn("a.out_from_game = bool(a.prepare and not a.out)", source)
        self.assertLess(source.index("game_folders_for_dump(a)\n    out = os.path.abspath(a.out)"),
                        source.index("a.language = build_language(a, out)"))


LAUNCH = ROOT / "builder" / "linux" / "hookshot-launch"


def built_game(folder):
    folder.mkdir(parents=True)
    (folder / "image.bin").write_bytes(b"image")
    exe = folder / "hookshot"
    exe.write_text("#!/bin/sh\npwd\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)


class LinuxPlay(unittest.TestCase):
    def play(self, *args, tools=str(ROOT)):
        env = dict(os.environ, HOOKSHOT_TOOLS=tools, HOOKSHOT_LAUNCH_CONFIG="/nonexistent/builder.ini")
        return subprocess.run([str(LAUNCH), *args], env=env, text=True, capture_output=True, timeout=60)

    def test_each_game_starts_its_own_folder(self):
        with tempfile.TemporaryDirectory(prefix="launcher-play-") as tmp:
            base = Path(tmp) / "Hookshot"
            built_game(base)
            built_game(Path(tmp) / "Hookshot-zz")
            ran = self.play(str(base), "--game", "zz")
            self.assertEqual((ran.returncode, ran.stdout.strip()), (0, str(Path(tmp) / "Hookshot-zz")), ran.stderr)
            ran = self.play(str(base) + "/", "--game", DEFAULT)
            self.assertEqual((ran.returncode, ran.stdout.strip()), (0, str(base)), ran.stderr)
            ran = self.play(str(base))
            self.assertEqual((ran.returncode, ran.stdout.strip()), (0, str(base)), ran.stderr)
            # (the default game's key from the script's own tree when HOOKSHOT_TOOLS has no game/)
            ran = self.play(str(base), "--game", DEFAULT, tools="/no/such/tools")
            self.assertEqual((ran.returncode, ran.stdout.strip()), (0, str(base)), ran.stderr)

    def test_a_game_not_built_and_a_bad_key_are_errors(self):
        with tempfile.TemporaryDirectory(prefix="launcher-play-") as tmp:
            base = Path(tmp) / "Hookshot"
            built_game(base)
            self.assertEqual(self.play(str(base), "--game", "zz").returncode, 1)
            for bad in ("ZZ", "a" * 17, "../x"):
                self.assertEqual(self.play(str(base), "--game", bad).returncode, 2, bad)


SETUP_FIXTURE = r'''
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#define HOOKSHOT_WIDEN2(s) L##s
#define HOOKSHOT_WIDEN(s) HOOKSHOT_WIDEN2(s)
@DEFINES@
@TARGET@
static int fails;
static void expect(const wchar_t *args, int ret, const wchar_t *want) {
    wchar_t folder[260];
    const int r = play_target(args, folder, 260);
    if (r != ret || wcscmp(folder, want)) { fprintf(stderr, "FAIL: %ls -> %d %ls\n", args, r, folder); fails++; }
}
int main(void) {
    expect(L" C:\\Games\\Hookshot", 0, L"C:\\Games\\Hookshot");
    expect(L" C:\\Games\\Hookshot --game zz", 0, L"C:\\Games\\Hookshot-zz");
    expect(L" \"C:\\My Games\\Hookshot\\\" --game zz", 0, L"C:\\My Games\\Hookshot-zz");
    expect(L" \"C:\\My Games\\Hookshot\" --game @DEFAULT@", 0, L"C:\\My Games\\Hookshot");
    expect(L" C:\\Games\\Hookshot --game ZZ", -1, L"");
    expect(L" C:\\Games\\Hookshot --game aaaaaaaaaaaaaaaaa", -1, L"");
    expect(L" C:\\Games\\Hookshot --game", -1, L"");
    expect(L" C:\\Games\\Hookshot --gamex zz", 0, L"C:\\Games\\Hookshot");
    return fails ? 1 : 0;
}
'''


class WindowsPlay(unittest.TestCase):
    def test_play_target(self):
        source = (ROOT / "builder" / "setup" / "setup.c").read_text(encoding="utf-8")
        default = re.search(r'#define HOOKSHOT_DEFAULT_GAME "([a-z0-9]+)"', source)
        self.assertTrue(default, "builder/setup/setup.c names no HOOKSHOT_DEFAULT_GAME")
        self.assertEqual(default.group(1), DEFAULT, "setup.c's default game is not nx2/game_profile.py's DEFAULT")
        start = source.index("static int play_target(")
        body = source[start:start + re.search(r"^}", source[start:], re.M).end()]
        defines = source[source.index("#ifndef HOOKSHOT_DEFAULT_GAME"):source.index("#define HOOKSHOT_DEFAULT_GAME_W")]
        defines += "#define HOOKSHOT_DEFAULT_GAME_W HOOKSHOT_WIDEN(HOOKSHOT_DEFAULT_GAME)\n"
        self.assertIn("play_target(args, folder, MAX_PATH)", source, "play_folder does not use play_target")
        with tempfile.TemporaryDirectory(prefix="launcher-setup-") as tmp:
            c = Path(tmp) / "play.c"
            exe = Path(tmp) / "play"
            c.write_text(SETUP_FIXTURE.replace("@DEFINES@", defines).replace("@TARGET@", body)
                         .replace("@DEFAULT@", DEFAULT), encoding="utf-8")
            subprocess.run([CC, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
            ran = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="gcc")
    a, rest = ap.parse_known_args()
    CC = a.cc
    unittest.main(argv=[sys.argv[0]] + rest)
