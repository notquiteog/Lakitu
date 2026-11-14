// (hookshot fork) The picture neural rendering is given, whichever backend runs (vk_dlssnr_ngx.cpp nr::apply):
//  - the picture's part of the game's window image alone. The game presents a part of a larger image (2048x1152 of
//    2560x1440 at the default output resolution): the model was run over all of it, a third of its time on pixels nobody
//    sees, and with what lay outside the picture in what it took the frame's tone from;
//  - the Resolution scale row (the Insert menu's Neural tab; nr_plan.h): the model on a smaller copy of the picture, and
//    its detail put back on the picture at full size.
#pragma once

#include <cstdint>

#include "vk_internal.h"

namespace mkwvk::nr_scale {

/// The picture (the x, y, w, h part of src: GENERAL, the game's window image) copied for the model, recorded into cmd: at
/// `percent` of its width and height (nr_plan.h scaled_side) when that is under 100, else as it is. This module's own
/// image, GENERAL, its size in lw and lh. Null when it could not be made: no model this frame
[[nodiscard]] VkImage take(VkCommandBuffer cmd, VkImage src, uint32_t x, uint32_t y, uint32_t w, uint32_t h, int percent,
                           uint32_t* lw, uint32_t* lh);
/// After a take under 100%, with the model's picture of the copy (model_view: lw x lh, GENERAL, written before this in
/// cmd): the picture with the model's detail added, w x h, this module's own image (GENERAL) and its view. Null: not made
[[nodiscard]] VkImage restore(VkCommandBuffer cmd, VkImageView model_view, VkImageView* out_view);
/// Its images and its pass let go. Before the device goes
void shutdown();

} // namespace mkwvk::nr_scale
