// (hookshot fork) The picture neural rendering is given, and its Resolution scale: vk_nr_scale.h says what, nr_plan.h the sizes.
#include "vk_nr_scale.h"

#include <mutex>

#include "nr_plan.h"
#include "shaders/nr_detail_comp_spv.h"
#include "vk_work.h"   // (after the others: its commands through the recorder, counted as work for full_barrier)

namespace mkwvk::nr_scale {
namespace {

constexpr VkFormat kFormat = VK_FORMAT_R8G8B8A8_UNORM;   // (the backends' own working format: vk_dlssnr_ngx.cpp)
constexpr VkImageSubresourceRange kOneLevel{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};

struct Image {
    VkImage image{};
    VkImageView view{};
    VmaAllocation memory{};
};

struct State {
    // (the picture at full size; under 100%, the model's smaller copy and the picture with its detail)
    Image frame{}, small{}, result{};
    uint32_t w{}, h{}, lw{}, lh{};   // (lw x lh: the copy's size, w x h when there is none)
    uint32_t bad[4]{};               // (the sizes the images were last refused for, 0: none)
    VkDescriptorSetLayout set_layout{};
    VkPipelineLayout layout{};
    VkPipeline pipeline{};
    VkSampler linear{}, nearest{};
    VkDescriptorPool pool{};
    VkDescriptorSet set{};
    VkImageView bound_model{};   // (the model's view the set names)
    bool pass_failed{};
    bool shrunk{};               // (shrink ran in this recording: restore has its inputs)
    bool told{};
};

State& state() {
    static State s;
    return s;
}

/// The device idle, for freeing or rewriting what a frame in flight may still use (vk_dlssnr.cpp's resize says why not a
/// bare vkDeviceWaitIdle)
void idle() {
    std::lock_guard qk(dev.present_mu);
    device_wait_idle_locked();
}

void drop(Image& t) {
    if (t.view) vkDestroyImageView(dev.device, t.view, nullptr);
    if (t.image) destroy_image(t.image, t.memory);
    t = Image{};
}

bool make(Image& t, uint32_t w, uint32_t h, VkImageUsageFlags usage) {
    drop(t);
    VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    ci.imageType = VK_IMAGE_TYPE_2D;
    ci.format = kFormat;
    ci.extent = {w, h, 1};
    ci.mipLevels = ci.arrayLayers = 1;
    ci.samples = VK_SAMPLE_COUNT_1_BIT;
    ci.tiling = VK_IMAGE_TILING_OPTIMAL;
    ci.usage = usage;
    if (!create_image(ci, t.image, t.memory, false)) return false;
    VkImageViewCreateInfo vi{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
    vi.image = t.image;
    vi.viewType = VK_IMAGE_VIEW_TYPE_2D;
    vi.format = kFormat;
    vi.subresourceRange = kOneLevel;
    if (vkCreateImageView(dev.device, &vi, nullptr, &t.view) != VK_SUCCESS) {
        drop(t);
        return false;
    }
    return true;
}

void barrier(VkCommandBuffer cmd, VkImage image, VkImageLayout from, VkImageLayout to, VkAccessFlags2 src_access,
             VkAccessFlags2 dst_access) {
    VkImageMemoryBarrier2 b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2};
    b.srcStageMask = b.dstStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
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

/// The pass that adds the detail (shaders/nr_detail.comp), its samplers and its one descriptor set: once
bool make_pass(State& s) {
    if (s.pipeline) return true;
    if (s.pass_failed) return false;
    s.pass_failed = true;   // (until all of it is made)
    const VkDescriptorSetLayoutBinding b[4] = {
        {0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
        {1, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
        {2, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
        {3, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}};
    VkDescriptorSetLayoutCreateInfo li{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    li.bindingCount = 4;
    li.pBindings = b;
    if (vkCreateDescriptorSetLayout(dev.device, &li, nullptr, &s.set_layout) != VK_SUCCESS) return false;
    VkPipelineLayoutCreateInfo pi{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    pi.setLayoutCount = 1;
    pi.pSetLayouts = &s.set_layout;
    if (vkCreatePipelineLayout(dev.device, &pi, nullptr, &s.layout) != VK_SUCCESS) return false;
    VkShaderModuleCreateInfo mi{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    mi.codeSize = sizeof NR_DETAIL_COMP_SPV;
    mi.pCode = NR_DETAIL_COMP_SPV;
    VkShaderModule module{};
    if (vkCreateShaderModule(dev.device, &mi, nullptr, &module) != VK_SUCCESS) return false;
    VkComputePipelineCreateInfo ci{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
    ci.stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO};
    ci.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT;
    ci.stage.module = module;
    ci.stage.pName = "main";
    ci.layout = s.layout;
    const VkResult made = vkCreateComputePipelines(dev.device, VK_NULL_HANDLE, 1, &ci, nullptr, &s.pipeline);
    vkDestroyShaderModule(dev.device, module, nullptr);
    if (made != VK_SUCCESS) return s.pipeline = VK_NULL_HANDLE, false;
    VkSamplerCreateInfo si{VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO};
    si.magFilter = si.minFilter = VK_FILTER_LINEAR;
    si.mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST;
    si.addressModeU = si.addressModeV = si.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    if (vkCreateSampler(dev.device, &si, nullptr, &s.linear) != VK_SUCCESS) return false;
    si.magFilter = si.minFilter = VK_FILTER_NEAREST;
    if (vkCreateSampler(dev.device, &si, nullptr, &s.nearest) != VK_SUCCESS) return false;
    const VkDescriptorPoolSize sizes[2] = {{VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 3},
                                           {VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1}};
    VkDescriptorPoolCreateInfo dpi{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
    dpi.maxSets = 1;
    dpi.poolSizeCount = 2;
    dpi.pPoolSizes = sizes;
    if (vkCreateDescriptorPool(dev.device, &dpi, nullptr, &s.pool) != VK_SUCCESS) return false;
    VkDescriptorSetAllocateInfo ai{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
    ai.descriptorPool = s.pool;
    ai.descriptorSetCount = 1;
    ai.pSetLayouts = &s.set_layout;
    if (vkAllocateDescriptorSets(dev.device, &ai, &s.set) != VK_SUCCESS) return false;
    s.pass_failed = false;
    return true;
}

/// The set, naming this module's images and the model's view. Only with nothing in flight that uses it (the caller idles)
void write_set(State& s, VkImageView model) {
    const VkDescriptorImageInfo frame{s.nearest, s.frame.view, VK_IMAGE_LAYOUT_GENERAL};
    const VkDescriptorImageInfo small{s.linear, s.small.view, VK_IMAGE_LAYOUT_GENERAL};
    const VkDescriptorImageInfo picture{s.linear, model, VK_IMAGE_LAYOUT_GENERAL};
    const VkDescriptorImageInfo result{VK_NULL_HANDLE, s.result.view, VK_IMAGE_LAYOUT_GENERAL};
    VkWriteDescriptorSet w[4]{};
    const VkDescriptorImageInfo* infos[4] = {&frame, &small, &picture, &result};
    for (uint32_t i = 0; i < 4; i++) {
        w[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        w[i].dstSet = s.set;
        w[i].dstBinding = i;
        w[i].descriptorCount = 1;
        w[i].descriptorType = i < 3 ? VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER : VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
        w[i].pImageInfo = infos[i];
    }
    vkUpdateDescriptorSets(dev.device, 4, w, 0, nullptr);
    s.bound_model = model;
}

/// Its images for a picture of w x h and, under 100%, a copy of lw x lh (lw x lh is w x h at 100%: no copy, no result),
/// made again when either changes (the device idle first: the ones before may be in a frame not shown yet)
bool resize(State& s, uint32_t w, uint32_t h, uint32_t lw, uint32_t lh) {
    if (s.frame.image && s.w == w && s.h == h && s.lw == lw && s.lh == lh) return true;
    // (sizes they could not be made for: not asked again, with the device idled and a log line, at every present)
    if (s.bad[0] == w && s.bad[1] == h && s.bad[2] == lw && s.bad[3] == lh) return false;
    idle();
    constexpr VkImageUsageFlags read = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT |
                                       VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    const bool scaled = lw != w || lh != h;
    drop(s.small), drop(s.result);
    // (what a backend is handed in the game's image's place: it reads it as it reads that one)
    if (!make(s.frame, w, h, read) || (scaled && (!make(s.small, lw, lh, read) ||
                                                  !make(s.result, w, h, read | VK_IMAGE_USAGE_STORAGE_BIT)))) {
        drop(s.frame), drop(s.small), drop(s.result);
        s.w = s.h = s.lw = s.lh = 0;
        s.bad[0] = w, s.bad[1] = h, s.bad[2] = lw, s.bad[3] = lh;
        logf("vk: neural rendering: the picture's copies were not made (%ux%u, %ux%u): no model this frame", w, h, lw, lh);
        return false;
    }
    s.w = w, s.h = h, s.lw = lw, s.lh = lh;
    s.bad[0] = s.bad[1] = s.bad[2] = s.bad[3] = 0;
    s.bound_model = VK_NULL_HANDLE;   // (the set names images that are gone)
    return true;
}

} // namespace

VkImage take(VkCommandBuffer cmd, VkImage src, uint32_t x, uint32_t y, uint32_t w, uint32_t h, int percent, uint32_t* lw,
             uint32_t* lh) {
    State& s = state();
    s.shrunk = false;
    if (!src || !w || !h) return VK_NULL_HANDLE;
    uint32_t cw = w, ch = h;   // (the copy's size)
    if (nr_plan::scaled(percent)) cw = nr_plan::scaled_side(w, percent), ch = nr_plan::scaled_side(h, percent);
    const bool scaled = cw != w || ch != h;   // (a picture too small to shrink is given as it is)
    if ((scaled && !make_pass(s)) || !resize(s, w, h, cw, ch)) return VK_NULL_HANDLE;
    // The picture into ours, read in place (GENERAL is a layout a blit may read from): the game's is only read.
    barrier(cmd, src, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL,
            VK_ACCESS_2_COLOR_ATTACHMENT_WRITE_BIT | VK_ACCESS_2_SHADER_WRITE_BIT | VK_ACCESS_2_TRANSFER_WRITE_BIT,
            VK_ACCESS_2_TRANSFER_READ_BIT);
    barrier(cmd, s.frame.image, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 0,
            VK_ACCESS_2_TRANSFER_WRITE_BIT);
    VkImageBlit b{};
    b.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    b.dstSubresource = b.srcSubresource;
    b.srcOffsets[0] = {(int32_t)x, (int32_t)y, 0};
    b.srcOffsets[1] = {(int32_t)(x + w), (int32_t)(y + h), 1};
    b.dstOffsets[1] = {(int32_t)w, (int32_t)h, 1};
    vkCmdBlitImage(cmd, src, VK_IMAGE_LAYOUT_GENERAL, s.frame.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b,
                   VK_FILTER_NEAREST);
    barrier(cmd, s.frame.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_GENERAL,
            VK_ACCESS_2_TRANSFER_WRITE_BIT, VK_ACCESS_2_TRANSFER_READ_BIT | VK_ACCESS_2_SHADER_READ_BIT);
    *lw = cw, *lh = ch;
    if (!scaled) return s.frame.image;
    barrier(cmd, s.small.image, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 0,
            VK_ACCESS_2_TRANSFER_WRITE_BIT);
    b.dstOffsets[1] = {(int32_t)cw, (int32_t)ch, 1};
    // (linear: at half the size and above, every pixel of the picture is in a pixel of the copy)
    vkCmdBlitImage(cmd, src, VK_IMAGE_LAYOUT_GENERAL, s.small.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b,
                   VK_FILTER_LINEAR);
    barrier(cmd, s.small.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_GENERAL,
            VK_ACCESS_2_TRANSFER_WRITE_BIT, VK_ACCESS_2_TRANSFER_READ_BIT | VK_ACCESS_2_SHADER_READ_BIT);
    s.shrunk = true;
    if (!s.told) {
        s.told = true;
        logf("vk: neural rendering: Resolution scale %d%%: the model on %ux%u of a %ux%u picture, its detail put back at "
             "full size", nr_plan::scale(percent), cw, ch, w, h);
    }
    return s.small.image;
}

VkImage restore(VkCommandBuffer cmd, VkImageView model_view, VkImageView* out_view) {
    State& s = state();
    if (!s.shrunk || !model_view || !s.result.image) return VK_NULL_HANDLE;
    s.shrunk = false;
    if (s.bound_model != model_view) {
        // (the model's picture is another image than the set names: a backend's new size, another backend, another count
        // of passes. Rare; the set may be in a frame not shown yet, so the device idles first)
        if (s.bound_model) idle();
        write_set(s, model_view);
    }
    barrier(cmd, s.result.image, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, 0, VK_ACCESS_2_SHADER_WRITE_BIT);
    {   // (the model's picture was written by its backend, by whatever means: everything before, done)
        VkMemoryBarrier2 mb{VK_STRUCTURE_TYPE_MEMORY_BARRIER_2};
        mb.srcStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
        mb.srcAccessMask = VK_ACCESS_2_MEMORY_WRITE_BIT;
        mb.dstStageMask = VK_PIPELINE_STAGE_2_COMPUTE_SHADER_BIT;
        mb.dstAccessMask = VK_ACCESS_2_SHADER_READ_BIT | VK_ACCESS_2_SHADER_WRITE_BIT;
        VkDependencyInfo di{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
        di.memoryBarrierCount = 1, di.pMemoryBarriers = &mb;
        vkCmdPipelineBarrier2(cmd, &di);
    }
    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s.pipeline);
    vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s.layout, 0, 1, &s.set, 0, nullptr);
    vkCmdDispatch(cmd, (s.w + 7) / 8, (s.h + 7) / 8, 1);
    barrier(cmd, s.result.image, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_2_SHADER_WRITE_BIT,
            VK_ACCESS_2_TRANSFER_READ_BIT | VK_ACCESS_2_SHADER_READ_BIT);
    if (out_view) *out_view = s.result.view;
    return s.result.image;
}

void shutdown() {
    State& s = state();
    if (!s.frame.image && !s.pipeline) return;
    idle();
    drop(s.frame), drop(s.small), drop(s.result);
    if (s.pool) vkDestroyDescriptorPool(dev.device, s.pool, nullptr);
    if (s.linear) vkDestroySampler(dev.device, s.linear, nullptr);
    if (s.nearest) vkDestroySampler(dev.device, s.nearest, nullptr);
    if (s.pipeline) vkDestroyPipeline(dev.device, s.pipeline, nullptr);
    if (s.layout) vkDestroyPipelineLayout(dev.device, s.layout, nullptr);
    if (s.set_layout) vkDestroyDescriptorSetLayout(dev.device, s.set_layout, nullptr);
    s = State{};
}

} // namespace mkwvk::nr_scale
