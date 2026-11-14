"""A linked pipeline the worker's full build replaces is destroyed once the GPU is past every submission that may have bound
it (gpu/vk/vk_draw.cpp fast_retire, fast_reap; no game/GPU).

With stage libraries (RX_VK_GPL) a draw's first pipeline is linked from them and the full build takes its place in the
entry. The linked one was never destroyed, so each pipeline a run drew held the driver memory of two (NX2navi, chrg6,
commit bc28416: 907 replaced, 491 MiB). The two functions are compiled as they are in vk_draw.cpp over a stand-in timeline:
a replaced pipeline waits for the newest value handed out when it was replaced, not one before; it goes once the timeline
reaches it, once; with no timeline it is kept. The worker's job must exchange the entry's pipeline and retire what it
held, and the frame statistics must count it.

python -I -B tests/test_gpl_fast_retire.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <mutex>
#include <set>
#include <vector>
using VkPipeline = uint64_t;
#define VK_NULL_HANDLE 0
struct { int device; } dev;
uint64_t handed_out, completed_value;
uint64_t vk_values_handed_out() { return handed_out; }
uint64_t vk_timeline_completed() { return completed_value; }
std::multiset<VkPipeline> destroyed;
void vkDestroyPipeline(int, VkPipeline p, void*) { destroyed.insert(p); }
@CODE@
#define CHECK(x) do { if (!(x)) { std::printf("FAIL line %d: %s\n", __LINE__, #x); return 1; } } while (0)
int main() {
    completed_value = 7, handed_out = 10;
    fast_retire(101);   // (recordings up to 10 may hold it: 8, 9 and 10 are not done)
    CHECK(destroyed.empty() && st_fast_replaced == 1);
    completed_value = 9, fast_reap();
    CHECK(destroyed.empty());
    handed_out = 12;
    fast_retire(102);
    completed_value = 10, fast_reap();
    CHECK(destroyed.count(101) == 1 && !destroyed.count(102) && st_fast_given_back == 1);
    completed_value = 12, fast_reap(), fast_reap();
    CHECK(destroyed.count(101) == 1 && destroyed.count(102) == 1 && st_fast_given_back == 2);   // (once each)
    completed_value = 0, handed_out = 5;   // (no timeline: nothing is known to be done)
    fast_retire(103), fast_reap();
    CHECK(!destroyed.count(103) && st_fast_replaced == 3);
    std::puts("PASS: a replaced linked pipeline is destroyed once, when the GPU is past every submission that may hold it");
    return 0;
}
"""


def between(text, start, end):
    a = text.index(start)
    return text[a:text.index(end, a)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    code = between(draw, "struct FastRetired {", "\nPipeEntry* graphics_pipeline(")
    job = between(draw, "    jobs_push([job] {\n        // (over a linked one", "}, false, &e->ready,")
    if "if (const VkPipeline linked = job->e->pipeline.exchange(full)) fast_retire(linked);" not in job:
        raise SystemExit("FAIL: the full build does not hand the linked pipeline it replaces to fast_retire")
    stats = between(draw, "bool draw_stats4(", "\n}\n")
    if "fast_reap();" not in stats or "*fast_given_back = st_fast_given_back.load()" not in stats:
        raise SystemExit("FAIL: the frame statistics neither give back the replaced pipelines the GPU is done with nor count them")
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    if "uint64_t vk_values_handed_out() { return q_values.load(); }" not in replay:
        raise SystemExit("FAIL: vk_values_handed_out is not the newest fence value handed out")
    with tempfile.TemporaryDirectory(prefix="gpl-fast-retire-") as tmp:
        tmp = Path(tmp)
        (tmp / "t.cpp").write_text(FIXTURE.replace("@CODE@", code), encoding="utf-8")
        exe = tmp / "gpl-fast-retire"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(tmp / "t.cpp"), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        print(r.stdout, end="")
        if r.returncode:
            raise SystemExit("FAIL: fast_retire / fast_reap")


if __name__ == "__main__":
    main()
