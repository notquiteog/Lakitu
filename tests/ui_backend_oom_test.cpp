// (tests/test_ui_backend_oom.py) Dear ImGui's Vulkan back end, as the renderer compiles it (nx2/imgui_backend.py), over fake
// Vulkan functions whose vertex and index memory can be made to fail: the overlay's draw is left out, nothing is copied
// through a null mapping, and the next frame asks for the memory again.
#include "imgui.h"
#include "imgui_impl_vulkan.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <set>
#include <vector>

static int fails;
#define CHECK(t, what) do { if (!(t)) { std::printf("FAIL: %s\n", what); fails++; } } while (0)

static uint64_t next_handle = 0x1000;
template <class T> static T make() { return (T)(uintptr_t)(next_handle += 0x10); }
static int alloc_fail;           // (the next vkAllocateMemory calls that fail with VK_ERROR_OUT_OF_DEVICE_MEMORY)
static int create_buffer_fail;   // (the same for vkCreateBuffer)
static int allocs, draws, maps_bad;
static std::set<uint64_t> live_memory;
static std::vector<std::vector<unsigned char>> mapped;

#define FAKE(ret, name, ...) static VKAPI_ATTR ret VKAPI_CALL f_##name(__VA_ARGS__)
FAKE(VkResult, vkCreateBuffer, VkDevice, const VkBufferCreateInfo*, const VkAllocationCallbacks*, VkBuffer* b) {
    if (create_buffer_fail) { create_buffer_fail--; return VK_ERROR_OUT_OF_DEVICE_MEMORY; }
    *b = make<VkBuffer>();
    return VK_SUCCESS;
}
FAKE(void, vkGetBufferMemoryRequirements, VkDevice, VkBuffer, VkMemoryRequirements* r) {
    r->size = 1 << 16, r->alignment = 256, r->memoryTypeBits = 1;
}
FAKE(void, vkGetPhysicalDeviceMemoryProperties, VkPhysicalDevice, VkPhysicalDeviceMemoryProperties* p) {
    std::memset(p, 0, sizeof *p);
    p->memoryTypeCount = 1;
    p->memoryTypes[0].propertyFlags = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
}
FAKE(VkResult, vkAllocateMemory, VkDevice, const VkMemoryAllocateInfo*, const VkAllocationCallbacks*, VkDeviceMemory* m) {
    allocs++;
    if (alloc_fail) { alloc_fail--; return VK_ERROR_OUT_OF_DEVICE_MEMORY; }   // (*m left as it was, as a driver may)
    *m = make<VkDeviceMemory>();
    live_memory.insert((uint64_t)(uintptr_t)*m);
    return VK_SUCCESS;
}
FAKE(void, vkFreeMemory, VkDevice, VkDeviceMemory m, const VkAllocationCallbacks*) { live_memory.erase((uint64_t)(uintptr_t)m); }
FAKE(VkResult, vkBindBufferMemory, VkDevice, VkBuffer, VkDeviceMemory m, VkDeviceSize) {
    return live_memory.count((uint64_t)(uintptr_t)m) ? VK_SUCCESS : VK_ERROR_UNKNOWN;
}
FAKE(VkResult, vkMapMemory, VkDevice, VkDeviceMemory m, VkDeviceSize, VkDeviceSize size, VkMemoryMapFlags, void** p) {
    if (!live_memory.count((uint64_t)(uintptr_t)m)) { maps_bad++; return VK_ERROR_MEMORY_MAP_FAILED; }   // (*p left alone)
    mapped.emplace_back((size_t)size);
    *p = mapped.back().data();
    return VK_SUCCESS;
}
FAKE(void, vkCmdDrawIndexed, VkCommandBuffer, uint32_t, uint32_t, uint32_t, int32_t, uint32_t) { draws++; }
FAKE(VkResult, vkCreateSampler, VkDevice, const VkSamplerCreateInfo*, const VkAllocationCallbacks*, VkSampler* s) {
    *s = make<VkSampler>(); return VK_SUCCESS;
}
FAKE(VkResult, vkCreateDescriptorSetLayout, VkDevice, const VkDescriptorSetLayoutCreateInfo*, const VkAllocationCallbacks*,
     VkDescriptorSetLayout* l) { *l = make<VkDescriptorSetLayout>(); return VK_SUCCESS; }
FAKE(VkResult, vkCreatePipelineLayout, VkDevice, const VkPipelineLayoutCreateInfo*, const VkAllocationCallbacks*, VkPipelineLayout* l) {
    *l = make<VkPipelineLayout>(); return VK_SUCCESS;
}
FAKE(VkResult, vkCreateShaderModule, VkDevice, const VkShaderModuleCreateInfo*, const VkAllocationCallbacks*, VkShaderModule* m) {
    *m = make<VkShaderModule>(); return VK_SUCCESS;
}
FAKE(VkResult, vkCreateGraphicsPipelines, VkDevice, VkPipelineCache, uint32_t n, const VkGraphicsPipelineCreateInfo*,
     const VkAllocationCallbacks*, VkPipeline* p) {
    for (uint32_t i = 0; i < n; i++) p[i] = make<VkPipeline>();
    return VK_SUCCESS;
}
FAKE(VkResult, vkCreateDescriptorPool, VkDevice, const VkDescriptorPoolCreateInfo*, const VkAllocationCallbacks*, VkDescriptorPool* p) {
    *p = make<VkDescriptorPool>(); return VK_SUCCESS;
}
FAKE(VkResult, vkAllocateDescriptorSets, VkDevice, const VkDescriptorSetAllocateInfo* i, VkDescriptorSet* s) {
    for (uint32_t k = 0; k < i->descriptorSetCount; k++) s[k] = make<VkDescriptorSet>();
    return VK_SUCCESS;
}
FAKE(VkResult, vkCreateCommandPool, VkDevice, const VkCommandPoolCreateInfo*, const VkAllocationCallbacks*, VkCommandPool* p) {
    *p = make<VkCommandPool>(); return VK_SUCCESS;
}
FAKE(VkResult, vkAllocateCommandBuffers, VkDevice, const VkCommandBufferAllocateInfo* i, VkCommandBuffer* b) {
    for (uint32_t k = 0; k < i->commandBufferCount; k++) b[k] = make<VkCommandBuffer>();
    return VK_SUCCESS;
}
FAKE(VkResult, vkCreateFence, VkDevice, const VkFenceCreateInfo*, const VkAllocationCallbacks*, VkFence* f) {
    *f = make<VkFence>(); return VK_SUCCESS;
}
// (everything else the back end loads: nothing to do, and success. Called through its own pointer type: these take no
//  arguments, which the calling conventions of the platforms CI builds for allow)
static VKAPI_ATTR VkResult VKAPI_CALL f_nothing() { return VK_SUCCESS; }

static PFN_vkVoidFunction load(const char* name, void*) {
#define HAVE(n) if (!std::strcmp(name, #n)) return (PFN_vkVoidFunction)f_##n;
    HAVE(vkCreateBuffer) HAVE(vkGetBufferMemoryRequirements) HAVE(vkGetPhysicalDeviceMemoryProperties) HAVE(vkAllocateMemory)
    HAVE(vkFreeMemory) HAVE(vkBindBufferMemory) HAVE(vkMapMemory) HAVE(vkCmdDrawIndexed) HAVE(vkCreateSampler)
    HAVE(vkCreateDescriptorSetLayout) HAVE(vkCreatePipelineLayout) HAVE(vkCreateShaderModule) HAVE(vkCreateGraphicsPipelines)
    HAVE(vkCreateDescriptorPool) HAVE(vkAllocateDescriptorSets) HAVE(vkCreateCommandPool) HAVE(vkAllocateCommandBuffers)
    HAVE(vkCreateFence)
#undef HAVE
    return (PFN_vkVoidFunction)f_nothing;
}

// One frame of an overlay with n rectangles (a menu: more vertices than the frames before), rendered: the draws recorded
static int frame(int n) {
    ImGui::GetIO().DisplaySize = ImVec2(1280, 720);
    ImGui::GetIO().DeltaTime = 1.0f / 60.0f;
    ImGui::NewFrame();
    ImDrawList* dl = ImGui::GetForegroundDrawList();
    for (int i = 0; i < n; i++) dl->AddRectFilled(ImVec2((float)(i % 100), (float)(i / 100)), ImVec2(i % 100 + 5.0f, i / 100 + 5.0f), 0xff00ff00);
    ImGui::Render();
    ImDrawData* dd = ImGui::GetDrawData();
    for (ImTextureData* tex : ImGui::GetPlatformIO().Textures)   // (as gpu/vk/vk_imgui.cpp: its own uploads, here none)
        if (tex->Status != ImTextureStatus_OK && tex->Status != ImTextureStatus_Destroyed) {
            tex->SetTexID((ImTextureID)1);
            tex->SetStatus(ImTextureStatus_OK);
        }
    dd->Textures = nullptr;
    const int before = draws;
    ImGui_ImplVulkan_RenderDrawData(dd, make<VkCommandBuffer>());
    return draws - before;
}

int main() {
    ImGui::CreateContext();
    ImGui::GetIO().IniFilename = nullptr;
    if (!ImGui_ImplVulkan_LoadFunctions(VK_API_VERSION_1_3, load)) return 2;
    VkFormat format = VK_FORMAT_B8G8R8A8_UNORM;
    ImGui_ImplVulkan_InitInfo ii{};
    ii.ApiVersion = VK_API_VERSION_1_3;
    ii.Instance = make<VkInstance>(), ii.PhysicalDevice = make<VkPhysicalDevice>(), ii.Device = make<VkDevice>();
    ii.Queue = make<VkQueue>();
    ii.DescriptorPoolSize = 16, ii.MinImageCount = 2, ii.ImageCount = 2;   // (two frames' buffers in turn)
    ii.UseDynamicRendering = true;
    ii.PipelineInfoMain.PipelineRenderingCreateInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO;
    ii.PipelineInfoMain.PipelineRenderingCreateInfo.colorAttachmentCount = 1;
    ii.PipelineInfoMain.PipelineRenderingCreateInfo.pColorAttachmentFormats = &format;
    if (!ImGui_ImplVulkan_Init(&ii)) return 3;
    ImGui::GetIO().Fonts->AddFontDefault();

    CHECK(frame(4) > 0 && frame(4) > 0, "the counter draws in both of its frames' buffers");
    // (the menu opens with video memory used up: each buffer that grows cannot get its memory)
    alloc_fail = 2;
    int a = allocs;
    CHECK(frame(3000) == 0, "a frame whose vertex memory cannot be allocated records no draw");
    CHECK(allocs > a, "the frame asked for the memory");
    CHECK(maps_bad == 0, "no memory that was not allocated is mapped");
    alloc_fail = 1000;
    for (int i = 0; i < 6; i++) CHECK(frame(3000) == 0, "while memory stays full the overlay is left out, frame after frame");
    alloc_fail = 0;
    a = allocs;
    CHECK(frame(3000) > 0 && frame(3000) > 0, "once memory is free again the next frames ask again and draw");
    CHECK(allocs > a, "the buffers left out were allocated again");
    // (vkCreateBuffer failing is left out the same way)
    create_buffer_fail = 1;
    CHECK(frame(9000) == 0, "a frame whose buffer cannot be created records no draw");
    CHECK(frame(9000) > 0 || frame(9000) > 0, "and a later frame draws");
    CHECK(maps_bad == 0, "nothing was mapped that was not memory");
    if (!fails) std::puts("PASS: the overlay's draw is left out while its buffers cannot be made");
    return fails != 0;
}
