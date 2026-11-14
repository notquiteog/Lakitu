/* (hookshot fork) Neural rendering's Passes and Resolution scale rows (the Insert menu's Neural tab), as plain functions:
   no Vulkan, no NGX. tests/test_nr_plan.cpp checks them.

   Both are the settings the RenoDX DLSS add-on has under the same names (its DirectNeuralRenderingPassCount, 1 to 10,
   and DirectNeuralRenderingProcessingScale, a percentage).

   Passes: the model goes over the frame that many times, each pass on the picture of the one before. Every pass is a
   feature of its own (the model keeps a history, and one feature evaluated twice a frame would be handed its own output
   as the next frame), and the passes read and write a pair of images in turn: pass n reads image n % 2 and writes the
   other, so the last one's picture is image passes % 2. Passes after the first are given no local tone: the tone would
   otherwise be applied again by every pass (the default of the multipass integrations this follows,
   wilsjo2/OptiScaler-DLSSNR-PreSR-Multipass and those after it).

   Resolution scale: below 100% the model is given the frame at that share of its width and height, and its detail (its
   picture less the small frame, both stretched back) is added to the full-size frame: vk_nr_scale.h. */
#pragma once

#include <cstdint>

namespace mkwvk::nr_plan {

constexpr int kMaxPasses = 10;
/// The Passes row's value as a count: 1 to kMaxPasses (an older file without the row: 1)
inline int passes(int row) { return row < 1 ? 1 : row > kMaxPasses ? kMaxPasses : row; }
/// The local tone strength pass `pass` (0 the first) is given
inline float local_tone(float strength, int pass) { return pass == 0 ? strength : 0.0f; }
/// Of the pair of images, the one pass `pass` reads, the one it writes, and the one that holds the last pass's picture
inline int reads(int pass) { return pass & 1; }
inline int writes(int pass) { return (pass + 1) & 1; }
inline int result(int passes) { return passes & 1; }

constexpr int kMinScale = 50, kMaxScale = 100;
/// The Resolution scale row's value in percent: kMinScale to 100 (under half, a plain two-tap reduction would skip pixels)
inline int scale(int row) { return row < kMinScale ? kMinScale : row > kMaxScale ? kMaxScale : row; }
/// Whether the model works on a smaller copy at this scale
inline bool scaled(int row) { return scale(row) < kMaxScale; }
/// A side of the smaller copy for a side of the frame: rounded, even, at least 16 and never more than the frame's
inline uint32_t scaled_side(uint32_t full, int row) {
    const uint64_t v = ((uint64_t)full * (uint64_t)scale(row) + 50) / 100;
    uint32_t side = (uint32_t)((v + 1) & ~1ull);
    if (side < 16) side = 16;
    return side > full ? full : side;
}

} // namespace mkwvk::nr_plan
