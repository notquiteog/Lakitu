// (hookshot) DLSS 5 neural rendering through NGX directly; gpu/vk/vk_dlssnr_ngx.h says why there are two paths and where
// the parameter names come from (openNR, MIT). Everything that touches NGX is inside HOOKSHOT_NGX; the stubs at the bottom
// of the first namespace are what a build without an NGX SDK compiles, and `nr::` dispatches either way.
#include "vk_dlssnr_ngx.h"
#include "vk_opennr.h"   // (the Backend row's fourth value)

#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include "nr_plan.h"       // (the Passes and Resolution scale rows)
#include "vk_dlssnr.h"
#include "vk_menu.h"
#include "vk_nr_scale.h"   // (the picture's part of the frame, and the Resolution scale: whichever backend runs)
#include "vk_present_rect.h"
#include "vk_streamline.h"
#include "vk_texture.h"   // (texture_frame_no: whether the model ran at the frame before)

#if defined(HOOKSHOT_NGX)
#include "vk_dlss.h"   // (dlss_ngx_session, dlss_ngx_runtime: the one NGX session and the folders it was given)
#include "vk_ngx.h"
#if defined(_WIN32)
#include <windows.h>
#if defined(RX_VK_STREAMLINE)
// (only where the Streamline build already links wintrust and crypt32: nx2/build.py streamline_link)
#include <softpub.h>
#include <wincrypt.h>
#include <wintrust.h>
#endif
#endif
#endif
#include "vk_work.h"   // (after the others: its commands through the recorder, counted as work for full_barrier)

namespace mkwvk::dlssnr_ngx {
namespace {

/// The same switch as the Streamline path's (dlssnr::asked), read live every call: the row the player just changed has to
/// reach the next frame (tests/test_nr_settings_live.py says why that matters here).
bool asked() {
    if (const char* e = getenv("RX_VK_DLSS_NR")) return atoi(e) != 0;
    return nr_settings().on;
}

} // namespace

#if defined(HOOKSHOT_NGX)

namespace {

constexpr NVSDK_NGX_Feature kFeature = NVSDK_NGX_Feature_Reserved18;
#if defined(_WIN32)
constexpr const char* kRuntime = "nvngx_dlssnr.dll";
#else
constexpr const char* kRuntime = "libnvidia-ngx-dlssnr.so";   // (NGX's Linux name for a feature: libnvidia-ngx-<name>.so*)
#endif

// The capability keys. The public SDK defines none for this feature; these follow the naming every NGX feature's keys use
// (SuperSampling.Available, FrameGeneration.FeatureInitResult, ...), and the first two are the ones the Linux NGX core
// answers for. A key NGX does not set is reported as not answered, never guessed at.
constexpr const char* kAvailable = "DLSSNR.Available";
constexpr const char* kInitResult = "DLSSNR.FeatureInitResult";
constexpr const char* kNeedsDriver = "DLSSNR.NeedsUpdatedDriver";
constexpr const char* kDriverMajor = "DLSSNR.MinDriverVersionMajor";
constexpr const char* kDriverMinor = "DLSSNR.MinDriverVersionMinor";

// The working formats: eight bits a channel, as the Streamline path uses and as the window's image already is, so the two
// backends are handed the same picture; a flat float depth and two-channel float motion, as DLSS's own inputs are.
constexpr VkFormat kColorFormat = VK_FORMAT_R8G8B8A8_UNORM;
constexpr VkFormat kDepthFormat = VK_FORMAT_R32_SFLOAT;
constexpr VkFormat kMotionFormat = VK_FORMAT_R16G16_SFLOAT;
constexpr VkImageSubresourceRange kOneLevel{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
/// Failures after which the path stays off for the run instead of trying again at every change of a row.
constexpr int kMaxFailures = 6;

struct Image {
    VkImage image{};
    VkImageView view{};
    VmaAllocation memory{};
};

struct State {
    bool probed{}, ok{};
    std::string why;
    NVSDK_NGX_Parameter* params{};
    // One feature a pass (nr_plan.h: each keeps its own history). features: how many were made; features_asked: for how
    // many passes, which is more when NGX would not make them all (video memory): the row is then not asked again for
    // the same count at every frame
    NVSDK_NGX_Handle* feature[nr_plan::kMaxPasses]{};
    unsigned features{}, features_asked{};
    uint32_t feature_w{}, feature_h{};
    unsigned feature_preset{}, feature_quality{};
    // (in and out are the pair the passes read and write in turn: nr_plan.h reads / writes)
    Image in{}, out{}, depth{}, motion{};
    uint32_t width{}, height{};
    bool scene_cleared{};
    bool reset_next{true};
    // A setting NGX would not take is the player's to change: it is held against those exact settings and that size, so
    // changing any row tries again, and after kMaxFailures the path is off for the run.
    bool have_rejected{};
    NrSettings rejected{};
    uint32_t rejected_w{}, rejected_h{};
    int failures{};
    bool explained{};
    std::atomic<bool> failed{};
    bool told_running{};
};

State& state() {
    static State s;
    return s;
}

void drop(Image& t) {
    if (t.view) vkDestroyImageView(dev.device, t.view, nullptr);
    if (t.image) destroy_image(t.image, t.memory);
    t = Image{};
}

bool make(Image& t, VkFormat format, uint32_t w, uint32_t h, VkImageUsageFlags usage) {
    drop(t);
    VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    ci.imageType = VK_IMAGE_TYPE_2D;
    ci.format = format;
    ci.extent = {w, h, 1};
    ci.mipLevels = 1;
    ci.arrayLayers = 1;
    ci.samples = VK_SAMPLE_COUNT_1_BIT;
    ci.tiling = VK_IMAGE_TILING_OPTIMAL;
    ci.usage = usage;
    ci.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    if (!create_image(ci, t.image, t.memory, false)) {
        logf("vk: dlss-nr (ngx): a %ux%u image was not made", w, h);
        return false;
    }
    VkImageViewCreateInfo vi{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
    vi.image = t.image;
    vi.viewType = VK_IMAGE_VIEW_TYPE_2D;
    vi.format = format;
    vi.subresourceRange = kOneLevel;
    if (vkCreateImageView(dev.device, &vi, nullptr, &t.view) != VK_SUCCESS) {
        logf("vk: dlss-nr (ngx): an image's view was not made");
        drop(t);
        return false;
    }
    return true;
}

void barrier(VkCommandBuffer cmd, VkImage image, VkImageLayout from, VkImageLayout to, VkAccessFlags2 src_access,
             VkAccessFlags2 dst_access) {
    VkImageMemoryBarrier2 b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2};
    b.srcStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
    b.dstStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
    b.srcAccessMask = src_access;
    b.dstAccessMask = dst_access;
    b.oldLayout = from;
    b.newLayout = to;
    b.srcQueueFamilyIndex = b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.image = image;
    b.subresourceRange = kOneLevel;
    VkDependencyInfo di{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
    di.imageMemoryBarrierCount = 1;
    di.pImageMemoryBarriers = &b;
    vkCmdPipelineBarrier2(cmd, &di);
}

/// The device idle, for freeing what a frame in flight may still use. Not a bare vkDeviceWaitIdle: vk_dlssnr.cpp's resize
/// says why (every queue externally synchronized; apply runs on the display thread before present_image takes the lock).
void idle() {
    std::lock_guard qk(dev.present_mu);
    device_wait_idle_locked();
}

// ---- the platform's half of why it was refused ----

#if defined(_WIN32)
/// The RTX generation from the device's name (vk_streamline.cpp's rule): 50, 40, 30, 20, or 0 when not recognized.
int rtx_series() {
    VkPhysicalDeviceProperties p{};
    vkGetPhysicalDeviceProperties(dev.physical, &p);
    const char* n = strstr(p.deviceName, "RTX ");
    if (!n || n[4] < '0' || n[4] > '9' || n[5] < '0' || n[5] > '9') return 0;
    const int series = (n[4] - '0') * 10;
    return series >= 20 && series <= 50 ? series : 0;
}

/// NVIDIA's NGX signature override as the player set it: read only, never written. -1 when it is not there.
int signature_override() {
    DWORD value = 0, size = sizeof value;
    if (RegGetValueW(HKEY_LOCAL_MACHINE, L"SOFTWARE\\NVIDIA Corporation\\Global\\NGXCore", L"EnableSignatureOverride",
                     RRF_RT_REG_DWORD, nullptr, &value, &size) != ERROR_SUCCESS)
        return -1;
    return (int)value;
}

/// 1 when Windows trusts the file's signature, 0 when it does not (a patched nvngx_dlssnr.dll has none), -1 where this
/// build cannot ask (no wintrust linked: a build without Streamline's headers).
int signed_file(const std::string& utf8) {
#if defined(RX_VK_STREAMLINE)
    std::wstring path(utf8.size() + 1, L'\0');
    const int n = MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), (int)utf8.size(), path.data(), (int)path.size());
    path.resize(n > 0 ? n : 0);
    WINTRUST_FILE_INFO file{};
    file.cbStruct = sizeof file;
    file.pcwszFilePath = path.c_str();
    GUID action = WINTRUST_ACTION_GENERIC_VERIFY_V2;
    WINTRUST_DATA data{};
    data.cbStruct = sizeof data;
    data.dwUIChoice = WTD_UI_NONE;
    data.fdwRevocationChecks = WTD_REVOKE_NONE;
    data.dwUnionChoice = WTD_CHOICE_FILE;
    data.pFile = &file;
    data.dwStateAction = WTD_STATEACTION_VERIFY;
    const LONG status = WinVerifyTrust(nullptr, &action, &data);
    data.dwStateAction = WTD_STATEACTION_CLOSE;
    WinVerifyTrust(nullptr, &action, &data);
    return status == ERROR_SUCCESS ? 1 : 0;
#else
    (void)utf8;
    return -1;
#endif
}
#endif

/// Why NGX said no (`result`: the feature's init result or CreateFeature's answer), in the log in full and for the menu in
/// short. Once: the first refusal is the one worth explaining.
void explain(State& s, unsigned result, bool needs_driver, unsigned major, unsigned minor) {
    if (s.explained) return;
    s.explained = true;
    std::string where, found;
    const bool have = dlss_ngx_runtime(kRuntime, &where, &found);
    if (needs_driver) {
        logf("vk: DLSS 5 neural rendering (NGX direct): NGX says this driver is too old (%u.%u or newer wanted)", major,
             minor);
        s.why = "Not available: NVIDIA's driver is too old for DLSS 5 neural rendering.";
        return;
    }
#if defined(_WIN32)
    const int series = rtx_series();
    const int signature = have ? signed_file(found) : -1;
    const int override_value = signature_override();
    logf("vk: DLSS 5 neural rendering (NGX direct) is not available here (NGX result %#x). GPU: %s; %s: %s; NGX signature "
         "override: %s",
         result, series ? (series == 50 ? "RTX 50" : series == 40 ? "RTX 40" : series == 30 ? "RTX 30" : "RTX 20")
                        : "not recognized as RTX 20 to 50",
         kRuntime,
         !have ? ("in none of " + where).c_str()
               : (found + (signature == 1 ? " (NVIDIA's, signed)" : signature == 0 ? " (unsigned: a patched build)" : ""))
                     .c_str(),
         override_value < 0 ? "not set" : override_value ? "on" : "off");
    if (!have) {
        logf("vk:   put nvngx_dlssnr.dll in the game folder's ngx folder, or in one of: %s (readme.md: DLSS 5 neural "
             "rendering)", where.c_str());
        s.why = "Not available: no nvngx_dlssnr.dll in the game folder's ngx folder (readme).";
    } else if (series && series < 50 && signature != 0) {
        logf("vk:   NVIDIA's own nvngx_dlssnr.dll runs on RTX 50 only. On an RTX %d, a community build of it that adds "
             "Turing, Ampere and Ada is needed instead, and NGX loads that unsigned file only with its signature override "
             "on: HKLM\\SOFTWARE\\NVIDIA Corporation\\Global\\NGXCore, DWORD EnableSignatureOverride = 1 (readme.md). "
             "Hookshot reads it and never sets it", series);
        s.why = "Not available: NVIDIA's model is RTX 50 only. RTX 20-40: a patched nvngx_dlssnr.dll (readme).";
    } else if (signature == 0 && override_value <= 0) {
        logf("vk:   this nvngx_dlssnr.dll is unsigned, and NGX loads an unsigned one only with its signature override on: "
             "HKLM\\SOFTWARE\\NVIDIA Corporation\\Global\\NGXCore, DWORD EnableSignatureOverride = 1 (readme.md). "
             "Hookshot does not change it for you");
        s.why = "Not available: the patched nvngx_dlssnr.dll needs NGX's signature override (readme).";
    } else {
        s.why = "Not available on this GPU or driver (the log says what NGX answered).";
    }
#else
    if (!have) {
        logf("vk: DLSS 5 neural rendering (NGX direct): NVIDIA has not shipped it for Linux yet. NGX knows the feature (NGX "
             "result %#x), but there is no %s to load: the driver has none and NVIDIA's SDK ships none (looked in %s too). "
             "On Linux, run the Windows build under Proton for it (readme.md). The day NVIDIA ships the library, putting "
             "it in the game folder's ngx folder should be all this needs",
             result, kRuntime, where.c_str());
        s.why = "Not on Linux yet: NVIDIA ships no Linux library for it. The Windows build under Proton has it.";
    } else {
        logf("vk: DLSS 5 neural rendering (NGX direct): NGX refused %s (NGX result %#x)", found.c_str(), result);
        s.why = "Not available: NGX refused libnvidia-ngx-dlssnr.so (the log says why).";
    }
#endif
}

/// Asks NGX once, after the device exists, whether the feature is here. False until then, without asking.
bool probe(State& s) {
    if (s.probed) return s.ok;
    if (!dev.device) return false;
    s.probed = true;
    if (dlss_why() == DLSS_ENV_OFF) {
        logf("vk: DLSS 5 neural rendering (NGX direct): NGX is off for this run (RX_VK_DLSS=0)");
        s.why = "Not available: NGX is off for this run (RX_VK_DLSS=0).";
        return false;
    }
    if (!dlss_ngx_session()) {
        logf("vk: DLSS 5 neural rendering (NGX direct): no NGX session on this device (the NVIDIA DLSS lines say why)");
        s.why = "Not available: NGX did not start on this GPU (NVIDIA RTX only).";
        return false;
    }
    NVSDK_NGX_Parameter* caps = nullptr;
    if (NVSDK_NGX_FAILED(NVSDK_NGX_VULKAN_GetCapabilityParameters(&caps)) || !caps) {
        logf("vk: DLSS 5 neural rendering (NGX direct): NGX gave no capability parameters");
        s.why = "Not available: NGX gave no capabilities on this GPU.";
        return false;
    }
    // (NGX's C functions, not NVSDK_NGX_Parameter's virtual ones: vk_dlss.cpp ngx_init says why)
    int available = 0, init = 0, needs_driver = 0;
    unsigned major = 0, minor = 0;
    const bool available_known = NVSDK_NGX_SUCCEED(NVSDK_NGX_Parameter_GetI(caps, kAvailable, &available));
    const bool init_known = NVSDK_NGX_SUCCEED(NVSDK_NGX_Parameter_GetI(caps, kInitResult, &init));
    const bool driver_known = NVSDK_NGX_SUCCEED(NVSDK_NGX_Parameter_GetI(caps, kNeedsDriver, &needs_driver));
    NVSDK_NGX_Parameter_GetUI(caps, kDriverMajor, &major);
    NVSDK_NGX_Parameter_GetUI(caps, kDriverMinor, &minor);
    NVSDK_NGX_VULKAN_DestroyParameters(caps);
    char a[16], r[16];
    snprintf(a, sizeof a, "%d", available);
    snprintf(r, sizeof r, "%#x", (unsigned)init);
    logf("vk: DLSS 5 neural rendering (NGX direct): NGX answers %s = %s, %s = %s%s", kAvailable,
         available_known ? a : "(not answered)", kInitResult, init_known ? r : "(not answered)",
         driver_known && needs_driver ? ", and says the driver is too old" : "");
    if (available_known && available) {
        logf("vk: DLSS 5 neural rendering (NGX direct) is available on this device");
        s.ok = true;
        return true;
    }
    if (!available_known) {
        // A core that does not answer for the feature at all may still create it (openNR's benchmark never asks): the
        // creation's own answer is then the one explained.
        logf("vk: DLSS 5 neural rendering (NGX direct): NGX does not answer for the feature; it is tried at the first "
             "frame and its answer is what counts");
        s.ok = true;
        return true;
    }
    explain(s, init_known ? (unsigned)init : 0u, driver_known && needs_driver, major, minor);
    return false;
}

/// NGX asks the feature's caller for the ratio of output to input through this; it is always 1 here, the uplift being
/// at the size it is shown (openNR answers the same).
NVSDK_NGX_Result NVSDK_CONV compute_scaling_ratio(NVSDK_NGX_Parameter* params) {
    if (!params) return NVSDK_NGX_Result_FAIL_InvalidParameter;
    NVSDK_NGX_Parameter_SetF(params, "DLSSNR.ScalingRatio", 1.0f);
    return NVSDK_NGX_Result_Success;
}

/// The sizes, at creation and again at every evaluation (openNR sets both): input and output are one size here.
void set_sizes(NVSDK_NGX_Parameter* p, uint32_t w, uint32_t h) {
    NVSDK_NGX_Parameter_SetUI(p, NVSDK_NGX_Parameter_Width, w);
    NVSDK_NGX_Parameter_SetUI(p, NVSDK_NGX_Parameter_Height, h);
    NVSDK_NGX_Parameter_SetUI(p, NVSDK_NGX_Parameter_OutWidth, w);
    NVSDK_NGX_Parameter_SetUI(p, NVSDK_NGX_Parameter_OutHeight, h);
    NVSDK_NGX_Parameter_SetUI(p, "DLSSNR.Width", w);
    NVSDK_NGX_Parameter_SetUI(p, "DLSSNR.Height", h);
    NVSDK_NGX_Parameter_SetUI(p, "DLSSNR.InputWidth", w);
    NVSDK_NGX_Parameter_SetUI(p, "DLSSNR.InputHeight", h);
    NVSDK_NGX_Parameter_SetUI(p, "DLSSNR.OutputWidth", w);
    NVSDK_NGX_Parameter_SetUI(p, "DLSSNR.OutputHeight", h);
    NVSDK_NGX_Parameter_SetUI(p, "DLSSNR.Output.Width", w);
    NVSDK_NGX_Parameter_SetUI(p, "DLSSNR.Output.Height", h);
}

void set_subrect(NVSDK_NGX_Parameter* p, const char* which, uint32_t w, uint32_t h) {
    // ("DLSSNR.ColorSubrectBaseX" and its siblings, for each of the four images)
    const struct {
        const char* field;
        uint32_t value;
    } fields[] = {{"BaseX", 0u}, {"BaseY", 0u}, {"Width", w}, {"Height", h}};
    for (const auto& f : fields) {
        char key[64];
        snprintf(key, sizeof key, "DLSSNR.%sSubrect%s", which, f.field);
        NVSDK_NGX_Parameter_SetUI(p, key, f.value);
    }
}

/// Holds a refusal against these settings and this size, and turns the path off after too many.
void refused(State& s, const NrSettings& want, uint32_t w, uint32_t h) {
    s.have_rejected = true;
    s.rejected = want;
    s.rejected_w = w, s.rejected_h = h;
    if (++s.failures >= kMaxFailures) {
        logf("vk: DLSS 5 neural rendering (NGX direct): refused %d times, off for this run", s.failures);
        s.failed.store(true, std::memory_order_relaxed);
    }
}

void release_features(State& s) {
    if (!s.features) return;
    idle();
    for (unsigned i = 0; i < s.features; i++) ngx::release_feature(s.feature[i]), s.feature[i] = nullptr;
    s.features = s.features_asked = 0;
}

/// The parameters a feature is made with, for this size, preset and quality.
void set_creation(NVSDK_NGX_Parameter* p, const NrSettings& want, uint32_t w, uint32_t h) {
    NVSDK_NGX_Parameter_SetUI(p, NVSDK_NGX_Parameter_CreationNodeMask, 1u);
    NVSDK_NGX_Parameter_SetUI(p, NVSDK_NGX_Parameter_VisibilityNodeMask, 1u);
    set_sizes(p, w, h);
    // 0 is the model's default; 1 to 7 pin presets A to G (docs/neural-rendering.md: a default of 1 silently pins A).
    NVSDK_NGX_Parameter_SetUI(p, "DLSSNR.Hint.Render.Preset", want.preset);
    // The quality is an sl::DLSSMode (1 performance, 2 balanced, 3 quality, 6 DLAA); NGX's PerfQualityValue is that less
    // one (NVSDK_NGX_PerfQuality_Value_MaxPerf 0 ... _DLAA 5), as openNR sends it.
    NVSDK_NGX_Parameter_SetI(p, NVSDK_NGX_Parameter_PerfQualityValue, (int)want.quality - 1);
    NVSDK_NGX_Parameter_SetVoidPointer(p, "DLSSNRComputeScalingRatioCallback", (void*)&compute_scaling_ratio);
    NVSDK_NGX_Parameter_SetF(p, "DLSSNR.ScalingRatio", 1.0f);
    NVSDK_NGX_Parameter_SetF(p, "DLSSNR.Scale", 1.0f);
    NVSDK_NGX_Parameter_SetI(p, "DLSSNR.Upscaling", 0);
}

/// The features, one a pass (the Passes row), made for this size, preset and quality: those are creation parameters, so
/// a change of any of them, or of the count, makes them again. Creation records into `cmd`. False when not even the
/// first could be made; when a later one could not (each holds the model's memory again), the passes that were made run
/// and the log says how many.
bool ensure_features(State& s, VkCommandBuffer cmd, const NrSettings& want, uint32_t w, uint32_t h) {
    if (s.features && s.features_asked == want.passes && s.feature_w == w && s.feature_h == h &&
        s.feature_preset == want.preset && s.feature_quality == want.quality)
        return true;
    release_features(s);
    if (!s.params) s.params = ngx::allocate_params();
    if (!s.params) {
        s.failed.store(true, std::memory_order_relaxed);
        return false;
    }
    NVSDK_NGX_Parameter* p = s.params;
    for (unsigned pass = 0; pass < want.passes; pass++) {
        set_creation(p, want, w, h);
        NVSDK_NGX_Handle* handle = nullptr;
        const NVSDK_NGX_Result res = ngx::create_feature(cmd, kFeature, p, &handle);
        if (NVSDK_NGX_FAILED(res) || !handle) {
            if (handle) ngx::release_feature(handle);
            if (pass) {   // (the first passes stand: the rest are left out, and said)
                logf("vk: DLSS 5 neural rendering (NGX direct): pass %u of %u was refused (%#x: each pass holds the model "
                     "again): %u pass(es) run", pass + 1, want.passes, (unsigned)res, pass);
                break;
            }
            logf("vk: DLSS 5 neural rendering (NGX direct): CreateFeature(18) refused %ux%u, preset %u, quality %u (%#x)",
                 w, h, want.preset, want.quality, (unsigned)res);
            if (res == NVSDK_NGX_Result_FAIL_PlatformError)
                logf("vk:   FAIL_PlatformError: usually a device made without the feature's extensions (the \"dlss-nr "
                     "wants\" lines at start-up), or a model file this GPU cannot run");
            explain(s, (unsigned)res, false, 0, 0);
            refused(s, want, w, h);
            return false;
        }
        s.feature[s.features++] = handle;
    }
    s.features_asked = want.passes;
    s.feature_w = w, s.feature_h = h;
    s.feature_preset = want.preset, s.feature_quality = want.quality;
    s.reset_next = true;
    s.why.clear();
    logf("vk: DLSS 5 neural rendering (NGX direct): %u feature(s) ready (Passes %u), %ux%u, preset %u, quality %u",
         s.features, want.passes, w, h, want.preset, want.quality);
    return true;
}

bool resize(State& s, uint32_t w, uint32_t h) {
    idle();
    constexpr VkImageUsageFlags color = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_STORAGE_BIT |
                                        VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    constexpr VkImageUsageFlags scene = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    if (!make(s.in, kColorFormat, w, h, color) || !make(s.out, kColorFormat, w, h, color) ||
        !make(s.depth, kDepthFormat, w, h, scene) || !make(s.motion, kMotionFormat, w, h, scene)) {
        drop(s.in), drop(s.out), drop(s.depth), drop(s.motion);
        return false;
    }
    s.width = w, s.height = h, s.scene_cleared = false;
    return true;
}

/// Depth and motion, once per size: one flat depth at mid-scene and no motion (vk_dlssnr.cpp clear_scene says why), left
/// in GENERAL as NGX takes every image.
void clear_scene(VkCommandBuffer cmd, State& s) {
    for (VkImage i : {s.depth.image, s.motion.image})
        barrier(cmd, i, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 0, VK_ACCESS_2_TRANSFER_WRITE_BIT);
    VkClearColorValue flat{};
    flat.float32[0] = 0.5f;
    vkCmdClearColorImage(cmd, s.depth.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &flat, 1, &kOneLevel);
    const VkClearColorValue none{};
    vkCmdClearColorImage(cmd, s.motion.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &none, 1, &kOneLevel);
    for (VkImage i : {s.depth.image, s.motion.image})
        barrier(cmd, i, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_2_TRANSFER_WRITE_BIT,
                VK_ACCESS_2_SHADER_READ_BIT);
}

} // namespace

bool built_with_sdk() { return true; }

bool capable() {
    State& s = state();
    return probe(s) && !s.failed.load(std::memory_order_relaxed);
}

const char* why() {
    State& s = state();
    (void)probe(s);   // (the menu asks before any frame has: the answer is NGX's either way, and asked once)
    return s.why.c_str();
}

size_t device_extensions(VkInstance instance, VkPhysicalDevice gpu, const char** out, size_t max) {
    // Asked whatever the switch says: the device is made before a player can turn the row on, and a device without these
    // could never run the feature this session. RX_VK_DLSS_NR=0 (or RX_VK_DLSS=0, which leaves NGX off) asks nothing.
    if (const char* e = getenv("RX_VK_DLSS_NR"); e && atoi(e) == 0) return 0;
    if (const char* e = getenv("RX_VK_DLSS"); e && *e && atoi(e) == 0) return 0;
    return ngx::device_extensions(instance, gpu, kFeature, out, max);
}

void history_gap() { state().reset_next = true; }

VkImage apply(VkCommandBuffer cmd, VkImage src, uint32_t sw, uint32_t sh, VkImageView* out_view) {
    State& s = state();
    if (!src || !sw || !sh || !asked()) return VK_NULL_HANDLE;
    if (s.failed.load(std::memory_order_relaxed) || !probe(s)) return VK_NULL_HANDLE;
    const NrSettings want = nr_settings();
    if (s.have_rejected && s.rejected == want && s.rejected_w == sw && s.rejected_h == sh) return VK_NULL_HANDLE;

    if ((!s.out.image || s.width != sw || s.height != sh) && !resize(s, sw, sh)) {
        s.failed.store(true, std::memory_order_relaxed);
        return VK_NULL_HANDLE;
    }
    if (!s.scene_cleared) {
        clear_scene(cmd, s);
        s.scene_cleared = true;
    }
    if (!ensure_features(s, cmd, want, sw, sh)) return VK_NULL_HANDLE;

    // The window's image into ours, read in place (GENERAL is a layout a blit may read from): the game's is only read.
    barrier(cmd, src, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL,
            VK_ACCESS_2_COLOR_ATTACHMENT_WRITE_BIT | VK_ACCESS_2_SHADER_WRITE_BIT | VK_ACCESS_2_TRANSFER_WRITE_BIT,
            VK_ACCESS_2_TRANSFER_READ_BIT);
    barrier(cmd, s.in.image, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 0,
            VK_ACCESS_2_TRANSFER_WRITE_BIT);
    VkImageBlit b{};
    b.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    b.dstSubresource = b.srcSubresource;
    b.srcOffsets[1] = {(int32_t)sw, (int32_t)sh, 1};
    b.dstOffsets[1] = b.srcOffsets[1];
    vkCmdBlitImage(cmd, src, VK_IMAGE_LAYOUT_GENERAL, s.in.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b,
                   VK_FILTER_NEAREST);
    barrier(cmd, s.in.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_2_TRANSFER_WRITE_BIT,
            VK_ACCESS_2_SHADER_READ_BIT);
    barrier(cmd, s.out.image, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, 0,
            VK_ACCESS_2_SHADER_WRITE_BIT | VK_ACCESS_2_SHADER_READ_BIT);

    // The evaluation's parameters: openNR's set, by name (vk_dlssnr_ngx.h). The resources must outlive the call, which
    // these do; the UI pair is set to null rather than left from before, a parameter block being reused.
    // One evaluation a pass (the Passes row; nr_plan.h): each with its own feature, reading the picture the pass before
    // wrote, the two images in turn.
    NVSDK_NGX_Parameter* p = s.params;
    Image* const pair[2] = {&s.in, &s.out};
    NVSDK_NGX_Resource_VK motion = ngx::resource(s.motion.view, s.motion.image, kMotionFormat, sw, sh, false);
    NVSDK_NGX_Resource_VK depth = ngx::resource(s.depth.view, s.depth.image, kDepthFormat, sw, sh, false);
    for (unsigned pass = 0; pass < s.features; pass++) {
        Image& from = *pair[nr_plan::reads((int)pass)];
        Image& to = *pair[nr_plan::writes((int)pass)];
        if (pass)   // (the pass before wrote `from`, and read `to`, which this one writes)
            for (Image* i : pair)
                barrier(cmd, i->image, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL,
                        VK_ACCESS_2_SHADER_WRITE_BIT | VK_ACCESS_2_SHADER_READ_BIT,
                        VK_ACCESS_2_SHADER_READ_BIT | VK_ACCESS_2_SHADER_WRITE_BIT);
        NVSDK_NGX_Resource_VK color = ngx::resource(from.view, from.image, kColorFormat, sw, sh, false);
        NVSDK_NGX_Resource_VK output = ngx::resource(to.view, to.image, kColorFormat, sw, sh, true);
        set_sizes(p, sw, sh);
        NVSDK_NGX_Parameter_SetVoidPointer(p, "DLSSNR.Color", &color);
        NVSDK_NGX_Parameter_SetVoidPointer(p, "DLSSNR.Output", &output);
        NVSDK_NGX_Parameter_SetVoidPointer(p, "DLSSNR.MVec", &motion);
        NVSDK_NGX_Parameter_SetVoidPointer(p, "DLSSNR.Depth", &depth);
        NVSDK_NGX_Parameter_SetVoidPointer(p, "DLSSNR.UI", nullptr);
        NVSDK_NGX_Parameter_SetVoidPointer(p, "DLSSNR.UIAlpha", nullptr);
        for (const char* which : {"Color", "Output", "MVec", "Depth"}) set_subrect(p, which, sw, sh);
        // No camera: an identity one with no jitter and no motion is the honest description of a finished frame
        // (vk_dlssnr.cpp scene_constants).
        NVSDK_NGX_Parameter_SetF(p, NVSDK_NGX_Parameter_Jitter_Offset_X, 0.0f);
        NVSDK_NGX_Parameter_SetF(p, NVSDK_NGX_Parameter_Jitter_Offset_Y, 0.0f);
        NVSDK_NGX_Parameter_SetF(p, "DLSSNR.JitterOffsetX", 0.0f);
        NVSDK_NGX_Parameter_SetF(p, "DLSSNR.JitterOffsetY", 0.0f);
        NVSDK_NGX_Parameter_SetF(p, "DLSSNR.MVecScaleX", 1.0f);
        NVSDK_NGX_Parameter_SetF(p, "DLSSNR.MVecScaleY", 1.0f);
        NVSDK_NGX_Parameter_SetI(p, "DLSSNR.DepthInverted", 0);
        NVSDK_NGX_Parameter_SetI(p, "DLSSNR.Enabled", 1);
        NVSDK_NGX_Parameter_SetI(p, "DLSSNR.Reset", s.reset_next ? 1 : 0);
        NVSDK_NGX_Parameter_SetF(p, "DLSSNR.Intensity", want.intensity);
        // (passes after the first are given no local tone: it would be applied again by each, nr_plan.h)
        NVSDK_NGX_Parameter_SetF(p, "DLSSNR.LocalToneStrength", nr_plan::local_tone(want.local_tone, (int)pass));
        NVSDK_NGX_Parameter_SetF(p, "DLSSNR.LocalStructureStrength", want.local_structure);
        NVSDK_NGX_Parameter_SetF(p, "DLSSNR.GlobalToneStrength", want.global_tone);
        NVSDK_NGX_Parameter_SetI(p, "DLSSNR.UseAutoMask", want.auto_mask ? 1 : 0);
        NVSDK_NGX_Parameter_SetF(p, "DLSSNR.SkinStructureStrength", want.skin);
        NVSDK_NGX_Parameter_SetUI(p, "DLSSNR.Style", want.style);
        NVSDK_NGX_Parameter_SetI(p, "DLSSNR.UICorrection", 0);   // (no UI layer handed over: there is none to correct)
        NVSDK_NGX_Parameter_SetI(p, "DLSS.Indicator.Invert.X.Axis", 0);
        NVSDK_NGX_Parameter_SetI(p, "DLSS.Indicator.Invert.Y.Axis", 0);
        const NVSDK_NGX_Result res = ngx::evaluate_feature(cmd, s.feature[pass], p);
        if (NVSDK_NGX_FAILED(res)) {
            logf("vk: DLSS 5 neural rendering (NGX direct): pass %u's evaluation was refused (%#x); waiting for a setting "
                 "to change", pass + 1, (unsigned)res);
            refused(s, want, sw, sh);
            return VK_NULL_HANDLE;
        }
    }
    s.reset_next = false;
    if (!s.told_running) {
        s.told_running = true;
        logf("vk: DLSS 5 neural rendering (NGX direct) runs over %ux%u frames, %u pass(es) a frame", sw, sh, s.features);
    }
    // The last pass's picture: the caller presents it instead of the game's image.
    Image& result = *pair[nr_plan::result((int)s.features)];
    barrier(cmd, result.image, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_2_SHADER_WRITE_BIT,
            VK_ACCESS_2_TRANSFER_READ_BIT | VK_ACCESS_2_SHADER_READ_BIT);
    if (out_view) *out_view = result.view;
    return result.image;
}

void shutdown() {
    State& s = state();
    release_features(s);
    ngx::destroy_params(s.params);
    s.params = nullptr;
    if (s.in.image || s.out.image) idle();
    drop(s.in), drop(s.out), drop(s.depth), drop(s.motion);
    s.width = s.height = 0;
    s.scene_cleared = false;
}

#else // no NGX SDK

bool built_with_sdk() { return false; }
bool capable() { return false; }
const char* why() { return ""; }
size_t device_extensions(VkInstance, VkPhysicalDevice, const char**, size_t) { return 0; }
VkImage apply(VkCommandBuffer, VkImage, uint32_t, uint32_t, VkImageView*) {
    (void)asked;
    return VK_NULL_HANDLE;
}
void history_gap() {}
void shutdown() {}

#endif

} // namespace mkwvk::dlssnr_ngx

namespace mkwvk::nr {

// (the open backend, OpenDLSS-NR, is in every build: so is the Neural tab)
bool built() { return true; }

bool wanted() {
    if (const char* e = getenv("RX_VK_DLSS_NR")) return atoi(e) != 0;
    return nr_settings().on;
}

int asked_backend() {
    // Live, every call, like the switch: the row changes the next frame.
    if (const char* e = getenv("RX_VK_DLSS_NR_BACKEND"); e && *e) {
        if (!strcmp(e, "streamline") || !strcmp(e, "1")) return STREAMLINE;
        if (!strcmp(e, "ngx") || !strcmp(e, "2")) return NGX;
        if (!strcmp(e, "open") || !strcmp(e, "3")) return OPEN;
        return AUTO;
    }
    if (const char* e = getenv("RX_VK_NR_BACKEND"); e && !strcmp(e, "open")) return OPEN;
    return opts.nr_backend >= STREAMLINE && opts.nr_backend <= OPEN ? opts.nr_backend : AUTO;
}

int running_backend() {
    const int b = asked_backend();
    if (b != AUTO) return b;
    if (streamline::nr_available()) return STREAMLINE;
    // (NGX direct where it can run; the open network where the device was made for it, which it is when a model folder
    // was there at the start; else NGX direct, whose refusal says why)
    if (dlssnr_ngx::built_with_sdk() && !*dlssnr_ngx::why()) return NGX;
    if (opennr::ready()) return OPEN;
    return dlssnr_ngx::built_with_sdk() ? NGX : STREAMLINE;
}

VkImage apply(VkCommandBuffer cmd, VkImage src, uint32_t sw, uint32_t sh, const int crop[4], VkImageView* out_view,
              uint32_t* out_w, uint32_t* out_h) {
    static int told = -1;
    const int b = running_backend();
    if (b != told && nr_settings().on) {
        told = b;
        logf("vk: DLSS 5 neural rendering through %s (Backend: %s)",
             b == NGX ? "NGX directly" : b == OPEN ? "OpenDLSS-NR" : "Streamline",
             asked_backend() == AUTO ? "Auto" : b == NGX ? "NGX direct" : b == OPEN ? "Open" : "Streamline");
    }
    // (the model's own history is the frame before's only when it ran then: after the row was off, a stretch of Native
    // HDR, another backend or a refusal held, what it kept is a picture from before, and the first frame back would blend
    // with it or reproject from it. Each backend starts its history again; two frames' slack, as the upscale chain's)
    static uint64_t ran_at = 0;
    static int ran_backend = -1;
    const uint64_t now = texture_frame_no();
    if (ran_backend != b || now - ran_at > 2) opennr::history_gap(), dlssnr_ngx::history_gap(), dlssnr::history_gap();
    const auto backend = [b, cmd, now](VkImage from, uint32_t w, uint32_t h, VkImageView* view) {
        const VkImage made = b == OPEN  ? opennr::apply(cmd, from, w, h, view)
                             : b == NGX ? dlssnr_ngx::apply(cmd, from, w, h, view)
                                        : dlssnr::apply(cmd, from, w, h, view);
        if (made) ran_at = now, ran_backend = b;
        return made;
    };
    if (!wanted()) return VK_NULL_HANDLE;
    // The picture is a part of the window's image (the crop: 2048x1152 of 2560x1440 at the default output resolution),
    // and the model is given that part alone: vk_nr_scale.h says what running it over all of it cost.
    const PresentSourceRect picture = present_source_rect(sw, sh, crop);
    if (!picture.w || !picture.h) return VK_NULL_HANDLE;
    *out_w = picture.w, *out_h = picture.h;
    // The Resolution scale row (nr_plan.h): under 100% the backend is handed a smaller copy of the picture, and its
    // detail is put back on the picture at full size. Read each frame, as every row of the tab is.
    const int percent = opts.nr_scale;
    const bool whole = !picture.x && !picture.y && picture.w == sw && picture.h == sh;
    if (whole && !nr_plan::scaled(percent)) return backend(src, sw, sh, out_view);
    uint32_t lw = 0, lh = 0;
    const VkImage copy = nr_scale::take(cmd, src, picture.x, picture.y, picture.w, picture.h, percent, &lw, &lh);
    if (!copy) return VK_NULL_HANDLE;
    VkImageView model_view = VK_NULL_HANDLE;
    const VkImage model = backend(copy, lw, lh, &model_view);
    if (!model || !model_view) return VK_NULL_HANDLE;
    if (lw == picture.w && lh == picture.h) {   // (at full size: the model's picture is the one to show)
        *out_view = model_view;
        return model;
    }
    return nr_scale::restore(cmd, model_view, out_view);
}

const char* why() {
    if (running_backend() == OPEN) return opennr::why();
    if (running_backend() == NGX) {
        if (!dlssnr_ngx::built_with_sdk()) return "Not available: this build has no NGX SDK, so no NGX direct (readme).";
        return dlssnr_ngx::why();
    }
    if (!dlssnr::built_with_sdk()) return "Not available: Streamline is not in this build (Windows only). Try Auto.";
    return streamline::nr_why();
}

} // namespace mkwvk::nr
