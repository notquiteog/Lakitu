"""The Insert menu's Frame generation by row (gpu/vk/framegen_methods.h): upstream's two values and AMD's two after them,
its stepping, and that the menu and vk_framegen.cpp use those rules rather than their own. No game or GPU required.

python -I -B tests/test_framegen_methods.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    with tempfile.TemporaryDirectory(prefix="framegen-methods-") as tmp:
        exe = Path(tmp) / "t"
        subprocess.run([a.cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(ROOT / "tests" / "test_framegen_methods.cpp"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    fg = (ROOT / "gpu" / "vk" / "vk_framegen.cpp").read_text(encoding="utf-8")
    fi = (ROOT / "gpu" / "vk" / "vk_fsr3fi.cpp").read_text(encoding="utf-8")
    for needle, where, what in (
            ('"Frame generation by", &opts.framegen_by, 0, framegen_methods::kMethods - 1', menu, "the row, with AMD's values"),
            ("return fgm::pick(fgm::effective(v, framegen_by_available()), want, dir, framegen_by_available());", menu,
             "the row choosing through framegen_methods.h"),
            ("if (r.value == &opts.framegen_by) v = framegen_by_pick(*r.value, v, dir);", menu, "set_row choosing that way"),
            ("const int e = fgm::effective(v, framegen_by_available());", menu, "the row showing the value in effect"),
            ("if (!who) return t[e];", menu, "the row's value in effect where no one is named at Auto"),
            ("opts.framegen_by = fgm::from_old(old_method)", menu, "an older file's Frame generation method"),
            ("fgm::effective(env_method >= 0 ? env_method : opts.framegen_by, fgm::available(framegen_here()))", fg,
             "vk_framegen.cpp choosing through framegen_methods.h"),
            ("ffx::max_frames()", fg, "FSR 4 frame generation within its limit"),
            ("set->made = dlss_fg_frames(", fg, "upstream's DLSS Frame Generation first, as upstream has it"),
            ("if (set->made == 0 && blend && mk > 1 && ffx_set_wanted(mk)) {\n        set->made = ffx_frames(cmd, *set, cur, uw, uh, mk - 1, sequence);",
             fg, "FSR 4 frame generation making the sets it makes whole, after DLSS's and before the renderer's own"),
            ("return opts.framegen_by == framegen_methods::FSR3 && opts.framegen == 2 ? 1u : 0u;", fi, "the row's AMD FSR 3.1 asking for it")):
        if needle not in where:
            raise SystemExit("missing: %s (%s)" % (what, needle))
    # (DLSS Frame Generation is Auto's alone, and Auto as the row shows it: a saved AMD method that does not run on this PC
    # is shown as Auto, and fg_asked takes it as Auto too, through framegen_by_auto, which asks the backends only for such
    # a saved choice)
    dlss = (ROOT / "gpu" / "vk" / "vk_dlss.cpp").read_text(encoding="utf-8")
    if "return fg_possible() && (forced || framegen_by_auto());" not in dlss:
        raise SystemExit("vk_dlss.cpp fg_asked no longer reads Frame generation by's Auto as the row shows it")
    by_auto = fg[fg.index("bool framegen_by_auto() {"):]
    by_auto = by_auto[:by_auto.index("\n}\n")]
    for needle in ("opts.framegen_by == fgm::AUTO || opts.framegen_by == fgm::BUILTIN", "return framegen_method() == fgm::AUTO;"):
        if needle not in by_auto:
            raise SystemExit("vk_framegen.cpp framegen_by_auto: missing %s" % needle)
    # (the choice is read each frame, so the menu's change reaches the next frame: not cached in a static)
    if "static const int chosen" in fg or "static int chosen" in fg:
        raise SystemExit("vk_framegen.cpp caches the method: a change in the menu would wait for a restart")
    print("PASS: the menu and frame generation take the row's value from framegen_methods.h, read live")


if __name__ == "__main__":
    main()
