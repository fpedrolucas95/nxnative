// pkg_alias_evict_idle (nvn_mtl.m): a packaged texture kept by storage (g_pkg_alias) leaves once no serial resolves to it
// (live, ghost or active) and it has not been resolved for PKG_IDLE_FRAMES frames; one a serial still resolves to, and one
// resolved lately, stay. Before, entries left only with their pool, so streamed textures of areas left behind kept their
// Metal copies for the rest of the session (Ocarina of Time's guest-memory textures beside their pool bytes).
#include "../nvn/nvn_mtl.m"
void *front_metal_layer(void) { return NULL; }
module_t *module_of(const void *p) { (void)p; return NULL; }
module_t *g_mod; int g_nmod;
void svc_thread_dump(void) {}
uint64_t now_ns(void) { return bp_now(); }
static int checks, failed;
#define CHECK(c, label) do { checks++; if (!(c)) { failed++; fprintf(stderr, "FAIL: %s (line %d)\n", label, __LINE__); } } while (0)

static alias_key key(int64_t off) { alias_key k; memset(&k, 0, sizeof k); k.pool = 0x1000; k.off = off; return k; }
static int kept(const alias_key *k) { pthread_mutex_lock(&g_smu); int r = hm_get_id(&g_pkg_alias, k) != nil; pthread_mutex_unlock(&g_smu); return r; }
static void put(const alias_key *k, NvPkg *pk, uint64_t used) {
    pk->used = used;
    pthread_mutex_lock(&g_smu); pkg_alias_put(k, pk); pthread_mutex_unlock(&g_smu);
}

int main(void) { @autoreleasepool {
    mtl_init(); mtl_sub_begin();
    atomic_store(&g_cur_frame, (uint64_t)PKG_IDLE_FRAMES + 100);
    NvPkg *live = [NvPkg new], *idle = [NvPkg new], *recent = [NvPkg new];
    alias_key kl = key(0), ki = key(1 << 16), kr = key(2 << 16);
    put(&kl, live, 1); put(&ki, idle, 1); put(&kr, recent, atomic_load(&g_cur_frame));
    tex_t lt = {.serial = 92001};
    mtl_tex_init(&lt); tex_put(lt.serial, live);
    unsigned n = pkg_alias_evict_idle();
    CHECK(n == 1, "only the unheld idle entry goes");
    CHECK(kept(&kl) && !kept(&ki) && kept(&kr), "held and recent entries stay, the idle one goes");
    CHECK(pkg_alias_evict_idle() == 0, "nothing left to evict");
    serial_del(lt.serial);
    CHECK(pkg_alias_evict_idle() == 1 && !kept(&kl), "once its serial goes, the idle entry goes too");
    CHECK(mtl_wait(mtl_sub_commit(), 5000000000ull), "submission completes");
    defer_drain();
    printf("t_pkg_idle: %d checks, %d failed\n", checks, failed); return failed != 0;
} }
