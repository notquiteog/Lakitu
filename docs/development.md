# Lakitu (mkw fork of Hookshot)

**Lakitu** is this fork's name (as Hookshot is the Ocarina port's, Skybound is TOTKPort's and BlueShell is
mkw-recomp's). The repository folder and the built file names are unchanged (`hookshot.exe` + `hookshot_vk.dll`,
`HOOKSHOT_*` variables): they are plumbing, and renaming them would break the release layout and the builder for no
gain. One constant holds the project's name, `PROJECT` in [`nx2/game_profile.py`](../nx2/game_profile.py), and the
window, the AppImage and the builder read it from there.

A static recompilation of a Switch 2 title to native x86-64 Windows and Linux: the game's code lifted to C
(NotRexed's a64-kit, Rexcomp's AArch64 kit), the Horizon OS and NVN2 implemented natively, the GPU work replayed on
Vulkan. Hookshot is mkw-recomp (Mario Kart World) retargeted to Ocarina of Time; this fork is the engine being
taken back to Mario Kart World, which is why the Vulkan back end is still `namespace mkwvk` with an `MkwVkRenderer`
and `host/mkw_glue.c` is still in the tree. Those names are correct for this game and are left alone.

**Which game a build is for: the game profile.** Everything that is one game's rather than the engine's &mdash;
patch sites, the base `main` is loaded at, the offsets into the graphics module, the shader program keys &mdash;
lives in [`nx2/game_profile.py`](../nx2/game_profile.py), with Ocarina's measured values as the `oot` profile and an
empty `mkw` profile beside it. `HOOKSHOT_GAME=<key>` picks one; the default is `oot`, because it is the only game
whose values have been measured.

- `nx2/lift.py` asks the profile which patch modules to install and never imports a game's modules by name.
- `host/` and `gpu/vk/` read the same profile through `game/game_profile.h`, which is generated from that file by
  `python -I nx2/game_profile.py --emit-header` and committed. `tests/test_game_profile.py` fails if the committed
  header stops matching, so the two cannot drift.
- A field the profile does not know is `None`, and the feature that needs it is off: the runtime says once that it
  has no offset for a pacing field and leaves it alone, and a profile with no patch modules is lifted without
  patches. A guessed address would be a crash or silent memory corruption instead.
- Every patch site carries the instruction word the game is expected to have at it. `game_profile.install_sites()`
  checks that word and skips the site when it differs, so pointing a profile at the wrong build cannot patch
  anything. Keep that property in any new patch module.
- `python -I nx2/game_profile.py` prints both profiles and what is still unknown in each.

**No game files are in this repository.** The dump is read where it lies (`work/dump.txt`); everything made from it
(modules, image, lifted C, builds, runs) goes to `work/`, which git ignores.

Status, `oot` profile: the dump is read, lifted and played. Status, `mkw` profile: scaffolding only &mdash; no dump,
so no measured value in it. The readme's "What a Mario Kart World build still needs" lists what has to be found
first. Plan, stages and the lessons carried over from MKW: [design.md](design.md).

## Use

Requirements: Python 3 with `lz4`, `numpy`, `capstone`, `unicorn` (2.1), `zstandard`; emsdk's clang at `C:\emsdk` (or `EMSDK`);
for the Vulkan back end, Eden's CPM package cache (found in mkw-recomp's `work/eg` or `..\Eglantine\.cache\cpm`, or
`RX_CPM`).

Run everything with `python -I` from this folder.

| Command | What |
|---|---|
| `python -I nx2/nup.py <file.nup> --extract work/dump` | the `.nup` dump package to `work/dump/exefs` + `romfs` (newest title; ZBIC NSOs made plain by `nx2/unpack.py`) |
| `python -I nx2/dump.py --dump <folder with exefs/ and romfs/> --set` | what the dump is (Switch 1 or 2, ids, modules, SDK, NVN); `--set` records it in `work/dump.txt` |
| `python -I nx2/game_profile.py` | both game profiles and what each still does not know; `--emit-header` rewrites `game/game_profile.h` |
| `python -I nx2/lift.py [--write]` | image + discovery + coverage (`work/image/coverage.txt`); `--write` emits the C to `work/gen` |
| `python -I nx2/census.py --nx2` | instruction census per module, after the Switch 2 forms |
| `python -I nx2/test_insn.py [--per 6 --states 12]` | every instruction form the game uses, Unicorn vs lifted C |
| `python -I nx2/test_leaf.py [--count 3000 --states 4] [--calls]` | random whole functions (or call trees), Unicorn vs recompiled native code on the real image |
| `python -I nx2/lift.py --standalone --write` then `python -I nx2/build.py --standalone --jobs 4` | the standalone game: `work/sa/build/hookshot.exe` + `hookshot_vk.dll` |
| `powershell -File scripts/run-vk.ps1 [-Window] [-Seconds 120] [-Name x]` | a muted test run on Vulkan, with screenshots in `work/runs/<name>/shots` |
| `python -I scripts/prof.py <stacks file>` | a profile sampled with `HOS_SAMPLE=<thread>` + `HOS_SAMPLE_FILE=<stacks file>`, named from the linker maps |

The dump can also come from `OOT_DUMP` (its folder) or `OOT_EXEFS`; `OOT_WORK` moves the work folder.
`HOOKSHOT_GAME=<oot|mkw>` picks the game profile; without it, `oot`.

The built game's own arguments (`image.bin`, `--romfs`, `--user`, `--trace`, `--prepare-shaders`) are in the README's
[Running the game from the command line](../readme.md#running-the-game-from-the-command-line).

Scripted test input (`HOS_INPUT_SCRIPT` and `HOS_INPUT_LIVE`) is applied before the window-focus check. A log saying
the game window is not in front does not mean those presses were discarded. `HOS_HEADLESS` and
`HOS_WINDOW_NOACTIVATE` change window creation, not this input routing. The game must still reach a state that reads
and responds to the supplied controller input.

Physical keyboard and mouse input stays with the foreground window. Physical controllers can also play in the
background when the existing "Controller in background" option or `HOS_INPUT_BACKGROUND=1` enables them;
`HOS_INPUT_BACKGROUND=0` overrides that option. `HOS_INPUT_EXCLUSIVE=1` controls merging the player's devices while
the script's existing exclusive interval is active; it is not a focus override.

## Layout

| Path | What |
|---|---|
| `docs/design.md` | why mkw-recomp's pipeline, the architecture, MKW's lessons as rules, stages, testing |
| `nx2/game_profile.py`, `game/game_profile.h` | which game a build is for, and that game's addresses, offsets and keys |
| `nx2/` | the lift pipeline and its tests (mkw-recomp's, made game-neutral; `kit.py` has the paths) |
| `host/` | the standalone Horizon runtime (TOTKPort's `hos/` as adapted by mkw-recomp), with the native NVN2 layer `nvn_native.c` |
| `gpu/vk/` | the Vulkan back end (`hookshot_vk.dll`), with Eden's shader recompiler and sirit |
| `gpu/render/`, `gpu/third_party/` | the WebGPU renderer the exe falls back to, its op stream (`rx_nvn.h`), suyu's decoders |
| `scripts/` | test runs and the profile reader |
| `third_party/` | a64-kit (unmodified), libopus, zbic (Atmosphere's zstd with ZBIC, for unpacking only) |

License: GPL-3.0-or-later, as Hookshot and mkw-recomp: a64-kit's translator is suyu's (GPL-2.0-or-later) and Eden's code is
GPL-3.0.
