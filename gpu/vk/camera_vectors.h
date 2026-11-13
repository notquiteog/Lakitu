/* (hookshot fork) The scene's camera in the world, from the matrices the renderer keeps: plain functions, no Vulkan.
   tests/test_camera_vectors.cpp checks them. AMD FSR 4's frame generation is handed these (vk_framegen.cpp ffx_frames).

   The matrices are as the game fills them (vk_fsr3_inputs.h Frame): row major with column vectors (clip = M * position)
   and a view that looks down -z (the projection's w row is 0 0 -1 0). The view is inverse(projection) * view-projection;
   its rotation's rows are the camera's axes in the world (x right, y up, z backward), and its position is minus the
   rotation's transpose times the translation. vk_dlss.cpp's dlss_fg_inputs takes the same from the view's inverse. */
#pragma once

#include <cmath>

namespace mkwvk::camera_vectors {

struct Vectors {
    float position[3]{}, right[3]{}, up[3]{}, forward[3]{};   ///< forward: the way the camera looks
};

namespace detail {

/// m inverted (row major, 4x4) by Gauss-Jordan with partial pivoting, in doubles; false when it is singular or not finite
inline bool invert(const double m[16], double out[16]) {
    double a[4][8];
    for (int r = 0; r < 4; r++)
        for (int c = 0; c < 8; c++) {
            a[r][c] = c < 4 ? m[r * 4 + c] : (c - 4 == r ? 1.0 : 0.0);
            if (!std::isfinite(a[r][c])) return false;
        }
    for (int c = 0; c < 4; c++) {
        int p = c;
        for (int r = c + 1; r < 4; r++)
            if (std::fabs(a[r][c]) > std::fabs(a[p][c])) p = r;
        if (std::fabs(a[p][c]) < 1e-12) return false;
        if (p != c)
            for (int k = 0; k < 8; k++) {
                const double t = a[p][k];
                a[p][k] = a[c][k], a[c][k] = t;
            }
        const double inv = 1.0 / a[c][c];
        for (int k = 0; k < 8; k++) a[c][k] *= inv;
        for (int r = 0; r < 4; r++) {
            if (r == c || a[r][c] == 0.0) continue;
            const double f = a[r][c];
            for (int k = 0; k < 8; k++) a[r][k] -= f * a[c][k];
        }
    }
    for (int r = 0; r < 4; r++)
        for (int c = 0; c < 4; c++) out[r * 4 + c] = a[r][c + 4];
    return true;
}

}  // namespace detail

/// The camera of a scene drawn with this projection and view-projection (without their jitter). False when the projection
/// is not a perspective one looking down -z, or cannot be inverted: no frame from AMD's runtime then
inline bool from(const float projection[16], const float view_projection[16], Vectors& out) {
    out = Vectors{};
    if (projection[12] != 0.0f || projection[13] != 0.0f || projection[14] != -1.0f || projection[15] != 0.0f) return false;
    double p[16], vp[16], ip[16], v[16];
    for (int i = 0; i < 16; i++) p[i] = projection[i], vp[i] = view_projection[i];
    if (!detail::invert(p, ip)) return false;
    for (int r = 0; r < 4; r++)
        for (int c = 0; c < 4; c++) {
            double sum = 0;
            for (int k = 0; k < 4; k++) sum += ip[r * 4 + k] * vp[k * 4 + c];
            v[r * 4 + c] = sum;
        }
    for (int c = 0; c < 3; c++) {
        out.right[c] = (float)v[0 * 4 + c];
        out.up[c] = (float)v[1 * 4 + c];
        out.forward[c] = (float)-v[2 * 4 + c];
        out.position[c] = (float)-(v[0 * 4 + c] * v[0 * 4 + 3] + v[1 * 4 + c] * v[1 * 4 + 3] + v[2 * 4 + c] * v[2 * 4 + 3]);
    }
    for (int c = 0; c < 3; c++)
        if (!std::isfinite(out.right[c]) || !std::isfinite(out.up[c]) || !std::isfinite(out.forward[c]) ||
            !std::isfinite(out.position[c]))
            return false;
    return true;
}

}  // namespace mkwvk::camera_vectors
