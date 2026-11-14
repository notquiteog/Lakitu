/* What the runtime requires of a game profile (game_profile.h, from nx2/game_profile.py) before it will be
   compiled against it. nx2/game_profile.py and tests/test_game_profile.py say the same in Python; this is the C side,
   so a header written by hand, or by a profile that slipped past the test, stops the build instead of a game.

   A profile that names the return address the graphics module is captured at must name every offset the runtime reads
   in that module: host/nn_vi.c uses them unguarded once a module is captured, because capturing it is the guard. */
#ifndef GAME_PROFILE_CHECK_H
#define GAME_PROFILE_CHECK_H
#if GAME_HAVE_LR_GFX_CLOCK && !(GAME_GFX_HAVE_FRAME_LIMITER && GAME_GFX_HAVE_NOMINAL_FPS && GAME_GFX_HAVE_VRR_MODE && \
                                GAME_GFX_HAVE_VRR_GATE && GAME_GFX_HAVE_CONTROLLER && \
                                GAME_GFX_CONTROLLER_WORD_COUNT > 0 && GAME_GFX_CONTROLLER_RATE_WORD_COUNT > 0)
#error "game_profile.h names the graphics module's return address but not every offset read in it"
#endif
#if (GAME_HAVE_LR_GFX_CLOCK || GAME_HAVE_LR_PRESENT_POLL || GAME_LR_PRESENT_EVENT_COUNT) && !GAME_HAVE_BUILD_ID
#error "game_profile.h recognises return addresses without saying which build of main they are in"
#endif
#endif
