// (hookshot fork) AMD FSR 4's frame generation, through AMD's own runtime and its FSR API (the "FidelityFX API":
// third_party/ffx-api): the Frame generation by row's "AMD FSR 4" (framegen_methods.h, vk_framegen.cpp).
//
// FSR 4's upscaler is upstream's engine on the temporal chain (gpu/vk/vk_fsr4.cpp, the Upscaler row's AMD FSR 4 and its
// native AA); this fork's own upscale through the same runtime is gone with it. What is here is what upstream has not:
// AMD's frame generation, which ships only inside AMD's signed runtime (amd_fidelityfx_framegeneration_vk.dll, reached
// through amd_fidelityfx_loader_vk.dll). Those are Windows DLLs: on Linux this backend answers "not here". Nothing is
// linked -- the loader is LoadLibrary'd from beside the game at run time (the folders vk_fsr4.cpp looks in, and
// RX_VK_FFX_DIR before them) -- so a PC without the DLLs runs exactly as before.
//
// The inputs are the scene's (gpu/vk/vk_fsr3_inputs.h: the depth reversed, the camera's motion in render pixels without
// the jitter, the jitter, the camera's planes and field of view from the scene's own projection), handed over as whole
// images: AMD's API takes resources (an image, its format and extent) rather than views, as NGX does. It is given the
// presented picture with the HUD on it and no picture without (there is none here), so it moves the HUD with the scene:
// a method for the player to choose, not Auto's (framegen_methods.h).
#pragma once

#include <cstdint>

#include "vk_internal.h"

namespace mkwvk::ffx {

/// One frame generation's inputs: vk_fsr3fi.h's, with the images the API needs.
struct FrameInputs {
    VkImage color = VK_NULL_HANDLE;   ///< the presented frame (RGBA8 UNORM, display size)
    VkFormat color_format = VK_FORMAT_UNDEFINED;
    uint32_t width = 0, height = 0;
    VkImage depth = VK_NULL_HANDLE;   ///< reversed: 1 at the near plane (vk_fsr3_inputs.h Frame)
    VkFormat depth_format = VK_FORMAT_UNDEFINED;
    VkImage motion = VK_NULL_HANDLE;  ///< render pixels, pointing at the previous frame, without the jitter
    VkFormat motion_format = VK_FORMAT_UNDEFINED;
    uint32_t render_width = 0, render_height = 0;
    float motion_scale[2]{1.0f, 1.0f};   ///< turns a motion vector into render pixels
    float jitter[2]{};                   ///< render pixels, x right and y down
    float near_plane = 0.1f;
    float far_plane = 0.0f;   ///< 0 or FLT_MAX: infinite (FFX_FRAMEGENERATION_ENABLE_DEPTH_INFINITE); the scene's is 1000.5
    float fov_y = 60.0f * 3.14159265358979f / 180.0f;
    float frame_time_ms = 16.667f;
    /// The camera in the world (camera_vectors.h: forward is the way it looks)
    float camera_position[3]{}, camera_right[3]{}, camera_up[3]{}, camera_forward[3]{};
    bool reset = false;
    /// The present's number (vk_framegen.cpp framegen_record's): one that does not follow the last made one is a reset
    uint64_t sequence = 0;
    uint32_t frames = 1;   ///< how many to make between the last frame and this one (1 to max_frames())
};

/// Whether this build has the backend at all: Windows only (AMD's runtime is Windows DLLs).
[[nodiscard]] bool built();
/// Asks AMD's runtime, once, what it offers on this device: called from vk_main.cpp right after the device is made, on the
/// render thread, with each call into the runtime logged first and guarded. frames_supported() only reads the answer
/// (false before it), so the Insert menu never waits on AMD's DLLs.
void probe();
/// Whether FSR 4 frame generation can run here: a Windows build, amd_fidelityfx_loader_vk.dll found and loaded, and AMD's
/// runtime naming a frame generation provider for this device. RX_VK_FFX=0 keeps the DLL from being loaded at all,
/// RX_VK_FFX_FG=0 leaves frame generation out.
[[nodiscard]] bool frames_supported();
/// The most made frames one dispatch is asked for: 1, or RX_VK_FFX_FG_MAX=<1-4> (AMD's API has four outputs; whether its
/// runtime fills more than one has not been seen here, and a refusal costs the frame its vendor method, so more than one
/// is a switch to try, not the default). 0 where frame generation is not supported.
[[nodiscard]] uint32_t max_frames();
/// Prepares and dispatches frame generation for in.frames made frames, into the backend's own images.
[[nodiscard]] bool generate(VkCommandBuffer cmd, const FrameInputs& in);
/// The k-th made frame (1-based) of the last generate(), RGBA8 UNORM at the display size, GENERAL.
[[nodiscard]] VkImage made_image(uint32_t k);
/// The next generate() starts again (a cut, a resize, frame generation turned off and on).
void reset();

/// Frees the context, the images and the DLL. Safe when nothing was made.
void shutdown();

} // namespace mkwvk::ffx
