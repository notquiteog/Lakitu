// (hookshot fork) gpu/vk/framegen_methods.h: the Frame generation by row's values past upstream's two, and their stepping.
#include <cstdio>
#include "../gpu/vk/framegen_methods.h"

namespace fgm = mkwvk::framegen_methods;
static int failures;
#define CHECK(name, c) do { if (!(c)) { std::printf("FAIL: %s\n", name); ++failures; } } while (0)

int main() {
    using namespace fgm;
    // upstream's row: 0 Auto, 1 Built-in. A file written by either build reads the same in the other
    CHECK("upstream's two values keep their numbers", AUTO == 0 && BUILTIN == 1 && FSR4 == 2 && FSR3 == 3 && kMethods == 4);
    const unsigned all = bit(AUTO) | bit(BUILTIN) | bit(FSR4) | bit(FSR3);
    const unsigned fsr3 = bit(FSR3);   // (Auto and Built-in are always there)
    CHECK("steps through all four", step(AUTO, 1, all) == BUILTIN && step(BUILTIN, 1, all) == FSR4 &&
                                        step(FSR4, 1, all) == FSR3 && step(FSR3, 1, all) == AUTO);
    CHECK("steps back", step(AUTO, -1, all) == FSR3 && step(BUILTIN, -1, all) == AUTO);
    CHECK("skips what does not run", step(BUILTIN, 1, fsr3) == FSR3 && step(FSR3, 1, fsr3) == AUTO &&
                                         step(AUTO, -1, fsr3) == FSR3 && step(FSR3, -1, fsr3) == BUILTIN);
    CHECK("upstream's row where neither of AMD's runs", step(AUTO, 1, 0) == BUILTIN && step(BUILTIN, 1, 0) == AUTO &&
                                                            step(AUTO, -1, 0) == BUILTIN);
    CHECK("a bad value steps from Auto", step(9, 1, all) == BUILTIN && step(-3, -1, all) == FSR3);
    CHECK("a choice that runs is kept", effective(FSR3, fsr3) == FSR3 && effective(BUILTIN, 0) == BUILTIN &&
                                            effective(AUTO, 0) == AUTO);
    CHECK("a choice that does not run is Auto", effective(FSR4, fsr3) == AUTO && effective(FSR3, 0) == AUTO &&
                                                    effective(7, all) == AUTO && effective(-1, all) == AUTO);
    // a value asked for: the arrows ask the one beside, the control bridge any one
    CHECK("a value that runs is taken as asked", pick(AUTO, FSR3, 1, fsr3) == FSR3 && pick(FSR3, AUTO, -1, fsr3) == AUTO &&
                                                     pick(AUTO, BUILTIN, 1, 0) == BUILTIN && pick(BUILTIN, FSR4, 1, all) == FSR4);
    CHECK("one that does not run: the next that does, the way asked", pick(BUILTIN, FSR4, 1, fsr3) == FSR3 &&
                                                                          pick(FSR3, FSR4, -1, fsr3) == BUILTIN);
    CHECK("past the ends: around", pick(FSR3, 4, 1, all) == AUTO && pick(AUTO, -1, -1, all) == FSR3 &&
                                       pick(BUILTIN, 2, 1, 0) == AUTO && pick(AUTO, -1, -1, 0) == BUILTIN);
    // what runs here: the most frames each of AMD's makes between two of the game's (0: it does not run)
    Here none, linux_pc, amd, every;
    linux_pc.most[FSR3] = 1;
    amd.most[FSR4] = 1, amd.most[FSR3] = 1;
    every.most[FSR4] = 4, every.most[FSR3] = 1;
    CHECK("the row offers what runs", available(none) == always() && available(linux_pc) == (always() | bit(FSR3)) &&
                                          available(amd) == all && available(every) == all);
    // a method makes a set only whole: multiplier - 1 frames, within what it makes here
    CHECK("FSR 3.1 makes 2x sets only", makes_set(every, FSR3, 2) && !makes_set(every, FSR3, 3) && !makes_set(every, FSR3, 8));
    CHECK("FSR 4 within its own limit", makes_set(amd, FSR4, 2) && !makes_set(amd, FSR4, 3) && makes_set(every, FSR4, 5) &&
                                            !makes_set(every, FSR4, 6));
    CHECK("what does not run makes nothing", !makes_set(none, FSR4, 2) && !makes_set(none, FSR3, 2) &&
                                                 !makes_set(linux_pc, FSR4, 2));
    CHECK("no set under 2x, and none by upstream's two through here",
          !makes_set(every, FSR4, 1) && !makes_set(every, FSR4, 0) && !makes_set(every, AUTO, 2) && !makes_set(every, BUILTIN, 2));
    // RX_VK_FG_METHOD
    CHECK("names", from_name("auto") == AUTO && from_name("builtin") == BUILTIN && from_name("fsr4") == FSR4 &&
                       from_name("fsr3") == FSR3);
    CHECK("numbers", from_name("0") == AUTO && from_name("1") == BUILTIN && from_name("2") == FSR4 && from_name("3") == FSR3);
    CHECK("anything else is not set", from_name(nullptr) == -1 && from_name("") == -1 && from_name("dlss") == -1 &&
                                          from_name("4") == -1 && from_name("22") == -1);
    // the row this fork had before: 0 Auto, 1 NVIDIA DLSS, 2 AMD FSR 4, 3 AMD FSR 3.1, 4 Built-in
    CHECK("an older file's method", from_old(0) == AUTO && from_old(1) == AUTO && from_old(2) == FSR4 && from_old(3) == FSR3 &&
                                        from_old(4) == BUILTIN && from_old(9) == AUTO && from_old(-1) == AUTO);
    if (failures) return 1;
    std::printf("PASS: the Frame generation by row steps over what runs, and AMD's methods make only the sets they make whole\n");
    return 0;
}
