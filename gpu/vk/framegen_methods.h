/* (hookshot fork) The Insert menu's Frame generation by row (opts.framegen_by, vk_menu.cpp), as plain functions: no Vulkan,
   no menu. tests/test_framegen_methods.cpp checks them.

   Upstream's row has two values, kept as they are and saved under the same key: Auto (NVIDIA DLSS Frame Generation
   through NGX where it runs, vk_dlss.cpp, else the renderer's own interpolation) and Built-in (the renderer's own). This
   fork adds AMD's two after them, where they run on this PC:

    - AMD FSR 4: AMD's frame generation through its runtime (vk_ffx.h; Windows, AMD's DLLs beside the game).
    - AMD FSR 3.1: the vendored frame interpolation (vk_fsr3fi.h), which upstream keeps behind RX_VK_FSR_FG=1.

   Neither is Auto's. They are given the presented picture with the HUD in it (the game draws its HUD into the same
   picture, and the renderer has no copy from before it), and AMD's interpolation then moves the HUD with the scene:
   upstream measured it with FSR 3.1's (a smeared HUD, a trail behind Link: its #1635 and seven duplicates) and made that
   one opt-in. FSR 4's takes the same inputs through the same kind of pass, so both are for the player to choose.

   How many frames a method makes between two of the game's is its own limit here (Here): FSR 3.1's interpolation has no
   phase input (ffx_frameinterpolation.h fixes t at 0.5), so it makes the midpoint and nothing else, 2x sets only; FSR 4
   one unless RX_VK_FFX_FG_MAX says more (vk_ffx.h). A set of more frames than a method makes is not half-made by it --
   that would show a lower multiplier than the row says, or the same picture twice -- it is the renderer's own, as is any
   frame a method refuses (no history yet, a cut, its inputs missing): a frame is never left out. */
#pragma once

#include <cstring>
#include <initializer_list>

namespace mkwvk::framegen_methods {

// (AUTO and BUILTIN are upstream's 0 and 1: an ini written by either build reads the same in the other)
enum { AUTO = 0, BUILTIN = 1, FSR4 = 2, FSR3 = 3, kMethods = 4 };

inline unsigned bit(int method) { return 1u << method; }
/// What can always be chosen: upstream's two
inline unsigned always() { return bit(AUTO) | bit(BUILTIN); }

/// What runs on this PC: the most frames each of AMD's methods makes between two of the game's, 0 where it does not run
/// (most[AUTO] and most[BUILTIN] are not read)
struct Here {
    int most[kMethods] = {0, 0, 0, 0};
};
/// One bit per value the row can show here (bit() of each): what it steps through
inline unsigned available(const Here& here) {
    unsigned mask = always();
    for (int method : {FSR4, FSR3})
        if (here.most[method] > 0) mask |= bit(method);
    return mask;
}

/// The row's next value from v (dir +1 / -1), wrapping over what runs here (available: bit() of each)
inline int step(int v, int dir, unsigned available) {
    available |= always();
    int at = v < 0 || v >= kMethods || !(available & bit(v)) ? AUTO : v;
    for (int i = 0; i < kMethods; i++) {
        at = (at + (dir > 0 ? 1 : kMethods - 1)) % kMethods;
        if (available & bit(at)) return at;
    }
    return AUTO;
}

/// The row's value when `want` is asked from `from` (set_row: an arrow asks the value beside, the control bridge any
/// value): `want` itself where it can be chosen here, else the next one that can in the direction asked
inline int pick(int from, int want, int dir, unsigned available) {
    available |= always();
    if (want >= 0 && want < kMethods && (available & bit(want))) return want;
    return step(from, dir, available);
}

/// The value shown and used: the one chosen when it runs here, else Auto (a saved choice is kept for a PC where it runs)
inline int effective(int chosen, unsigned available) {
    available |= always();
    return chosen >= 0 && chosen < kMethods && (available & bit(chosen)) ? chosen : AUTO;
}

/// Whether one of AMD's methods makes a whole set of this multiplier here (2 to 8: multiplier - 1 made frames)
inline bool makes_set(const Here& here, int method, int multiplier) {
    return multiplier >= 2 && (method == FSR4 || method == FSR3) && multiplier - 1 <= here.most[method];
}

/// RX_VK_FG_METHOD's value as a row value: auto, builtin, fsr4, fsr3 (or the number); -1 when unset or not one of them
inline int from_name(const char* name) {
    if (!name || !*name) return -1;
    static const char* const names[kMethods] = {"auto", "builtin", "fsr4", "fsr3"};
    for (int i = 0; i < kMethods; i++)
        if (!std::strcmp(name, names[i]) || (name[0] == '0' + i && !name[1])) return i;
    return -1;
}

/// The value an older ini of this fork saved as framegen_method (0 Auto, 1 NVIDIA DLSS, 2 AMD FSR 4, 3 AMD FSR 3.1,
/// 4 Built-in), as this row's: DLSS is Auto's own here
inline int from_old(int old) { return old == 2 ? FSR4 : old == 3 ? FSR3 : old == 4 ? BUILTIN : AUTO; }

} // namespace mkwvk::framegen_methods
