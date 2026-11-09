"""Occlusion Off for Ocarina of Time 1.1.1: C added after six instructions of the game (a64_lift.py Lifter.after).

The game decides at six places whether to make its z-prepass occlusion queries and its samples-passed queries, each by a
byte it loads (ldrb w8, [x0]). With hos_occlusion_off set (HOOKSHOT_OCCLUSION_OFF=1), that byte reads 0: the game makes
no occlusion queries, so it issues no occlusion reports and no conditional renders, and every candidate object is drawn.
Our renderer has no real occlusion counts (each draw adds 16 samples), so the game's visibility answers came from that guess.

The sites are cLohan's community patch (zortos293/Lichii#641), as Fritchii ships it (Frizti/Fritchii 1a46ba972,
"Occlusion Off", ldrb w8, [x0] -> mov w8, wzr). Each site's original word is checked: another game version leaves it out.
"""

import game_profile

LDRB_W8_X0 = 0x39400008
OFFSETS = (0x11ACE68, 0x11B828C, 0x11B82A4, 0x11ACEC8, 0x11B82DC, 0x11B82F4)
TEXT = ("{ extern volatile int hos_occlusion_off; if (hos_occlusion_off) c->x[8] = 0; }   "
        "/* (nx2/oot_occlusion.py: no occlusion queries) */")
SITES = tuple((off, LDRB_W8_X0, TEXT) for off in OFFSETS)


def install(lifter, img, profile=None):
    """The sites into lifter.after; a site whose word differs (another game version) is left out"""
    return game_profile.install_sites(lifter, img, profile or game_profile.active(), SITES, "occlusion off")
