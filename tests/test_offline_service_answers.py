"""The offline answers in host/nn_applet.c that Donkey Kong Bananza needs say "not here" the way the game handles it.

The generic stub answered 0 for each of these (success, with outputs left as they were), and the lifted SDK's
GetRequiredMemorySize asked a service through sm: and aborted. The fixture compiles the four answers, cut from the
source, over a stub context and guest memory, and checks:

- nn::streamplay::GetRequiredMemorySize: 0 bytes, said once in the log;
- nn::bcat::MountDeliveryCacheStorage: 0x47a (bcat module 122, description 2), said once;
- nn::account::LoadCachedNintendoAccountInfo: a failure in account module 124 with a description in 200..269, the
  family Bananza's call site (main 0x8048f460 on 3.2.0) tests for, and the outputs left alone;
- nn::account::GetLastOpenedUser: the uid TryOpenPreselectedUser's handle carries, the one user (user_uid).

Game-free. python -I -B tests/test_offline_service_answers.py [--cc gcc]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]
NAMES = {
    "memory": "HLE(_ZN2nn10streamplay21GetRequiredMemorySizeENS0_14StreamPlayTypeENS0_13StreamingModeEi) {",
    "bcat": "HLE(_ZN2nn4bcat25MountDeliveryCacheStorageEv) {",
    "cached": "HLE(_ZN2nn7account29LoadCachedNintendoAccountInfoEPNS0_25CachedNintendoAccountInfoERKNS0_10UserHandleEPvm) {",
    "last": "HLE(_ZN2nn7account17GetLastOpenedUserEPNS0_3UidE) {",
    "preselected": "HLE(_ZN2nn7account22TryOpenPreselectedUserEPNS0_10UserHandleE) {",
}
UID = "static const uint64_t user_uid[2] ="


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def function(source, marker):
    check(marker in source, "host/nn_applet.c has no '%s'" % marker)
    start = source.index(marker)
    return source[start:start + re.search(r"^}", source[start:], re.M).end()]


FIXTURE = r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef long LONG;
static LONG InterlockedExchange(volatile LONG *p, LONG v) { LONG o = *p; *p = v; return o; }
typedef struct { uint64_t x[32]; } Ctx;
static uint8_t mem[0x10000];   /* guest memory: addresses are offsets into it */
#define GP(a) ((void *)(mem + (a)))
#define G64(a) (*(uint64_t *)GP(a))
#define ARG(n) (c->x[n])
#define RET(v) (c->x[0] = (uint64_t)(v))
#define HLE(sym) static void imp_##sym(Ctx *c)
static int said;
static void hos_log(const char *fmt, ...) { (void)fmt; said++; }
@UID@
@FUNCTIONS@

int main(void) {
    Ctx c = {{0}};
    /* streamplay: no GameShare, no memory; the log says so once */
    c.x[0] = 1, c.x[1] = 1, c.x[2] = 4;
    imp__ZN2nn10streamplay21GetRequiredMemorySizeENS0_14StreamPlayTypeENS0_13StreamingModeEi(&c);
    CHECK(c.x[0] == 0 && said == 1);
    imp__ZN2nn10streamplay21GetRequiredMemorySizeENS0_14StreamPlayTypeENS0_13StreamingModeEi(&c);
    CHECK(c.x[0] == 0 && said == 1);
    /* bcat: no delivery cache */
    imp__ZN2nn4bcat25MountDeliveryCacheStorageEv(&c);
    CHECK(c.x[0] == 0x47a && (c.x[0] & 0x1ff) == 122 && ((c.x[0] >> 9) & 0x1fff) == 2 && said == 2);
    imp__ZN2nn4bcat25MountDeliveryCacheStorageEv(&c);
    CHECK(c.x[0] == 0x47a && said == 2);
    /* the cached Nintendo Account: a failure in the family the game tests, outputs untouched */
    memset(mem + 0x1000, 0xAB, 0x800);
    c.x[0] = 0x1000, c.x[1] = 0x2000, c.x[2] = 0x3000, c.x[3] = 0x800;
    imp__ZN2nn7account29LoadCachedNintendoAccountInfoEPNS0_25CachedNintendoAccountInfoERKNS0_10UserHandleEPvm(&c);
    const uint32_t r = (uint32_t)c.x[0], desc = (r >> 9) & 0x1ffe;   /* (as main 0x8048f464.. reads it) */
    CHECK(r != 0 && (r & 0x1ff) == 124 && desc - 200 < 70);
    for (int i = 0; i < 0x800; i++) CHECK(mem[0x1000 + i] == 0xAB);
    /* the last opened user is the preselected one */
    c.x[0] = 0x4000;
    imp__ZN2nn7account22TryOpenPreselectedUserEPNS0_10UserHandleE(&c);
    CHECK(c.x[0] == 1);
    c.x[0] = 0x5000;
    imp__ZN2nn7account17GetLastOpenedUserEPNS0_3UidE(&c);
    CHECK(c.x[0] == 0 && G64(0x5000) == G64(0x4000) && G64(0x5008) == G64(0x4008));
    CHECK(G64(0x5000) == user_uid[0] && G64(0x5008) == user_uid[1] && (user_uid[0] | user_uid[1]));
    puts("ok");
    return 0;
}
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default=os.environ.get("CC", "cc"))
    a = ap.parse_args()
    source = (ROOT / "host" / "nn_applet.c").read_text(encoding="utf-8")
    check(UID in source, "host/nn_applet.c has no '%s'" % UID)
    uid = source[source.index(UID):source.index(";", source.index(UID)) + 1]
    funcs = "\n".join(function(source, m) for m in NAMES.values())
    fixture = FIXTURE.replace("@UID@", uid).replace("@FUNCTIONS@", funcs)
    with tempfile.TemporaryDirectory(prefix="offline-answers-") as tmp:
        src, exe = Path(tmp, "offline.c"), Path(tmp, "offline")
        src.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Werror", "-Wno-unused-function", "-o", str(exe), str(src)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        check(r.returncode == 0 and r.stdout.strip() == "ok", "the fixture failed: %s%s" % (r.stdout, r.stderr))
    print("PASS: streamplay, BCAT and the account say \"not here\" the way the game handles it, the user is the one user")


if __name__ == "__main__":
    main()
