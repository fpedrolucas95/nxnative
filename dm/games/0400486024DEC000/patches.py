# The Legend of Zelda: Ocarina of Time (Switch 2, 0400486024DEC000): the rewriter's patches of this game's own builds. dm/tools/patch_nso.py loads every profile's patches.py and applies those
# of a module's NSO build ID; CUTS, OBS and FRAME_STEP as described there ("Registered patches"). Patches of Nintendo SDK module builds are in dm/tools/sdk_patches.py
from nso_asm import ADRP, B

# Render scale (state +0x10, the float the loader writes: DM_RENDER_SCALE, 1.0 by default). The scene is the output (2560x1440 docked, 1920x1080 handheld) times a scale the game's
# dynamic-resolution controller picks from its level palette (0.75 down to 0.333 docked). The controller's update (main+0x805aa0) returns the chosen level's scale in the low word of x0
# through main+0x805ff0 (fmov w9,s8), with a level-changed flag above it, and its caller (main+0x31d3ee0) makes it the scene's scale when the level changes or the stage starts
# (found by lunks with read watchpoints on the palette, github.com/lunks/nxnative 9c613234 and be545073). The stub keeps that word at scale 1.0 and otherwise returns the host's
# scale instead, so every level has it: 0.5 renders 1280x720 docked. After main+0x805ff0 the flags are set again (cmp w8,w20) and x10 / x11 are not read before the return.
# On a MacBook Air M4 the GPU is the limit in Kokiri Forest (34-65 ms a frame at the game's own 1536x864); the setting trades that for resolution
def frame_step(ctx):
    here, emit, fs_site, fs_put, FS_STATE_OFF = ctx.here, ctx.emit, ctx.site, ctx.put, ctx.state
    fs_site(0x805ff0, '0901261e')
    start = here(); emit(0x1e260109)   # fmov w9,s8            (original: the level's scale)
    emit(ADRP(10, here(), FS_STATE_OFF))
    for w in (0xb940114a,   # ldr w10,[x10,#0x10]  render scale
              0x52a7f00b,   # mov w11,#0x3f800000  1.0
              0x6b0b015f,   # cmp w10,w11
              0x54000060,   # b.eq done (+12)      1.0: the game's dynamic resolution
              0x3400004a,   # cbz w10,done (+8)    not set
              0x2a0a03e9):  # mov w9,w10           a fixed scale
        emit(w)
    emit(B(here(), 0x805ff4))
    fs_put(0x805ff0, [B(0x805ff0, start)], 'scene scale = the host render scale (1.0 = the game\'s dynamic resolution)'); ctx.render_scale = 1

FRAME_STEP = {'e0f3ccfaf50065ae4ea01eb5aeb13b1a': frame_step}

# How general each patch is and could be (dm/tools/docs_patches.py "Binding", listed in docs/agents/game-patches.md)
BINDING = [
    {'what': 'render scale', 'now': 'build', 'goal': 'game', 'purpose': 'frame rate',
     'why': "the game's own dynamic-resolution controller",
     'blocked': 'frame-step stubs have no function-matched form yet'},
]
