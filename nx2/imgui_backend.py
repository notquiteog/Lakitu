"""Dear ImGui's Vulkan back end as the renderer compiles it (gpu/vk/vk_imgui.cpp draws the overlays with it): a copy of
third_party/imgui/backends/imgui_impl_vulkan.cpp in the build's own folder with BACKEND_PATCHES applied, so third_party/
stays byte for byte upstream's (CONTRIBUTING.md), as scripts/opennr_kernels.py does for OpenDLSS-NR.

    python -I nx2/imgui_backend.py <out folder>
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
IMGUI = os.path.join(ROOT, "third_party", "imgui")
BACKEND = os.path.join(IMGUI, "backends", "imgui_impl_vulkan.cpp")
NAME = "imgui_impl_vulkan.cpp"

# (exact replacements, each applied exactly once: a replacement that no longer matches fails the build instead of being
# skipped. Each says why.)
# A vertex or index buffer that cannot be made. The back end went on after a failed vkCreateBuffer, vkAllocateMemory or
# vkBindBufferMemory (its check_vk_result only reports, and the renderer sets no callback for it): it bound and mapped
# memory it did not have and copied the frame's vertices through the null pointer the failed mapping left. That is an
# access violation in memcpy, not on a guest thread, when the overlays need a larger buffer (the Insert menu opening)
# while video memory is used up. Now a buffer that cannot be made is left as none, with size 0, so the frame's overlay
# draws nothing and the next frame asks for it again. After NX2navi (chrg6), commit 18aa16f, used with its author's
# permission; reports of that crash: an integrated AMD GPU and an RTX 2050, "got VkResult -2" twice, then the copy.
BACKEND_PATCHES = [
    ("    err = vkCreateBuffer(v->Device, &buffer_info, v->Allocator, &buffer);\n"
     "    check_vk_result(err);\n",
     "    err = vkCreateBuffer(v->Device, &buffer_info, v->Allocator, &buffer);\n"
     "    check_vk_result(err);\n"
     "    if (err != VK_SUCCESS)   // (hookshot, nx2/imgui_backend.py: no buffer, and the frame draws nothing)\n"
     "    {\n"
     "        buffer = VK_NULL_HANDLE;\n"
     "        buffer_memory = VK_NULL_HANDLE;\n"
     "        buffer_size = 0;\n"
     "        return;\n"
     "    }\n",
     "a buffer that could not be created was used as one"),
    ("    err = vkAllocateMemory(v->Device, &alloc_info, v->Allocator, &buffer_memory);\n"
     "    check_vk_result(err);\n"
     "\n"
     "    err = vkBindBufferMemory(v->Device, buffer, buffer_memory, 0);\n"
     "    check_vk_result(err);\n",
     "    buffer_memory = VK_NULL_HANDLE;   // (hookshot: the memory freed above is not kept when this fails)\n"
     "    err = vkAllocateMemory(v->Device, &alloc_info, v->Allocator, &buffer_memory);\n"
     "    check_vk_result(err);\n"
     "    if (err == VK_SUCCESS)\n"
     "    {\n"
     "        err = vkBindBufferMemory(v->Device, buffer, buffer_memory, 0);\n"
     "        check_vk_result(err);\n"
     "    }\n"
     "    if (err != VK_SUCCESS)   // (hookshot, nx2/imgui_backend.py: out of memory. No buffer and size 0: the frame draws\n"
     "    {                        // nothing, and the next frame asks again)\n"
     "        if (buffer_memory != VK_NULL_HANDLE)\n"
     "            vkFreeMemory(v->Device, buffer_memory, v->Allocator);\n"
     "        vkDestroyBuffer(v->Device, buffer, v->Allocator);\n"
     "        buffer = VK_NULL_HANDLE;\n"
     "        buffer_memory = VK_NULL_HANDLE;\n"
     "        buffer_size = 0;\n"
     "        return;\n"
     "    }\n",
     "memory that could not be allocated or bound was bound and mapped"),
    ("            CreateOrResizeBuffer(rb->IndexBuffer, rb->IndexBufferMemory, rb->IndexBufferSize, index_size, VK_BUFFER_USAGE_INDEX_BUFFER_BIT);\n"
     "\n",
     "            CreateOrResizeBuffer(rb->IndexBuffer, rb->IndexBufferMemory, rb->IndexBufferSize, index_size, VK_BUFFER_USAGE_INDEX_BUFFER_BIT);\n"
     "        if (rb->VertexBufferMemory == VK_NULL_HANDLE || rb->IndexBufferMemory == VK_NULL_HANDLE)\n"
     "            return;   // (hookshot, nx2/imgui_backend.py: a buffer that could not be made: nothing is recorded this frame)\n"
     "\n",
     "the draw went on without its buffers"),
    ("        VkResult err = vkMapMemory(v->Device, rb->VertexBufferMemory, 0, vertex_size, 0, (void**)&vtx_dst);\n"
     "        check_vk_result(err);\n"
     "        err = vkMapMemory(v->Device, rb->IndexBufferMemory, 0, index_size, 0, (void**)&idx_dst);\n"
     "        check_vk_result(err);\n",
     "        VkResult err = vkMapMemory(v->Device, rb->VertexBufferMemory, 0, vertex_size, 0, (void**)&vtx_dst);\n"
     "        check_vk_result(err);\n"
     "        if (err != VK_SUCCESS || !vtx_dst)\n"
     "            return;   // (hookshot, nx2/imgui_backend.py: a mapping that failed leaves nothing to copy into)\n"
     "        err = vkMapMemory(v->Device, rb->IndexBufferMemory, 0, index_size, 0, (void**)&idx_dst);\n"
     "        check_vk_result(err);\n"
     "        if (err != VK_SUCCESS || !idx_dst)\n"
     "        {\n"
     "            vkUnmapMemory(v->Device, rb->VertexBufferMemory);\n"
     "            return;\n"
     "        }\n",
     "the vertices were copied through a failed mapping"),
]


def patched_source():
    """The back end's text with BACKEND_PATCHES applied"""
    with open(BACKEND, encoding="utf-8", newline="") as f:
        text = f.read()
    for old, new, why in BACKEND_PATCHES:
        if text.count(old) != 1:
            raise RuntimeError("the ImGui Vulkan back end's patch (%s) no longer matches %s exactly once" % (why, BACKEND))
        text = text.replace(old, new)
    return text


def write(out_dir):
    """Writes out_dir/imgui_impl_vulkan.cpp when it differs (an unchanged one keeps its timestamp); returns its path. It
    includes "imgui_impl_vulkan.h" from its own folder first, so the compile needs -I third_party/imgui/backends."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, NAME)
    text = patched_source()
    try:
        with open(path, encoding="utf-8", newline="") as f:
            if f.read() == text:
                return path
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return path


if __name__ == "__main__":
    print(write(sys.argv[1] if len(sys.argv) > 1 else "."))
