"""The scene's camera in the world without a game or GPU (gpu/vk/camera_vectors.h, checked by behaviour in
tests/test_camera_vectors.cpp): its position and its right, up and forward axes from the projection and view-projection the
renderer keeps; and that vk_framegen.cpp hands AMD FSR 4's frame generation those.

python -I -B tests/test_camera_vectors.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="camera-vectors-") as tmp:
        exe = Path(tmp) / "camera-vectors"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(ROOT / "tests" / "test_camera_vectors.cpp"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    fg = (ROOT / "gpu" / "vk" / "vk_framegen.cpp").read_text(encoding="utf-8")
    start = fg.index("int ffx_frames(")
    body = fg[start:fg.index("\n}\n", start)]
    for needle, what in (
            ("camera_vectors::from(f.projection, f.view_projection, camera)", "the camera through camera_vectors.h"),
            ("in.camera_forward[c] = camera.forward[c]", "forward the way the camera looks"),
            ("if (!ffx::made_image((uint32_t)k)) return 0;", "no half-made set")):
        if needle not in body:
            raise SystemExit("vk_framegen.cpp ffx_frames: missing %s (%s)" % (what, needle))
    print("PASS: vk_framegen.cpp gives AMD FSR 4's frame generation camera_vectors.h's camera")


if __name__ == "__main__":
    main()
