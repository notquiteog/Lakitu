"""The ASTC upload's BC1/BC3 choice reads the blocks where they came from, not back out of the staging arena.

upload_astc_gpu (gpu/vk/vk_texture.cpp) copies a texture's ASTC blocks into a staging arena for the GPU decoder, and a big
texture kept as BC decides between BC1 and BC3 from those blocks (astc_opaque.h). The arena is write-combined memory, or
VRAM through the BAR: reading it back on the CPU is slow, and the scan took 10-160 ms for one 1-2K texture and 12-14 s for a
2048 x 2048 x 68 array on the replay thread (Mario Kart World 1.0.0's races and course loads, RTX 5060 Ti, Linux). The scan
now reads each part of the guest's storage as it is copied.

Checked here, from the function's text: astc_opaque::scan is called on the copy's source, inside the copy loop, and never
on the staging arena's mapping (s.data).

python -I -B tests/test_astc_scan_source.py
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py)
from srccut import block   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class ScanSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = (ROOT / "gpu" / "vk" / "vk_texture.cpp").read_text(encoding="utf-8")
        cls.fn = block(src, "bool upload_astc_gpu(Texture& tex, uint64_t total, const Ranges* dirty) {", "gpu/vk/vk_texture.cpp")

    def test_never_reads_the_staging_arena(self):
        calls = re.findall(r"astc_opaque::scan\(([^,]+),", self.fn)
        self.assertTrue(calls, "upload_astc_gpu no longer scans its blocks: update this check")
        for arg in calls:
            self.assertNotIn("s.data", arg, "the scan reads the staging arena back (write-combined memory)")

    def test_scans_the_copy_source(self):
        loop = self.fn[self.fn.index("for (size_t k = 0; k < layers.size(); k++) {"):]
        loop = loop[:loop.index("\n    }\n") + 6]
        m = re.search(r"const uint8_t\* (\w+) = guest_bytes\(", loop)
        self.assertIsNotNone(m, "the copy loop names its source")
        self.assertIn("std::memcpy(s.data + k * tail, %s, n);" % m.group(1), loop)
        self.assertIn("astc_opaque::scan(%s, n)" % m.group(1), loop)


if __name__ == "__main__":
    unittest.main()
