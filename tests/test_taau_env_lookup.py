"""Actual-source TAAU key/full stand-in spy; GPU boundaries are spies, no Vulkan loader or performance measurement.

Use --emit-only FILE to stage C++ without invoking a compiler.
"""
# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def block(source, marker):
    start = source.index(marker)
    return source[start:start + re.search(r'^}', source[start:], re.M).end()]


def fixture(source):
    return (PREFIX + block(source, 'bool taau_key(uint64_t key) {') + '\n' +
            block(source, 'bool taau_stand_in(VkCommandBuffer cmd,') + '\n' + SUFFIX)


PREFIX = r'''
#define _CRT_SECURE_NO_WARNINGS
// (the game profile's key prefixes, as the real file reads them: game/game_profile.h)
#include "game_profile.h"
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>
static const char *configured_keys, *no_f16;
static int key_reads;
static const char* fixture_getenv(const char* name) {
    if (!strcmp(name, "RX_VK_TAAU_KEYS")) { ++key_reads; return configured_keys; }
    if (!strcmp(name, "RX_VK_NO_F16")) return no_f16;
    return nullptr;
}
#define getenv fixture_getenv
namespace Shader { namespace Backend { namespace SPIRV { static bool mma_software = true; } } }
using VkCommandBuffer = int;
using VkImageView = int;
constexpr int VK_IMAGE_VIEW_TYPE_2D=2, VK_FORMAT_B10G11R11_UFLOAT_PACK32=7;
enum class ViewUse { Storage };
struct Desc { unsigned count=1; int format=23; };
struct Info { std::vector<Desc> texture_descriptors, image_descriptors; };
struct Stage { Info info; };
struct NvnState {};
struct Program { uint64_t key; std::vector<Stage> stages; };
struct Texture { int format=VK_FORMAT_B10G11R11_UFLOAT_PACK32; uint32_t width=1, height=1; int image=0; };
static Texture texture;
static struct { bool push_descriptor=false; } dev;
// Upstream's fixture sets this to true/false; this fork's seam also compares it with nullptr, so
// the spy answers both without pretending to be a real function pointer.
struct PushDescriptorSpy {
    bool on = true;
    PushDescriptorSpy& operator=(bool v) { on = v; return *this; }
    explicit operator bool() const { return on; }
    friend bool operator!=(const PushDescriptorSpy& p, std::nullptr_t) { return p.on; }
    friend bool operator==(const PushDescriptorSpy& p, std::nullptr_t) { return !p.on; }
};
static PushDescriptorSpy vkCmdPushDescriptorSetKHR;
struct ImageInfo { VkImageView imageView; };
struct SrcInfo { int image = 0; int format = 0; uint32_t width = 0, height = 0; };
static struct DrawWork { std::vector<ImageInfo> imgs; std::vector<SrcInfo> srcs; } draw_work;
static DrawWork& dw() { return draw_work; }

// (hookshot) This fork's taau_stand_in is the backend seam, not upstream's four-line gate: it
// resolves the dispatch into an upscale::Request, asks which backend takes it, and runs that one.
// The seam's own headers are plain data and Vulkan-free, so they are included rather than faked --
// a hand-written Verdict or Request would be a second definition to keep in step, and the test
// would pass while the real contract moved. Each backend reports itself unavailable here, so the
// stand-in path runs, which is the path this test is about.
#include "upscale_contract.h"
#include "upscale_seam.h"
using namespace mkwvk;
constexpr int VK_NULL_HANDLE = 0;
using VkImage = int;
constexpr int VK_IMAGE_ASPECT_COLOR_BIT = 1, VK_FILTER_NEAREST = 0, VK_FORMAT_UNDEFINED = 0;
constexpr int VK_IMAGE_LAYOUT_GENERAL = 1;
struct VkImageSubLayers { uint32_t aspectMask, mipLevel, baseArrayLayer, layerCount; };
struct VkOffset3D { int32_t x, y, z; };
struct VkImageBlit { VkImageSubLayers srcSubresource; VkOffset3D srcOffsets[2];
                     VkImageSubLayers dstSubresource; VkOffset3D dstOffsets[2]; };
static void vkCmdBlitImage(VkCommandBuffer, VkImage, int, VkImage, int, uint32_t, const VkImageBlit*, int) {}
static struct { int image = 0, view = 0, format = 0; uint32_t width = 0, height = 0; } scene_depth;
static struct { float m[16]; bool have = false; } scene_vp;
static void logf(const char*, ...) {}
static int scene_upscaler() { return 0; }
static bool upscale_trace_key(uint64_t) { return false; }
static void upscale_bindings(const NvnState&, const Stage&, std::vector<upscale::Binding>&) {}
static bool scene_history_stale(uint32_t, uint32_t) { return false; }
static void scene_jitter_display_width(uint32_t) {}
static bool scene_jitter(float* x, float* y) { if (x) *x = 0.0f; if (y) *y = 0.0f; return false; }
// In the renderer these two are weak symbols the host may or may not define, and the seam tests the
// address before calling; a plain function here would make that test always true.
static float (*hos_oot_camera)(float*, float*) = nullptr;
static int (*hos_oot_view_projection)(float*) = nullptr;
struct FakeMatrix { float m[16]; };
namespace mkwvk {
namespace camera_motion {
using Matrix = FakeMatrix;
static VkImageView record(VkCommandBuffer, VkImageView, int, uint32_t, uint32_t, const Matrix&) { return 0; }
static VkImage motion_image() { return 0; }
static int motion_format() { return 0; }
}
namespace fsr3 {
struct Inputs { VkImageView color=0, depth=0, motion=0; uint32_t render_width=0, render_height=0,
                upscale_width=0, upscale_height=0; float motion_scale[2]{}, jitter[2]{};
                float near_plane=0.0f, fov_y=0.0f; bool reset=false; };
static bool supported() { return false; }
static bool upscale(VkCommandBuffer, const Inputs&) { return false; }
static VkImage output_image() { return 0; }
static int fsr_stage() { return 0; }
static void note_frame() {}
}
namespace dlss {
struct Inputs { VkImageView color=0, depth=0, motion=0; VkImage color_image=0, depth_image=0, motion_image=0;
                int color_format=0, depth_format=0, motion_format=0;
                uint32_t render_width=0, render_height=0, upscale_width=0, upscale_height=0;
                float motion_scale[2]{}, jitter[2]{}; float near_plane=0.0f, fov_y=0.0f; bool reset=false; };
static bool supported() { return false; }
static bool upscale(VkCommandBuffer, const Inputs&) { return false; }
static VkImage output_image() { return 0; }
}
}   // (vk_draw.cpp's dw is a TLS_OBJECT: the calling thread's, by a call)
static unsigned handle_value=5;
static bool resolve_image=true, upscale_result=true;
static int upscale_calls, view_calls, handle_calls;
static VkCommandBuffer forwarded_cmd;
static VkImageView forwarded_input,forwarded_output;
static Texture* forwarded_texture;
static uint32_t forwarded_level;
static uint64_t forwarded_key;
static std::string forwarded_text;
static bool forwarded_temporal;
static uint32_t handle_of(const NvnState&,const Stage&,const Desc&,uint32_t index){
    ++handle_calls;return index==0?handle_value:0;
}
static int image_format(int f){return f+100;}
static VkImageView texture_view_of(uint32_t handle,int type,ViewUse use,int format,Texture** out,uint32_t* level){
    ++view_calls;
    if(handle!=5 || type!=VK_IMAGE_VIEW_TYPE_2D || use!=ViewUse::Storage || format!=123) return 0;
    *out=resolve_image?&texture:nullptr;*level=7;return 99;
}
static bool typed_upscale(VkCommandBuffer cmd,VkImageView input,VkImageView output,Texture* out,uint32_t level,uint64_t key,const char* text,bool temporal){
    ++upscale_calls;forwarded_cmd=cmd;forwarded_input=input;forwarded_output=output;forwarded_texture=out;
    forwarded_level=level;forwarded_key=key;forwarded_text=text;forwarded_temporal=temporal;return upscale_result;
}
'''

SUFFIX = r'''
static unsigned failures=0;
static void check(bool ok,const char* what){if(!ok){++failures;fprintf(stderr,"FAIL: %s\n",what);}}
int main(int argc,char** argv){
    if(argc!=2)return 90;
    uint64_t target=0xfd029a317a9a4b94ull;bool expected=true;
    if(!strcmp(argv[1],"hardware"))Shader::Backend::SPIRV::mma_software=false,expected=false;
    else if(!strcmp(argv[1],"no-f16"))Shader::Backend::SPIRV::mma_software=false,no_f16="1";
    else if(!strcmp(argv[1],"empty"))configured_keys="",expected=false;
    else if(!strcmp(argv[1],"disabled"))configured_keys="-",expected=false;
    else if(!strcmp(argv[1],"custom"))configured_keys="0123456789abcdef",target=0x0123456789abcdefull;
    else if(!strcmp(argv[1],"prefixes"))configured_keys="abcd,fd029a";
    else if(strcmp(argv[1],"software"))return 91;
    check(taau_key(target)==expected && !taau_key(0),"existing key matcher unchanged");
    NvnState state{};Program program{target,{}};Stage stage;
    stage.info.texture_descriptors={{1,23},{2,23}};stage.info.image_descriptors={{1,23}};program.stages.push_back(stage);
    key_reads=0;
    check(!taau_stand_in(19,state,program),"capability rejection unchanged");
    check(key_reads==0,"first rejected invocation performs no key lookup after matcher priming");
    key_reads=0;
    for(int i=0;i<1000;i++)check(!taau_stand_in(19,state,program),"warm rejection unchanged");
    check(key_reads==0,"1000 warm rejected invocations perform no key lookup");
    check(handle_calls==0 && view_calls==0 && upscale_calls==0,"capability rejection avoids resource boundary calls");
    if(expected){
        dev.push_descriptor=true;dw().imgs={{11},{22},{33},{44}};
        auto rejected=[&](const char* what){key_reads=0;int prior=upscale_calls;check(!taau_stand_in(19,state,program),what);check(key_reads==0 && upscale_calls==prior,"rejected resource guard never reads/forwards keys");};
        vkCmdPushDescriptorSetKHR=false;rejected("missing push entry");vkCmdPushDescriptorSetKHR=true;
        auto stages=program.stages;program.stages.clear();rejected("empty stages");program.stages=stages;
        program.stages[0].info.texture_descriptors.clear();rejected("no textures");program.stages=stages;
        program.stages[0].info.image_descriptors.clear();rejected("no images");program.stages=stages;
        dw().imgs.pop_back();rejected("descriptor span too short");dw().imgs.push_back({44});
        dw().imgs[0].imageView=0;rejected("no input view");dw().imgs[0].imageView=11;
        dw().imgs[3].imageView=0;rejected("no output view");dw().imgs[3].imageView=44;
        handle_value=0;rejected("no handle");handle_value=5;
        resolve_image=false;rejected("no resolved image");resolve_image=true;
        texture.format=0;rejected("wrong output format");texture.format=VK_FORMAT_B10G11R11_UFLOAT_PACK32;
        auto accepted=[&](const char* text,bool result){
            key_reads=0;int prior=upscale_calls;upscale_result=result;
            check(taau_stand_in(19,state,program)==result,"eligible helper result forwarded");
            check(upscale_calls==prior+1 && key_reads==(configured_keys?2:1),"eligible invocation retains per-call lookup count");
            check(forwarded_cmd==19 && forwarded_input==11 && forwarded_output==44 && forwarded_texture==&texture && forwarded_level==7 && forwarded_key==target && forwarded_temporal,"eligible arguments preserved");
            check(forwarded_text==text,"current key text forwarded verbatim");
        };
        accepted(configured_keys?configured_keys:"fd029a317a9a4b94",true);
        configured_keys="later diagnostic override";accepted(configured_keys,false);
        configured_keys=nullptr;accepted("fd029a317a9a4b94",true);
    }
    printf("%s failures=%u eligible=%d\n",argv[1],failures,upscale_calls);
    return failures?1:0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=ROOT)
    p.add_argument('--cxx', default='clang++')
    p.add_argument('--emit-only', type=Path)
    p.add_argument('--cxx-arg', action='append', default=[], help='extra compiler/linker flag (repeatable)')
    args = p.parse_args()
    cpp = fixture((args.source / 'gpu/vk/vk_draw.cpp').read_text(encoding='utf-8'))
    if args.emit_only:
        with args.emit_only.open('x', encoding='utf-8') as f:
            f.write(cpp)
        print('STAGED ONLY:', args.emit_only)
        return
    with tempfile.TemporaryDirectory(prefix='taau-env-') as temp:
        folder = Path(temp)
        source, exe = folder / 'fixture.cpp', folder / 'fixture.exe'
        source.write_text(cpp, encoding='utf-8')
        if Path(args.cxx).name.lower() in ('cl', 'cl.exe', 'clang-cl', 'clang-cl.exe'):
            command = [args.cxx, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                       '/I' + str(ROOT / 'gpu' / 'vk'), '/I' + str(ROOT / 'game'), str(source),
                       '/Fo' + str(folder / 'fixture.obj'), '/Fe' + str(exe), *args.cxx_arg]
        else:
            # (this fork's taau_stand_in includes the seam's own headers, which live in gpu/vk; game/ holds the
            #  game profile's C view, which is where the default key prefixes come from)
            command = [args.cxx, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                       '-I' + str(ROOT / 'gpu' / 'vk'), '-I' + str(ROOT / 'game'),
                       *args.cxx_arg, str(source), '-o', str(exe)]
        subprocess.run(command, cwd=folder, check=True)
        failed = False
        for case in ('software', 'hardware', 'no-f16', 'empty', 'disabled', 'custom', 'prefixes'):
            result = subprocess.run([str(exe), case], cwd=folder)
            print(case, 'exit', result.returncode, flush=True)
            failed |= result.returncode != 0
        if failed:
            raise SystemExit(1)
    print('PASS: seven key configurations; rejected lookups removed, eligible per-call forwarding preserved')


if __name__ == '__main__':
    main()
