"""Ocarina's camera, published from sead's perspective projection so the renderer can read it.

The projection's matrix update (main+0x3485cc0, the whole function f_834a5cc0) has the object in x0
and has just loaded tan(fovy/2) and the aspect ratio from it. This appends a block there that also
reads the near and far planes and writes all three to host globals (host/hos_oot_camera.c), which a
temporal upscaler needs: FSR builds device_to_view_depth and tan_half_fov from the near plane and
the field of view, and camera-derived motion needs the same projection.

The field layout, and how each offset was identified from what the function does with it, is in
docs/upscaling.md. The site is shared with nx2/oot_wide.py's camera-ratio patch, so this appends to
whatever is already there rather than replacing it; the "oot" profile lists oot_wide before
oot_camera (nx2/game_profile.py), which is what puts the ratio in first.

Which of +0x98 and +0x9C is the near plane depends on the byte at +0x0A, which the function uses to
swap them before taking their difference. Rather than decide what that flag means, this takes the
smaller of the two as the near plane and the larger as the far, and publishes nothing unless both
are positive and ordered. A projection with a near plane behind the eye is not one to hand an
upscaler.

It also snapshots the first 48 floats of the projection object at publish time, which
HOS_CAMERA_DUMP=1 logs. A snapshot rather than a pointer because the object the inlined copies build
is transient: reading the published address a frame later came back all zeros, so it is a stack
temporary. The view projection a temporal upscaler reprojects with is not the projection alone, and
this window is how the rest of it gets identified from real values instead of a guess.
"""

import game_profile

# The same four sites nx2/oot_wide.py patches for the camera ratio: sead's perspective projection
# matrix update and its three inlined copies. The projection object is in a different register in
# each, which is the second argument of oot_wide's _ratio() at the same offsets. Patching only the
# out-of-line copy published nothing in a real run, because the path that runs is inlined.
SITES = (
    # (offset, the original word, the register holding the projection, whether x1 is known to hold
    #  the 4x4 it writes: verified only in the out-of-line copy, and the dump dereferences it)
    (0x3485cc0, 0x2d558400, 0, True),
    (0x4f1e8, 0x2d558ea0, 21, False),
    (0x23b9a8, 0x2d558c00, 0, False),
    (0x33b82c, 0x2d558440, 2, False),
)

def _publish(base, with_matrix):
    matrix = ("hos_oot_proj_matrix = c->x[1]; " if with_matrix else "")
    return (
    "{ extern volatile float hos_oot_cam_near, hos_oot_cam_far, hos_oot_cam_tan_half_fov; "
    "extern volatile int hos_oot_camera_valid; const uint64_t _cp = c->x[0]; "
    "uint32_t _c0 = (uint32_t)recomp_load32(c, _cp + 0x98), _c1 = (uint32_t)recomp_load32(c, _cp + 0x9c), "
    "_ct = (uint32_t)recomp_load32(c, _cp + 0xac); float _f0, _f1, _ft; "
    "memcpy(&_f0, &_c0, 4); memcpy(&_f1, &_c1, 4); memcpy(&_ft, &_ct, 4); "
    "{ const float _nr = _f0 < _f1 ? _f0 : _f1, _fr = _f0 < _f1 ? _f1 : _f0; "
    "if (_nr > 0.0f && _fr > _nr && _ft > 0.0f) { hos_oot_cam_near = _nr; hos_oot_cam_far = _fr; "
    "hos_oot_cam_tan_half_fov = _ft; hos_oot_camera_valid = 1; } } "
    "{ extern volatile uint64_t hos_oot_proj_object, hos_oot_proj_matrix; (void)hos_oot_proj_matrix; "
    "hos_oot_proj_object = _cp; " + matrix + "} "
    "{ extern volatile float hos_oot_cam_window[48]; extern volatile int hos_oot_cam_window_have; "
    "if (!hos_oot_cam_window_have) { for (int _i = 0; _i < 48; _i++) { "
    "uint32_t _w = (uint32_t)recomp_load32(c, _cp + (uint64_t)_i * 4); float _fv; memcpy(&_fv, &_w, 4); "
    "hos_oot_cam_window[_i] = _fv; } hos_oot_cam_window_have = 1; } } }"
    "   /* (nx2/oot_camera.py: the camera a temporal upscaler needs) */"
    ).replace("const uint64_t _cp = c->x[0];", "const uint64_t _cp = c->x[%d];" % base)


def install(lifter, img, profile=None):
    """Appends the publish to every projection update site. A site whose word differs is left out;
    0 sites leaves the renderer on its own defaults."""
    sites = tuple((off, word, _publish(base, with_matrix)) for off, word, base, with_matrix in SITES)
    return game_profile.install_sites(lifter, img, profile or game_profile.active(), sites, "camera")
