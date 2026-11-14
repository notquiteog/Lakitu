"""A jump table is not bounded by a compare above an unconditional branch (third_party/a64-kit/lift/a64_lift.py).

Lifter.jump_table reads the straight-line code before a BR. A `ret`, `b` or `br` in that window means what follows is
reached from elsewhere, so the values and bounds known above it are forgotten. One was not: the window-wide CMP +
B.HI bound. A compare of other code above a `b` then gave the table its entry count, the read was strict, and the switch
lost the cases past it. Mario Kart World 1.0.0's br at 0x81e0f0c0 got 2 of its 5 entries (the real bound is on a path
into the dispatch, not in the window), and its race stopped at "indirect jump to an address with no function" when
the fifth was taken.

A real a64_lift.Lifter over a made-up image (instruction encodings only):
  - STALE: `cmp w8, #1; b.hi` (2 entries), then `b` to the dispatch block, which loads a byte table of 5 entries and
    jumps: all 5 targets (before the fix, 2);
  - BOUNDED: `cmp w8, #4; b.hi` in the dispatch block itself: exactly the 5 entries, read as a bounded table (the
    bound still applies, the entry after them is not read).

python -I -B tests/test_jump_table_stale_bound.py
"""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import kit  # noqa: E402,F401  (a64-kit on the path)
import a64_lift  # noqa: E402
import lift_fixes  # noqa: E402

BASE = 0x80000000
STALE, BOUNDED, END = BASE + 0x1000, BASE + 0x1100, BASE + 0x1200   # two functions; END starts the next one
TABLE = BASE + 0x8010                                               # data: the byte table both use
RET, NOP = 0xd65f03c0, 0xd503201f


def cmp_w8(imm):
    return 0x7100001f | (imm << 10) | (8 << 5)


def b_hi(pc, target):
    return 0x54000008 | ((((target - pc) >> 2) & 0x7FFFF) << 5)


def b(pc, target):
    return 0x14000000 | (((target - pc) >> 2) & 0x3FFFFFF)


def adrp_x9(pc, target):
    imm = ((target & ~0xFFF) - (pc & ~0xFFF)) >> 12
    return 0x90000009 | ((imm & 3) << 29) | (((imm >> 2) & 0x7FFFF) << 5)


def add_x9(off):
    return 0x91000129 | (off << 10)


def adr_x10(pc, target):
    imm = target - pc
    return 0x1000000a | ((imm & 3) << 29) | (((imm >> 2) & 0x7FFFF) << 5)


LDRB_W11 = 0x3868692b   # ldrb w11, [x9, x8]
ADD_X10 = 0x8b0b094a    # add x10, x10, x11, lsl #2
BR_X10 = 0xd61f0140     # br x10


def dispatch(at):
    """adrp/add the table, adr the cases' base, load the entry, br: 6 words at `at`, 5 one-word cases after them"""
    base = at + 24
    return {at: adrp_x9(at, TABLE), at + 4: add_x9(TABLE & 0xFFF), at + 8: adr_x10(at + 8, base),
            at + 12: LDRB_W11, at + 16: ADD_X10, at + 20: BR_X10,
            **{base + 4 * i: RET for i in range(5)}}, at + 20, [base + 4 * i for i in range(5)]


S_CODE, S_BR, S_CASES = dispatch(STALE + 0x20)
B_CODE, B_BR, B_CASES = dispatch(BOUNDED + 0x08)
WORDS = {
    STALE: cmp_w8(1), STALE + 4: b_hi(STALE + 4, STALE + 0x10),     # other code's compare: 2 entries
    STALE + 8: b(STALE + 8, STALE + 0x20), STALE + 12: RET,         # then a `b` to the dispatch block
    STALE + 0x10: RET, STALE + 0x14: NOP, STALE + 0x18: NOP, STALE + 0x1c: NOP,
    **S_CODE,
    BOUNDED: cmp_w8(4), BOUNDED + 4: b_hi(BOUNDED + 4, BOUNDED + 0x80),   # the table's own bound: 5 entries
    **B_CODE, BOUNDED + 0x80: RET,
    END: RET,
}
# entries 0..4 are the five cases; the sixth (8, a case's address too) is read only by a table with no bound
DATA = {TABLE + i: e for i, e in enumerate([0, 1, 2, 3, 4, 8, 0x80])}


class Image:
    entries = {STALE, BOUNDED, END}
    hooks = {}
    names = {}

    def word(self, pc):
        return WORDS[pc]

    def in_code(self, pc):
        return pc in WORDS

    def read(self, pc, n):
        if all(pc + i in DATA for i in range(n)):
            return bytes(DATA[pc + i] for i in range(n))
        if all(pc + i in WORDS for i in range(0, n, 4)) and not pc % 4:
            return b"".join(struct.pack("<I", WORDS[pc + i]) for i in range(0, n, 4))
        raise ValueError("unmapped %#x" % pc)


class StaleBound(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lift_fixes.install()

    def lifter(self):
        return a64_lift.Lifter(Image())

    def test_compare_above_a_b_does_not_bound_the_table(self):
        L = self.lifter()
        got = L.jump_table(S_BR, 10)
        self.assertIsNotNone(got)
        for t in S_CASES:
            self.assertIn(t, got, "case %#x lost: the table took a bound from code above a `b`" % t)
        self.assertEqual(L.stats["jt_bounded"], 0, "no bound reaches this br in its window")

    def test_a_bound_in_the_dispatch_block_still_applies(self):
        L = self.lifter()
        got = L.jump_table(B_BR, 10)
        self.assertEqual(got, B_CASES)
        self.assertEqual(L.stats["jt_bounded"], 1)


if __name__ == "__main__":
    unittest.main()
