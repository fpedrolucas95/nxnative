# The Legend of Zelda: Ocarina of Time

The Switch 2 base dump and update 1.2.0 (`v131072`) reach the title screen, the opening movie and playable Kokiri Forest on the Mac. VideoToolbox decodes the 1920×1080 AV1 track. The movie library runs its NDVE compute shaders to produce the background behind the logo and menu. Gameplay in Kokiri Forest runs at ~60 fps (frame p50 16.29 ms, GPU p50 13.87 ms on Apple M5 Pro).

## Profile

SDK 22.2.8, NVN API 231.40, with Nintendo's sead, agl and gsys. The three loaded modules are `main`, `subsdk0` (NintendoSDK_movie), and `sdk`. The NPDM declares 48 MiB of system resources. Startup requests a 6.20 GiB heap out of the 9.00 GiB application pool, leaving 2.80 GiB for virtual-address-memory mappings in the 16 GiB alias region (`mem_alias 0x400000000`, `mem_reserve 0x668000000`). The registered builds are the base dump (`v0`) and update 1.2.0 (`v131072`).

## Mac dry run

Use the rewritten `patched_v0` (or `patched_v131072`) and the extracted `romfs`. Build the host with `make -C dm/host GAME=0400486024DEC000` and use the [Mac shader build](../../../docs/development.md#build-by-hand-mac). From the repository, set `DUMP` to the folder containing `base` and `WORK` to the build and run workspace beside it.

```sh
mkdir -p "$WORK/run/save" "$WORK/run/temp" "$WORK/font"
python3 dm/tools/make_ext_font.py "$WORK/font/nintendo_ext.ttf"
DM_ROOT="$WORK" DM_ROMFS="$DUMP/base/romfs" DM_SAVE="$WORK/run/save" \
  DM_TEMP="$WORK/run/temp" DM_MSL_DIR="$WORK/shader/cache" DM_FONT_DIR="$WORK/font" \
  DM_NVN_SHMAP="$PWD/dm/games/0400486024DEC000/shader_map.tsv" \
  DM_WINDOW=1 DM_METAL_HUD=1 DM_FOCUS_KEEP=1 DM_AUDIO=1 \
  dm/host/dmhost "$WORK/patched_v0"
```

`DM_FOCUS_KEEP=1` lets the title keep playing while another app has focus. The profile prewarms the NDVE compute pipelines and 8,308 scene shaders (965 render pipelines, 121 compute pipelines).

Start a new game to reproduce the opening scene transition. With the test save and title flow, `DM_KEYS=f2600:A,f2950:A` advances the menu automatically. `DM_NVN_SHDUMP` saves control sections and code for missing keys to the directory it names.

For a run past the opening, copy the committed save folder to the new run's `DM_SAVE` and load slot 00 from the menu. The checkpoint contains both `slot_00/progress.sav` and `slot_00/caption.sav`. The load screen identifies it as **Kokiri Forest Autosave**. A windowed reload reached the playable scene with the HUD and controls, so rendering can be tested without replaying the movie.

## Found on this game

- The online library's [eventfd for its poller](../../../docs/reference/services.md#eventfds-served-offline) and the [virtual audio input list](../../../docs/reference/audio.md#no-virtual-audio-input-devices-sdk-22) blocked startup.
- The SDK's [NDVE pack](../../../docs/reference/shaders.md#the-movie-librarys-ndve-shader-pack) contains 22 compute programs. The title route uses 11.
- The [raw write log and pool lookup](../../../docs/reference/frame-rate.md#a-full-frame-shader-overflows-the-raw-write-log) took the windowed title movie from a 47.6 ms median to 16.67 ms on an Apple M5, at 1920×1080 decode. A steady 300-frame window averaged 60.0 fps and its GPU median was 15.94 ms. A simultaneous ten-worker shader build caused additional stalls. The same run returned to 60.0 fps when the build paused.
- A [play report send](../../../docs/reference/services.md#an-asynchronous-play-report-opens-prepou) aborted at the first gameplay transition after a failed `prepo:u` connection. A Mac dry run with the offline completion finished the 9,254-picture opening movie and continued submitting the live scene. The title-only shader set left the scene black.
- The white 3D scene was agl's [conditional depth clears](../../../docs/reference/rendering.md#conditional-rendering-evaluated-at-replay) run unconditionally (resolved; the profile sets `render_cond on`). The main opaque pass tests `EQUAL` against a copy of the prepass depth that agl clears under a condition right after copying, a clear the console skips. Without the key the copy was 1.0, no lit geometry passed, and the full-screen sky (`943d8c0ece545cc8`) showed through. With the key the saved Kokiri Forest scene renders: Link, the ground, the props, lighting and the HUD.
- Mesh-shaded models were missing, among them the door of Link's house: the split read six stage slots of each BNSH program, and NVN2 keeps [task and mesh shaders in slots 7 and 8](../../../docs/reference/shaders.md#task-and-mesh-shaders-in-nvn2-bnsh-program-slots-7-and-8) (resolved). The new split adds 491 mesh and 17 task shaders to the map, 53 of the 54 keys the Kokiri Forest scene had asked for. All 21,648 shaders in the map now translate and build cleanly.
- Kokiri Forest ran at about 20 fps with the GPU two-thirds idle: the [bindless pool table was rebuilt for every registration](../../../docs/reference/frame-rate.md#a-bindless-pool-table-rebuilt-for-every-registration), and about 12,000 descriptors of finalized texture objects churned the ghost ring (resolved). The frame is now 16–21 ms at the median on an Apple M5, submit 5–8 ms, and the GPU (14–21 ms) is the limit.
- The first 3D scene exhausted Metal memory when [bindless pool walks churned finalized textures](../../../docs/reference/nvn-objects.md#a-bindless-pool-churns-finalized-textures-within-a-submission). On the Apple M5, the failing run reached 18,930 MiB of residency. With submission-local backing, residency was 7,946 MiB about ten seconds after the movie and 7,871 MiB at 35 seconds. The opening 3D scene and its subtitles presented, and the test host exited normally.
- Three compute shaders (`d17eefaff4f0bc23`, `92918e9b7e2f89a4` and `1fdc85178b60f6ce`) live inside `Shader/agl_ndsr.pck` (`NDSR` upscaler pack, version `0x102`, code size at header `+0x14`, code at `+0x20`, control at `+0x30 + code_size`). `shader_split.py` (`ndsr_shaders`) extracts them and brings the profile's map to 21,648 shaders (`cs_lib.bin` 5,288,536 bytes).
- Entering gameplay after the opening Kokiri Forest cutscene triggered a macOS `WindowServer` watchdog panic (`bug_type 409`, 40 s GPU hang). Five causes were resolved:
  1. `GMEM_RUN_MAX` raised from 256 to 1024 in `nvn_mtl.m`: the game allocates 521 contiguous 64 KB NVN memory pools for a 32.56 MB arena (`0x71072c0000..0x7109350000`), which previously exhausted the 256-slot merged-buffer cache and overflowed `DMSH_GMEM_MAP_ENTRIES` (`511` entries), returning `0` from `dmsh_gmem` on raw global pointers; with `GMEM_RUN_MAX = 1024`, all 2,167 pools merge into 407 ranges.
  2. Twelve unskinned (`#var0`, `MAX_BONES = 0`) task and mesh shaders (including task shaders `46766c69242c5253` and `47234a5c637b0c1d`) had a `do { ... i++; } while (int(i - 0u) != (-1))` loop that ran `4,294,967,296` iterations per thread when `c0_u[8]` was 0; `loop_guard` in `dmsh_build.py` bounds every `for`, `while` and `do-while` loop at `262,144` iterations.
  3. Conditional `threadgroup_barrier` inside divergent branches (`BarrierExits` in `BarrierDivergence.cs`) and warp-synchronous shared memory stores without barriers (`tg_fence` in `dmsh_build.py`) were fixed across 34 shaders.
  4. `nvnCommandBufferDrawMeshTasksIndirect` (`OP_DRAW_MESH_INDIRECT`) is implemented and clamps GPU-written task group counts via `dpc_clamp` (`DM_NVN_DISPATCH_CLAMP`, max `65,535` per axis and `2^22` total threadgroups), matching indirect compute dispatches.
  5. A GPU watchdog (`DM_NVN_GPU_WATCHDOG`, default 4 s) and submission shader ring (`wk_note` / `wk_dump`) terminate the process before a stuck command buffer can hang `WindowServer`.
- Foliage vertex jitter and missing fairy/water rendering were caused by Ampere `F2FP` (`0x23e` / `0x83e`, mode `0x4ff` `MERGE_AB`) and `I2FP` (`0x243`, two-register pack when `sA != RZ`) missing from `InstEmitAmpereAlu.cs`, and by `a5288d0a6c4971fd`'s 3D volume texture (`cp_t_tcb_18_`) misclassified as `Texture2D` instead of `Texture3D` in `shader_facts.tsv`.
- Rapid foliage jitter across Kokiri Forest came from three wind/displacement field compute shaders (`04942f42cae10d0f`, `69c96afef37c6010` and `9dc103f230b6cfde` in `AglShader.sharcb`): when one result component of an image load (`SULD`) was unused while another remained live, [dead-code removal dropped the instruction's coordinate inputs](../../../docs/reference/shaders.md#dead-code-removal-dropped-the-inputs-of-atomics) and replaced the Y coordinate with an uninitialized local (`int _139;`) before computing the finite-difference gradient written to `cp_i_tcb_4A_`.
- Steady memory growth (14–18 GB resident after six minutes of play, `50.8 GB` of textures created per 300 frames), periodic 50–136 ms stutters and transparent ground patches were caused by [retired texture descriptors evicting live alias textures and rebuilding the bindless pool](../../../docs/reference/rendering.md#retired-texture-descriptors-evicting-live-alias-textures-and-rebuilding-the-bindless-pool): `alias_take_over` bumped `g_ser_gen` without `alias_note`, forcing full 33,024-entry bindless pool scans during which `treg_tex` recreated retired descriptors at `(pool_id, off)`, inserted them into `g_ghost` and evicted the live terrain blend maps occupying the same address range (`TerrainGround` fragment shaders `100b4fdb77bd97bb` and `e8202838bd8b66c8` then discarded ground fragments where the zeroed blend weight tested `<= 0.50186`).
- Inside the Great Deku Tree and at scene transitions after the boss cutscene:
  1. The 2.38 GiB alias region (`mem_alias 0x98000000`) ran out of virtual address space once virtual-address-memory mappings reached 2.02–2.25 GiB out of the 2.80 GiB `pool - heap` budget, causing `sead` resource-heap `AllocateAddressRegion` failures and hanging `OptimizeChangeBanc` on a black screen when returning to Kokiri Forest after the Triforce cutscene or reloading that save (`mem_alias 0x400000000`, `mem_reserve 0x668000000`).
  2. Streamed terrain tiles and level textures written into CPU-cached pools after initial resolution stayed zeroed without `tex_flush_upload on` and `tex_dirty_upload on`.
  3. Finalizing packaged room textures left retired descriptors in `g_treg` that `pool_entry` re-uploaded into `g_ghost` and marked transient (`p->sub = g_sub_serial`), forcing full 10,496-ID bindless pool rebuilds and re-uploads on every subsequent submission; and `mtl_alias_drop_pool` dropped `g_cpu_tex_retired` before marking the pool's descriptors `gone`, allowing a concurrent `tex_mtl_` lookup to return a cached `NvPkg` where an `id<MTLTexture>` was expected.

## Open

- The GPU's 14–21 ms a frame in Kokiri Forest occasionally drops frames below 60 fps; TBDR optimizations are off for this bindless game (`DM_NVN_TBDR=1` turns them on), and attachments load and store about 330 MB a frame.
