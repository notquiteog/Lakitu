"""The overlays' draw is left out, not a crash, while their vertex or index buffer cannot be made (nx2/imgui_backend.py).

Dear ImGui's Vulkan back end went on after a failed vkCreateBuffer, vkAllocateMemory or vkBindBufferMemory and copied the
frame's vertices through the null pointer its failed mapping left: an access violation when the Insert menu opened with
video memory used up (NX2navi's reports: an integrated AMD GPU and an RTX 2050). The build compiles the back end from a
copy with BACKEND_PATCHES applied (third_party/ stays upstream's). This compiles that copy with Dear ImGui's core and
tests/ui_backend_oom_test.cpp, whose fake Vulkan functions fail the memory on demand: the frame records no draw, maps
nothing that was not allocated, and a later frame allocates again and draws. The same fixture over the unpatched back end
must fail (it crashes in the copy). Each patch must still match upstream's file exactly once.

python -I -B tests/test_ui_backend_oom.py --headers <Vulkan headers> [--cxx g++]
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import imgui_backend  # noqa: E402

IMGUI = ROOT / "third_party" / "imgui"
DEFINES = ["-DIMGUI_IMPL_VULKAN_NO_PROTOTYPES", "-DIMGUI_DISABLE_DEFAULT_SHELL_FUNCTIONS", "-DIMGUI_DISABLE_WIN32_FUNCTIONS",
           "-DIMGUI_DISABLE_DEMO_WINDOWS", "-DIMGUI_DISABLE_DEBUG_TOOLS"]   # (nx2/build.py's imgui_flags)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--headers", type=Path, required=True, help="the Vulkan headers (their include folder or its parent)")
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    headers = a.headers / "include" if (a.headers / "include" / "vulkan").is_dir() else a.headers
    patched = imgui_backend.patched_source()   # (raises when a patch no longer matches exactly once)
    for old, new, why in imgui_backend.BACKEND_PATCHES:
        assert new in patched and old != new, why
    with tempfile.TemporaryDirectory(prefix="ui-backend-oom-") as tmp:
        tmp = Path(tmp)
        flags = ["-std=c++17", "-O1", "-g0", "-w", "-I" + str(headers), "-I" + str(IMGUI), "-I" + str(IMGUI / "backends")]
        flags += DEFINES
        objects = []
        for name in ("imgui.cpp", "imgui_draw.cpp", "imgui_tables.cpp", "imgui_widgets.cpp"):
            obj = tmp / (name[:-4] + ".o")
            objects.append(subprocess.Popen([a.cxx, *flags, "-c", str(IMGUI / name), "-o", str(obj)]))
        fixture = tmp / "fixture.o"
        objects.append(subprocess.Popen([a.cxx, *flags, "-c", str(ROOT / "tests" / "ui_backend_oom_test.cpp"), "-o", str(fixture)]))
        (tmp / "patched").mkdir()
        (tmp / "patched" / "imgui_impl_vulkan.cpp").write_text(patched, encoding="utf-8", newline="")
        builds = {"patched": tmp / "patched" / "imgui_impl_vulkan.cpp", "upstream": IMGUI / "backends" / "imgui_impl_vulkan.cpp"}
        for which, src in builds.items():
            objects.append(subprocess.Popen([a.cxx, *flags, "-c", str(src), "-o", str(tmp / (which + ".o"))]))
        for proc in objects:
            if proc.wait():
                raise SystemExit("FAIL: a compile failed")
        core = [str(tmp / (n + ".o")) for n in ("imgui", "imgui_draw", "imgui_tables", "imgui_widgets")]
        results = {}
        for which in builds:
            exe = tmp / (which + ".exe")
            subprocess.run([a.cxx, str(fixture), str(tmp / (which + ".o")), *core, "-o", str(exe)], check=True)
            results[which] = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        r = results["patched"]
        print(r.stdout, end="")
        if r.returncode:
            raise SystemExit("FAIL: the patched back end (exit %d)\n%s" % (r.returncode, r.stderr))
        if results["upstream"].returncode == 0:
            raise SystemExit("FAIL: the unpatched back end passed the same checks")
        print("PASS: the unpatched back end fails them (exit %d)" % results["upstream"].returncode)


if __name__ == "__main__":
    main()
