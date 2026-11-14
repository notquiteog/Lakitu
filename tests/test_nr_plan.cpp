// (hookshot fork) gpu/vk/nr_plan.h: neural rendering's Passes and Resolution scale rows (tests/test_nr_plan.py)
#include <cstdio>
#include <initializer_list>
#include "../gpu/vk/nr_plan.h"

namespace np = mkwvk::nr_plan;
static int failures;
#define CHECK(name, c) do { if (!(c)) { std::printf("FAIL: %s\n", name); ++failures; } } while (0)

int main() {
    // Passes: 1 to 10, as the RenoDX DLSS add-on's pass count
    CHECK("the row's range", np::kMaxPasses == 10 && np::passes(1) == 1 && np::passes(10) == 10 && np::passes(4) == 4);
    CHECK("an older file, or nonsense, is one pass or the most", np::passes(0) == 1 && np::passes(-3) == 1 && np::passes(99) == 10);
    // the pair of images: pass n reads image n % 2 and writes the other; the result is the last one written
    for (int passes = 1; passes <= np::kMaxPasses; passes++) {
        int holds = 0;   // (the image with the newest picture: the frame is copied into image 0)
        for (int pass = 0; pass < passes; pass++) {
            CHECK("a pass reads the newest picture", np::reads(pass) == holds);
            CHECK("and writes the other image", np::writes(pass) == 1 - holds && np::writes(pass) != np::reads(pass));
            holds = np::writes(pass);
        }
        CHECK("the result is the last pass's image", np::result(passes) == holds);
    }
    CHECK("one pass: in to out, as before the row", np::reads(0) == 0 && np::writes(0) == 1 && np::result(1) == 1);
    // local tone: the first pass's alone
    CHECK("the first pass has the row's local tone", np::local_tone(0.7f, 0) == 0.7f && np::local_tone(0.0f, 0) == 0.0f);
    CHECK("later passes have none", np::local_tone(0.7f, 1) == 0.0f && np::local_tone(1.0f, 9) == 0.0f);
    // Resolution scale: 50 to 100 percent
    CHECK("the row's range", np::kMinScale == 50 && np::kMaxScale == 100 && np::scale(75) == 75 && np::scale(100) == 100);
    CHECK("out of range", np::scale(0) == 50 && np::scale(49) == 50 && np::scale(250) == 100 && np::scale(-5) == 50);
    CHECK("100% is the frame itself", !np::scaled(100) && !np::scaled(150) && np::scaled(95) && np::scaled(50) && np::scaled(0));
    CHECK("a side at a scale", np::scaled_side(2048, 50) == 1024 && np::scaled_side(1152, 50) == 576 &&
                                   np::scaled_side(2560, 75) == 1920 && np::scaled_side(1440, 75) == 1080 &&
                                   np::scaled_side(3840, 100) == 3840);
    for (int row = 50; row <= 100; row += 5)
        for (uint32_t full : {16u, 17u, 360u, 719u, 1080u, 1152u, 1440u, 2160u, 2880u, 16384u}) {
            const uint32_t side = np::scaled_side(full, row);
            CHECK("never more than the frame", side <= full);
            CHECK("even, unless the frame's own odd side", side % 2 == 0 || side == full);
            CHECK("at least 16, or the frame", side >= 16 || side == full);
            // (within a pixel and a rounding of the share asked)
            const double want = (double)full * row / 100.0;
            // (but for a frame so small that the 16 pixel floor decides)
            CHECK("the share asked", want < 16.0 || ((double)side >= want - 1.5 && (double)side <= want + 1.5));
        }
    CHECK("a tiny frame is not shrunk under 16", np::scaled_side(20, 50) == 16 && np::scaled_side(8, 50) == 8);
    CHECK("no overflow at the largest sides", np::scaled_side(4294967295u, 50) >= 2147483646u);
    if (failures) return 1;
    std::printf("PASS: the passes' images and local tone, and the Resolution scale's sizes\n");
    return 0;
}
