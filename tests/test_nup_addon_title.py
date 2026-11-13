"""A .nup can carry add-on content beside the game: Donkey Kong Bananza's has a third title, 040074a01bf13001 v0,
with a romfs and no exefs (its exefs directory is 0xffffffff). nup.py's listing walked every title's exefs and stopped
with an IndexError before the check could name the build, and the default title had to stay the newest program, not a
content title. Game-free: the package is a few authored records."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import nup  # noqa: E402


def package():
    """Three titles: base v0 and update v458752 of one program (exefs dir, romfs dir each), and add-on content with
    only a romfs. Each directory holds one file."""
    p = object.__new__(nup.Nup)
    names = [b"main", b"a.bin", b"main", b"b.bin", b"c.bin"]
    p.strings = b"".join(names)
    offsets, at = [], 0
    for n in names:
        offsets.append((at, len(n)))
        at += len(n)
    # dirs: (name off, name len, first kid, kid count); roots 0, 3, 6; exefs 1, 4; romfs 2, 5, 7
    p.dirs = [(0, 0, 0, 2), (0, 0, 2, 1), (0, 0, 3, 1),
              (0, 0, 4, 2), (0, 0, 6, 1), (0, 0, 7, 1),
              (0, 0, 8, 1), (0, 0, 9, 1)]
    p.nd = len(p.dirs)
    p.files = [(o, n, 10 + i, 0, 10 + i, 0) for i, (o, n) in enumerate(offsets)]
    p.nf = len(p.files)
    d = p.nd
    p.kids = (1, 2, d + 0, d + 1, 4, 5, d + 2, d + 3, 7, d + 4)
    p.titles = [dict(index=0, id=0x040074a01bf12000, root=0, exefs=1, romfs=2, version=0),
                dict(index=1, id=0x040074a01bf12000, root=3, exefs=4, romfs=5, version=458752),
                dict(index=2, id=0x040074a01bf13001, root=6, exefs=nup.ABSENT, romfs=7, version=0)]
    return p


class AddOnTitle(unittest.TestCase):
    def test_absent_part_walks_to_nothing(self):
        p = package()
        self.assertEqual(list(p.walk(nup.ABSENT)), [])
        self.assertEqual([name for name, _ in p.walk(7)], ["c.bin"])
        self.assertEqual([name for name, _ in p.walk(4)], ["main"])

    def test_default_title_is_the_newest_program(self):
        p = package()
        self.assertEqual(nup.pick_title(p, None)["index"], 1)
        p.titles[2]["version"] = 1 << 20   # (content newer than the update is still not the game)
        self.assertEqual(nup.pick_title(p, None)["index"], 1)
        self.assertEqual(nup.pick_title(p, "2")["index"], 2)   # (asked for by index, it is given)

    def test_listing_names_the_content_title(self):
        p = package()
        p.file_size = 0
        out = io.StringIO()
        with mock.patch.object(nup, "Nup", return_value=p), \
                mock.patch.object(sys, "argv", ["nup.py", "authored.nup"]), contextlib.redirect_stdout(out):
            self.assertIsNone(nup.main())
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[3].startswith("title 2: 040074a01bf13001 v0  exefs 0 files ()  romfs 1 files"), lines)
        self.assertIn("add-on content: no exefs", lines[3])


if __name__ == "__main__":
    unittest.main()
