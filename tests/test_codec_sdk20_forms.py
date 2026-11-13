"""SDK 20's nn::codec forms (host/nn_video.c), which Donkey Kong Bananza 3.2.0 plays its guide movies through, write
only what is theirs.

Two things were checked against the game's code and are held here:
- SDK 20's MakeDecodeImagePreference fills a 64-byte preference (the SDK's own, sdk 0x82b0aa50, writes 64 bytes; the
  game's buffers are 72 and 64). The answer writes no more than 64, keeps width - 1 and height - 1 at +8 and +10 where
  the SDK does, and returns the buffer.
- SDK 20's InitializeDecoderImagePool owns 24 bytes of the pool object; the game keeps its own fields after them
  (+0x20 size, written by the game itself once the call succeeds). The answer writes nothing in the guest object:
  the pool is the runtime's, by address.

Also: CalculateDecoderImagePoolBuffer sizes a pool from either preference, and CalculateVp9DecoderWorkBuffer answers a
page and a page alignment. The fixture compiles the code cut from the source over stubs. Game-free.

python -I -B tests/test_codec_sdk20_forms.py [--cc gcc]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]
BLOCKS = [
    "#define PREF_MAGIC ",
    "typedef struct {\n    int w, h, format, count;",
    "typedef struct { uint32_t magic; uint16_t w, h; uint32_t format, tiling; } Pref;",
    "#define PREF20_MAGIC ",
    "typedef struct { uint32_t magic; uint16_t w, h; uint16_t w_minus_1, h_minus_1; uint32_t format, mode; } Pref20;",
    "_Static_assert(sizeof(Pref20) <= 64,",
]
FUNCTIONS = [
    "static void pool_init(Ctx *c, int pw, int ph, int format) {",
    "HLE(_ZN2nn5codec31CalculateDecoderImagePoolBufferEPmS1_RKNS0_27VideoDecoderImagePreferenceEj) {",
    "HLE(_ZN2nn5codec25MakeDecodeImagePreferenceEttNS0_24VideoDecoderOutputFormatENS0_9CodecModeE) {",
    "HLE(_ZN2nn5codec26InitializeDecoderImagePoolEPNS0_25VideoDecoderImagePoolTypeEPvmRKNS0_27VideoDecoderImagePreferenceEjNS0_9CodecModeE) {",
    "HLE(_ZN2nn5codec29CalculateVp9DecoderWorkBufferEPmS1_mtt) {",
]


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def line(source, marker):
    check(marker in source, "host/nn_video.c has no '%s'" % marker)
    start = source.index(marker)
    return source[start:source.index("\n", start)]


def block(source, marker):
    check(marker in source, "host/nn_video.c has no '%s'" % marker.splitlines()[0])
    start = source.index(marker)
    return source[start:start + re.search(r"^}[^\n]*", source[start:], re.M).end()]


FIXTURE = r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef struct { uint64_t x[32]; } Ctx;
static uint8_t mem[0x10000];
#define GP(a) ((void *)(mem + (a)))
#define G64(a) (*(uint64_t *)GP(a))
#define ARG(n) (c->x[n])
#define RET(v) (c->x[0] = (uint64_t)(v))
#define HLE(sym) static void imp_##sym(Ctx *c)
#define POOL_MAGIC 0x4c4f4f50u
static void hos_fatal(void *c, const char *m) { (void)c; fprintf(stderr, "%s\n", m); exit(2); }
static void hos_log(const char *f, ...) { (void)f; }
static int video_log(void) { return 0; }
static uint64_t host_obj; static uint32_t host_magic; static void *host_p;
static void set_host(uint64_t obj, uint32_t magic, void *p) { host_obj = obj, host_magic = magic, host_p = p; }
@BLOCKS@
@FUNCTIONS@

int main(void) {
    Ctx c = {{0}};
    /* the preference: at most 64 bytes, width - 1 and height - 1 at +8 / +10, the buffer returned */
    memset(mem + 0x1000, 0xAA, 0x100);
    c.x[0] = 960, c.x[1] = 540, c.x[2] = 3, c.x[3] = 1, c.x[8] = 0x1000;
    imp__ZN2nn5codec25MakeDecodeImagePreferenceEttNS0_24VideoDecoderOutputFormatENS0_9CodecModeE(&c);
    CHECK(c.x[0] == 0x1000);
    uint16_t a, b;
    memcpy(&a, mem + 0x1008, 2), memcpy(&b, mem + 0x100a, 2);
    CHECK(a == 959 && b == 539);
    for (int i = 64; i < 0x100; i++) CHECK(mem[0x1000 + i] == 0xAA);
    /* the pool: nothing written in the guest object, the runtime's pool at the preference's size */
    memset(mem + 0x2000, 0x5C, 0x100);
    c.x[0] = 0x2000, c.x[1] = 0x8000, c.x[2] = 0x1fb000, c.x[3] = 0x1000, c.x[4] = 1, c.x[5] = 1;
    imp__ZN2nn5codec26InitializeDecoderImagePoolEPNS0_25VideoDecoderImagePoolTypeEPvmRKNS0_27VideoDecoderImagePreferenceEjNS0_9CodecModeE(&c);
    CHECK(c.x[0] == 0 && host_obj == 0x2000 && host_magic == POOL_MAGIC && host_p);
    for (int i = 0; i < 0x100; i++) CHECK(mem[0x2000 + i] == 0x5C);
    const Pool *o = (const Pool *)host_p;
    CHECK(o->w == 960 && o->h == 540 && o->format == 3 && o->count == 1 && o->nv12 && o->mem == 0x8000);
    /* the pool's buffer from SDK 20's preference: w * h * 4 a picture, in pages */
    c.x[0] = 0x3000, c.x[1] = 0x3008, c.x[2] = 0x1000, c.x[3] = 2;
    imp__ZN2nn5codec31CalculateDecoderImagePoolBufferEPmS1_RKNS0_27VideoDecoderImagePreferenceEj(&c);
    CHECK(G64(0x3000) == ((960ull * 540 * 4 * 2 + 0xfff) & ~0xfffull) && G64(0x3008) == 0x1000);
    /* the VP9 work buffer: a page, page-aligned */
    c.x[0] = 0x3010, c.x[1] = 0x3018, c.x[2] = 0, c.x[3] = 960, c.x[4] = 540;
    imp__ZN2nn5codec29CalculateVp9DecoderWorkBufferEPmS1_mtt(&c);
    CHECK(c.x[0] == 0 && G64(0x3010) == 0x1000 && G64(0x3018) == 0x1000);
    puts("ok");
    return 0;
}
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default=os.environ.get("CC", "cc"))
    a = ap.parse_args()
    source = (ROOT / "host" / "nn_video.c").read_text(encoding="utf-8")
    blocks = "\n".join(block(source, m) if m.startswith("typedef struct {\n") else line(source, m) for m in BLOCKS)
    funcs = "\n".join(block(source, m) for m in FUNCTIONS)
    sdk20_pool = block(source, FUNCTIONS[3])
    check("ARG(0) +" not in sdk20_pool and "G64(ARG(0)" not in sdk20_pool and "G32(ARG(0)" not in sdk20_pool,
          "SDK 20's InitializeDecoderImagePool writes into the guest pool object again (the game owns +0x20 on)")
    fixture = FIXTURE.replace("@BLOCKS@", blocks).replace("@FUNCTIONS@", funcs)
    with tempfile.TemporaryDirectory(prefix="codec-sdk20-") as tmp:
        src, exe = Path(tmp, "codec.c"), Path(tmp, "codec")
        src.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Werror", "-Wno-unused-function", "-o", str(exe), str(src)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        check(r.returncode == 0 and r.stdout.strip() == "ok", "the fixture failed: %s%s" % (r.stdout, r.stderr))
    print("PASS: SDK 20's preference fits its 64 bytes, its pool leaves the game's fields alone, the sizes answer")


if __name__ == "__main__":
    main()
