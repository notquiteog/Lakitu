"""On Linux a null guest pointer faults, as on Windows and on the console: guest addresses below 1 MB are not mapped.

The Linux guest window is mapped readable and writable whole (host/hos_main.c), so before the guard a game's null
reads and writes went into guest page 0 silently and its crash came later and elsewhere. Windows never commits guest
addresses below 1 MB (host/mkw_glue.c commit_on_touch), so a null pointer faults where it is used.

This compiles host/hos_main.c's real guest_null_guard against a window of its own, then checks in child processes
that a read at guest 0x58 (a null object's field) dies of SIGSEGV, that a read at guest 1 MB does not, and that every
path that maps the window (the memfd one and the anonymous one) calls the guard.

python -I -B tests/test_linux_null_guard.py [--cc gcc]
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cc", "gcc"]
RUN_ALL_SKIP = {"windows": "the Linux window and mprotect: Windows leaves low guest memory uncommitted instead"}

FIXTURE = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>
static unsigned char *window;
#define A64_HOST_BASE window
static void hos_log(const char *f, ...) { va_list a; va_start(a, f); vfprintf(stderr, f, a); va_end(a); fputc('\n', stderr); }
@GUARD@
static int dies_reading(size_t at) {   /* 1: a read at guest `at` killed the child with SIGSEGV */
    const pid_t pid = fork();
    if (pid == 0) { volatile unsigned char v = window[at]; (void)v; _exit(0); }
    int status = 0;
    waitpid(pid, &status, 0);
    return WIFSIGNALED(status) && WTERMSIG(status) == SIGSEGV;
}
int main(void) {
    window = mmap(NULL, 4 << 20, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (window == MAP_FAILED) return 2;
    if (dies_reading(0x58)) { fprintf(stderr, "FAIL: the window faults before the guard\n"); return 1; }
    guest_null_guard();
    if (!dies_reading(0x58)) { fprintf(stderr, "FAIL: a null object's field (guest 0x58) reads without a fault\n"); return 1; }
    if (!dies_reading(0xfffff)) { fprintf(stderr, "FAIL: the last byte below 1 MB reads without a fault\n"); return 1; }
    if (dies_reading(0x100000)) { fprintf(stderr, "FAIL: guest 1 MB faults: the guard covers more than the null range\n"); return 1; }
    printf("PASS: guest addresses below 1 MB fault on Linux, the window above them does not\n");
    return 0;
}
'''


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    src = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    if "static void guest_null_guard(void) {" not in src:
        raise SystemExit("FAIL: host/hos_main.c has no guest_null_guard: a null guest pointer does not fault on Linux")
    guard = block(src, "static void guest_null_guard(void) {")
    if "mprotect(" not in guard or "0x100000" not in guard:
        raise SystemExit("FAIL: host/hos_main.c guest_null_guard no longer protects guest addresses below 1 MB")
    # every mapping of the guest window is followed by the guard: the memfd one and the anonymous one
    maps = [m.start() for m in re.finditer(r"mmap\(\(void \*\)A64_HOST_BASE, GUEST_SPACE", src)]
    if len(maps) < 2:
        raise SystemExit("FAIL: host/hos_main.c: the guest window's mappings were not found, so nothing could be checked")
    for at in maps:
        if "guest_null_guard();" not in src[at:at + 400]:
            raise SystemExit("FAIL: host/hos_main.c maps the guest window at offset %d without the null guard" % at)
    with tempfile.TemporaryDirectory(prefix="null-guard-") as tmp:
        c, exe = Path(tmp) / "fixture.c", Path(tmp) / "fixture"
        c.write_text(FIXTURE.replace("@GUARD@", guard), encoding="utf-8")
        subprocess.run([a.cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
