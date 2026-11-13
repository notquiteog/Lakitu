"""Adjust the gameplay lens before its projection and frustum are built (OoT 1.1.1).

The camera update loads its vertical angle at +0x13c, then writes the angle and its
half-angle's sine, cosine and tangent into sead's perspective projection. Changing
only that load lets the game build both rendering and CPU culling from the chosen
angle, without changing the camera's authored angle or accumulating a scale.
"""

import game_profile

MAIN = game_profile.OOT.main_base   # (the "oot" profile names this module: nx2/game_profile.py)
BUILD_ID = game_profile.OOT.build_id
SITE = MAIN + 0x4c52f8
# The angle load, half-angle multiply and projection angle store.
WORDS = (0xbd413e60, 0x1e210808, 0xbd00a280)
HOOK = ("{ extern void hos_oot_fov(Ctx *c, uint64_t camera); hos_oot_fov(c, c->x[19]); }"
        "   /* (nx2/oot_fov.py: gameplay field of view) */")


# (main offset, the three consecutive words the hook relies on, the C after the first: nx2/game_profile.py install_sites)
SITES = ((SITE - MAIN, WORDS, HOOK),)


def install(lifter, img, build_id, profile=None):
    if build_id != BUILD_ID:
        print("field of view: unsupported camera code, left out")
        return 0
    n = game_profile.install_sites(lifter, img, profile or game_profile.OOT, SITES, "field of view")
    if n:
        print("field of view: gameplay lens hooked")
    return n
