"""An R_AARCH64_TLSDESC relocation is bound to the host's stop, not refused and not left as a jump to 0.

a64-kit's loader (third_party/a64-kit/hos/nx_image.py) takes RELATIVE, ABS64, GLOB_DAT and JUMP_SLOT and stops the whole
lift at anything else. A Switch 2 game can carry TLS descriptors (Kirby Air Riders has one, in NVIDIA's DLSS library),
so nx2/image.py's EdenImage binds each one's resolver word to a trampoline for host/hos_thread.c's
hos_tlsdesc_unsupported and its argument word to the descriptor's own address, which the stop names.

This runs the real EdenImage._relocate (and through it a64-kit's own) over an authored module: no dump. It checks that
the descriptor's two words are the stop's trampoline and the descriptor's address, that the trampoline is hooked to the
host function host/ defines, that the module's other relocations are applied as before, and that the module keeps no
TLSDESC entry for a64-kit's loop to refuse.

python -I -B tests/test_tlsdesc_stop.py
"""
import re
import struct
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
# (a64-kit's nso.py imports lz4 to decompress modules from a dump. This check builds its module by hand and decompresses
# nothing, and CI installs no lz4, so an empty stand-in is enough when the real package is not there)
try:
    import lz4.block  # noqa: F401
except ImportError:
    sys.modules["lz4"] = types.ModuleType("lz4")
    sys.modules["lz4.block"] = sys.modules["lz4"].block = types.ModuleType("lz4.block")
import image  # noqa: E402  (nx2/image.py: kit puts a64-kit on the path)
import nx_image  # noqa: E402

FAILURES = []


def check(cond, what):
    if not cond:
        FAILURES.append(what)


class Module(object):
    """Only what the relocation touches: a name, a base, symbols, relocations."""

    def __init__(self, name, base, relocs):
        self.name, self.base, self.symbols, self.relocs = name, base, [], relocs


def main():
    base = 0x80000000
    nx_image.MAIN_BASE = base
    img = object.__new__(image.EdenImage)   # (the relocation alone: no exefs to load)
    tls_at, rel_at = 0x100, 0x200
    img.modules = [Module("subsdk1", base, [
        {"offset": tls_at, "type": image.TLSDESC, "sym": None, "addend": 0},
        {"offset": rel_at, "type": "RELATIVE", "sym": None, "addend": 0x1234},
    ])]
    img.mem = bytearray(0x1000)
    img.hle, img.exports, img.hooks, img.hook_syms, img.tramp, img.unresolved = set(), {}, {}, {}, {}, {}
    img._relocate()
    resolver, argument = struct.unpack_from("<QQ", img.mem, tls_at)
    check(resolver and resolver in img.hooks, "the descriptor's resolver is not a hooked trampoline (%#x)" % resolver)
    check(img.hooks.get(resolver) == "imp_" + image.TLSDESC_STOP,
          "the descriptor's trampoline is not the host's stop (%r)" % img.hooks.get(resolver))
    check(argument == base + tls_at, "the descriptor's argument is not its own address (%#x)" % argument)
    check(struct.unpack_from("<Q", img.mem, rel_at)[0] == base + 0x1234, "the module's other relocation was not applied")
    check(all(r["type"] != image.TLSDESC for r in img.modules[0].relocs), "a TLSDESC entry was left for a64-kit to refuse")
    # a64-kit's parse names relocation types by its own table, R_AARCH64 in tools/nso.py, which calls 1030 (really
    # TLS_TPREL64) "TLSDESC" and leaves 1031 a bare number. Whatever it does with 1031, nx2/image.py's check must see it
    import nso
    parsed = nso.R_AARCH64.get(1031, 1031)
    check(parsed == image.TLSDESC,
          "a64-kit's parse turns R_AARCH64_TLSDESC (1031) into %r, which nx2/image.py does not match" % (parsed,))
    # the stop is a host function the runtime defines, under the name the trampoline calls
    host = (ROOT / "host" / "hos_thread.c").read_text(encoding="utf-8")
    check(re.search(r"^HLE\(%s\)" % image.TLSDESC_STOP, host, re.M),
          "host/hos_thread.c does not define HLE(%s)" % image.TLSDESC_STOP)
    for f in FAILURES:
        print("FAIL: " + f)
    if FAILURES:
        sys.exit(1)
    print("PASS: a TLS descriptor is bound to the host's stop; the other relocations as before")


if __name__ == "__main__":
    main()
