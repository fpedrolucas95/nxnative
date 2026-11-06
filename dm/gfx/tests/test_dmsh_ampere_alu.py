#!/usr/bin/env python3
"""Ampere ALU instructions through the offline translator (dmsh_xlate, arch sm86), on registers the translator cannot fold, their result stored to shared memory so
that it is kept: BREV, BMSK, F2IP, UIMAD with an immediate in C, and HADD2 / HMUL2 with an immediate (test_dmsh_ampere_mem.py's Pokopia class has those two on constants, a negative immediate's sign, F2FP.MERGE_C,
F2I from a half, UP2UR, MEMBAR and ERRBAR). Needs DMSH_TEST_XLATE (the translator) like the other translator tests."""
import re, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dmsh_ampere_mem import EXIT, Translated, inst

STORE = (0x000fe8000000c800, 0x0000080609008388)   # STS.U32 [R9 * 16 + 8], R6 (Mario Kart World f94552a2a2bff505): the sink, R9 the thread index


def uldc(ur, bank, offset): return (0x000fe20000000800, 0x7ab9 | ur << 16 | offset << 38 | bank << 54)   # ULDC URd, c[bank][offset]
def waiting(i): return (i[0] | 0x3f << 52, i[1])   # the instruction waits on every scoreboard (control bits 116..121): it reads what an S2R before it wrote
def s2r_tid(rd): return (0x000e260000002100, 0x0000000000007919 | rd << 16)   # S2R Rd, SR_TID.X (Mario Kart World's encoding, write barrier 0)


class Alu(Translated):
    def kept(self, *code, srcs=()):
        """code between S2R R9 (and each register of srcs) = the thread index and the store of R6"""
        pre = b''.join(inst(*s2r_tid(r)) for r in (9, *srcs))
        body = b''.join(inst(*waiting(i)) for i in code)
        return self.translate(pre + body + inst(*waiting(STORE)) + inst(*EXIT), shared=0x1000)


class Brev(Alu):
    BREV = (0x001e240000000000, 0x0000001300067301)   # BREV R6, R19 (Pokémon Pokopia 6e8db04c25a53d8c, whose destination is R3)

    def test_reverses_the_bits(self):
        self.assertIn('reverse_bits', self.kept(self.BREV, srcs=(19,)))


class HalfImmediate(Alu):
    """HADD2 / HMUL2 Rd, Ra, imm (form 2): the second source is the immediate at bits 32..63, not the register field at 64 that HFMA2's B uses in that form. Pokopia's
    blur 85446a6753300fc8 steps its loop with HADD2 R6, R6, 2.0h; reading R0 there, the loop never ended and the GPU hung"""
    HADD2 = (0x000fe20000000800, 0x4000400006067430)   # HADD2 R6, R6, 2, 2 (field 64 = R0)
    HMUL2 = (HADD2[0], HADD2[1] & ~0xfff | 0x432)      # HMUL2 R6, R6, 2, 2: the same fields (no game encoding met)

    def test_hadd2_adds_the_immediate(self):
        msl = self.kept(self.HADD2, srcs=(6,))
        self.assertIn('spvFAdd', msl)
        self.assertRegex(msl, r'\b2\.0\b')   # read from R0 (never written) it was 0, and the add folded away

    def test_hmul2_multiplies_by_the_immediate(self):
        msl = self.kept(self.HMUL2, srcs=(6,))
        self.assertIn('spvFMul', msl)
        self.assertRegex(msl, r'\b2\.0\b')


class SharedAtomics(Alu):
    """ATOMS.INC / ATOMS.DEC (operations 3 and 4) had no case in EmitAtomicOp: the result was the constant 0 and shared memory was not touched. They are a compare-and-swap loop.
    ATOMS.CAS with bit 87 clear is CUDA's atomicCAS: Rd is the old value; CAST (87) and CAST.SPIN (87, 88) keep Rd = 1 when the swap happened. A GPU cross-check of 400 shared
    accesses against a reference (one thread, production options): INC / DEC / CAS 84 mismatches, none with the fix. Encodings built from the sm_86 oracle corpus, checked with nvdisasm"""
    INC = (0x000fe20001800000, 0x000000141306738c)    # ATOMS.INC R6, [R19], R20
    DEC = (0x000fe20002000000, 0x000000141306738c)    # ATOMS.DEC R6, [R19], R20
    CAS = (0x000fe20000000015, 0x000000141306738d)    # ATOMS.CAS R6, [R19], R20, R21
    SPIN = (0x000fe20001800015, 0x000000141306738d)   # ATOMS.CAST.SPIN R6, [R19], R20, R21

    def test_inc_is_a_compare_and_swap_loop(self):
        self.assertIn('atomic_compare_exchange', self.kept(self.INC, srcs=(19, 20)))

    def test_dec_is_a_compare_and_swap_loop(self):
        self.assertIn('atomic_compare_exchange', self.kept(self.DEC, srcs=(19, 20)))

    def test_cas_gives_the_old_value(self):   # the success test of CAST.SPIN is not there
        cas, spin = self.kept(self.CAS, srcs=(19, 20, 21)), self.kept(self.SPIN, srcs=(19, 20, 21))
        self.assertIn('atomic_compare_exchange', cas)
        success = r'bool _\d+ = int\(_\d+\) =='   # the old value compared with the expected one (not the swap loop's own test)
        self.assertRegex(spin, success)
        self.assertNotRegex(cas, success)
class MufuTurns(Alu):
    """MUFU.SIN / COS take turns (sm_70 and later): NVIDIA reduces them exactly, so the angle comes from x - floor(x); 2pi x in 32 bits lost the fraction as x grew
    (a GPU cross-check against sin(2pi frac x): errors up to 7e-4 at a few thousand turns, none with the reduction). MUFU.TANH (op 9) is translated, not refused.
    Encodings built from the sm_86 oracle corpus and checked with nvdisasm"""
    SIN = (0x000fe20000000400, 0x0000001300067308)    # MUFU.SIN R6, R19
    COS = (0x000fe20000000000, 0x0000001300067308)    # MUFU.COS R6, R19
    TANH = (0x000fe20000002400, 0x0000001300067308)   # MUFU.TANH R6, R19

    def test_sin_reduces_the_turns(self):
        msl = self.kept(self.SIN, srcs=(19,))
        self.assertIn('floor(', msl)
        self.assertIn('sin(', msl)

    def test_cos_reduces_the_turns(self):
        self.assertIn('floor(', self.kept(self.COS, srcs=(19,)))

    def test_tanh_is_translated(self):
        msl = self.kept(self.TANH, srcs=(19,))
        self.assertIn('exp2(', msl)
class DirectedRounding(Alu):
    """I2F (32-bit source, 32-bit float) and F2F.F16.F32 with .RM / .RP / .RZ (78..79): the result rounded to nearest is compared with the exact value and stepped to
    its neighbour. The compiler's 32-bit division starts with I2F.U32.RP; rounded to nearest, a value above 2^24 came out one ulp off in about half the cases (a GPU
    cross-check against an exact reference: 45 mismatches in 300 I2F, none with the fix). Encodings built from the sm_86 oracle corpus and checked with nvdisasm"""
    I2F_RP = (0x000fe20000209000, 0x0000001300067306)     # I2F.U32.RP R6, R19
    I2F_RN = (0x000fe20000201000, 0x0000001300067306)     # I2F.U32 R6, R19
    F2F_RP = (0x000fe20000208800, 0x0000001300067304)     # F2F.F16.F32.RP R6, R19
    F2F_RN = (0x000fe20000200800, 0x0000001300067304)     # F2F.F16.F32 R6, R19

    def test_i2f_rp_checks_against_the_integer(self):
        msl = self.kept(self.I2F_RP, srcs=(19,))
        self.assertIn('4294967296', msl)                     # the bound above which the rounded float is above every u32
        self.assertRegex(msl, r'as_type<int>\(_\d+\) \+ 1\b')   # the float's bits stepped up

    def test_i2f_to_nearest_is_plain(self):
        self.assertNotIn('4294967296', self.kept(self.I2F_RN, srcs=(19,)))

    def test_f2f_rp_reads_the_half_back(self):   # through a mask: an unpack of the pack would be folded into the float itself (PropagatePack)
        self.assertIn('& 65535', self.kept(self.F2F_RP, srcs=(19,)))

    def test_f2f_to_nearest_is_plain(self):
        self.assertNotIn('& 65535', self.kept(self.F2F_RN, srcs=(19,)))
class GlobalMemory(Alu):
    """Global memory. desc[URb][Ra.64] (bit 76 of LDG / STG, bit 71 of ATOMG / RED; nvdisasm): URb is a memory descriptor, not part of the address, which is Ra.64 (plus the offset)
    alone; [Ra.64+URb] adds it. The descriptor's value was added to the address. ATOMG.CAS (0x3a9) was refused; ATOMG / RED INC and DEC had no case in EmitAtomicOp (the operation
    vanished). A GPU cross-check of 300 LDG / STG / ATOMG / RED through the host's gmem_map (one-thread compute shaders, production options): 135 identical to 300. Encodings
    built from the sm_86 oracle corpus and checked with nvdisasm"""
    R2UR = (0x000fe200000e0000, 0x00000000130473c2)       # R2UR UR4, R19
    LDG_DESC = (0x000fe2200c1e1900, 0x0000000414067981)   # LDG.E R6, desc[UR4][R20.64]
    LDG_URZ = (0x000fe2200c1e1900, 0x0000003f14067981)    # LDG.E R6, desc[URZ][R20.64]
    CAS = (0x000fe200001ee116, 0x00000013140673a9)        # ATOMG.E.CAS.STRONG.GPU PT, R6, [R20], R19, R22
    INC = (0x000fe200019ee100, 0x00000013140673a8)        # ATOMG.E.INC.STRONG.GPU PT, R6, [R20], R19

    def test_a_descriptor_is_not_an_offset(self):   # the same code whatever the descriptor register holds
        self.assertEqual(self.kept(self.R2UR, self.LDG_DESC, srcs=(19, 20, 21)), self.kept(self.R2UR, self.LDG_URZ, srcs=(19, 20, 21)))

    def test_atomg_cas_is_translated(self):
        self.assertIn('atomic_compare_exchange', self.kept(self.CAS, srcs=(19, 20, 21, 22)))

    def test_atomg_inc_is_a_compare_and_swap_loop(self):
        self.assertIn('atomic_compare_exchange', self.kept(self.INC, srcs=(19, 20, 21)))
class HalfSwizzle(Alu):
    """A half-pair operand's swizzle (A 74..75, the 32 slot 60..61, the 64 slot 81..82: 0 as is, 1 .F32, 2 .H0_H0, 3 .H1_H1) applies to a constant too: nvdisasm prints
    HMUL2 R37, R37.H0_H0, c[0x0] [0x168].H0_H0 (bits 60..61 = 2), a half scaled by one half of a uniform. Read as is, the high lane took the constant's other half.
    Value 1 is .F32, the 32-bit float itself in both lanes (nvdisasm: R20.F32), not .H1_H1. Encodings from the sm_86 oracle corpus, registers renamed"""
    C_H0 = (0x000fe20000000800, 0x20005a0013067a32)    # HMUL2 R6, R19.H0_H0, c[0x0] [0x168].H0_H0
    C_H1 = (0x000fe20000000c00, 0x30005a0013067a32)    # HMUL2 R6, R19.H1_H1, c[0x0] [0x168].H1_H1
    F32 = (0x000fe20000000800, 0x1000001413067232)     # HMUL2 R6, R19.H0_H0, R20.F32
    LANE = re.compile(r'float2\(as_type<half2>\([^;]*?\)\)\.([xy])')

    def lanes(self, *code, srcs=(19,)):
        msl = self.kept(*code, srcs=srcs)
        return msl, set(self.LANE.findall(msl))

    def test_constant_low_half_in_both_lanes(self):
        msl, read = self.lanes(self.C_H0)
        self.assertEqual(read, {'x'}, msl)   # A and the constant: their low halves only

    def test_constant_high_half_in_both_lanes(self):
        msl, read = self.lanes(self.C_H1)
        self.assertEqual(read, {'y'}, msl)

    def test_f32_operand_is_the_float(self):
        msl, read = self.lanes(self.F32, srcs=(19, 20))
        self.assertEqual(msl.count('as_type<half2>'), 1, msl)   # A's unpack alone: R20 is used as a float, not split into halves
        self.assertEqual(read, {'x'}, msl)


class HalfCompareFtz(Alu):
    """HSETP2 / HSET2 .FTZ (bit 80): a subnormal half compares as zero, as FSETP.FTZ's float does (CompareFtz). The lanes are unpacked to 32-bit floats, where a half's
    subnormals are normal, so the half's own bound (2^-14) flushes them. Encodings built from the sm_86 oracle corpus and checked with nvdisasm"""
    HSETP2 = (0x000fca0003f14000, 0x0000001413007234)      # HSETP2.GT.FTZ.AND P0, PT, R19, R20, PT
    HSETP2_NO = (0x000fca0003f04000, 0x0000001413007234)   # HSETP2.GT.AND P0, PT, R19, R20, PT
    HSET2 = (0x000fe20003814080, 0x0000001413067233)       # HSET2.BF.GT.FTZ.AND R6, R19, R20, PT
    BOUND = re.compile(r'6\.10351\d*e-05')

    def test_hsetp2_flushes_both_operands(self):   # only P0 (the low lanes) is read: the high lanes' comparison goes to PT and is dropped with its flushes
        msl = self.kept(self.HSETP2, (0x000fe40000000000, 0x0000001413067208), srcs=(19, 20))
        self.assertEqual(len(self.BOUND.findall(msl)), 2, msl)

    def test_hset2_flushes_both_lanes_of_both_operands(self):
        msl = self.kept(self.HSET2, srcs=(19, 20))
        self.assertEqual(len(self.BOUND.findall(msl)), 4, msl)

    def test_without_ftz_compares_as_is(self):
        self.assertFalse(self.BOUND.search(self.kept(self.HSETP2_NO, (0x000fe40000000000, 0x0000001413067208), srcs=(19, 20))))


class CompareFtz(Alu):
    """FSETP / FSET .FTZ (bit 80): a denormal operand compares as zero, as on NVIDIA; Apple's GPUs keep denormals. Mario Kart World's deferred lighting 635061c90d75a8d1
    normalises its four depth-weighted samples by 1 / sum only where FSETP.NEU.FTZ says sum != 0: a denormal sum passed, its reciprocal overflowed, and the NaN came out
    of a min(x, 1.0) as a fully lit dot. test_dmsh_maxwell_ftz.py has Maxwell's"""
    FSETP = (0x000fca0003f1d000, 0x800000141300720b)   # FSETP.NEU.FTZ.AND P0, PT, R19, -R20, PT (the game's guard, there on R35 and -R10)
    FSET = (0x000fe2000381d000, 0x800000141306720a)    # FSET.NEU.FTZ.AND R6, R19, -R20, PT
    FSEL = (0x000fe40000000000, 0x0000001413067208)    # FSEL R6, R19, R20, P0: keeps the predicate
    FLUSH = '1.1754943508222875'                       # FLT_MIN, the bound under which an operand is flushed

    def test_fsetp_flushes_both_operands(self):
        self.assertEqual(self.kept(self.FSETP, self.FSEL, srcs=(19, 20)).count(self.FLUSH), 2)

    def test_fset_flushes_both_operands(self):
        self.assertEqual(self.kept(self.FSET, srcs=(19, 20)).count(self.FLUSH), 2)

    def test_without_ftz_compares_as_is(self):
        self.assertNotIn(self.FLUSH, self.kept((self.FSETP[0] & ~(1 << 16), self.FSETP[1]), self.FSEL, srcs=(19, 20)))

    def test_against_zero_flushes_one(self):
        self.assertEqual(self.kept((self.FSETP[0], 0x000000ff1300720b), self.FSEL, srcs=(19, 20)).count(self.FLUSH), 1)


def s2r(rd, sr): return (0x000e260000000000 | sr << 8, 0x0000000000007919 | rd << 16)   # S2R Rd, SR (0x21 SR_TID.X, 0x25 SR_CTAID.X)


class F2ip(Alu):
    """F2IP.U8.F32.NTZ Rd, a, b, RZ (0x243): each float rounded to the nearest integer, saturated to a byte and NaN to 0, b in byte 0 and a in byte 1. The Legend of Zelda:
    Ocarina of Time's colour converter 99951da6e5cd38f5 has F2IP R22, R13, R12, RZ at +0x530; here it is on R6, R4, R5"""
    GAME = (0x000fe200000004ff, 0x0000000c0d167243)
    F2IP = (GAME[0], GAME[1] & ~0xffffffff0000 | 6 << 16 | 4 << 24 | 5 << 32)

    def msl(self):   # a (R4) from SR_TID.X, b (R5) from SR_CTAID.X
        return self.kept(s2r(4, 0x21), s2r(5, 0x25), self.F2IP)

    def test_rounds_saturates_and_drops_nan(self):
        msl = self.msl()
        self.assertEqual(len(re.findall(r'\brint\(', msl)), 2, msl)   # ties to even
        self.assertEqual(len(re.findall(r'\bisnan\(', msl)), 2, msl)
        self.assertEqual(len(re.findall(r'\bmin\([^;]*255\.0\)', msl)), 2, msl)

    def test_a_is_the_high_byte(self):
        msl = self.msl()
        defs = dict(re.findall(r'^\s*\w+ (_\d+) = (.*);$', msl, re.M))
        def source(v, seen=()):   # the shader inputs a value is computed from
            return set().union(*(source(u, seen + (v,)) for u in re.findall(r'_\d+', defs.get(v, '')) if u not in seen),
                               set(re.findall(r'gl_\w+', defs.get(v, ''))))
        high, low = re.search(r'(_\d+) << 8;', msl).group(1), re.search(r'= _\d+ \| (_\d+);', msl).group(1)
        self.assertEqual(source(high), {'gl_LocalInvocationID'}, msl)
        self.assertEqual(source(low), {'gl_WorkGroupID'}, msl)

    def test_other_encodings_are_refused(self):
        for hi in (self.F2IP[0] & ~0xffffff00, self.F2IP[0] | 1 << 8, self.F2IP[0] & ~0xff | 7, self.F2IP[0] | 1 << 16):   # bit 74 clear, 72 set (signed), C = R7, 80 set
            with self.subTest(hi=hex(hi)), self.assertRaises(AssertionError):
                self.kept(s2r(4, 0x21), (hi, self.F2IP[1]))


class F2ipTruncate(Alu):
    """F2IP.U8.F32.NTZ.TRUNC Rd, RZ, b, RZ (78..79 = 3, F2I's rounding field): Ocarina of Time's foliage mesh shader 740e2b04db624fb1 has F2IP R5, RZ, R5, RZ at +0x370, a
    colour channel times 255 that it then shifts by 16 into an RGBA8 word; here it is on R6 and R5. The other rounding modes are the same field (no game encoding met)"""
    GAME = (0x000fe4000000c4ff, 0x00000005ff057243)
    F2IP = (GAME[0], GAME[1] & ~0xff0000 | 6 << 16)

    def msl(self, hi=GAME[0]):   # b (R5) from SR_CTAID.X
        return self.kept(s2r(5, 0x25), (hi, self.F2IP[1]))

    def test_truncates_b_into_byte_0(self):
        msl = self.msl()
        self.assertEqual(len(re.findall(r'\btrunc\(', msl)), 1, msl)
        self.assertNotIn('rint(', msl)
        self.assertEqual(len(re.findall(r'\bisnan\(', msl)), 1, msl)
        self.assertEqual(len(re.findall(r'\bmin\([^;]*255\.0\)', msl)), 1, msl)
        self.assertNotRegex(msl, r'<< 8;')   # a = RZ: byte 1 stays zero

    def test_floor_and_ceiling(self):
        for mode, fn in ((1, 'floor'), (2, 'ceil')):
            with self.subTest(mode=mode):
                msl = self.msl(self.GAME[0] & ~(3 << 14) | mode << 14)
                self.assertEqual(len(re.findall(rf'\b{fn}\(', msl)), 1, msl)
                self.assertNotIn('trunc(', msl)


class UimadImmediateC(Alu):
    """UIMAD URd, URa, URb, imm (0x4a4, form 2: the immediate in the C slot): Ocarina of Time's e9213c7fba8ccf93 +0x43c0 UIMAD UR4, UR4, UR6, 0xa, here with UR4 and UR6
    from c[0], moved to R6"""
    UIMAD = (0x000fcc000f8e0206, 0x0000000a040474a4)
    MOV = (0x000fe20000000f00, 0x0000000400067c02)   # MOV R6, UR4

    def test_adds_the_immediate(self):
        msl = self.kept(uldc(4, 0, 0x40), uldc(6, 0, 0x44), self.UIMAD, self.MOV)
        self.assertRegex(msl, r'\* as_type<int>\([^;]*\);\s*int _\d+ = _\d+ \+ 10;')


class Vote(Alu):
    """VOTEU (0x886) writes the uniform predicate UPd and leaves the lane predicate of that number alone; VOTE (0x806) writes the lane predicate. nvdisasm reads 0x886 as
    VOTEU.ANY UP0, P0 (CuAssembler's sm_86 records) and NAK encodes it with a uniform destination at 81..84. Yoshi and the Mysterious Book's cbd80cb96ad38a61 votes P0 into
    UP0, guards a handle's bounds mask on !UP0 and its TEX on !P0: written to P0, UP0 stayed undefined and every lane's guard became the subgroup's"""
    VOTEU = (0x000fe20000000100, 0x00000000003f7886)   # VOTEU.ANY UP0, P0 (the game's, destination register URZ)
    VOTE = (0x000fe20000000100, 0x0000000000ff7806)    # VOTE.ANY P0, P0 (destination register RZ)
    FSETP = CompareFtz.FSETP                           # P0 from R19 and R20: differs across a subgroup
    MOV_P0 = (0x000fe20000000f00, 0x0000001300060202)  # @P0 MOV R6, R19: a lane guard
    UR4_0 = (0x000fe20000000000, 0x0000003f00047c82)   # UMOV UR4, URZ
    UR4_UP0 = (0x000fe20000000000, 0x0000123400040882)   # @UP0 UMOV UR4, 0x1234: a uniform guard
    MOV_UR4 = (0x000fe20000000f00, 0x0000000400067c02)   # MOV R6, UR4

    def test_voteu_writes_the_uniform_predicate(self):
        msl = self.kept(self.FSETP, self.VOTEU, self.UR4_0, self.UR4_UP0, self.MOV_UR4, srcs=(19, 20))
        self.assertIn('simd_any', msl)
        self.assertNotIn('if (false)', msl)   # an unwritten predicate reads false, so the uniform guard never held

    def test_voteu_leaves_the_lane_predicate(self):   # nothing reads UP0: the guards (the store's !P0 too) read the comparison, not the vote
        self.assertNotIn('simd_any', self.kept(self.FSETP, self.VOTEU, self.MOV_P0, srcs=(6, 19, 20)))

    def test_vote_writes_the_lane_predicate(self):
        self.assertIn('simd_any', self.kept(self.FSETP, self.VOTE, self.MOV_P0, srcs=(6, 19, 20)))


if __name__ == '__main__':
    unittest.main()
