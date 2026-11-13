// gpu/vk/camera_vectors.h: the scene's camera in the world from its matrices (tests/test_camera_vectors.py)
#include "../gpu/vk/camera_vectors.h"

#include <algorithm>
#include <cmath>
#include <cstdio>

#define CHECK(name, condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL %s at line %d\n", name, __LINE__); return 1; } } while (0)

namespace cv = mkwvk::camera_vectors;

static bool near(double a, double b, double tol) { return std::fabs(a - b) <= tol * std::max(1.0, std::fabs(b)); }

// a perspective projection as the game fills it: row major, clip = p * view position, the view looking down -z, clip depth
// -1 (near) to 1 (far), or the other way round (reversed)
static void perspective(float p[16], double fovy, double aspect, double n, double f, bool reversed) {
    for (int i = 0; i < 16; i++) p[i] = 0.0f;
    const double c = 1.0 / std::tan(fovy / 2);
    p[0] = (float)(c / aspect), p[5] = (float)c, p[14] = -1.0f;
    const double zn = reversed ? 1.0 : -1.0, zf = -zn;
    const double p23 = (zn - zf) / (1.0 / n - 1.0 / f), p22 = p23 / n - zn;
    p[10] = (float)p22, p[11] = (float)p23;
}

// a view (world to camera), row major with column vectors: a turn about y by `yaw`, a tilt about x by `pitch`, then the
// camera at `eye`
static void view(float v[16], double yaw, double pitch, const double eye[3]) {
    const double c = std::cos(yaw), s = std::sin(yaw), cp = std::cos(pitch), sp = std::sin(pitch);
    const double y[3][3] = {{c, 0, -s}, {0, 1, 0}, {s, 0, c}};
    const double x[3][3] = {{1, 0, 0}, {0, cp, sp}, {0, -sp, cp}};
    double r[3][3];   // (rows: the camera's right, up and backward in the world)
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++) r[i][j] = x[i][0] * y[0][j] + x[i][1] * y[1][j] + x[i][2] * y[2][j];
    for (int i = 0; i < 16; i++) v[i] = 0.0f;
    for (int i = 0; i < 3; i++) {
        for (int j = 0; j < 3; j++) v[i * 4 + j] = (float)r[i][j];
        v[i * 4 + 3] = (float)-(r[i][0] * eye[0] + r[i][1] * eye[1] + r[i][2] * eye[2]);
    }
    v[15] = 1.0f;
}

static void mul(const float a[16], const float b[16], float out[16]) {
    for (int r = 0; r < 4; r++)
        for (int c = 0; c < 4; c++) {
            double s = 0;
            for (int k = 0; k < 4; k++) s += (double)a[r * 4 + k] * b[k * 4 + c];
            out[r * 4 + c] = (float)s;
        }
}

// a column-vector matrix times a position: out = m * v
static void times(const float m[16], const double v[4], double out[4]) {
    for (int r = 0; r < 4; r++) {
        out[r] = 0;
        for (int c = 0; c < 4; c++) out[r] += (double)m[r * 4 + c] * v[c];
    }
}

static int run(bool reversed) {
    float p[16], v[16], vp[16];
    perspective(p, 45.0 * 3.14159265358979 / 180.0, 16.0 / 9.0, 0.1, 1000.5, reversed);
    const double eye[3] = {3.4, 1.5, -6.2};
    view(v, 0.37, -0.21, eye);
    mul(p, v, vp);
    cv::Vectors cam;
    CHECK("camera", cv::from(p, vp, cam));
    for (int i = 0; i < 3; i++) CHECK("the camera's position", near(cam.position[i], eye[i], 1e-4));
    // the axes are the view's rotation rows, forward minus the third (the view looks down -z)
    for (int i = 0; i < 3; i++) {
        CHECK("right", near(cam.right[i], v[0 * 4 + i], 1e-5));
        CHECK("up", near(cam.up[i], v[1 * 4 + i], 1e-5));
        CHECK("forward", near(cam.forward[i], -v[2 * 4 + i], 1e-5));
    }
    {   // (unit length, at right angles, and right x up = backward: a right-handed camera)
        double rr = 0, uu = 0, ff = 0, ru = 0, rf = 0, uf = 0;
        for (int i = 0; i < 3; i++) {
            rr += cam.right[i] * cam.right[i], uu += cam.up[i] * cam.up[i], ff += cam.forward[i] * cam.forward[i];
            ru += cam.right[i] * cam.up[i], rf += cam.right[i] * cam.forward[i], uf += cam.up[i] * cam.forward[i];
        }
        CHECK("unit axes", near(rr, 1, 1e-5) && near(uu, 1, 1e-5) && near(ff, 1, 1e-5));
        CHECK("at right angles", std::fabs(ru) < 1e-5 && std::fabs(rf) < 1e-5 && std::fabs(uf) < 1e-5);
        const double cross[3] = {cam.right[1] * cam.up[2] - cam.right[2] * cam.up[1],
                                 cam.right[2] * cam.up[0] - cam.right[0] * cam.up[2],
                                 cam.right[0] * cam.up[1] - cam.right[1] * cam.up[0]};
        for (int i = 0; i < 3; i++) CHECK("right x up is backward", near(cross[i], -cam.forward[i], 1e-5));
    }
    {   // (a point one unit along forward is in front of the camera and in the middle of the picture)
        const double ahead[4] = {eye[0] + cam.forward[0], eye[1] + cam.forward[1], eye[2] + cam.forward[2], 1.0};
        double av[4], ac[4];
        times(v, ahead, av);
        times(vp, ahead, ac);
        CHECK("forward points into the picture", near(av[2], -1.0, 1e-4) && ac[3] > 0);
        CHECK("and at its middle", std::fabs(ac[0] / ac[3]) < 1e-4 && std::fabs(ac[1] / ac[3]) < 1e-4);
    }
    {   // (a point along right is on the right of the picture, one along up above its middle: clip y is up)
        const double side[4] = {eye[0] + 5 * cam.forward[0] + cam.right[0], eye[1] + 5 * cam.forward[1] + cam.right[1],
                                eye[2] + 5 * cam.forward[2] + cam.right[2], 1.0};
        const double above[4] = {eye[0] + 5 * cam.forward[0] + cam.up[0], eye[1] + 5 * cam.forward[1] + cam.up[1],
                                 eye[2] + 5 * cam.forward[2] + cam.up[2], 1.0};
        double sc[4], uc[4];
        times(vp, side, sc);
        times(vp, above, uc);
        CHECK("right is the picture's right", sc[0] / sc[3] > 0.01 && std::fabs(sc[1] / sc[3]) < 1e-4);
        CHECK("up is the picture's up", uc[1] / uc[3] > 0.01 && std::fabs(uc[0] / uc[3]) < 1e-4);
    }
    return 0;
}

int main() {
    if (run(false)) return 1;   // (the game's depth as shipped)
    if (run(true)) return 1;    // (a reversed projection: the same camera)
    // what is not a perspective projection looking down -z, or cannot be inverted, makes no camera
    float p[16], id[16];
    perspective(p, 1.0, 16.0 / 9.0, 0.1, 1000.5, false);
    for (int i = 0; i < 16; i++) id[i] = i % 5 == 0 ? 1.0f : 0.0f;
    cv::Vectors cam;
    CHECK("an orthographic projection", !cv::from(id, id, cam));
    float singular[16];
    for (int i = 0; i < 16; i++) singular[i] = p[i];
    singular[0] = 0.0f;
    CHECK("a projection that cannot be inverted", !cv::from(singular, p, cam));
    float bad[16];
    for (int i = 0; i < 16; i++) bad[i] = p[i];
    bad[3] = NAN;
    CHECK("a view-projection that is not finite", !cv::from(p, bad, cam));
    std::printf("PASS: the camera's position and axes in the world from the scene's matrices\n");
    return 0;
}
