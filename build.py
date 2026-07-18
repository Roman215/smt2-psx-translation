#!/usr/bin/env python3
"""SMT2 English translation — master build. Regenerates the xdelta patch from scratch.

Run from the project root:  python build.py
Outputs:  build/SMT2_EN.bin  and  SMT2_EN.xdelta

Pipeline: mine dictionary -> kern font -> build exe (VWF hook + width table +
dictionary-compressed English C/D tree) ->
translate ALL name tables (demons/races/spells/items/locations/NPCs/traits/drinks) ->
translate menu table -> translate dialogue banks -> patch bin (EDC/ECC) -> xdelta.

All translation DATA lives in tools/: name_tables.py, translations.py, menu_table.py.
Add/extend translations there, then re-run this script.
"""
import argparse
import os, sys, struct, json, heapq
from collections import Counter
from pathlib import Path
sys.path.insert(0, "tools")
import build_en_tree as ET, block_rebuild as BR, build_prod_exe as BP, translate_pipeline as TP
import name_tables as NT, translations as TR, menu_table as MT, sys_strings as SS
import rdlogo as RD, map_names as MN, status_screen as STATUS
from cdecc import fix_mode2form1
import pyxdelta

CMDINIT_SECTOR = 67152                        # CMDINIT.BIN base sector in the bin
RDLOGO_SECTOR = 67181                         # RDLOGO.BIN base sector in the bin

# ---- Static exe dialogue banks 6/7 -------------------------------------------------
# Banks 6 and 7 are NOT loaded from disc; they are static data inside the exe and are
# addressed only by the seek routine 0x80056a20, which materializes each base in two
# instructions (an addiu for the block base and an lhu for its data_off u16).
#
# The gap after a bank is NOT free space.  Bank 7's block ends at exactly 0x801171d8,
# where a 16-entry bitmask table begins (read by 0x8005d23c / 0x8005d62c); ~107 further
# structures are referenced between there and the file-ID table at 0x80117cc8.  Sizing
# bank 7 as "0x80117cc8 - base" therefore overruns live data -- the same class of bug as
# the NPC name table overflowing into the demon battle data.  A reference scan over the
# exe, every overlay, PACKA and ZZZZZZZZ.ZZZ finds only the 4 seek-routine sites below,
# so [BANK6_BASE, BANK6_LIMIT) belongs exclusively to banks 6+7 -- and nothing else.
#
# English needs more than the 5632 B those two banks share, so bank 7 (the smaller) is
# moved into the rodata font-placeholder cave, giving bank 6 the whole native region.
BANK6_BASE = 0x80115bd8
BANK6_LIMIT = 0x801171d8          # first foreign data (bitmask table) -- hard ceiling
BANK7_JP_BASE = 0x80116f2c        # stock bank 7 base (source only; block is 684 B)
BANK7_CAVE = 0x800d8500           # free tofu run: 0x800d8500..0x800d9144 (3140 B)
# Seek-routine sites that materialize bank 7's base (all share one lui).
SEEK_B7_LUI = 0x80056b50          # lui   $a0, 0x8011
SEEK_B7_ADDIU = 0x80056b54        # addiu $a3, $a0, 0x6f2c
SEEK_B7_LHU = 0x80056b70          # lhu   $v1, 0x6f2c($a0)
DEFAULT_BIN_NAME = "Shin Megami Tensei II (Japan) (Rev 1).bin"
EXPECTED_BIN_SIZE = 222_694_416
OUT_BIN = "build/SMT2_EN.bin"
OUT_XDELTA = "build/SMT2_EN.xdelta"

# ============================ DICTIONARY MINING ============================
# The compression dictionary is derived deterministically from the authored
# dialogue on every build. It is never written to the source tree: the exact
# same in-memory entry list configures tokenization, Huffman weights, and the
# runtime expansion table.
DICT_MIN_LEN = 3
DICT_MAX_LEN = 16
DICT_MIN_COUNT = 3
DICT_TOKEN_NIBBLES = 3
DICT_ROUND_PICKS = 8

def dictionary_corpus_texts():
    parts = []
    for author in TR.TRANS.values():
        for part in author:
            if isinstance(part, str) and part not in TP.CTRL_NAME:
                parts.append(part)
    return parts

def dictionary_encodable(s):
    for ch in s:
        try:
            ET.fullwidth(ch)
        except KeyError:
            return False
    return True

def dictionary_char_nibble_costs(text):
    """Approximate per-character cost with a 16-ary corpus Huffman tree."""
    freqs = Counter(text)
    freqs.pop("\x00", None)
    items = list(freqs.items())
    pad = (-(len(items) - 1)) % 15
    heap = []
    tree = {}
    nid = 0
    for ch, frequency in items:
        tree[nid] = ("leaf", ch)
        heapq.heappush(heap, (frequency, nid))
        nid += 1
    for _ in range(pad):
        tree[nid] = ("leaf", None)
        heapq.heappush(heap, (0.0, nid))
        nid += 1
    while len(heap) > 1:
        children = [heapq.heappop(heap) for _ in range(min(16, len(heap)))]
        tree[nid] = ("node", [child[1] for child in children])
        heapq.heappush(heap, (sum(child[0] for child in children), nid))
        nid += 1
    depths = {}
    def walk(node, depth):
        kind, value = tree[node]
        if kind == "leaf":
            if value is not None:
                depths[value] = max(depth, 1)
            return
        for child in value:
            walk(child, depth + 1)
    walk(heap[0][1], 0)
    return depths

def dictionary_runtime_cost(s):
    return 4 + 2 * len(s) + 1  # pointer + fullwidth string + NUL

def mine_dictionary(budget):
    """Return dictionary entries selected from the current translation corpus."""
    corpus = "\x00".join(dictionary_corpus_texts())
    costs = dictionary_char_nibble_costs(corpus)
    chosen = []
    spent = 0
    while spent < budget:
        counts = Counter()
        for length in range(DICT_MIN_LEN, DICT_MAX_LEN + 1):
            for i in range(len(corpus) - length + 1):
                candidate = corpus[i:i + length]
                if "\x00" not in candidate:
                    counts[candidate] += 1
        scored = []
        for candidate, count in counts.items():
            if count < DICT_MIN_COUNT or not dictionary_encodable(candidate):
                continue
            saved = count * (
                sum(costs.get(ch, 4) for ch in candidate) - DICT_TOKEN_NIBBLES
            )
            if saved <= 0:
                continue
            scored.append((
                saved / dictionary_runtime_cost(candidate), saved, candidate, count
            ))
        scored.sort(reverse=True)
        picked = 0
        for _density, saved, candidate, _count in scored:
            cost = dictionary_runtime_cost(candidate)
            if spent + cost > budget or candidate not in corpus:
                continue
            chosen.append((candidate, saved))
            spent += cost
            corpus = corpus.replace(candidate, "\x00")
            picked += 1
            if picked >= DICT_ROUND_PICKS or spent >= budget:
                break
        if picked == 0:
            break
    chosen.sort(key=lambda entry: -entry[1])
    return chosen, spent

def foff(a): return (a - 0x80010000) + 0x800

# ============================ 1. FONT KERNING ============================
def kern_font(slpm):
    """Left-kern the 12x12 Latin/punct glyphs; return (modified slpm bytes, widths dict keyed by sidx)."""
    exe = bytearray(slpm)
    FONT, W, H, GB = 0x800d4188, 12, 12, 18
    def get_glyph(idx):
        base = foff(FONT) + idx*GB
        return [[(exe[base+((y*W+x)>>3)] >> (7-((y*W+x)&7))) & 1 for x in range(W)] for y in range(H)]
    def set_glyph(idx, rows):
        base = foff(FONT) + idx*GB
        for i in range(GB): exe[base+i] = 0
        for y in range(H):
            for x in range(W):
                if rows[y][x]:
                    k = y*W+x; exe[base+(k>>3)] |= (1 << (7-(k&7)))
    def kern(idx, left=0, sp=1):
        rows = get_glyph(idx); cols = [x for y in range(H) for x in range(W) if rows[y][x]]
        if not cols: return 4
        lo, hi = min(cols), max(cols); shift = lo-left
        new = [[0]*W for _ in range(H)]
        for y in range(H):
            for x in range(W):
                nx = x-shift
                if 0 <= nx < W and rows[y][x]: new[y][nx] = 1
        set_glyph(idx, new); return (hi-lo+1)+left+sp
    def sidx(code):
        b1, b2 = code>>8, code&0xff; row = (b1-0x81) if b1 < 0xa0 else (b1-0xc1); return (b2-0x40)+row*189
    widths = {}
    for c in range(0x8260,0x827a): widths[sidx(c)] = kern(sidx(c))   # A-Z
    for c in range(0x8281,0x829b): widths[sidx(c)] = kern(sidx(c))   # a-z
    for c in range(0x824f,0x8259): widths[sidx(c)] = kern(sidx(c))   # 0-9
    PUNCT = [0x8149,0x8148,0x8144,0x8143,0x8146,0x8147,0x8151,0x815e,0x8184,0x8166,0x8165,0x8168,
             0x8167,0x815d,0x8169,0x816a,0x8163,0x8160,0x8192,0x817b,0x8195,0x8193]
    for c in PUNCT: widths[sidx(c)] = kern(sidx(c))
    widths[0] = 4  # space
    return bytes(exe), widths

# ============================ 2. BUILD EXE ============================
def build_exe(font_slpm, widths, slpm):
    """VWF advance hooks + width table + English-only C/D tree. Returns exe bytearray."""
    exe = bytearray(font_slpm)
    def w32(a, v): struct.pack_into("<I", exe, foff(a), v)
    CAVE, RAW_CAVE, WTABLE = 0x800d7254, 0x800d7294, 0x800d7300
    BACK, RAW_BACK = 0x80048b88, 0x80048284
    R = {'zero':0,'v0':2,'v1':3,'a0':4,'a2':6,'t6':14,'t7':15,'s2':18,'t8':24,'t9':25,'sp':29}
    I = lambda op,rs,rt,imm: ((op&0x3f)<<26)|((R[rs]&0x1f)<<21)|((R[rt]&0x1f)<<16)|(imm&0xffff)
    Rr = lambda rs,rt,rd,sa,fn: ((R[rs]&0x1f)<<21)|((R[rt]&0x1f)<<16)|((R[rd]&0x1f)<<11)|((sa&0x1f)<<6)|(fn&0x3f)
    lbu=lambda rt,o,rs:I(0x24,rs,rt,o); lhu=lambda rt,o,rs:I(0x25,rs,rt,o)
    addiu=lambda rt,rs,i:I(0x09,rs,rt,i); sltiu=lambda rt,rs,i:I(0x0b,rs,rt,i)
    beq=lambda rs,rt,o:I(0x04,rs,rt,o); sll=lambda rd,rt,sa:Rr('zero',rt,rd,sa,0)
    addu=lambda rd,rs,rt:Rr(rs,rt,rd,0,0x21); lui=lambda rt,i:I(0x0f,'zero',rt,i)
    jj=lambda t:(0x02<<26)|((t>>2)&0x03ffffff)
    lo=lambda x:x&0xffff; hi=lambda x:((x>>16)+(1 if x&0x8000 else 0))&0xffff
    hook=[lbu('t6',0x10,'sp'),lbu('t7',0x11,'sp'),addiu('t9','t6',-0x81),sltiu('t8','t9',2)]
    IB=len(hook); hook.append(0)
    hook+=[sll('t9','t9',8),addu('t9','t9','t7'),lui('t8',hi(WTABLE)),addiu('t8','t8',lo(WTABLE)),
           addu('t8','t8','t9'),lbu('v1',0,'t8'),jj(BACK),0]
    ID=len(hook); hook+=[lhu('v1',0,'a2'),jj(BACK),0]
    hook[IB]=beq('t8','zero',((CAVE+ID*4)-((CAVE+IB*4)+4))>>2)
    for i,wd in enumerate(hook): w32(CAVE+i*4, wd)

    # The immediate/raw-SJIS printer at 0x80048048 has a second, independent
    # fixed-width advance.  Status-screen equipment names use this path, so
    # hooking only the buffered compositor above leaves an eight-glyph (96px)
    # effective limit and lets longer names write into the following rows.
    raw_hook=[lbu('t6',0x10,'sp'),lbu('t7',0x11,'sp'),addiu('t9','t6',-0x81),sltiu('t8','t9',2)]
    raw_ib=len(raw_hook); raw_hook.append(0)
    raw_hook+=[sll('t9','t9',8),addu('t9','t9','t7'),lui('t8',hi(WTABLE)),addiu('t8','t8',lo(WTABLE)),
               addu('t8','t8','t9'),lbu('v1',0,'t8'),jj(RAW_BACK),0]
    raw_id=len(raw_hook); raw_hook+=[lhu('v1',0,'a0'),jj(RAW_BACK),0]
    raw_hook[raw_ib]=beq('t8','zero',((RAW_CAVE+raw_id*4)-((RAW_CAVE+raw_ib*4)+4))>>2)
    for i,wd in enumerate(raw_hook): w32(RAW_CAVE+i*4, wd)

    # The object compositor at 0x8004c5ac (Equip screen and other 4bpp menu
    # captions; ~200 call sites via the string walker 0x8004c7c0) has a THIRD
    # independent fixed-width advance: penX(obj+0xa) += the font's full cell
    # width from the per-font size table 0x800f853c.  English through it lands
    # on a 12px grid and overruns the 96px name buffers after 8 glyphs.  The
    # character is in no register at the advance, so the fix is two-staged:
    # a wrapper on the glyph-index lookup call (0x8004c604: jal 0x8004c55c,
    # a0 = char ptr) records the char's VWF width in a scratch byte, and the
    # advance site (0x8004c78c) consumes it.  Gated to 12px-cell fonts so the
    # 8x8/8x10/10x10 users of this printer keep their stock metrics.
    OBJ_A, OBJ_B, OBJ_SCR = 0x800d8290, 0x800d82d4, 0x800d72d4
    OBJ_LOOKUP, OBJ_ADV_RET = 0x8004c55c, 0x8004c794
    sb=lambda rt,o,rs:I(0x28,rs,rt,o); bne=lambda rs,rt,o:I(0x05,rs,rt,o)
    jal=lambda t:(0x03<<26)|((t>>2)&0x03ffffff)
    obj_a=[lui('t9',hi(OBJ_SCR)), sb('zero',lo(OBJ_SCR),'t9'),
           lbu('t6',0,'a0'), lbu('t7',1,'a0'),
           addiu('t6','t6',-0x81), sltiu('t8','t6',2),
           0,                                   # beq t8,zero -> OUT (patched below)
           sll('t6','t6',8),
           addu('t6','t6','t7'), lui('t8',hi(WTABLE)), addiu('t8','t8',lo(WTABLE)),
           addu('t8','t8','t6'), lbu('t8',0,'t8'), 0,
           sb('t8',lo(OBJ_SCR),'t9'),
           jj(OBJ_LOOKUP), 0]
    obj_a[6]=beq('t8','zero',(15-(6+1)))
    obj_b=[lui('t9',hi(OBJ_SCR)), lbu('t8',lo(OBJ_SCR),'t9'),
           addiu('t9','t6',-12), bne('t9','zero',(8-(3+1))), 0,
           beq('t8','zero',(8-(5+1))), 0,
           addu('t6','t8','zero'),
           lhu('v0',0xa,'s2'),
           jj(OBJ_ADV_RET), 0]
    if len(obj_a)!=17 or len(obj_b)!=11 or OBJ_A+len(obj_a)*4!=OBJ_B or OBJ_B+len(obj_b)*4!=0x800d8300:
        raise SystemExit("object-printer VWF cave layout changed; re-check reservations")
    for addr, expect in ((0x8004c604,0x0c013157),   # jal 0x8004c55c
                         (0x8004c78c,0x9642000a),   # lhu $v0, 0xa($s2)
                         (0x8004c790,0x00000000)):  # delay-slot nop we rely on
        got=struct.unpack_from("<I",exe,foff(addr))[0]
        if got!=expect:
            raise SystemExit(f"object-printer site {addr:#x}: expected {expect:#010x}, got {got:#010x}")
    for i,wd in enumerate(obj_a): w32(OBJ_A+i*4, wd)
    for i,wd in enumerate(obj_b): w32(OBJ_B+i*4, wd)
    w32(0x8004c604, jal(OBJ_A))
    w32(0x8004c78c, jj(OBJ_B))
    tbl=bytearray([12])*512
    def sidx(code):
        b1,b2=code>>8,code&0xff; row=(b1-0x81) if b1<0xa0 else (b1-0xc1); return (b2-0x40)+row*189
    def setw(code):
        v=widths.get(sidx(code))
        if v is None: return
        idx=((code>>8)-0x81)*256+(code&0xff)
        if 0<=idx<512: tbl[idx]=v
    for c in range(0x8260,0x827a): setw(c)
    for c in range(0x8281,0x829b): setw(c)
    for c in range(0x824f,0x8259): setw(c)
    for c in [0x8149,0x8148,0x8144,0x8143,0x8146,0x8147,0x8151,0x815e,0x8166,0x8165,0x8168,
              0x8167,0x815d,0x8169,0x816a,0x8163,0x8160,0x8192,0x817b,0x8195,0x8193]: setw(c)
    tbl[0x40]=widths.get(0,4)
    for i in range(512): exe[foff(WTABLE)+i]=tbl[i]
    w32(0x80048b80, jj(CAVE))
    w32(0x8004827c, jj(RAW_CAVE))
    BP.build_english_tree(exe, slpm)   # Dictionary-compressed C/D tree at 0x80117ec4 / 0x801187a4
    # NOTE: names are English, so the name decoder (0x80056e84 -> 0x80057fe4) uses the English
    # tree directly. No private Japanese-tree decoder is installed (that was for Japanese names).
    # Marker-prefixed system strings use one byte per English character.  The wrapper expands
    # each byte to the corresponding existing fullwidth SJIS glyph before calling the stock blit,
    # so they retain this same VWF/font while unmarked Japanese remains on the stock path.
    _install_sys_printer(exe, w32)
    _relocate_bank7_base(exe, w32)
    return exe

def _relocate_bank7_base(exe, w32):
    """Repoint dialogue bank 7 from 0x80116f2c into the rodata cave.

    Frees bank 7's native 684 B so bank 6 can use the whole [BANK6_BASE, BANK6_LIMIT)
    region.  Only three instructions reference the base, and all three share one lui,
    so the register keeps a consistent value:

        lui   $a0, hi      ; hi/lo split of BANK7_CAVE
        addiu $a3, $a0, lo ; block base
        lhu   $v1, lo($a0) ; data_off u16 at block[0]

    $a0 is dead immediately after (overwritten at 0x80056b7c), so re-using it is safe.
    """
    hi = (BANK7_CAVE >> 16) + (1 if BANK7_CAVE & 0x8000 else 0)   # addiu/lhu sign-extend
    lo = BANK7_CAVE & 0xffff
    # Verify the stock instructions are exactly what we expect before rewriting them.
    for addr, expect in ((SEEK_B7_LUI, 0x3c048011),      # lui   $a0, 0x8011
                         (SEEK_B7_ADDIU, 0x24876f2c),    # addiu $a3, $a0, 0x6f2c
                         (SEEK_B7_LHU, 0x94836f2c)):     # lhu   $v1, 0x6f2c($a0)
        got = struct.unpack_from("<I", exe, foff(addr))[0]
        if got != expect:
            raise SystemExit(f"bank7 seek site {addr:#x}: expected {expect:#010x}, got {got:#010x}")
    w32(SEEK_B7_LUI,   0x3c040000 | hi)                  # lui   $a0, hi
    w32(SEEK_B7_ADDIU, 0x24870000 | lo)                  # addiu $a3, $a0, lo
    w32(SEEK_B7_LHU,   0x94830000 | lo)                  # lhu   $v1, lo($a0)

def _apply_lowercase_font(exe):
    """Draw lowercase a-z into the 8x10 halfwidth font's a-z glyph slots (idx 0x41-0x5a).
    Needed so the ASCII-aware system printer can render lowercase (font ships uppercase-only)."""
    patch = json.load(open("tools/lowercase_font_patch.json"))
    for off_hex, data_hex in patch.items():
        off = int(off_hex, 16); data = bytes.fromhex(data_hex)
        exe[off:off+len(data)] = data

# CMDINIT.BIN default party-name template: 7 entries, 17 bytes each, fullwidth-name + NUL.
# ホーク=Hawk (hero's Colosseum/amnesiac name), アレフ=Aleph (his true name, revealed later),
# ヒロコ=Hiroko (heroine); ベス/ギメル/ダレス/ザイン = Hebrew letters.
CMDINIT_NAMES = {
    0x558: "Hawk",    # ホーク
    0x569: "Hiroko",  # ヒロコ
    0x57a: "Beth",    # ベス
    0x58b: "Gimel",   # ギメル
    0x59c: "Daleth",  # ダレス
    0x5ad: "Zayin",   # ザイン
    0x5be: "Aleph",   # アレフ
}
def apply_cmdinit_names(cmdinit, names=None):
    """Patch the new-game default party-name template in CMDINIT.BIN (loaded to RAM, feeds the
    runtime name array 0x8020bd4c). Each entry is 17 bytes: fullwidth Latin name + NUL pad."""
    names = names or CMDINIT_NAMES
    for off, en in names.items():
        data = b"".join(struct.pack(">H", ET.fullwidth(c)) for c in en)
        if len(data) > 16:
            raise SystemExit(f"CMDINIT name too long for 17-byte entry: {en!r}")
        for i in range(17):
            cmdinit[off + i] = data[i] if i < len(data) else 0

# ---- Marker-based one-byte system-string printer ---------------------------------------
# Strings beginning with 0x1f contain one-byte English.  Each byte is mapped back to its
# fullwidth SJIS glyph in a temporary two-byte buffer and drawn by the original blitter.
# Unmarked strings reproduce the two overwritten stock prologue instructions and jump back
# to 0x800482ac, leaving every original Japanese caller byte-for-byte compatible.
def _install_sys_printer(exe, w32):
    PR, TABLE, BLIT, STOCK = 0x800d8300, 0x800d8400, 0x80048048, 0x800482ac
    MARKER = 0x1f
    ZERO,T0,T1,T2,T3,A0,A1,S0,S1,SP,RA = 0,8,9,10,11,4,5,16,17,29,31
    def RI(op,rs,rt,imm): return ((op&0x3f)<<26)|((rs&0x1f)<<21)|((rt&0x1f)<<16)|(imm&0xffff)
    def RR(rs,rt,rd,sa,fn): return ((rs&0x1f)<<21)|((rt&0x1f)<<16)|((rd&0x1f)<<11)|((sa&0x1f)<<6)|(fn&0x3f)
    ADDIU=lambda rt,rs,i:RI(0x09,rs,rt,i); LBU=lambda rt,o,rs:RI(0x24,rs,rt,o)
    LHU=lambda rt,o,rs:RI(0x25,rs,rt,o);   SH=lambda rt,o,rs:RI(0x29,rs,rt,o)
    LW=lambda rt,o,rs:RI(0x23,rs,rt,o);    SW=lambda rt,o,rs:RI(0x2b,rs,rt,o)
    BEQ=lambda rs,rt,off:RI(0x04,rs,rt,off); BNE=lambda rs,rt,off:RI(0x05,rs,rt,off)
    LUI=lambda rt,i:RI(0x0f,0,rt,i);       MOVE=lambda rd,rs:RR(rs,0,rd,0,0x25)
    SLL=lambda rd,rt,sa:RR(0,rt,rd,sa,0);  ADDU=lambda rd,rs,rt:RR(rs,rt,rd,0,0x21)
    JAL=lambda t:(0x03<<26)|((t>>2)&0x03ffffff); JR=lambda rs:RR(rs,0,0,0,0x08)
    J=lambda t:(0x02<<26)|((t>>2)&0x03ffffff); NOP=0
    tlo, thi = TABLE & 0xffff, (TABLE>>16)+(1 if TABLE & 0x8000 else 0)
    prog = [
        LBU(T0,0,A1), ADDIU(T1,ZERO,MARKER), 0, NOP,
        ADDIU(SP,SP,-0x30), SW(RA,0x2c,SP), SW(S0,0x20,SP), SW(S1,0x24,SP),
        MOVE(S1,A0), ADDIU(S0,A1,1),
        # loop @10
        # The PSX R3000 exposes load-delay slots: do not consume LBU/LHU results in
        # the immediately following instruction.
        LBU(T0,0,S0), NOP, 0, NOP,
        SLL(T1,T0,1), LUI(T2,thi), ADDIU(T2,T2,tlo), ADDU(T2,T2,T1),
        LHU(T3,0,T2), NOP, SH(T3,0x10,SP), MOVE(A0,S1), ADDIU(A1,SP,0x10), JAL(BLIT), NOP,
        ADDIU(S0,S0,1), J(PR+10*4), NOP,
        # end @28
        LW(RA,0x2c,SP), LW(S0,0x20,SP), LW(S1,0x24,SP), JR(RA), ADDIU(SP,SP,0x30),
        # stock fallback @33: reproduce 0x800482a4/a8, then continue at 0x800482ac
        ADDIU(SP,SP,-0x20), SW(S0,0x10,SP), J(STOCK), NOP,
    ]
    prog[2] = BNE(T0,T1,33-(2+1))
    prog[12] = BEQ(T0,ZERO,28-(12+1))
    for i,wd in enumerate(prog): w32(PR+i*4, wd)

    # Raw-byte table: lhu/sh preserves the big-endian SJIS byte pair in memory.
    # The game's glyph at SJIS 0x8192 is the Macca currency symbol (ћ), despite that
    # code point conventionally decoding as a pound sign.
    table = bytearray()
    for value in range(128):
        if value == 0x7f:
            table += struct.pack(">H", 0x8192)
            continue
        char = chr(value) if 0x20 <= value <= 0x7e else "?"
        try:
            table += struct.pack(">H", ET.fullwidth(char))
        except (KeyError, ValueError):
            table += struct.pack(">H", ET.fullwidth("?"))
    exe[foff(TABLE):foff(TABLE)+len(table)] = table
    w32(0x800482a4, J(PR)); w32(0x800482a8, NOP)

# ============================ 3. NAME TABLES ============================
def apply_name_tables(exe, slpm, PATHS):
    # single-level [N u16 offsets][data]: (base, list, alloc_end)
    NT.rebuild_single(exe, 0x80102962, NT.DEMONS,    0x801034da, PATHS)  # demons  (311)
    NT.rebuild_single(exe, 0x801043f8, NT.RACES,     0x8010452c, PATHS)  # races   (42)
    NT.rebuild_single(exe, 0x801119f2, NT.NPCS,      0x80111ad8, PATHS)  # NPCs (23); TRUE end is
    # 0x80111ad8 (8-byte battle-data records follow) -- NOT 0x801132f2 (LOCATIONS). Overflowing
    # past here corrupts demon/battle data (unwinnable early fights).
    NT.rebuild_single(exe, 0x801132f2, NT.LOCATIONS, 0x80113388, PATHS)  # locs    (16)
    NT.rebuild_single(exe, 0x80113388, NT.DRINKS,    0x801133fc, PATHS)  # drinks (9); TRUE end
    # 0x801133fc (data follows, not 0x80113486=SPELLS). English currently fits; bounded for safety.
    # two-level [u16 data_off][N u16 offs][data]
    NT.rebuild_twolevel(exe, 0x80113486, NT.SPELLS, 0x80114952, PATHS)   # spells  (321)
    NT.rebuild_twolevel(exe, 0x80114952, NT.ITEMS,  0x80115bd8, PATHS)   # items   (349)
    # traits: split OT(0x801034da)/DATA(0x801036da), 256 entries, dedup via TRAITS_MAP
    traits = _decode_traits(slpm)
    NT.rebuild_split(exe, 0x801034da, 0x801036da, traits, 0x801043f8, PATHS)

def _decode_traits(slpm):
    """Decode the 256 JP trait entries and map each to English via NT.TRAITS_MAP."""
    def U16(a): return struct.unpack_from("<H", slpm, foff(a))[0]
    CS, CY = 0x80117ec4, 0x801187a4
    def dec(ram):
        pos=foff(ram); hi=True; t=[]
        for _ in range(120):
            node=0
            for _ in range(40):
                b=slpm[pos]; nib=(b>>4) if hi else (b&0xf); hi=not hi
                if hi: pos+=1
                ea=(node&0xFFFE)+nib*2; nx=U16(CS+ea)
                if nx==0x7fff: return t
                if nx&0x8000: t.append((U16(CY+ea), bool(nx&0x4000))); break
                node=nx
            else: return t
            if t and t[-1]==(0x4544,True): break
        return t
    def render(t):
        s=""
        for sym,c in t:
            if sym==0x4544: break
            if c and sym==0x4352: s+="/"; continue
            try: s+=struct.pack(">H",sym).decode("shift_jis")
            except: s+="?"
        return s
    out=[]
    for i in range(256):
        jp=render(dec(0x801036da + U16(0x801034da + i*2)))
        out.append(NT.TRAITS_MAP.get(jp, "?"))
    return out

# ============================ 4. DIALOGUE + MENU (banks) ============================
CD_BANKS = None
def apply_banks(exe, packa, slpm, PATHS):
    """Rebuild C/D dialogue banks with TR.TRANS (translated) + placeholders.

    Banks 2 and 3 remain within their original fixed archive entries: 16 sectors
    for Bank 2 and 13 sectors for Bank 3.  No PACKA entry is relocated.
    """
    ED=(0x4544,True)
    def U16(a): return struct.unpack_from("<H", exe, foff(a))[0]
    # Source allocations only bound the JP decode (blocks self-terminate, so a generous
    # bound is harmless).  Destination allocations are the TRUE limits -- see the
    # BANK6_LIMIT / BANK7_CAVE notes at the top of this file.
    src_alloc6=BANK7_JP_BASE-BANK6_BASE            # 4948: stock bank 6 region
    src_alloc7=0x80117cc8-BANK7_JP_BASE            # 3484: bounds the decode only
    dst_alloc6=BANK6_LIMIT-BANK6_BASE              # 5632: bank 6 owns the whole region
    # The dictionary handler + strings occupy the cave tail from BP.DICT_BASE,
    # so bank 7's allocation ends there.
    dst_alloc7=BP.DICT_BASE-BANK7_CAVE
    source_packa=bytes(packa)
    packa=bytearray(packa)

    # bank: (buffer, source base, source allocation, destination base, destination allocation)
    banks={
        0:("packa",0x32fb000,15*2048,0x32fb000,15*2048),
        1:("packa",0x3302800, 2*2048,0x3302800, 2*2048),
        2:("packa",0x3303800,16*2048,0x3303800,16*2048),
        3:("packa",0x330b800,13*2048,0x330b800,13*2048),
        6:("exe",BANK6_BASE,src_alloc6,BANK6_BASE,dst_alloc6),
        7:("exe",BANK7_JP_BASE,src_alloc7,BANK7_CAVE,dst_alloc7),
    }
    def build_block(msgs,N):
        # Offset entries may safely share an identical self-terminating stream.
        # Interning exact duplicates is lossless and leaves extra headroom in the
        # fixed-size dialogue allocations.
        offs=[]; data=bytearray(); interned={}; previous_terminated=True
        for m in msgs:
            cur=[]
            for t in m: cur+=PATHS[t]
            encoded=bytearray(); b=0; hi=True
            for n in cur:
                if hi: b=(n&0xf)<<4; hi=False
                else: encoded.append(b|(n&0xf)); hi=True
            if not hi: encoded.append(b)
            encoded=bytes(encoded)
            terminated=ED in m
            # An unterminated stream deliberately continues into the next
            # message (Bank 3 has one such split entry), so its successor must
            # remain physically adjacent even when that successor is a duplicate.
            if previous_terminated and terminated and encoded in interned:
                offs.append(interned[encoded])
            else:
                offs.append(len(data))
                if terminated: interned.setdefault(encoded,len(data))
                data+=encoded
            previous_terminated=terminated
        do=2+2*N; out=bytearray(struct.pack("<H",do)); out+=struct.pack("<%dH"%N,*offs); out+=data
        return bytes(out)
    for bank,(buf,src_base,src_alloc,dst_base,dst_alloc) in banks.items():
        src_fo=src_base if buf=="packa" else foff(src_base)
        dst_fo=dst_base if buf=="packa" else foff(dst_base)
        src=source_packa if buf=="packa" else slpm
        msgs,N=BR.decode_all(src[src_fo:src_fo+src_alloc],0x80117ec4,0x801187a4,slpm)
        out=[]
        for i in range(N):
            mid=(bank<<12)|i
            if mid in TR.TRANS:
                toks=TP.author_to_tokens(TR.TRANS[mid])
                # A stream without [ED] relies on decode flowing into the NEXT
                # message, which only works if its nibble count happens to be
                # even (build_block pads odd streams with a garbage nibble).
                # Author such messages self-contained instead (see 0x3077).
                if not toks or toks[-1]!=ED:
                    raise SystemExit(f"msg {mid:#06x} does not end with ED")
                out.append(toks)
            else:
                ph=TP.placeholder(msgs[i]); ph=ph+[ED] if (not ph or ph[-1]!=ED) else ph; out.append(ph)
        blk=build_block(out,N)
        print(f"  bank{bank}: {len(blk)}/{dst_alloc} bytes")
        if len(blk)>dst_alloc: raise SystemExit(f"bank{bank} OVERFLOW {len(blk)}>{dst_alloc}")
        if buf=="packa":
            packa[dst_fo:dst_fo+dst_alloc]=b"\xCC"*dst_alloc
            packa[dst_fo:dst_fo+len(blk)]=blk
        else:
            exe[dst_fo:dst_fo+len(blk)]=blk

    # Bank 3 and the following entry retain their original boundaries.
    if (struct.unpack_from("<H",slpm,0xda190)[0] != 0x6617 or
        struct.unpack_from("<H",slpm,0xda192)[0] != 0x6624):
        raise SystemExit("unexpected PACKA Bank 3 boundaries")
    return packa

# ============================ 5. PATCH + XDELTA ============================
def make_patch(input_bin, exe, packa, slpm, packa0, cmdinit=None, cmdinit0=None, rdlogo=None, rdlogo0=None):
    bind=bytearray(Path(input_bin).read_bytes())
    em=lambda f:(67202+f//2048)*2352+24+(f%2048)          # exe -> bin
    pm=lambda f:(68191+f//2048)*2352+24+(f%2048)          # PACKA -> bin
    cm=lambda f:(CMDINIT_SECTOR+f//2048)*2352+24+(f%2048) # CMDINIT.BIN -> bin
    rm=lambda f:(RDLOGO_SECTOR+f//2048)*2352+24+(f%2048)  # RDLOGO.BIN -> bin
    edits=[]
    for i in range(len(slpm)):
        if slpm[i]!=exe[i]: edits.append((em(i),exe[i]))
    if len(packa)%2048 or len(packa)<len(packa0):
        raise SystemExit("rebuilt PACKA has an invalid size")
    for i in range(len(packa)):
        old=packa0[i] if i<len(packa0) else bind[pm(i)]
        if old!=packa[i]: edits.append((pm(i),packa[i]))
    if cmdinit is not None:
        for i in range(len(cmdinit0)):
            if cmdinit0[i]!=cmdinit[i]: edits.append((cm(i),cmdinit[i]))
    if rdlogo is not None:
        for i in range(len(rdlogo0)):
            if rdlogo0[i]!=rdlogo[i]: edits.append((rm(i),rdlogo[i]))

    if len(packa)!=len(packa0):
        # PACKA.BIN is the last ISO file.  Update its directory-record size in
        # both byte orders while retaining its original extent.
        dir_lba=66991
        user=dir_lba*2352+24
        data=bind[user:user+2048]
        pos=0; record=None
        while pos<len(data):
            n=data[pos]
            if not n: break
            rec=data[pos:pos+n]
            name_len=rec[32] if len(rec)>32 else 0
            if rec[33:33+name_len]==b"PACKA.BIN;1":
                record=user+pos; break
            pos+=n
        if record is None:
            raise SystemExit("could not find PACKA.BIN ISO directory record")
        if (struct.unpack_from("<I",bind,record+2)[0]!=68191 or
            struct.unpack_from("<I",bind,record+10)[0]!=len(packa0) or
            struct.unpack_from(">I",bind,record+14)[0]!=len(packa0)):
            raise SystemExit("unexpected PACKA.BIN ISO directory record")
        size_fields=struct.pack("<I",len(packa))+struct.pack(">I",len(packa))
        for i,v in enumerate(size_fields): edits.append((record+10+i,v))

        # The original final sector carries the Mode 2 EOF/EOR submode.  Move
        # that marker to the expanded final sector and mark intervening sectors
        # as ordinary Form 1 data before regenerating EDC/ECC below.
        old_sectors=len(packa0)//2048; new_sectors=len(packa)//2048
        for rel in range(old_sectors-1,new_sectors):
            sec=68191+rel
            submode=0x89 if rel==new_sectors-1 else 0x08
            subheader=bytes((0,0,submode,0))*2
            for i,v in enumerate(subheader): edits.append((sec*2352+16+i,v))
    aff=set()
    for bo,v in edits: bind[bo]=v; aff.add(bo//2352)
    for sec in aff:
        so=sec*2352; s=bytearray(bind[so:so+2352]); fix_mode2form1(s); bind[so:so+2352]=s
    os.makedirs("build", exist_ok=True)
    open(OUT_BIN,"wb").write(bytes(bind))
    # pyxdelta refuses to replace an existing output file.  Builds are
    # reproducible, so discard only the previous generated patch first.
    out_xdelta = Path(OUT_XDELTA)
    if out_xdelta.exists():
        out_xdelta.unlink()
    ok=pyxdelta.run(str(input_bin), OUT_BIN, OUT_XDELTA)
    return ok, len(aff)

def extract_from_bin(bin_data, base_sector, file_size):
    """Extracts a file directly from the raw bin data."""
    extracted = bytearray(file_size)
    for f in range(file_size):
        # Using the exact same math from your make_patch lambdas
        bin_offset = (base_sector + f // 2048) * 2352 + 24 + (f % 2048)
        extracted[f] = bin_data[bin_offset]
    return extracted

def find_input_bin(requested=None):
    """Return the compatible source BIN supplied by the user.

    The default Redump-style filename is preferred.  If it has been renamed,
    a single BIN in the repository root is also accepted; use --input when
    more than one BIN is present.
    """
    if requested is not None:
        path = Path(requested)
    else:
        preferred = Path(DEFAULT_BIN_NAME)
        if preferred.is_file():
            path = preferred
        else:
            candidates = sorted(Path(".").glob("*.bin"))
            if len(candidates) != 1:
                names = ", ".join(p.name for p in candidates) or "none"
                raise SystemExit(
                    "Could not choose a source BIN (found: " + names + "). "
                    "Put one compatible BIN in the repository root or pass --input PATH."
                )
            path = candidates[0]
    if not path.is_file():
        raise SystemExit(f"Source BIN not found: {path}")
    if path.stat().st_size != EXPECTED_BIN_SIZE:
        raise SystemExit(
            f"Unexpected BIN size: {path} is {path.stat().st_size:,} bytes; "
            f"this build supports the {EXPECTED_BIN_SIZE:,}-byte Japan Rev 1 MODE2/2352 image only."
        )
    return path

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build the SMT2 PSX English translation and an xdelta patch."
    )
    parser.add_argument(
        "--input", metavar="BIN", help="source Japan Rev 1 MODE2/2352 BIN (default: auto-detect)"
    )
    args = parser.parse_args(argv)
    print("[1/6] mining compression dictionary...")
    dictionary, dictionary_bytes = mine_dictionary(BP.DICT_RUNTIME_BUDGET)
    BP.configure_dictionary(dictionary)
    TP.configure_dictionary(dictionary, BP.DICT_CODE_BASE)
    estimated_nibbles = sum(weight for _text, weight in dictionary)
    print(
        f"  dictionary: {len(dictionary)} entries, "
        f"{dictionary_bytes}/{BP.DICT_RUNTIME_BUDGET} bytes, "
        f"~{estimated_nibbles / 2 / 1024:.1f} KB saved"
    )
    input_bin = find_input_bin(args.input)
    bind = input_bin.read_bytes()
    
    # You will need to know the exact file sizes for this to work
    SLPM_SIZE = 2025472  # Size of SLPM_869.24
    PACKA_SIZE = 53948416 # Size of PACKA.BIN
    CMDINIT_SIZE = 1519
    RDLOGO_SIZE = 1728
    
    print("Extracting base files from bin...")
    slpm = extract_from_bin(bind, 67202, SLPM_SIZE)
    packa0 = extract_from_bin(bind, 68191, PACKA_SIZE)
    cmdinit0 = extract_from_bin(bind, CMDINIT_SECTOR, CMDINIT_SIZE)
    rdlogo0 = extract_from_bin(bind, RDLOGO_SECTOR, RDLOGO_SIZE)
    print("[2/6] kerning font...")
    font_slpm, widths = kern_font(slpm)
    print("[3/6] building exe (VWF hook + dictionary-compressed English tree)...")
    exe = build_exe(font_slpm, widths, slpm)
    PATHS = BR.build_paths(0x80117ec4, 0x801187a4, exe)
    print("[4/6] applying name tables")
    apply_name_tables(exe, slpm, PATHS)
    cmdinit = bytearray(cmdinit0)
    apply_cmdinit_names(cmdinit)             # REAL new-game party names (CMDINIT.BIN)
    MN.relocate_map_names(exe)               # field/location names (save list) -> English, relocated
                                             # to the rodata cave + both pointer tables repointed
    rdlogo = RD.patch_rdlogo(rdlogo0)        # boot disclaimer -> English (fullwidth, repointed)
    MT.rebuild_menu(exe, PATHS)
    SS.apply_sys(exe)                        # boot-safe system strings, kept in their original slots
    print("[5/6] applying dialogue + menu banks...")
    packa = apply_banks(exe, packa0, slpm, PATHS)
    STATUS.patch_status_texture(packa, exe)
    print("[6/6] patching bin + xdelta...")
    ok, sectors = make_patch(input_bin, exe, packa, slpm, packa0, cmdinit, cmdinit0, rdlogo, rdlogo0)
    print(f"DONE. {OUT_XDELTA} ok={ok}, {sectors} sectors, {os.path.getsize(OUT_XDELTA)} bytes")

if __name__ == "__main__":
    main()
