"""A headless run leaves SIGINT and SIGTERM to end it, whichever SDL subsystem starts first.

SDL turns SIGINT/SIGTERM into its quit event unless SDL_NO_SIGNAL_HANDLERS is set when the first subsystem that brings
its events starts, and only the window's loop (host/posix/display_sdl.c) reads that event. pads_start sets the hint for
HOS_HEADLESS (tests/test_headless_sigterm.py), but the sound starts SDL first: nn_audio.c asks for the speakers' layout
(hos_sdl_audio_channels, SDL_InitSubSystem(AUDIO)) before its HOS_AUDIO=0 check and before the controllers start, and
SDL's handlers were in by then. A headless run then ignored `timeout`'s SIGTERM, Ctrl+C and a harness's SIGINT, and
went on until SIGKILL (seen in Ocarina, Mario Kart World, Kirby Air Riders and Donkey Kong Bananza runs).

This cuts hos_sdl_load and hos_sdl_init out of host/hos_sdl.c and compiles them against a fake SDL that records, at
each SDL_InitSubSystem, whether SDL_NO_SIGNAL_HANDLERS is "1" yet. For SDL3 and SDL2: headless, every start (the first
sound's included) must see it; with a window none may (the window's close on SIGTERM needs SDL's handlers).

    python -I -B tests/test_headless_sdl_signals.py [--cc gcc]
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
ENV_ON_H = ROOT / "gpu" / "vk" / "compat" / "hookshot_env.h"

FIXTURE = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef void *HMODULE;
typedef long LONG;
static LONG InterlockedCompareExchange(volatile LONG *p, LONG v, LONG cmp) { LONG o = *p; if (o == cmp) *p = v; return o; }
static LONG InterlockedExchange(volatile LONG *p, LONG v) { LONG o = *p; *p = v; return o; }
static void Sleep(int ms) { (void)ms; }
static void hos_log(const char *fmt, ...) { (void)fmt; }

static int version;
static struct { void *InitSubSystem, *SetHint, *GetError; } f;
#define CALL(type, fn) ((type)f.fn)

static char no_signal_handlers[8];
static int starts, starts_with_hint, fake_version;
static int set_hint(const char *name, const char *value) {
    if (!strcmp(name, "SDL_NO_SIGNAL_HANDLERS")) snprintf(no_signal_handlers, sizeof no_signal_handlers, "%s", value);
    return 1;
}
static int init_subsystem(uint32_t subsystems) {   /* (SDL2's form: 0 for success; SDL3's bool 1 is read as true) */
    (void)subsystems;
    starts++;
    starts_with_hint += !strcmp(no_signal_handlers, "1");
    return fake_version == 3;
}
static HMODULE load_one(const char *dll) {
    return (fake_version == 3) == (strcmp(dll, "SDL3.dll") == 0) ? (HMODULE)&f : NULL;
}
static int get_all(HMODULE m, int three) {
    (void)m, (void)three;
    f.InitSubSystem = (void *)init_subsystem, f.SetHint = (void *)set_hint;
    return 1;
}

/* ACTUAL_SDL_LOAD */

int main(int argc, char **argv) {
    fake_version = atoi(argv[1]);
    const int headless = atoi(argv[2]);
    (void)argc;
    if (!hos_sdl_load()) { puts("no SDL loaded"); return 2; }
    hos_sdl_init(0x10);       /* the sound, first, as nn_audio.c's speakers' layout */
    hos_sdl_init(0x2000);     /* the controllers */
    printf("SDL%d %s: %d of %d starts with SDL_NO_SIGNAL_HANDLERS=1\n", fake_version, headless ? "headless" : "window",
           starts_with_hint, starts);
    return headless ? starts_with_hint != starts : starts_with_hint != 0;
}
"""


def function(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default=os.environ.get("CC") or shutil.which("gcc") or shutil.which("clang") or "cc")
    parser.add_argument("--source", type=Path, default=ROOT / "host" / "hos_sdl.c")
    args = parser.parse_args()
    if not shutil.which(args.cc):
        print("headless sdl signals: skipped (no C compiler %s)" % args.cc)
        return 0
    source = args.source.read_text(encoding="utf-8")
    code = function(source, "int hos_sdl_load(void)") + "\n\n" + function(source, "int hos_sdl_init(uint32_t subsystems)")
    with tempfile.TemporaryDirectory(prefix="hookshot-sdl-signals-") as temp:
        c_file, exe = Path(temp) / "fixture.c", Path(temp) / "fixture"
        c_file.write_text(FIXTURE.replace("/* ACTUAL_SDL_LOAD */", code), encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-include", str(ENV_ON_H), "-O0", "-Wall", "-Werror", "-Wno-unused-function",
                        "-o", str(exe), str(c_file)], check=True)
        failed = 0
        for sdl in (3, 2):
            for headless in (1, 0):
                env = dict(os.environ)
                env.pop("HOS_HEADLESS", None)
                if headless:
                    env["HOS_HEADLESS"] = "1"
                r = subprocess.run([str(exe), str(sdl), str(headless)], env=env, capture_output=True, text=True)
                print(r.stdout.strip())
                if r.returncode:
                    failed += 1
        if failed:
            print("FAIL: %d case(s): headless, SDL's own SIGINT/SIGTERM handlers come in with its first subsystem "
                  "(the sound's), and the run ignores those signals; with a window they must stay" % failed)
            return 1
    print("PASS: headless, SDL_NO_SIGNAL_HANDLERS is set before SDL's first subsystem starts; with a window it is not")
    return 0


if __name__ == "__main__":
    sys.exit(main())
