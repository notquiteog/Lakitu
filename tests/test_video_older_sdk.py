"""Mario Kart World 1.0.0's video decoder calls (SDK 21.4) that SDK 20's forms (tests/test_codec_sdk20_forms.py) leave out.

1.0.0's movie thread calls InitializeVp9Decoder, CalculateVp9DecoderWorkBuffer, GetVp9DecoderSubmissionReadyEvent
(through an out pointer), MakeDecodeImagePreference and InitializeDecoderImagePool with a CodecMode, which SDK 20's
forms answer, and three more: MakeDecodeImagePreferenceForCompat, InitializeVp8Decoder (with and without work memory)
and GetVp9DecoderOutputBufferProperties with a ColorSpace pointer. Without an HLE the generic stub answered 0 and the
thread stopped at svcBreak when a Grand Prix's opening movie started. The signatures and answers are mkw-recomp's
(adriadam10/mkw-recomp@5ff4fbb, runtime/sdk/ov/ov_codec.c, MIT).

Checked here, game-free: every name 1.0.0's movies need has an HLE; and the code of the three, cut from nn_video.c and
compiled with stand-ins: the ForCompat preference the same as the CodecMode one, and the properties with a ColorSpace
pointer (its index the ninth argument, from the guest stack, and pts and the last flag one argument on), beside the
form without one, which must not change.

python -I -B tests/test_video_older_sdk.py [--cc gcc]
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py)
from srccut import block   # noqa: E402

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]

OLDER = (
    "_ZN2nn5codec20InitializeVp9DecoderEPNS0_14Vp9DecoderTypeEPvmmttjNS0_23VideoDecoderInputFormatENS0_24VideoDecoderOutputFormatE",
    "_ZN2nn5codec20InitializeVp9DecoderEPNS0_14Vp9DecoderTypeEmmttjNS0_23VideoDecoderInputFormatENS0_24VideoDecoderOutputFormatE",
    "_ZN2nn5codec29CalculateVp9DecoderWorkBufferEPmS1_mtt",
    "_ZN2nn5codec33GetVp9DecoderSubmissionReadyEventEPPNS_2os15SystemEventTypeEPNS0_14Vp9DecoderTypeE",
    "_ZN2nn5codec25MakeDecodeImagePreferenceEttNS0_24VideoDecoderOutputFormatENS0_9CodecModeE",
    "_ZN2nn5codec3sdk34MakeDecodeImagePreferenceForCompatEttNS0_24VideoDecoderOutputFormatENS0_9CodecModeE",
    "_ZN2nn5codec26InitializeDecoderImagePoolEPNS0_25VideoDecoderImagePoolTypeEPvmRKNS0_27VideoDecoderImagePreferenceEjNS0_9CodecModeE",
    "_ZN2nn5codec35GetVp9DecoderOutputBufferPropertiesEPtS1_S1_S1_PNS_5movie10ColorSpaceEPNS_8TimeSpanEPbPNS0_14Vp9DecoderTypeEj",
    "_ZN2nn5codec20InitializeVp8DecoderEPNS0_14Vp8DecoderTypeEPvmmttjNS0_23VideoDecoderInputFormatENS0_24VideoDecoderOutputFormatE",
    "_ZN2nn5codec20InitializeVp8DecoderEPNS0_14Vp8DecoderTypeEmmttjNS0_23VideoDecoderInputFormatENS0_24VideoDecoderOutputFormatE",
)

HEAD = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef struct { uint64_t x[32]; } Ctx;
static uint8_t guest[0x10000];
#define GP(a) ((void *)(guest + (a)))
#define G64(a) (*(uint64_t *)GP(a))
#define G32(a) (*(uint32_t *)GP(a))
#define ARG(n) (c->x[n])
#define RET(v) (c->x[0] = (uint64_t)(v))
#define HLE(sym) void imp_##sym(Ctx *c)
#define MAX_SLOTS 16
#define PREF20_MAGIC 0x32465250u
#define DEC_MAGIC 1u
#define POOL_MAGIC 2u
typedef long LONG;
typedef struct { uint32_t magic; uint16_t w, h; uint16_t w_minus_1, h_minus_1; uint32_t format, mode; } Pref20;
typedef struct { int w, h; } Pool;
typedef struct { uint64_t slots[MAX_SLOTS]; int64_t slot_pts[MAX_SLOTS]; int slot_last[MAX_SLOTS]; } Dec;
static Dec dec;
static Pool pool = {640, 360};
static void *host_of(uint64_t obj, uint32_t magic) {
    if (magic == DEC_MAGIC && obj == 0x100) return &dec;
    if (magic == POOL_MAGIC && obj == 0x200) return &pool;
    return NULL;
}
static int video_log(void) { return 0; }
static LONG InterlockedIncrement(volatile LONG *p) { return ++*p; }
static void hos_log(const char *f, ...) { (void)f; }
'''

MAIN = r'''
int main(void) {
    Ctx c = {0};
    /* the ForCompat preference, returned through x8, the same as the CodecMode one */
    c.x[0] = 1280, c.x[1] = 720, c.x[2] = 2, c.x[3] = 1, c.x[8] = 0x1100;
    imp__ZN2nn5codec25MakeDecodeImagePreferenceEttNS0_24VideoDecoderOutputFormatENS0_9CodecModeE(&c);
    CHECK(c.x[0] == 0x1100);
    memset(&c, 0, sizeof c), c.x[0] = 1280, c.x[1] = 720, c.x[2] = 2, c.x[3] = 1, c.x[8] = 0x1200;
    imp__ZN2nn5codec3sdk34MakeDecodeImagePreferenceForCompatEttNS0_24VideoDecoderOutputFormatENS0_9CodecModeE(&c);
    const Pref20 *p = (const Pref20 *)GP(0x1200);
    CHECK(c.x[0] == 0x1200 && p->magic == PREF20_MAGIC && p->w == 1280 && p->h == 720 && p->format == 2);
    CHECK(memcmp(GP(0x1100), GP(0x1200), sizeof(Pref20)) == 0);
    /* decoded picture in buffer 3 */
    dec.slots[3] = 0x200, dec.slot_pts[3] = 123456, dec.slot_last[3] = 1;
    /* 1.0.0's properties: w, h, w, h, ColorSpace *, TimeSpan *, bool *, decoder, index on the stack */
    memset(guest + 0x2000, 0xee, 0x100);
    memset(&c, 0, sizeof c);
    c.x[0] = 0x2000, c.x[1] = 0x2002, c.x[2] = 0x2004, c.x[3] = 0x2006, c.x[4] = 0x2010, c.x[5] = 0x2020, c.x[6] = 0x2030;
    c.x[7] = 0x100, c.x[31] = 0x3000, G64(0x3000) = 3;
    imp__ZN2nn5codec35GetVp9DecoderOutputBufferPropertiesEPtS1_S1_S1_PNS_5movie10ColorSpaceEPNS_8TimeSpanEPbPNS0_14Vp9DecoderTypeEj(&c);
    CHECK(*(uint16_t *)GP(0x2000) == 640 && *(uint16_t *)GP(0x2002) == 360);
    CHECK(G32(0x2010) == 0);                         /* the colour space */
    CHECK((int64_t)G64(0x2020) == 123456);           /* pts, one argument on */
    CHECK(*(uint8_t *)GP(0x2030) == 1);              /* the last flag */
    CHECK(c.x[0] == 0);
    /* the form without a colour space, unchanged: w, h, w, h, TimeSpan *, bool *, decoder, index */
    memset(guest + 0x2000, 0xee, 0x100);
    memset(&c, 0, sizeof c);
    c.x[0] = 0x2000, c.x[1] = 0x2002, c.x[2] = 0x2004, c.x[3] = 0x2006, c.x[4] = 0x2020, c.x[5] = 0x2030;
    c.x[6] = 0x100, c.x[7] = 3, c.x[31] = 0x3000, G64(0x3000) = 9;
    dec_properties(&c);
    CHECK(*(uint16_t *)GP(0x2006) == 360 && (int64_t)G64(0x2020) == 123456 && *(uint8_t *)GP(0x2030) == 1);
    CHECK(*(uint8_t *)GP(0x2010) == 0xee);           /* nothing written where a colour space would be */
    puts("PASS: the older SDK's ForCompat preference and properties with a colour space");
    return 0;
}
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="gcc")
    a = ap.parse_args()
    src = (ROOT / "host" / "nn_video.c").read_text(encoding="utf-8")
    names = set(re.findall(r"^HLE\((\w+)\)", src, re.M))
    missing = [n for n in OLDER if n not in names]
    if missing:
        raise SystemExit("FAIL: host/nn_video.c has no HLE for the older SDK's %s" % ", ".join(missing))
    cut = "\n".join([
        block(src, "HLE(_ZN2nn5codec25MakeDecodeImagePreferenceEttNS0_24VideoDecoderOutputFormatENS0_9CodecModeE)",
              "host/nn_video.c"),
        block(src, "HLE(_ZN2nn5codec3sdk34MakeDecodeImagePreferenceForCompatEttNS0_24VideoDecoderOutputFormatENS0_9CodecModeE)",
              "host/nn_video.c"),
        "static void dec_properties_cs(Ctx *c, int colour_space);",
        block(src, "static void dec_properties(Ctx *c)", "host/nn_video.c"),
        block(src, "static void dec_properties_cs(Ctx *c, int colour_space) {", "host/nn_video.c"),
        block(src, "HLE(_ZN2nn5codec35GetVp9DecoderOutputBufferPropertiesEPtS1_S1_S1_PNS_5movie10ColorSpaceEPNS_8TimeSpanEPbPNS0_14Vp9DecoderTypeEj)",
              "host/nn_video.c"),
    ])
    with tempfile.TemporaryDirectory(prefix="video-older-sdk-") as tmp:
        c = Path(tmp) / "fixture.c"
        exe = Path(tmp) / "fixture"
        c.write_text(HEAD + cut + MAIN, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-O1", "-Wall", "-Wno-unused-function", str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise SystemExit(r.stdout + r.stderr)
        print(r.stdout.strip())


if __name__ == "__main__":
    main()
