"""Neural rendering's Passes and Resolution scale rows without a game or GPU (gpu/vk/nr_plan.h, checked by behaviour in
tests/test_nr_plan.cpp): which image each pass reads and writes, the local tone a pass is given, and the size the model
works at; and that the menu and the three backends take them from there.

python -I -B tests/test_nr_plan.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="nr-plan-") as tmp:
        exe = Path(tmp) / "nr-plan"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(ROOT / "tests" / "test_nr_plan.cpp"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
    header = (VK / "vk_menu.h").read_text(encoding="utf-8")
    ngx = (VK / "vk_dlssnr_ngx.cpp").read_text(encoding="utf-8")
    sl = (VK / "vk_dlssnr.cpp").read_text(encoding="utf-8")
    scale = (VK / "vk_nr_scale.cpp").read_text(encoding="utf-8")
    for needle, where, what in (
            ('{TAB_NEURAL, "Passes", &opts.nr_passes, 1, nr_plan::kMaxPasses, 1, tx_nr_passes', menu, "the Passes row"),
            ('{TAB_NEURAL, "Resolution scale", &opts.nr_scale, nr_plan::kMinScale, nr_plan::kMaxScale, 5, tx_nr_scale',
             menu, "the Resolution scale row"),
            ('if (r.value == &opts.nr_passes) return "nr_passes";', menu, "the Passes row's own key in the options file"),
            ('if (r.value == &opts.nr_scale) return "nr_scale";', menu, "the Resolution scale row's own key"),
            ("int nr_passes = 1;", header, "one pass by default"),
            ("int nr_scale = 100;", header, "the whole frame by default"),
            ("(unsigned)nr_plan::passes(opts.nr_passes)", header, "the settings read each frame carrying the passes"),
            # NGX direct: a feature a pass, the pair of images in turn, the first pass's local tone alone
            ("NVSDK_NGX_Handle* feature[nr_plan::kMaxPasses]{};", ngx, "NGX direct: a feature for each pass"),
            ("for (unsigned pass = 0; pass < want.passes; pass++) {", ngx, "NGX direct: the features made, one a pass"),
            ("s.features_asked == want.passes", ngx, "NGX direct: the features made again when the row changes"),
            ("Image& from = *pair[nr_plan::reads((int)pass)];", ngx, "NGX direct: a pass reading the pass before's picture"),
            ("Image& to = *pair[nr_plan::writes((int)pass)];", ngx, "NGX direct: and writing the other image"),
            ('"DLSSNR.LocalToneStrength", nr_plan::local_tone(want.local_tone, (int)pass)', ngx,
             "NGX direct: local tone on the first pass alone"),
            ("ngx::evaluate_feature(cmd, s.feature[pass], p)", ngx, "NGX direct: each pass through its own feature"),
            ("Image& result = *pair[nr_plan::result((int)s.features)];", ngx, "NGX direct: the last pass's picture shown"),
            # Streamline: a viewport a pass
            ("const sl::ViewportHandle viewport{kViewport + pass};", sl, "Streamline: a viewport for each pass"),
            ("o.localToneStrength = nr_plan::local_tone(want.local_tone, (int)pass);", sl,
             "Streamline: local tone on the first pass alone"),
            ("Image& picture = *pair[nr_plan::result((int)want.passes)];", sl, "Streamline: the last pass's picture shown"),
            # Resolution scale: whichever backend runs
            ("const PresentSourceRect picture = present_source_rect(sw, sh, crop);", ngx,
             "the picture's part of the window's image, not all of it"),
            ("if (whole && !nr_plan::scaled(percent)) return backend(src, sw, sh, out_view);", ngx,
             "the game's image itself when the picture is all of it, at 100%"),
            ("nr_scale::take(cmd, src, picture.x, picture.y, picture.w, picture.h, percent, &lw, &lh);", ngx,
             "the picture copied for the model, smaller under 100%"),
            ("return nr_scale::restore(cmd, model_view, out_view);", ngx, "the detail put back at full size"),
            ("cw = nr_plan::scaled_side(w, percent), ch = nr_plan::scaled_side(h, percent)", scale,
             "the copy's size from nr_plan.h"),
            ("b.srcOffsets[0] = {(int32_t)x, (int32_t)y, 0};", scale, "the copy taken from where the picture is")):
        if needle not in where:
            raise SystemExit("missing: %s (%s)" % (what, needle))
    # (a failed pass after the first keeps the passes made, and does not ask for the missing one again every frame)
    start = ngx.index("bool ensure_features(")
    body = ngx[start:ngx.index("\n}\n", start)]
    if "if (pass) {" not in body or "break;" not in body or "s.features_asked = want.passes;" not in body:
        raise SystemExit("vk_dlssnr_ngx.cpp ensure_features: a pass NGX cannot make must leave the earlier ones running")
    print("PASS: the menu, NGX direct, Streamline and the Resolution scale take the passes and sizes from nr_plan.h")


if __name__ == "__main__":
    main()
