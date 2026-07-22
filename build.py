#!/usr/bin/env python3
"""SMT2 English translation — master build.

Run from the project root:  python build.py
Default output:  build/SMT2_EN.bin

Pipeline: mine dictionary -> kern font -> build exe (VWF hook + width table +
dictionary-compressed English C/D tree) -> rebuild English A/B tree ->
translate ALL name tables (demons/races/spells/items/locations/NPCs/traits/drinks) ->
translate menu table -> translate dialogue banks -> patch bin (EDC/ECC).

Pass --xdelta to additionally create a patch from the supplied source BIN.

All translation DATA lives in tools/: name_tables.py, translations.py, menu_table.py.
Add/extend translations there, then re-run this script.
"""
import argparse
import sys, struct, json, heapq
from collections import Counter
from pathlib import Path
sys.path.insert(0, "tools")
import build_en_tree as ET, block_rebuild as BR, build_prod_exe as BP, translate_pipeline as TP
import name_tables as NT, translations as TR, menu_table as MT, sys_strings as SS
import rdlogo as RD, map_names as MN, status_screen as STATUS
import name_entry as NE
import opening_movie as OM
import overlay_text as OT
from cdecc import fix_mode2form1

CMDINIT_SECTOR = 67152                        # CMDINIT.BIN base sector in the bin
RDLOGO_SECTOR = 67181                         # RDLOGO.BIN base sector in the bin
OVERLAY_FILES = {
    # name: (base sector, byte size, translation function)
    "3DMAP.BIN": (67022, 58364, OT.patch_3dmap),
    "CASINO3.BIN": (67078, 33336, OT.patch_casino3),
    "OMAKE.BIN": (67171, 13840, OT.patch_omake),
    "RAG.BIN": (67178, 4157, OT.patch_rag),
}

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
DEFAULT_OUTPUT_DIR = "build"
OUTPUT_BIN_NAME = "SMT2_EN.bin"
OUTPUT_XDELTA_NAME = "SMT2_EN.xdelta"

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
# Mining budget for the A/B-local (negotiation) dictionary.  Deliberately a bit
# above what the dead-space string regions hold -- BP.fit_ab_local_dictionary
# trims the least-valuable entries to whatever provably fits this build.
AB_DICT_BUDGET = 4608

def dictionary_corpus_texts():
    # Keep mining driven by the fixed-size C/D banks. A/B text may reuse the
    # resulting entries, but must not displace entries that keep bank 0 viable.
    parts = []
    for message_id, author in TR.TRANS.items():
        if message_id >> 12 not in {0,1,2,3,6,7}:
            continue
        for part in author:
            if not isinstance(part, str):
                continue
            if part in TP.CTRL_NAME:
                suffix = TP.CONTROL_SUFFIX.get(part)
                if suffix:
                    parts.append(suffix)
            else:
                parts.append(part)
    return parts

def ab_corpus_texts():
    """Text from each physically distinct authored A/B stream.

    A/B blocks intern byte-identical messages, so counting aliases and other
    exact duplicates repeatedly would optimize the dictionary for bytes that
    are never stored repeatedly.
    """
    texts=[]; seen=set()
    for message_id,author in TR.TRANS.items():
        if message_id>>12 not in {4,5}:
            continue
        key=tuple(author)
        if key in seen:
            continue
        seen.add(key)
        for part in author:
            if not isinstance(part, str):
                continue
            if part in TP.AB_CTRL_INDEX:
                suffix = TP.AB_CONTROL_SUFFIX.get(part)
                if suffix:
                    texts.append(suffix)
            else:
                texts.append(part)
    return texts

def select_ab_dictionary(entries):
    """Choose shared-dictionary entries that occur in authored A/B text."""
    texts=ab_corpus_texts()
    ranked=[]
    for text,_weight in entries:
        count=sum(part.count(text) for part in texts)
        if count:
            ranked.append((count*(len(text)-1),text))
    ranked.sort(reverse=True)
    return [text for _score,text in ranked]

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

def mine_dictionary(budget, texts=None):
    """Return dictionary entries selected from the given corpus (default C/D)."""
    corpus = "\x00".join(dictionary_corpus_texts() if texts is None else texts)
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

# Punctuation kerned in both fullwidth fonts (names/dialogue repertoire).
KERN_PUNCT = [0x8149,0x8148,0x8144,0x8143,0x8146,0x8147,0x8151,0x815e,0x8184,0x8166,0x8165,0x8168,
              0x8167,0x815d,0x8169,0x816a,0x8163,0x8160,0x8192,0x817b,0x8195,0x8193]
# Unassigned SJIS cells used only when rendering cached Yamata-no-Orochi names.
# Their 10x10 and 12x12 glyphs are one pixel narrower than the corresponding
# normal a/o/m/r glyphs, while retaining a true blank tracking column after
# every character.
FIELD_NARROW_GLYPHS = {
    "a": 0x827a,
    "o": 0x827b,
    "m": 0x827c,
    "r": 0x827d,
}
# One-byte tokens stored only inside Yamata's marker-prefixed cached name.
# Both global marker printers translate them to FIELD_NARROW_GLYPHS, allowing
# the raw and object-compositor paths to share the same compact rendering.
FIELD_NARROW_SENTINELS = {
    "a": 0x01,
    "o": 0x02,
    "m": 0x03,
    "r": 0x04,
}

# ============================ 1. FONT KERNING ============================
def kern_font(slpm):
    """Left-kern the 12x12 and 10x10 Latin/punct glyphs.

    Returns (modified slpm bytes, 12px widths, 10px widths), width dicts keyed
    by sidx.  The 12x12 font is dialogue/menus; the 10x10 font draws the
    party/status name plates through the object compositor (see
    _install_obj_vwf).  Digits stay unkerned in the 10x10 so numeric columns
    in screens sharing that font keep their fixed grid.
    """
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
    for c in KERN_PUNCT: widths[sidx(c)] = kern(sidx(c))
    widths[0] = 4  # space

    # Some party panels use a separate 12x12 name renderer.  Populate the same
    # private SJIS cells in this atlas so the cached-name tokens work through
    # either printer.
    for char, dst_code in FIELD_NARROW_GLYPHS.items():
        src_index = sidx(ET.fullwidth(char))
        dst_index = sidx(dst_code)
        rows = get_glyph(src_index)
        columns = [x for y in range(H) for x in range(W) if rows[y][x]]
        lo_c, hi_c = min(columns), max(columns)
        source_width = hi_c - lo_c + 1
        target_width = source_width - 1
        if target_width < 2:
            raise SystemExit(f"cannot make compact 12px field glyph {char!r} narrower")
        compact = [[0] * W for _ in range(H)]
        for y in range(H):
            for x in range(lo_c, hi_c + 1):
                if not rows[y][x]:
                    continue
                nx = ((x - lo_c) * (target_width - 1) +
                      (source_width - 1) // 2) // (source_width - 1)
                compact[y][nx] = 1
        set_glyph(dst_index, compact)
        widths[dst_index] = target_width + 1

    # 10x10 font (0x800d25d8, SJIS rows 0x81-0x83 only).  100 bits per glyph, so
    # glyph boundaries are not byte-aligned -- address pixels by absolute bit.
    F10, W10, H10 = 0x800d25d8, 10, 10
    def bit10(k): return (exe[foff(F10)+(k>>3)] >> (7-(k&7))) & 1
    def setbit10(k, v):
        mask = 1 << (7-(k&7))
        if v: exe[foff(F10)+(k>>3)] |= mask
        else: exe[foff(F10)+(k>>3)] &= ~mask & 0xff

    # The stock 10x10 Latin capitals use heavy two-pixel strokes while the
    # lowercase glyphs use narrow one-pixel strokes.  Deliberate 5x7 capitals
    # make both cases share the same body width, cap/ascender height, and
    # stroke weight.  Hand-authored pixels also keep symmetric letters such as
    # H balanced; proportional scaling of the wider 12x12 atlas did not.
    capitals_5x7 = (
        ".###./#...#/#...#/#####/#...#/#...#/#...#",  # A
        "####./#...#/#...#/####./#...#/#...#/####.",  # B
        ".###./#...#/#..../#..../#..../#...#/.###.",  # C
        "####./#...#/#...#/#...#/#...#/#...#/####.",  # D
        "#####/#..../#..../####./#..../#..../#####",  # E
        "#####/#..../#..../####./#..../#..../#....",  # F
        ".###./#...#/#..../#.###/#...#/#...#/.###.",  # G
        "#...#/#...#/#...#/#####/#...#/#...#/#...#",  # H
        "###/.#./.#./.#./.#./.#./###",                  # I
        "..###/...#./...#./...#./#..#./#..#./.##..",  # J
        "#...#/#..#./#.#../##.../#.#../#..#./#...#",  # K
        "#..../#..../#..../#..../#..../#..../#####",  # L
        "#...#/##.##/#.#.#/#.#.#/#...#/#...#/#...#",  # M
        "#...#/##..#/##..#/#.#.#/#..##/#..##/#...#",  # N
        ".###./#...#/#...#/#...#/#...#/#...#/.###.",  # O
        "####./#...#/#...#/####./#..../#..../#....",  # P
        ".###./#...#/#...#/#...#/#.#.#/#..#./.##.#",  # Q
        "####./#...#/#...#/####./#.#../#..#./#...#",  # R
        ".####/#..../#..../.###./....#/....#/####.",  # S
        "#####/..#../..#../..#../..#../..#../..#..",  # T
        "#...#/#...#/#...#/#...#/#...#/#...#/.###.",  # U
        "#...#/#...#/#...#/#...#/.#.#./.#.#./..#..",  # V
        "#...#/#...#/#...#/#.#.#/#.#.#/#.#.#/.#.#.",  # W
        "#...#/#...#/.#.#./..#../.#.#./#...#/#...#",  # X
        "#...#/#...#/.#.#./..#../..#../..#../..#..",  # Y
        "#####/....#/...#./..#../.#.../#..../#####",  # Z
    )
    if len(capitals_5x7) != 26:
        raise SystemExit("compact capital atlas must contain A-Z")
    for code, encoded_rows in zip(range(0x8260, 0x827a), capitals_5x7):
        rows = encoded_rows.split("/")
        if (len(rows) != 7 or any(not 1 <= len(row) <= 5 for row in rows)
                or any(set(row) - {".", "#"} for row in rows)):
            raise SystemExit(f"invalid compact capital glyph {chr(code - 0x8260 + 65)}")
        glyph_start = sidx(code) * W10 * H10
        for y in range(H10):
            for x in range(W10):
                setbit10(glyph_start + y * W10 + x, 0)
        for y, row in enumerate(rows, 1):
            for x, pixel in enumerate(row):
                if pixel == "#":
                    setbit10(glyph_start + y * W10 + x, 1)

    def kern10(idx, left=0, sp=1):
        gb = idx*W10*H10
        rows = [[bit10(gb+y*W10+x) for x in range(W10)] for y in range(H10)]
        cols = [x for y in range(H10) for x in range(W10) if rows[y][x]]
        if not cols: return 4
        lo_c, hi_c = min(cols), max(cols); shift = lo_c-left
        for y in range(H10):
            for x in range(W10):
                nx = x+shift
                setbit10(gb+y*W10+x, rows[y][nx] if 0 <= nx < W10 else 0)
        return (hi_c-lo_c+1)+left+sp
    widths10 = {}
    for c in range(0x8260,0x827a): widths10[sidx(c)] = kern10(sidx(c))   # A-Z
    for c in range(0x8281,0x829b): widths10[sidx(c)] = kern10(sidx(c))   # a-z
    for c in KERN_PUNCT: widths10[sidx(c)] = kern10(sidx(c))
    widths10[0] = 4  # space

    # Yamata-no-Orochi is seven pixels wider than the field HUD's 80px name
    # strip.  Give that one call site alternate a/o/m/r glyphs: their actual
    # ink is compressed from N columns to N-1 and their advance is N, leaving
    # one blank column.  Reducing only the normal glyph advances made unrelated
    # pairs such as "an" and "ae" touch visually.
    for char, dst_code in FIELD_NARROW_GLYPHS.items():
        src_index = sidx(ET.fullwidth(char))
        dst_index = sidx(dst_code)
        src_start = src_index * W10 * H10
        dst_start = dst_index * W10 * H10
        rows = [
            [bit10(src_start + y * W10 + x) for x in range(W10)]
            for y in range(H10)
        ]
        columns = [x for y in range(H10) for x in range(W10) if rows[y][x]]
        lo_c, hi_c = min(columns), max(columns)
        source_width = hi_c - lo_c + 1
        target_width = source_width - 1
        if target_width < 2:
            raise SystemExit(f"cannot make compact field glyph {char!r} narrower")
        for pixel in range(W10 * H10):
            setbit10(dst_start + pixel, 0)
        for y in range(H10):
            for x in range(lo_c, hi_c + 1):
                if not rows[y][x]:
                    continue
                # Nearest-column resampling, with endpoints preserved.
                nx = ((x - lo_c) * (target_width - 1) +
                      (source_width - 1) // 2) // (source_width - 1)
                setbit10(dst_start + y * W10 + nx, 1)
        widths10[dst_index] = target_width + 1

    # Fullwidth asterisk (SJIS 0x8196) is used as a compact-font party marker
    # in roster UIs such as the church healing list.  English names now begin
    # at the marker's old position, so retaining it draws the star underneath
    # the first letter.  Blank only its 10x10 glyph: dialogue uses the separate
    # 12x12 font, preserving intentional stage directions such as *blush*.
    compact_asterisk = sidx(0x8196) * W10 * H10
    for pixel in range(W10 * H10):
        setbit10(compact_asterisk + pixel, 0)

    # The greyed YES/NO confirm options draw ＹＥＳ/ＮＯ through the game's only
    # 10x10 text context, where the stock heavy capitals visually matched the
    # bold selected-option overlay.  Preserve those five stock glyphs in the
    # unused SJIS cells 0x8259-0x825d (between '９' and 'Ａ'); the YES/NO
    # strings are rewritten onto these cells by _patch_confirm_font.  The cells
    # stay off every kern/width list, so they keep the stock 10px fixed
    # advance (WTABLE10 default) and stock centering.
    def srcbit10(k):
        return (slpm[foff(F10) + (k >> 3)] >> (7 - (k & 7))) & 1
    for src, dst in zip("YESNO", (0x8259, 0x825a, 0x825b, 0x825c, 0x825d)):
        src_start = sidx(0x8260 + ord(src) - 65) * W10 * H10
        dst_start = sidx(dst) * W10 * H10
        for k in range(W10 * H10):
            setbit10(dst_start + k, srcbit10(src_start + k))
    return bytes(exe), widths, widths10

# ============================ 2. BUILD EXE ============================
def build_exe(font_slpm, widths, widths10, slpm):
    """VWF advance hooks + width table + English-only C/D tree. Returns exe bytearray."""
    exe = bytearray(font_slpm)
    def w32(a, v): struct.pack_into("<I", exe, foff(a), v)
    CAVE, RAW_CAVE, WTABLE = 0x800d7254, 0x800d7294, 0x800d7300
    BACK, RAW_BACK = 0x80048b88, 0x80048284
    R = {'zero':0,'v0':2,'v1':3,'a0':4,'a1':5,'a2':6,
         't6':14,'t7':15,'s2':18,'t8':24,'t9':25,'sp':29}
    I = lambda op,rs,rt,imm: ((op&0x3f)<<26)|((R[rs]&0x1f)<<21)|((R[rt]&0x1f)<<16)|(imm&0xffff)
    Rr = lambda rs,rt,rd,sa,fn: ((R[rs]&0x1f)<<21)|((R[rt]&0x1f)<<16)|((R[rd]&0x1f)<<11)|((sa&0x1f)<<6)|(fn&0x3f)
    lbu=lambda rt,o,rs:I(0x24,rs,rt,o); lhu=lambda rt,o,rs:I(0x25,rs,rt,o)
    addiu=lambda rt,rs,i:I(0x09,rs,rt,i); sltiu=lambda rt,rs,i:I(0x0b,rs,rt,i)
    beq=lambda rs,rt,o:I(0x04,rs,rt,o); bne=lambda rs,rt,o:I(0x05,rs,rt,o)
    sll=lambda rd,rt,sa:Rr('zero',rt,rd,sa,0)
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
    # fixed-width advance.  It serves both the 12x12 font (equipment names)
    # and the 10x10 font (Cathedral roster/result names).  Select the matching
    # width table from the glyph descriptor's stock cell width; treating every
    # raw string as 12x12 leaves conspicuous space after the compact capitals
    # on fusion screens even though the party HUD is correctly kerned.
    #
    # At the hook site a0 is the glyph descriptor.  Preserve its original
    # width in v1 as the fallback for 8px fonts and non-Latin characters.
    # The overwritten instruction at 0x80048280 also loads descriptor+4 into
    # a1 (the font's extra spacing).  Restore that load in both return-jump
    # delay slots; omitting it leaves a pixel mask in a1, making the pen jump
    # far enough to wrap long names back over the start of a 96px surface.
    raw_hook=[lhu('v1',0,'a0'),
              lbu('t6',0x10,'sp'),lbu('t7',0x11,'sp'),
              addiu('t9','t6',-0x81),sltiu('t8','t9',2),
              0,                                   # beq t8,zero -> STOCK
              addiu('t6','v1',-10),                # delay slot
              0,                                   # bne t6,zero -> CHECK12
              sll('t9','t9',8),                    # delay slot
              lui('t8',hi(WTABLE10)),addiu('t8','t8',lo(WTABLE10)),
              0,0,                                 # j COMMON; nop
              addiu('t6','v1',-12),                # CHECK12
              0,0,                                 # bne t6,zero -> STOCK; nop
              lui('t8',hi(WTABLE)),addiu('t8','t8',lo(WTABLE)),
              addu('t9','t9','t7'),                # COMMON
              addu('t8','t8','t9'),lbu('v1',0,'t8'),jj(RAW_BACK),lhu('a1',4,'a0'),
              jj(RAW_BACK),lhu('a1',4,'a0')]        # STOCK
    RAW_CHECK12, RAW_COMMON, RAW_STOCK = 13,18,23
    raw_hook[5]=beq('t8','zero',((RAW_CAVE+RAW_STOCK*4)-((RAW_CAVE+5*4)+4))>>2)
    raw_hook[7]=bne('zero','t6',((RAW_CAVE+RAW_CHECK12*4)-((RAW_CAVE+7*4)+4))>>2)
    raw_hook[11]=jj(RAW_CAVE+RAW_COMMON*4)
    raw_hook[14]=bne('zero','t6',((RAW_CAVE+RAW_STOCK*4)-((RAW_CAVE+14*4)+4))>>2)
    if RAW_CAVE+len(raw_hook)*4 > OBJ_SCR12:
        raise SystemExit("raw-printer VWF overlaps object-printer scratch bytes")
    for i,wd in enumerate(raw_hook): w32(RAW_CAVE+i*4, wd)

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
    for c in KERN_PUNCT: setw(c)
    for c in FIELD_NARROW_GLYPHS.values(): setw(c)
    tbl[0x40]=widths.get(0,4)
    for i in range(512): exe[foff(WTABLE)+i]=tbl[i]
    w32(0x80048b80, jj(CAVE))
    w32(0x8004827c, jj(RAW_CAVE))
    _patch_casino_prize_sprite(exe, w32, widths)
    _patch_line_break_guard(exe, w32)
    BP.build_english_tree(exe, slpm)   # Dictionary-compressed C/D tree at 0x80117ec4 / 0x801187a4
    # AFTER the tree build: the object-compositor VWF lives in the SYM table's
    # tail, which build_english_tree fills with invalid entries first.
    _install_obj_vwf(exe, w32, widths10)
    # NOTE: names are English, so the name decoder (0x80056e84 -> 0x80057fe4) uses the English
    # tree directly. No private Japanese-tree decoder is installed (that was for Japanese names).
    # Marker-prefixed system strings use one byte per English character.  The wrapper expands
    # each byte to the corresponding existing fullwidth SJIS glyph before calling the stock blit,
    # so they retain this same VWF/font while unmarked Japanese remains on the stock path.
    _install_sys_printer(exe, w32)
    _install_compact_demon_name_cache(exe, w32)
    _install_compact_name_migrator(exe, w32)
    _patch_elevator_floor_labels(exe, w32)
    _patch_long_demon_name_layouts(exe, widths, widths10)
    _patch_message_control_literals(exe, w32)
    _relocate_bank7_base(exe, w32)
    _relocate_name_buffer(exe, w32)
    return exe


# ---- Casino minigame prize sprite (Big & Small / Hunter Chance) ------------------------
# 0x80018f7c renders the winnable item's name into a private 96x12 sprite (context
# 0x800d24e4, mask 0x801b2e28) that the minigame blits inside its PRIZE panel.  The
# stock routine centers the name with a lookup table of ten halfwords at 0x80010140
# -- 48, 42, 36, ..., 6, 0, 0 -- indexed by the name's *character* count, i.e. an
# indent of (96 - 12*chars)/2 for the fixed 12px Japanese cell, clamped at zero.
#
# Two things break for English.  The count is strlen/2, and a name of ten or more
# characters indexes past the twenty-byte copy the routine makes on its own stack,
# so the indent is whatever the previous callee left at sp+0x24.  For "Disparalyze"
# (eleven characters) that is -1: the cursor is read back unsigned at 0x800480c8, so
# the first glyph lands at x=65535, fails the sprite bounds check, and is dropped --
# the panel shows "isparalyze".  Even in range the indent is wrong, because kerned
# English advances 2-10px per character, not 12.
#
# Fix: measure the string with the same WTABLE the raw-printer VWF hook uses and
# center on the real pixel width.  0x80124060 (this routine's private scratch, no
# other reader in the exe) carries the finished indent instead of the character
# count, so the table, its stack copy, and the $s6 pointer to it all fall dead.
PRIZE_CAVE = 0x800d8290            # tofu spare between the map_names strings and the sys printer
PRIZE_CAVE_END = 0x800d8300        # _install_sys_printer's base
PRIZE_SPRITE_W = 96                # sprite context 0x800d24e4 +0x18


def _patch_casino_prize_sprite(exe, w32, widths):
    """Center casino prize names on their kerned width instead of a 12px grid."""
    WTABLE = 0x800d7300
    ZERO,V0,V1,A0,A1,T0,T1,T2,T3,T4,T5,RA = 0,2,3,4,5,8,9,10,11,12,13,31
    RI=lambda op,rs,rt,imm:((op&0x3f)<<26)|((rs&0x1f)<<21)|((rt&0x1f)<<16)|(imm&0xffff)
    LBU=lambda rt,o,rs:RI(0x24,rs,rt,o); ADDIU=lambda rt,rs,i:RI(0x09,rs,rt,i)
    SLTIU=lambda rt,rs,i:RI(0x0b,rs,rt,i); LUI=lambda rt,i:RI(0x0f,0,rt,i)
    BEQ=lambda rs,rt,off:RI(0x04,rs,rt,off); BGEZ=lambda rs,off:RI(0x01,rs,1,off)
    SLL=lambda rd,rt,sa:((rt&0x1f)<<16)|((rd&0x1f)<<11)|((sa&0x1f)<<6)
    SRA=lambda rd,rt,sa:((rt&0x1f)<<16)|((rd&0x1f)<<11)|((sa&0x1f)<<6)|3
    ADDU=lambda rd,rs,rt:((rs&0x1f)<<21)|((rt&0x1f)<<16)|((rd&0x1f)<<11)|0x21
    SUBU=lambda rd,rs,rt:((rs&0x1f)<<21)|((rt&0x1f)<<16)|((rd&0x1f)<<11)|0x23
    J=lambda t:(0x02<<26)|((t>>2)&0x03ffffff); JAL=lambda t:(0x03<<26)|((t>>2)&0x03ffffff)
    JR=lambda rs:((rs&0x1f)<<21)|8
    NOP=0
    lo=lambda x:x&0xffff; hi=lambda x:((x>>16)+(1 if x&0x8000 else 0))&0xffff

    def sidx(code):
        b1,b2=code>>8,code&0xff; row=(b1-0x81) if b1<0xa0 else (b1-0xc1); return (b2-0x40)+row*189
    def measure(text):
        return sum(widths.get(sidx(ET.fullwidth(ch)),12) for ch in text)

    # Item indices 300+ are the multi-line effect blurbs, never a prize.
    for name in NT.ITEMS[:300]:
        if measure(name) > PRIZE_SPRITE_W:
            raise SystemExit(
                f"Casino prize sprite: {name!r} is wider than the {PRIZE_SPRITE_W}px panel")

    # a0 = fullwidth SJIS name; returns v0 = max(0, (96 - kerned width) / 2).
    # Rows 0x81/0x82 take their WTABLE width, everything else the stock 12px cell.
    # R3000 load-delay slots are respected: no load feeds the next instruction.
    if WTABLE & 0x8000:
        raise SystemExit("WTABLE's low half can no longer be folded into the lbu displacement")
    LOOP,ACC,DONE,POS = 2,14,17,22
    prog=[LUI(T0,WTABLE>>16),                  # lo(WTABLE) rides the lbu below
          ADDU(V0,ZERO,ZERO),
          LBU(T1,0,A0),                        # LOOP
          LBU(T2,1,A0),
          0,                                   # beq t1,zero -> DONE (patched below)
          ADDIU(T3,T1,-0x81),                  # delay slot, harmless when taken
          SLTIU(T4,T3,2),
          ADDIU(T5,ZERO,12),                   # stock cell width, kept unless row 0x81/0x82
          0,                                   # beq t4,zero -> ACC (patched below)
          SLL(T3,T3,8),                        # delay slot, harmless when taken
          ADDU(T3,T3,T2), ADDU(T3,T0,T3), LBU(T5,lo(WTABLE),T3),
          NOP,                                 # t5's load delay
          ADDU(V0,V0,T5),                      # ACC
          J(PRIZE_CAVE+LOOP*4), ADDIU(A0,A0,2),
          ADDIU(T1,ZERO,PRIZE_SPRITE_W),       # DONE
          SUBU(V0,T1,V0),
          0,                                   # bgez v0 -> POS (patched below)
          NOP,
          ADDU(V0,ZERO,ZERO),                  # wider than the panel: flush left
          JR(RA), SRA(V0,V0,1)]                # POS
    prog[4]=BEQ(T1,ZERO,DONE-(4+1))
    prog[8]=BEQ(T4,ZERO,ACC-(8+1))
    prog[19]=BGEZ(V0,POS-(19+1))

    # Home: the 0x70 tofu bytes left over when the object-compositor VWF hook moved to
    # the SYM-table tail, between the relocated map names and the system-string printer
    # (see map_names.py's cave map).  Tofu placeholder glyphs use no byte but these
    # three, so anything else here means a neighbour has grown into the gap.
    span=len(prog)*4
    if PRIZE_CAVE < MN.CAVE_HI or PRIZE_CAVE+span > PRIZE_CAVE_END:
        raise SystemExit("casino prize sprite cave collides with a neighbouring reservation")
    if set(exe[foff(PRIZE_CAVE):foff(PRIZE_CAVE_END)]) - {0x00, 0x06, 0x60}:
        raise SystemExit(f"casino prize sprite cave {PRIZE_CAVE:#x} is not free tofu")
    for i,wd in enumerate(prog): w32(PRIZE_CAVE+i*4, wd)

    # address: (stock word, English replacement)
    patches={
        0x80019018:(0x0c034427,JAL(PRIZE_CAVE)),   # strlen(name) -> centering indent
        0x80019030:(0x00021fc2,ADDU(V1,V0,ZERO)),  # was srl $v1,$v0,31 \
        0x80019034:(0x00621821,NOP),               # was addu $v1,$v1,$v0 } strlen/2
        0x80019038:(0x00031843,NOP),               # was sra  $v1,$v1,1  /
        0x80019078:(0x00021040,NOP),               # was sll  $v0,$v0,1   \ table
        0x8001907c:(0x02c21021,NOP),               # was addu $v0,$s6,$v0 } lookup
        0x80019080:(0x84450000,ADDU(A1,V0,ZERO)),  # was lh   $a1,($v0)   /
        # The "ITEM MAX" placeholder shares the panel but is a raw literal at
        # 0x80010154, so its indent is constant.
        0x800190ac:(0x00002821,ADDIU(A1,ZERO,(PRIZE_SPRITE_W-measure("ITEM MAX"))//2)),
    }
    for address,(stock,replacement) in patches.items():
        found=struct.unpack_from("<I",exe,foff(address))[0]
        if found!=stock:
            raise SystemExit(
                f"Casino prize sprite {address:#x}: {found:#010x} != {stock:#010x}"
            )
        w32(address, replacement)


# ---- Dialogue line breaks -------------------------------------------------------------
# Before drawing a character the box asks whether the NEXT one would still fit, but it
# measures that hypothetical character with the font's stock 12px cell (0x80048ba0) even
# though kerned English advances 2-10px.  Any line whose ink ends past 260 of the box's
# 272px therefore wraps -- including when nothing follows it on that line.  A script CR
# arriving right after that already-taken wrap lands two lines down and leaves a blank
# line between the sentences.  Seen on Madam's speech, where 0x268's "and casino we
# operate," and 0x269's " surrendering themselves" concatenate to 263px just before
# 0x26a opens with CR.
#
# Relaxing the 12px lookahead would let a wide glyph run past the margin and be dropped
# by the blitter's bounds check, so instead make a break a no-op when the pen is already
# at the start of a line.  The shared newline routine 0x80047c58 (5 callers: the four
# dialogue control sites 0x80037d00/d08/dfc/e04 and the raw printer 0x80048094) gains
# that guard.  Nothing authored depends on a double break: translations.py has no
# 'CR','CR', and no 'PG' or 'WT' immediately followed by 'CR'.
# The Cyrillic block starts at 0x800d6966 -- an 18-byte glyph grid is not word-aligned,
# so round up: MIPS fetches instructions on 4-byte boundaries and J() would truncate.
LINE_BREAK_CAVE = 0x800d6968       # unused Cyrillic glyphs 567+; see map_names.CAVES
LINE_BREAK_FN = 0x80047c58


def _patch_line_break_guard(exe, w32):
    """Ignore a line break when the pen already sits at the start of a line."""
    V0,V1,A0,A1,A2,RA = 2,3,4,5,6,31
    RI=lambda op,rs,rt,imm:((op&0x3f)<<26)|((rs&0x1f)<<21)|((rt&0x1f)<<16)|(imm&0xffff)
    LHU=lambda rt,o,rs:RI(0x25,rs,rt,o); LW=lambda rt,o,rs:RI(0x23,rs,rt,o)
    SH=lambda rt,o,rs:RI(0x29,rs,rt,o);  BEQ=lambda rs,rt,off:RI(0x04,rs,rt,off)
    ADDU=lambda rd,rs,rt:((rs&0x1f)<<21)|((rt&0x1f)<<16)|((rd&0x1f)<<11)|0x21
    J=lambda t:(0x02<<26)|((t>>2)&0x03ffffff); JR=lambda rs:((rs&0x1f)<<21)|8
    NOP=0

    # Stock body, reproduced after the guard: penX = lineStart, penY += cell + spacing.
    # R3000 load-delay slots are respected: no load feeds the next instruction.
    RET = 11
    prog=[LHU(V0,0x20,A0),                     # penX
          LHU(V1,0x1c,A0),                     # line start
          LW(A1,0,A0),                         # font descriptor; covers v1's load delay
          0,                                   # beq v0,v1 -> RET (patched below)
          SH(V1,0x20,A0),                      # delay slot: rewrites the same value
          LHU(V0,2,A1), LHU(A2,6,A1), LHU(V1,0x22,A0),
          ADDU(V0,V0,A2), ADDU(V1,V1,V0), SH(V1,0x22,A0),
          JR(RA), NOP]                         # RET
    prog[3]=BEQ(V0,V1,RET-(3+1))

    if LINE_BREAK_CAVE & 3:
        raise SystemExit("line-break guard cave is not word-aligned")
    if LINE_BREAK_CAVE + len(prog)*4 > MN.CAVES[0][0]:
        raise SystemExit("line-break guard overruns the map_names cave")
    stock=[0x9482001c,0x8c850000,0xa4820020,0x94a30002,0x94a60006,
           0x94820022,0x00661821,0x00431021,0x03e00008,0xa4820022]
    for i,expect in enumerate(stock):
        got=struct.unpack_from("<I",exe,foff(LINE_BREAK_FN+i*4))[0]
        if got!=expect:
            raise SystemExit(
                f"line-break routine {LINE_BREAK_FN+i*4:#x}: {got:#010x} != {expect:#010x}")
    for i,wd in enumerate(prog): w32(LINE_BREAK_CAVE+i*4, wd)
    w32(LINE_BREAK_FN, J(LINE_BREAK_CAVE))     # the rest of the stock body falls dead
    w32(LINE_BREAK_FN+4, NOP)


def _patch_message_control_literals(exe, w32):
    """Translate Japanese text emitted directly by message-dispatch handlers.

    Most dialogue text lives in the compressed banks, but three dispatch paths
    append stock SJIS literals from the executable instead:

    * AG/A6F appends ``たち`` after the dynamically selected party leader.
    * PP selects one of six Japanese stat labels.
    * synthetic dispatch slot 89 appends the Bar's drink-selection prompt.

    Make the party-leader insert name-only so translate_pipeline.py can append
    ``'s party`` automatically, and translate the fixed literals in their
    original slots. The stat abbreviations match the localized status screen.
    """
    def expect(address, expected, description):
        offset = foff(address)
        actual = bytes(exe[offset:offset + len(expected)])
        if actual != expected:
            raise SystemExit(
                f"{description} at {address:#x}: expected {expected.hex()}, "
                f"got {actual.hex()}"
            )

    def fullwidth_z(text):
        out = bytearray()
        for char in text:
            out += ET.fullwidth(char).to_bytes(2, "big")
        out.append(0)
        return bytes(out)

    def replace_slot(address, size, expected, english, description):
        expect(address, expected.ljust(size, b"\0"), description)
        encoded = fullwidth_z(english)
        if len(encoded) > size:
            raise SystemExit(
                f"{description} does not fit: {len(encoded)}>{size} bytes"
            )
        offset = foff(address)
        exe[offset:offset + size] = encoded.ljust(size, b"\0")

    # AG and A6F share dispatch index 111. The stock handler first emits the
    # selected leader name, then calls the string appender on 0x80013718
    # (SJIS たち). Suppress only that second append; the name call at
    # 0x80061d70 remains intact.
    for address, expected in (
        (0x80061d78, 0x3c048001),  # lui   $a0, 0x8001
        (0x80061d7c, 0x0c016091),  # jal   0x80058244
        (0x80061d80, 0x24843718),  # addiu $a0, $a0, 0x3718
    ):
        actual = struct.unpack_from("<I", exe, foff(address))[0]
        if actual != expected:
            raise SystemExit(
                f"AG suffix site {address:#x}: expected {expected:#010x}, "
                f"got {actual:#010x}"
            )
        w32(address, 0)
    expect(0x80013718, bytes.fromhex("82bd82bf00000000"), "AG たち literal")
    exe[foff(0x80013718):foff(0x80013720)] = b"\0" * 8

    # Synthetic dispatcher slot 89 owns this prompt; it is not a compressed
    # message and therefore is not covered by translations.py.
    replace_slot(
        0x80013668, 24,
        bytes.fromhex("82c782bf82e782aa88f982dd82dc82b782a98148"),
        "Your drink?", "Bar drink prompt",
    )

    stat_slots = (
        (0x80013778, bytes.fromhex("97cd8140"), "ST"),
        (0x80013780, bytes.fromhex("926d8c628140"), "IN"),
        (0x80013788, bytes.fromhex("968297cd8140"), "MA"),
        (0x80013790, bytes.fromhex("91cc97cd8140"), "VI"),
        (0x80013798, bytes.fromhex("91ac82b38140"), "AG"),
        (0x800137a0, bytes.fromhex("895e8140"), "LU"),
    )
    for address, expected, english in stat_slots:
        replace_slot(address, 8, expected, english, f"PP stat label {english}")

# ---- Object-compositor VWF (12px and 10px fullwidth fonts) -----------------------------
# The object compositor at 0x8004c5ac (Equip captions, party/status name plates;
# ~200 call sites via the string walker 0x8004c7c0) has its own fixed-width
# advance: penX(obj+0xa) += the active font's full cell width from the per-font
# size table 0x800f853c.  Fullwidth English through it lands on a rigid 12px or
# 10px grid ("H a w k" name plates) and can overrun the 96px name buffers.
#
# The character is in no register at the advance site, so the fix is two-staged:
# a wrapper on the glyph-index lookup call (0x8004c604: jal 0x8004c55c, a0 =
# char ptr) records the char's VWF width for BOTH kerned fonts in two scratch
# bytes, and the advance site (0x8004c78c) consumes the one matching the active
# font's cell width: 12 -> dialogue WTABLE, 10 -> WTABLE10 (kerned 10x10, the
# party/status name-plate font).  Other cell widths (8x8/8x10) and non-Latin
# rows keep their stock metrics.
#
# Home: the tail of the C/D SYM table.  build_english_tree fills the whole
# table with entries the decoder can never reach before laying out the (much
# smaller) English tree, and BP.SYM_TAIL_RESERVE keeps the tree out of the
# reservation, so [0x80118ce8, 0x80119084) is never-written, never-read space.
#
# Shops expose two paths that the raw-string marker wrapper cannot cover:
# transaction text is appended after control codes (putting 0x1f in the middle
# of a composed buffer), and comparison/menu labels are drawn directly through
# the object compositor.  The first two wrappers below expand marker-prefixed
# ASCII while appending and while drawing an object string, respectively.
# The expanded raw-printer hook now uses the font cave through 0x800d72f7.
# Its final eight bytes remain free for these two object-printer scratch values.
OBJ_SCR12, OBJ_SCR10 = 0x800d72f8, 0x800d72f9
OBJ_APPEND, OBJ_MARKER = 0x80118ce8, 0x80118d4c
OBJ_A, OBJ_B, WTABLE10 = 0x80118de8, 0x80118e40, 0x80118e84
SYM_END = 0x80119084                             # 0x801187a4 + 2272 (table capacity)

def _install_obj_vwf(exe, w32, widths10):
    OBJ_LOOKUP, OBJ_GLYPH, OBJ_ADV_RET = 0x8004c55c, 0x8004c5ac, 0x8004c794
    OBJ_PRINT, OBJ_PRINT_STOCK = 0x8004c7c0, 0x8004c7c8
    APPEND, APPEND_STOCK = 0x8004a158, 0x8004a160
    WTABLE, ASCII_TABLE = 0x800d7300, 0x800d8400
    MIGRATOR = MN.DEMON_NAME_MIGRATOR_CAVE
    MARKER = 0x1f
    ZERO,V0,V1,A0,A1,T0,T1,T2,T3,T6,T7,T8,T9,S0,S1,S2,SP,RA = (
        0,2,3,4,5,8,9,10,11,14,15,24,25,16,17,18,29,31)
    RI=lambda op,rs,rt,imm:((op&0x3f)<<26)|((rs&0x1f)<<21)|((rt&0x1f)<<16)|(imm&0xffff)
    LBU=lambda rt,o,rs:RI(0x24,rs,rt,o); LHU=lambda rt,o,rs:RI(0x25,rs,rt,o)
    LW=lambda rt,o,rs:RI(0x23,rs,rt,o);  SW=lambda rt,o,rs:RI(0x2b,rs,rt,o)
    SB=lambda rt,o,rs:RI(0x28,rs,rt,o);  SH=lambda rt,o,rs:RI(0x29,rs,rt,o)
    ADDIU=lambda rt,rs,i:RI(0x09,rs,rt,i)
    SLTIU=lambda rt,rs,i:RI(0x0b,rs,rt,i); LUI=lambda rt,i:RI(0x0f,0,rt,i)
    BEQ=lambda rs,rt,off:RI(0x04,rs,rt,off); BNE=lambda rs,rt,off:RI(0x05,rs,rt,off)
    SLL=lambda rd,rt,sa:((rt&0x1f)<<16)|((rd&0x1f)<<11)|((sa&0x1f)<<6)
    ADDU=lambda rd,rs,rt:((rs&0x1f)<<21)|((rt&0x1f)<<16)|((rd&0x1f)<<11)|0x21
    MOVE=lambda rd,rs:ADDU(rd,rs,ZERO)
    J=lambda t:(0x02<<26)|((t>>2)&0x03ffffff); JAL=lambda t:(0x03<<26)|((t>>2)&0x03ffffff)
    JR=lambda rs:((rs&0x1f)<<21)|8
    NOP=0
    lo=lambda x:x&0xffff; hi=lambda x:((x>>16)+(1 if x&0x8000 else 0))&0xffff

    # The stock append routine copies a source string byte-for-byte into its
    # destination.  Expand a leading English marker there so a marker appended
    # after shop control codes cannot become an invalid mid-stream SJIS pair.
    # Non-English strings reproduce the overwritten load and return to stock.
    app_loop, app_done, app_stock = 6, 19, 22
    append_prog=[
        LBU(V0,0,A1), ADDIU(V1,ZERO,MARKER),
        0, NOP,                               # bne marker -> stock
        LW(T0,4,A0), ADDIU(A1,A1,1),          # destination cursor; load delay
        LBU(V0,0,A1), NOP,                    # loop
        0, SLL(V1,V0,1),                      # beq NUL -> done
        LUI(T1,hi(ASCII_TABLE)), ADDIU(T1,T1,lo(ASCII_TABLE)),
        ADDU(T1,T1,V1), LHU(T2,0,T1), ADDIU(A1,A1,1),
        SH(T2,0,T0), ADDIU(T0,T0,2),
        J(OBJ_APPEND+app_loop*4), NOP,
        SW(T0,4,A0), JR(RA), SB(ZERO,0,T0),   # done
        LBU(V1,0,A1), J(APPEND_STOCK), NOP,   # stock fallback
    ]
    append_prog[2]=BNE(V0,V1,app_stock-(2+1))
    append_prog[8]=BEQ(V0,ZERO,app_done-(8+1))

    # The direct object path similarly needs to recognize a marker at byte 0.
    # Translate each one-byte character through the same table used by the raw
    # printer, then feed one fullwidth SJIS glyph at a time to the stock object
    # blitter.  Unmarked strings resume at the untouched stock prologue.
    obj_loop, obj_done, obj_stock = 12, 30, 35
    marker_prog=[
        LBU(T0,0,A1), ADDIU(T1,ZERO,MARKER),
        0, NOP,                               # bne marker -> stock
        ADDIU(SP,SP,-0x30), SW(RA,0x2c,SP), SW(S0,0x20,SP), SW(S1,0x24,SP),
        JAL(MIGRATOR), NOP,
        MOVE(S1,A0), ADDIU(S0,A1,1),
        LBU(T0,0,S0), NOP,                    # loop
        0, NOP,                               # beq NUL -> done
        SLL(T1,T0,1), LUI(T2,hi(ASCII_TABLE)), ADDIU(T2,T2,lo(ASCII_TABLE)),
        ADDU(T2,T2,T1), LHU(T3,0,T2), NOP,
        SH(T3,0x10,SP), MOVE(A0,S1), ADDIU(A1,SP,0x10), JAL(OBJ_GLYPH), NOP,
        ADDIU(S0,S0,1), J(OBJ_MARKER+obj_loop*4), NOP,
        LW(RA,0x2c,SP), LW(S0,0x20,SP), LW(S1,0x24,SP),
        JR(RA), ADDIU(SP,SP,0x30),             # done
        ADDIU(SP,SP,-0x20), SW(S1,0x14,SP), J(OBJ_PRINT_STOCK), NOP,
    ]
    marker_prog[2]=BNE(T0,T1,obj_stock-(2+1))
    marker_prog[14]=BEQ(T0,ZERO,obj_done-(14+1))

    if (OBJ_APPEND+len(append_prog)*4!=OBJ_MARKER or
            OBJ_MARKER+len(marker_prog)*4>OBJ_A or
            OBJ_APPEND != 0x801187a4+BP.STCAP-BP.SYM_TAIL_RESERVE):
        raise SystemExit("marker-aware object-printer reservation layout changed; re-check")
    for address, expected in ((APPEND,0x90a30000), (APPEND+4,0x00000000),
                              (OBJ_PRINT,0x27bdffe0), (OBJ_PRINT+4,0xafb10014)):
        got=struct.unpack_from("<I",exe,foff(address))[0]
        if got!=expected:
            raise SystemExit(
                f"marker-aware text site {address:#x}: expected {expected:#010x}, got {got:#010x}")
    for i,wd in enumerate(append_prog): w32(OBJ_APPEND+i*4, wd)
    for i,wd in enumerate(marker_prog): w32(OBJ_MARKER+i*4, wd)
    w32(APPEND,J(OBJ_APPEND)); w32(APPEND+4,NOP)
    w32(OBJ_PRINT,J(OBJ_MARKER)); w32(OBJ_PRINT+4,NOP)

    # Wrapper: zero both scratches; for SJIS rows 0x81/0x82 record both widths.
    # R3000 load-delay slots are respected (a loaded register is never consumed
    # by the immediately following instruction).
    prog_a=[LUI(T9,hi(OBJ_SCR12)),
            SB(ZERO,lo(OBJ_SCR12),T9), SB(ZERO,lo(OBJ_SCR10),T9),
            LBU(T6,0,A0), LBU(T7,1,A0),
            ADDIU(T6,T6,-0x81), SLTIU(T8,T6,2),
            0,                                   # beq t8,zero -> OUT (patched below)
            SLL(T6,T6,8),                        # delay slot, harmless when taken
            ADDU(T6,T6,T7),
            LUI(T8,hi(WTABLE)), ADDIU(T8,T8,lo(WTABLE)), ADDU(T8,T8,T6), LBU(T8,0,T8),
            LUI(T7,hi(WTABLE10)), ADDIU(T7,T7,lo(WTABLE10)), ADDU(T7,T7,T6), LBU(T7,0,T7),
            SB(T8,lo(OBJ_SCR12),T9), SB(T7,lo(OBJ_SCR10),T9),
            J(OBJ_LOOKUP), NOP]                  # OUT
    OUT=len(prog_a)-2
    prog_a[7]=BEQ(T8,ZERO,OUT-(7+1))
    # Advance: t6 = the font's cell width.  12 -> scr12, 10 -> scr10, else stock.
    prog_b=[LUI(T9,hi(OBJ_SCR12)), LBU(T8,lo(OBJ_SCR12),T9),
            ADDIU(V0,T6,-12),
            0,                                   # beq v0,zero -> USE
            NOP,
            ADDIU(V0,T6,-10),
            0,                                   # bne v0,zero -> STOCK
            NOP,
            LBU(T8,lo(OBJ_SCR10),T9), NOP,
            0,                                   # USE: beq t8,zero -> STOCK
            NOP,
            ADDU(T6,T8,ZERO),
            LHU(V0,0xa,S2),                      # STOCK: reproduced advance read
            J(OBJ_ADV_RET), NOP]
    USE, STOCK = 10, 13
    prog_b[3]=BEQ(V0,ZERO,USE-(3+1))
    prog_b[6]=BNE(V0,ZERO,STOCK-(6+1))
    prog_b[10]=BEQ(T8,ZERO,STOCK-(10+1))
    if (OBJ_A+len(prog_a)*4!=OBJ_B or OBJ_B+len(prog_b)*4>WTABLE10 or
            WTABLE10+512!=SYM_END or
            OBJ_APPEND-0x801187a4!=BP.STCAP-BP.SYM_TAIL_RESERVE):
        raise SystemExit("object-printer VWF reservation layout changed; re-check")
    for addr, expect in ((0x8004c604,0x0c013157),   # jal 0x8004c55c
                         (0x8004c78c,0x9642000a),   # lhu $v0, 0xa($s2)
                         (0x8004c790,0x00000000)):  # delay-slot nop we rely on
        got=struct.unpack_from("<I",exe,foff(addr))[0]
        if got!=expect:
            raise SystemExit(f"object-printer site {addr:#x}: expected {expect:#010x}, got {got:#010x}")
    for i,wd in enumerate(prog_a): w32(OBJ_A+i*4, wd)
    for i,wd in enumerate(prog_b): w32(OBJ_B+i*4, wd)
    tbl=bytearray([10])*512
    def sidx(code):
        b1,b2=code>>8,code&0xff; row=(b1-0x81) if b1<0xa0 else (b1-0xc1); return (b2-0x40)+row*189
    for code in ([*range(0x8260,0x827a), *range(0x8281,0x829b)] +
                 KERN_PUNCT + list(FIELD_NARROW_GLYPHS.values())):
        v=widths10.get(sidx(code))
        if v is not None: tbl[((code>>8)-0x81)*256+(code&0xff)]=v
    tbl[0x40]=widths10.get(0,4)
    for i in range(512): exe[foff(WTABLE10)+i]=tbl[i]
    w32(0x8004c604, JAL(OBJ_A))
    w32(0x8004c78c, J(OBJ_B))

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

def _relocate_name_buffer(exe, w32):
    """Move the name-insert accumulation buffer out of 0x801d1458.

    The stock buffer is 256 bytes and its write-cursor global at 0x801d1558 is
    the very next word.  Decoded name inserts accumulate here between page
    resets; English names are longer than katakana, so a six-demon enemy group
    ("Demonoid Oracles" x6) overruns the buffer and the cursor write-back then
    stamps a pointer into the last decoded name -- the bytes render as ASCII
    garbage through the glyph path's byte-0x20 fallback (the fusion-era
    "composed-prompt" garble signature, seen 2026-07-20 as "Demonoid O<= cles").

    The buffer moves to BP.NAME_INSERT_BUF (504 B) in the C/D STRUCT-table
    tail band that the tree-extent cap keeps free of Huffman nodes; the cursor
    global stays at 0x801d1558, no longer adjacent to the text.  Three code
    sites materialize the base -- the reset fn 0x80051140 (whose zero loop
    grows to the new size), the draw/name text-state clear at 0x80056928, and
    the page-clear handler's batch reset at 0x80059b28 -- and a data-pointer
    scan of the exe finds no other reference to 0x801d1458.
    """
    hi = (BP.NAME_INSERT_BUF >> 16) + (1 if BP.NAME_INSERT_BUF & 0x8000 else 0)
    lo = BP.NAME_INSERT_BUF & 0xffff
    for addr, expect in ((0x80051140, 0x3c02801d),   # lui   $v0, 0x801d
                         (0x80051144, 0x24451458),   # addiu $a1, $v0, 0x1458
                         (0x80051158, 0x2c820040),   # sltiu $v0, $a0, 0x40
                         (0x80051164, 0x24631458),   # addiu $v1, $v1, 0x1458
                         (0x80056940, 0x3c03801d),   # lui   $v1, 0x801d
                         (0x80056944, 0x24651458),   # addiu $a1, $v1, 0x1458
                         (0x80059b1c, 0x3c02801d),   # lui   $v0, 0x801d
                         (0x80059b28, 0x24421458)):  # addiu $v0, $v0, 0x1458
        got = struct.unpack_from("<I", exe, foff(addr))[0]
        if got != expect:
            raise SystemExit(f"name-buffer site {addr:#x}: expected {expect:#010x}, got {got:#010x}")
    w32(0x80051140, 0x3c020000 | hi)                 # lui   $v0, hi
    w32(0x80051144, 0x24450000 | lo)                 # addiu $a1, $v0, lo
    w32(0x80051158, 0x2c820000 | BP.NAME_INSERT_BUF_WORDS)
    w32(0x80051164, 0x24630000 | lo)                 # addiu $v1, $v1, lo
    w32(0x80056940, 0x3c030000 | hi)                 # lui   $v1, hi
    w32(0x80056944, 0x24650000 | lo)                 # addiu $a1, $v1, lo
    w32(0x80059b1c, 0x3c020000 | hi)                 # lui   $v0, hi
    w32(0x80059b28, 0x24420000 | lo)                 # addiu $v0, $v0, lo

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
    MIGRATOR = MN.DEMON_NAME_MIGRATOR_CAVE
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
        JAL(MIGRATOR), NOP,
        MOVE(S1,A0), ADDIU(S0,A1,1),
        # loop @12
        # The PSX R3000 exposes load-delay slots: do not consume LBU/LHU results in
        # the immediately following instruction.
        LBU(T0,0,S0), NOP, 0, NOP,
        SLL(T1,T0,1), LUI(T2,thi), ADDIU(T2,T2,tlo), ADDU(T2,T2,T1),
        LHU(T3,0,T2), NOP, SH(T3,0x10,SP), MOVE(A0,S1), ADDIU(A1,SP,0x10), JAL(BLIT), NOP,
        ADDIU(S0,S0,1), J(PR+12*4), NOP,
        # end @30
        LW(RA,0x2c,SP), LW(S0,0x20,SP), LW(S1,0x24,SP), JR(RA), ADDIU(SP,SP,0x30),
        # stock fallback @35: reproduce 0x800482a4/a8, then continue at 0x800482ac
        ADDIU(SP,SP,-0x20), SW(S0,0x10,SP), J(STOCK), NOP,
    ]
    prog[2] = BNE(T0,T1,35-(2+1))
    prog[14] = BEQ(T0,ZERO,30-(14+1))
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
    for char, sentinel in FIELD_NARROW_SENTINELS.items():
        table[sentinel * 2:sentinel * 2 + 2] = struct.pack(
            ">H", FIELD_NARROW_GLYPHS[char]
        )
    exe[foff(TABLE):foff(TABLE)+len(table)] = table
    w32(0x800482a4, J(PR)); w32(0x800482a8, NOP)


# ---- Safe cached demon names + long-name layouts --------------------------------------
# A party record is 0x70 bytes and its cached name begins at +0x5d, leaving only
# 19 bytes through the end of the record.  Stock Japanese names fit as at most nine
# two-byte glyphs plus NUL.  English ``Yamata-no-Orochi`` needs 33 bytes in that
# representation, so the stock strcpy at 0x801f37d4 overwrites fourteen bytes of the
# following party record before any screen gets a chance to clip the text.
#
# Store translated demon names as the same marker-prefixed one-byte English accepted
# by both global printers.  The tiny converter below runs only when a demon record is
# initialized: it maps the decoder's fullwidth SJIS back through ASCII_TABLE, producing
# [0x1f][up to 17 ASCII bytes][NUL].  Human-entered names retain their stock fullwidth
# copy path at 0x801f3c0c.
DEMON_NAME_CACHE_FIELD_SIZE = 19
DEMON_NAME_CACHE_CONVERTER = MN.DEMON_NAME_CACHE_CAVE


def _install_compact_demon_name_cache(exe, w32):
    """Keep every translated demon name inside record+0x5d..record+0x6f."""
    CAVE = DEMON_NAME_CACHE_CONVERTER
    CAVE_END = MN.DEMON_NAME_CACHE_CAVE_END
    ASCII_TABLE = 0x800d8400
    STRCPY_CALL = 0x801f37d4
    MARKER = SS.ASCII_MARKER
    ZERO,V0,A0,A1,T0,T1,T2,T3,T4,T5,T6,T7,RA = (
        0,2,4,5,8,9,10,11,12,13,14,15,31)
    RI=lambda op,rs,rt,imm:((op&0x3f)<<26)|((rs&0x1f)<<21)|((rt&0x1f)<<16)|(imm&0xffff)
    LBU=lambda rt,o,rs:RI(0x24,rs,rt,o); SB=lambda rt,o,rs:RI(0x28,rs,rt,o)
    ADDIU=lambda rt,rs,i:RI(0x09,rs,rt,i); SLTIU=lambda rt,rs,i:RI(0x0b,rs,rt,i)
    LUI=lambda rt,i:RI(0x0f,ZERO,rt,i)
    BEQ=lambda rs,rt,off:RI(0x04,rs,rt,off); BNE=lambda rs,rt,off:RI(0x05,rs,rt,off)
    ADDU=lambda rd,rs,rt:((rs&0x1f)<<21)|((rt&0x1f)<<16)|((rd&0x1f)<<11)|0x21
    J=lambda target:(0x02<<26)|((target>>2)&0x03ffffff)
    JAL=lambda target:(0x03<<26)|((target>>2)&0x03ffffff)
    JR=lambda rs:((rs&0x1f)<<21)|8
    NOP=0
    lo=lambda x:x&0xffff
    hi=lambda x:((x>>16)+(1 if x&0x8000 else 0))&0xffff

    allowed = set(chr(value) for value in range(0x20, 0x7f))
    too_long = [name for name in NT.DEMONS
                if len(name) + 2 > DEMON_NAME_CACHE_FIELD_SIZE]
    non_ascii = [(name, sorted(set(name) - allowed)) for name in NT.DEMONS
                 if set(name) - allowed]
    if too_long or non_ascii:
        raise SystemExit(
            "Demon name does not fit the compact 19-byte record field: "
            f"too long={too_long!r}, non-ASCII={non_ascii!r}"
        )

    # Search the printable portion of ASCII_TABLE by its two raw SJIS bytes.
    # This is intentionally generic rather than hard-coding letter/punctuation
    # ranges; demon creation is rare and the longest possible scan is negligible.
    table_printable = ASCII_TABLE + 0x20 * 2
    LOOP, SEARCH, NEXT, EMIT, DONE = 3, 12, 20, 25, 29
    prog = [
        ADDIU(T7,ZERO,MARKER), SB(T7,0,A0), ADDIU(A0,A0,1),
        LBU(T0,0,A1), NOP,                         # LOOP: source high byte
        0, ADDIU(T6,ZERO,ord("?")),               # beq NUL -> DONE; default
        LBU(T1,1,A1), ADDIU(A1,A1,2),              # source low byte
        LUI(T2,hi(table_printable)), ADDIU(T2,T2,lo(table_printable)),
        ADDIU(T3,ZERO,0x20),
        LBU(T4,0,T2), LBU(T5,1,T2),                # SEARCH
        0, NOP,                                    # bne high -> NEXT
        0, NOP,                                    # bne low -> NEXT
        J(CAVE+EMIT*4), ADDU(T6,T3,ZERO),           # matched ASCII byte
        ADDIU(T2,T2,2), ADDIU(T3,T3,1),            # NEXT
        SLTIU(T4,T3,0x7f),
        0, NOP,                                    # bne printable -> SEARCH
        SB(T6,0,A0), ADDIU(A0,A0,1),               # EMIT
        J(CAVE+LOOP*4), NOP,
        JR(RA), SB(ZERO,0,A0),                     # DONE
    ]
    prog[5] = BEQ(T0,ZERO,DONE-(5+1))
    prog[14] = BNE(T4,T0,NEXT-(14+1))
    prog[16] = BNE(T5,T1,NEXT-(16+1))
    prog[23] = BNE(T4,ZERO,SEARCH-(23+1))

    if CAVE + len(prog)*4 > CAVE_END:
        raise SystemExit("compact demon-name converter exceeds its cave")
    cave = exe[foff(CAVE):foff(CAVE_END)]
    if set(cave) - {0x00, 0x06, 0x60}:
        raise SystemExit("compact demon-name converter cave is not free tofu")
    for index, word in enumerate(prog):
        w32(CAVE + index*4, word)

    expected = JAL(0x800d107c)                    # BIOS strcpy thunk
    actual = struct.unpack_from("<I", exe, foff(STRCPY_CALL))[0]
    if actual != expected:
        raise SystemExit(
            f"demon-name cache hook {STRCPY_CALL:#x}: "
            f"{actual:#010x} != {expected:#010x}"
        )
    w32(STRCPY_CALL, JAL(CAVE))


def _install_compact_name_migrator(exe, w32):
    """Convert Yamata's cached ASCII to private compact-glyph tokens in place.

    Party boxes are drawn through more than one front end, including the shared
    object compositor.  Both marker-aware printers call this routine, so an old
    save-state cache containing ``\x1fYamata-no-Orochi`` is upgraded the first
    time any affected UI renders it.  Only a/o/m/r are replaced; the complete
    name remains present and its final ``hi`` is rendered inside the panel.
    """
    CAVE = MN.DEMON_NAME_MIGRATOR_CAVE
    CAVE_END = MN.DEMON_NAME_MIGRATOR_CAVE_END
    MARKER = SS.ASCII_MARKER
    ZERO,A1,T0,T1,T2,RA = 0,5,8,9,10,31
    RI=lambda op,rs,rt,imm:((op&0x3f)<<26)|((rs&0x1f)<<21)|((rt&0x1f)<<16)|(imm&0xffff)
    RR=lambda rs,rt,rd,sa,fn:((rs&0x1f)<<21)|((rt&0x1f)<<16)|((rd&0x1f)<<11)|((sa&0x1f)<<6)|(fn&0x3f)
    LBU=lambda rt,o,rs:RI(0x24,rs,rt,o)
    SB=lambda rt,o,rs:RI(0x28,rs,rt,o)
    ADDIU=lambda rt,rs,i:RI(0x09,rs,rt,i)
    BEQ=lambda rs,rt,o:RI(0x04,rs,rt,o)
    BNE=lambda rs,rt,o:RI(0x05,rs,rt,o)
    J=lambda target:(0x02<<26)|((target>>2)&0x03ffffff)
    JR=lambda rs:RR(rs,ZERO,ZERO,0,0x08)
    NOP=0

    prog = []
    labels = {}
    branches = []
    jumps = []
    def label(name): labels[name] = len(prog)
    def emit(*words): prog.extend(words)
    def branch(kind, rs, rt, target):
        branches.append((len(prog), kind, rs, rt, target))
        prog.append(0)
    def jump(target):
        jumps.append((len(prog), target))
        prog.append(0)

    # Fast, load-delay-safe test for the unique marker-prefixed "Yam" prefix.
    emit(LBU(T0,0,A1), LBU(T1,1,A1), ADDIU(T2,ZERO,MARKER))
    branch(BNE,T0,T2,"done")
    emit(LBU(T0,2,A1), ADDIU(T2,ZERO,ord("Y")))
    branch(BNE,T1,T2,"done")
    emit(LBU(T1,3,A1), ADDIU(T2,ZERO,ord("a")))
    branch(BNE,T0,T2,"done")
    emit(ADDIU(T2,ZERO,ord("m")))
    branch(BNE,T1,T2,"done")
    emit(ADDIU(T0,A1,1))

    label("loop")
    emit(LBU(T1,0,T0), NOP)
    branch(BEQ,T1,ZERO,"done")
    emit(NOP)
    for char in FIELD_NARROW_SENTINELS:
        emit(ADDIU(T2,ZERO,ord(char)))
        branch(BEQ,T1,T2,f"map_{char}")
        emit(NOP)
    label("next")
    emit(ADDIU(T0,T0,1))
    jump("loop")
    emit(NOP)

    for char, sentinel in FIELD_NARROW_SENTINELS.items():
        label(f"map_{char}")
        emit(ADDIU(T1,ZERO,sentinel))
        jump("store")
        emit(NOP)
    label("store")
    emit(SB(T1,0,T0))
    jump("next")
    emit(NOP)

    label("done")
    emit(JR(RA), NOP)

    for index, kind, rs, rt, target in branches:
        prog[index] = kind(rs,rt,labels[target] - (index + 1))
    for index, target in jumps:
        prog[index] = J(CAVE + labels[target]*4)

    if CAVE + len(prog)*4 > CAVE_END:
        raise SystemExit(
            f"compact-name migrator exceeds cave ({len(prog)*4} bytes)"
        )
    cave = exe[foff(CAVE):foff(CAVE_END)]
    if set(cave) - {0x00, 0x06, 0x60}:
        raise SystemExit("compact-name migrator cave is not free tofu")
    for index, word in enumerate(prog):
        w32(CAVE + index*4, word)


def _patch_elevator_floor_labels(exe, w32):
    """Render elevator destinations as 22F/21F/20F instead of 22-floor."""
    for address, expected, replacement in (
        (0x80068c80, 0x2402008a, 0x24020082),  # SJIS 0x8a4b -> 0x8265
        (0x80068c8c, 0x2402004b, 0x24020065),
    ):
        actual = struct.unpack_from("<I", exe, foff(address))[0]
        if actual != expected:
            raise SystemExit(
                f"elevator floor suffix {address:#x}: "
                f"{actual:#010x} != {expected:#010x}"
            )
        w32(address, replacement)


def _patch_long_demon_name_layouts(exe, widths, widths10):
    """Give every cached-name UI enough room for the widest English demon."""
    def sidx(code):
        b1, b2 = code >> 8, code & 0xff
        row = (b1 - 0x81) if b1 < 0xa0 else (b1 - 0xc1)
        return (b2 - 0x40) + row * 189

    def text_width(text, table, fallback):
        return sum(table.get(sidx(ET.fullwidth(char)), fallback) for char in text)

    widest10 = max((text_width(name, widths10, 10), name) for name in NT.DEMONS)
    def field_text_width(name, table, fallback):
        variants = FIELD_NARROW_GLYPHS if name == "Yamata-no-Orochi" else {}
        return sum(
            table.get(
                sidx(variants.get(char, ET.fullwidth(char))), fallback
            )
            for char in name
        )
    widest_field10 = max(
        (field_text_width(name, widths10, 10), name) for name in NT.DEMONS
    )
    widest_field12 = max(
        (field_text_width(name, widths, 12), name) for name in NT.DEMONS
    )
    widest12 = max((text_width(name, widths, 12), name) for name in NT.DEMONS)
    width10, name10 = widest10
    field_width10, field_name10 = widest_field10
    field_width12, field_name12 = widest_field12
    width12, name12 = widest12

    def patch_word(address, expected, replacement, label):
        actual = struct.unpack_from("<I", exe, foff(address))[0]
        if actual != expected:
            raise SystemExit(
                f"{label} {address:#x}: {actual:#010x} != {expected:#010x}"
            )
        struct.pack_into("<I", exe, foff(address), replacement)

    # Use the compact font in the shared party/name renderer.  The cached-name
    # migrator substitutes private narrower glyph tokens for Yamata alone; all
    # other party, status, and Cathedral text retains normal spacing.
    if field_width10 > 80:
        raise SystemExit(
            f"80px party-name strip cannot fit {field_name10!r} "
            f"({field_width10}px)"
        )
    patch_word(0x80039d70, 0x24050008, 0x24050004,
               "party/name-plate font")

    # The field renderer independently draws the same UI marker for records
    # whose +0x5c flag is set.  Its literal has one caller (0x80093408); make it
    # empty as well rather than relying solely on the blank compact glyph.
    underprint = foff(0x80014c44)
    if exe[underprint:underprint+3] != b"\x81\x96\x00":
        raise SystemExit("unexpected party-name asterisk underprint")
    exe[underprint] = 0

    # Although each party cell is 96 pixels wide, its name texture exposes only
    # an 80-pixel strip.  The previous x=4 origin left 76 usable pixels and made
    # Yamata's final four pixels spill back onto the strip's left edge.  Use the
    # natural left edge for every name; this also accommodates the other 80px
    # worst case (Cailleach Bheare) without giving Yamata unique alignment.
    if field_width10 > 80:
        raise SystemExit(
            f"party HUD cannot fit {field_name10!r} ({field_width10}px)"
        )
    patch_word(0x80093414, 0x2405000f, 0x24050000,
               "party HUD name origin")

    # The normal field party panels are produced by a second renderer using
    # the 12x12 font and then sliced into 96px cells.  This was the path still
    # visible in state21: unmodified Yamata advances 100px from stock x=4.
    # Its private glyph tokens advance 93px, and x=0 leaves them fully inside
    # the panel while preserving normal metrics for every other name.
    if field_width12 > 96:
        raise SystemExit(
            f"96px field panel cannot fit {field_name12!r} ({field_width12}px)"
        )
    patch_word(0x80093dd8, 0x24050004, 0x24050000,
               "field party-panel name origin")

    # The demon status header owns a 120px sprite and uses the large font.
    # Center its worst case within that surface instead of starting at x=20.
    status_header_x = (120 - width12) // 2
    if status_header_x < 0:
        raise SystemExit(f"status header cannot fit {name12!r} ({width12}px)")
    patch_word(0x800951d8, 0x24050014,
               0x24050000 | status_header_x, "status-header name origin")

    # The status-selection roster uses 10px VWF names, 8px numeric text, and
    # one 288px surface.  Move the three data columns just far enough right to
    # fit the longest name while preserving gaps for %4d/%3d, %3d/%3d, and
    # the longest six-character status label (UNDEAD/PALYZE/FREEZE/POISON).
    name_x = 4
    hp_x, mp_x, status_x = 94, 162, 226
    hp_header_x = hp_x + 8
    if (name_x + width10 + 3 > hp_x or hp_x + 8*8 + 4 > mp_x
            or mp_x + 7*8 + 8 > status_x or status_x + 6*8 > 288):
        raise SystemExit("status-selection column geometry no longer fits")

    header_sites = {
        0x5a: (hp_header_x, (0x80042134,0x80042404,0x800426c8,0x80042c04)),
        0x9a: (mp_x,        (0x80042154,0x80042424,0x800426e8,0x80042c24)),
        0xda: (status_x,    (0x80042174,0x80042444,0x80042708,0x80042c44)),
    }
    row_sites = {
        0x52: (hp_x,     (0x8004223c,0x80042500,0x800427d0,0x80042d0c)),
        0x9a: (mp_x,     (0x80042284,0x80042530,0x80042814,0x80042d54)),
        0xda: (status_x, (0x800422a0,0x80042564,0x80042830,0x80042d70)),
    }
    for stock_x, (new_x, sites) in (*header_sites.items(), *row_sites.items()):
        for address in sites:
            patch_word(address, 0x24050000 | stock_x,
                       0x24050000 | new_x, "status-selection column")

# ============================ 3. NAME TABLES ============================
_COMPACT_RACE_POOL_START = 0x80011f9c
_COMPACT_RACE_POOL_END = 0x80012128
_COMPACT_RACE_PTR_TABLES = (0x800f77b0, 0x800f7860)
# Cathedral row renderers select the 12x12 font for the race column, then the
# compact 10x10 font for the demon-name column.  The mixed sizes make the race
# look like a second heading instead of part of the same row.  Keep this local
# to fusion: status screens still use the larger race label intentionally.
_CATHEDRAL_RACE_FONT_SITES = (
    0x8008ddfc,
    0x8008e5d4,
    0x8008e95c,
    0x8008ea80,  # fusion result race
    0x8008ed0c,
    0x8008ef64,
    0x8008f328,
    0x8008f418,  # alternate fusion result race
    0x8008f9f0,
    0x800902c8,
)
# Regular demon IDs are grouped by race in the loaded fusion module.  The
# module's lookup at 0x801fa594 returns the index of the first boundary greater
# than the demon ID (ID 0..9 -> race 1, 10..16 -> race 2, and so on).
_CATHEDRAL_RACE_BOUNDARIES = (
    0, 10, 17, 22, 28, 38, 44, 50, 58, 63, 70, 76, 84, 90,
    97, 104, 111, 117, 124, 130, 136, 145, 151, 159, 166, 173,
    178, 183, 188, 194, 196, 204, 212, 216, 222, 229, 235, 241,
    246, 252, 255,
)
# High-byte demon IDs use this race map, indexed by their low byte.  It is the
# table at 0x801fbf58 in the loaded fusion module; entries 42/43 are sentinels
# rather than printable races.  Low byte 0 corresponds to DEMONS[256].
_CATHEDRAL_SPECIAL_RACES = (
    41, 17, 36, 35, 22, 23, 41, 17, 41, 41, 23, 12, 41, 35,
    41, 1, 1, 1, 0, 35, 5, 17, 35, 35,
    42, 42, 42, 42, 42, 42, 42, 42, 42, 42, 42, 42,
    36, 5, 35, 35, 0, 0, 0, 0, 0, 0, 0, 35,
    43, 43, 43, 43, 43, 43, 43,
)

# Cathedral row fields are relative to the list's 288-pixel text surface.
# Race and demon are appended as one proportional field; this avoids paying
# for the independent worst case of both columns when no such race/demon pair
# exists in the game's data.
_CATHEDRAL_PAIR_GAP = 4
_CATHEDRAL_SOURCE_X = 13
_CATHEDRAL_FIRST_NAME_X = 66
_CATHEDRAL_FIRST_LEVEL_X = 166
_CATHEDRAL_RESULT_X = 144
_CATHEDRAL_RESULT_LEVEL_X = 268

# Four instructions which used to reset x to the stock NAME column.  Each is
# replaced by ``cursor_x += 4`` after the race has been printed, so the demon
# name follows it naturally.  Values are (address, context register).
_CATHEDRAL_JOIN_NAME_SITES = (
    (0x8008de44, 19),  # s3: compact selected-demon summary
    (0x8008e988, 16),  # s0: next-demon source
    (0x8008eadc, 17),  # s1: next-demon result
    (0x8008f350, 16),  # s0: alternate next-demon source
    (0x8008f464, 16),  # s0: alternate next-demon result
    (0x8008fa1c, 16),  # s0: special-fusion source roster
    (0x800902f4, 17),  # s1: equipment-fusion source roster
)
SPELL_DESCRIPTION_START = 160
SPELL_DESCRIPTION_MAX_PIXELS = 124
_COMPACT_RACE_PRIMARY_PTRS = (
    0x800120f8, 0x800120f0, 0x800120e8, 0x800120e0, 0x800120d8, 0x800120d0,
    0x800120c8, 0x800120c0, 0x800120b8, 0x800120b0, 0x800120a8, 0x800120a0,
    0x80012098, 0x80012090, 0x80012088, 0x8001207c, 0x80012074, 0x8001206c,
    0x80012064, 0x8001205c, 0x80012054, 0x8001204c, 0x80012040, 0x80012038,
    0x80012030, 0x80012028, 0x8001201c, 0x80012014, 0x8001200c, 0x80012004,
    0x80011ff8, 0x80011ff0, 0x80011fe8, 0x80011fe0, 0x80011fd8, 0x80011fd0,
    0x80011fc8, 0x80011fc0, 0x80011fb8, 0x80011fb0, 0x80011fa4, 0x80011f9c,
)


def _validate_spell_description_widths(widths):
    """Keep spell/skill descriptions inside their 124-pixel status box."""
    def sidx(code):
        b1, b2 = code >> 8, code & 0xff
        row = (b1 - 0x81) if b1 < 0xa0 else (b1 - 0xc1)
        return (b2 - 0x40) + row * 189

    overflows = []
    for index, description in enumerate(
            NT.SPELLS[SPELL_DESCRIPTION_START:], SPELL_DESCRIPTION_START):
        pixel_width = sum(
            widths.get(sidx(ET.fullwidth(char)), 12) for char in description
        )
        if pixel_width > SPELL_DESCRIPTION_MAX_PIXELS:
            overflows.append((index, pixel_width, description))

    if overflows:
        details = ", ".join(
            f"{index}={width}px {description!r}"
            for index, width, description in overflows
        )
        raise SystemExit(
            f"Spell descriptions exceed {SPELL_DESCRIPTION_MAX_PIXELS}px: {details}"
        )


def _patch_compact_race_labels(exe):
    """Translate the raw race-name pool used by demon status screens.

    These screens do not use the rebuildable RACES table at 0x801043f8.  They
    instead select from two executable-resident pointer tables; the second
    table substitutes five shorter Japanese aliases.  Repack the pool with
    the same Atlus race names as NT.RACES and point both tables at them.
    """
    if len(NT.RACES) != len(_COMPACT_RACE_PRIMARY_PTRS):
        raise RuntimeError(
            "Compact race table count no longer matches NT.RACES: "
            f"{len(_COMPACT_RACE_PRIMARY_PTRS)} != {len(NT.RACES)}"
        )

    expected_secondary = list(_COMPACT_RACE_PRIMARY_PTRS)
    expected_secondary[15] = 0x80012120  # Messian: shorter Japanese alias
    expected_secondary[22] = 0x80012118  # Demonoid
    expected_secondary[26] = 0x80012110  # Gaean
    expected_secondary[30] = 0x80012108  # Vaccine
    expected_secondary[40] = 0x80012100  # Virus
    expected_tables = (_COMPACT_RACE_PRIMARY_PTRS, tuple(expected_secondary))

    for table_addr, expected in zip(_COMPACT_RACE_PTR_TABLES, expected_tables):
        actual = struct.unpack_from(f"<{len(expected)}I", exe, foff(table_addr))
        if actual != expected:
            raise RuntimeError(
                f"Unexpected compact race pointer table at 0x{table_addr:08x}; "
                "refusing to overwrite an incompatible executable"
            )

    pool = bytearray()
    pointers = []
    for name in NT.RACES:
        pointers.append(_COMPACT_RACE_POOL_START + len(pool))
        pool += bytes([SS.ASCII_MARKER]) + name.encode("ascii") + b"\0"

    capacity = _COMPACT_RACE_POOL_END - _COMPACT_RACE_POOL_START
    if len(pool) > capacity:
        raise RuntimeError(
            f"Compact race labels overflow by {len(pool) - capacity} bytes"
        )

    pool_off = foff(_COMPACT_RACE_POOL_START)
    exe[pool_off:pool_off + capacity] = pool.ljust(capacity, b"\0")
    packed_pointers = struct.pack(f"<{len(pointers)}I", *pointers)
    for table_addr in _COMPACT_RACE_PTR_TABLES:
        table_off = foff(table_addr)
        exe[table_off:table_off + len(packed_pointers)] = packed_pointers


def _patch_cathedral_race_font(exe):
    """Draw fusion-list race and demon names with the same compact font.

    Enlarging demon names to 12x12 looks tempting, but the narrowest Cathedral
    NAME column is only wide enough for the existing 10x10 text; fifteen valid
    demon names would overrun it at 12x12.  Switching just the Cathedral race
    selectors from font 8 (12x12) to font 4 (10x10) gives the rows consistent
    typography without changing party, battle, or demon-status rendering.
    """
    stock_font_12 = 0x24050008  # addiu a1, zero, 8
    compact_font_10 = 0x24050004  # addiu a1, zero, 4
    for address in _CATHEDRAL_RACE_FONT_SITES:
        offset = foff(address)
        actual = struct.unpack_from("<I", exe, offset)[0]
        if actual != stock_font_12:
            raise RuntimeError(
                f"Unexpected Cathedral race-font selector at 0x{address:08x}: "
                f"0x{actual:08x}"
            )
        struct.pack_into("<I", exe, offset, compact_font_10)


def _patch_cathedral_columns(exe, widths10):
    """Fit every regular race/demon name on the Cathedral fusion screens.

    Stock reserves separate fixed columns for Japanese race and demon names.
    English ``Demonoid`` overruns the first column, while several demon names
    overrun the second.  The roomy first-demon screen keeps aligned columns:
    RACE is x=13..61 and NAME is x=66..157.  The crowded next-demon screen
    appends the two proportional strings with a 4-pixel gap, making the useful
    unit the *real* race/name pair.  Across all 255 normal demons the widest
    pair is 120 pixels, which fits both the source field (x=13 through the
    compatibility mark at x=134) and result field (x=144 through the level at
    x=268) without abbreviating a demon name.

    The first-demon screen has no result field, so its NAME column moves 15
    pixels right and its LV/numbered-affinity columns move 41 pixels right.  The
    next-demon RESULT header/result rows move
    four pixels left, leaving a visible gap before LV even for the widest pair.
    """
    from bisect import bisect_right

    def sidx(code):
        b1, b2 = code >> 8, code & 0xff
        row = (b1 - 0x81) if b1 < 0xa0 else (b1 - 0xc1)
        return (b2 - 0x40) + row * 189

    def text_width(text):
        return sum(widths10.get(sidx(ET.fullwidth(char)), 10) for char in text)

    if len(NT.DEMONS) < 255 or len(NT.RACES) != 42:
        raise RuntimeError("Cathedral width audit requires 255 demons and 42 races")

    pairs = []
    for demon_id, demon in enumerate(NT.DEMONS[:255]):
        race_id = bisect_right(_CATHEDRAL_RACE_BOUNDARIES, demon_id)
        race = NT.RACES[race_id]
        width = text_width(race) + _CATHEDRAL_PAIR_GAP + text_width(demon)
        pairs.append((width, demon_id, race, demon))
    for low_id, race_id in enumerate(_CATHEDRAL_SPECIAL_RACES):
        demon_index = 256 + low_id
        if demon_index >= len(NT.DEMONS) or race_id >= len(NT.RACES):
            continue
        demon = NT.DEMONS[demon_index]
        race = NT.RACES[race_id]
        width = text_width(race) + _CATHEDRAL_PAIR_GAP + text_width(demon)
        pairs.append((width, 0x100 + low_id, race, demon))

    widest, demon_id, race, demon = max(pairs)
    widest_race = max(map(text_width, NT.RACES))
    widest_demon = max(map(text_width, NT.DEMONS))
    first_race_capacity = _CATHEDRAL_FIRST_NAME_X - \
                          _CATHEDRAL_PAIR_GAP - _CATHEDRAL_SOURCE_X
    first_name_capacity = _CATHEDRAL_FIRST_LEVEL_X - 8 - \
                          _CATHEDRAL_FIRST_NAME_X
    if widest_race > first_race_capacity or widest_demon > first_name_capacity:
        raise SystemExit(
            "Cathedral first-demon columns do not fit: "
            f"race {widest_race}/{first_race_capacity}px, "
            f"name {widest_demon}/{first_name_capacity}px"
        )

    source_capacity = 134 - _CATHEDRAL_SOURCE_X
    # Preserve four clear pixels between the result text and its level.
    result_capacity = _CATHEDRAL_RESULT_LEVEL_X - 4 - _CATHEDRAL_RESULT_X
    if widest > min(source_capacity, result_capacity):
        raise SystemExit(
            "Cathedral race/name pair does not fit: "
            f"ID {demon_id} {race} {demon!r} is {widest}px; "
            f"capacities are {source_capacity}px/{result_capacity}px"
        )

    def patch_word(address, expected, replacement, label):
        offset = foff(address)
        actual = struct.unpack_from("<I", exe, offset)[0]
        if actual != expected:
            raise RuntimeError(
                f"Unexpected {label} instruction at 0x{address:08x}: "
                f"0x{actual:08x} != 0x{expected:08x}"
            )
        struct.pack_into("<I", exe, offset, replacement)

    def i_type(op, rs, rt, immediate):
        return ((op & 0x3f) << 26) | ((rs & 0x1f) << 21) | \
               ((rt & 0x1f) << 16) | (immediate & 0xffff)

    # Validate the whole stock four-instruction reset before replacing it.
    stock_name_x = {
        0x8008de44: 0x40,
        0x8008e988: 0x33, 0x8008eadc: 0xba, 0x8008f350: 0x33,
        0x8008f464: 0xba, 0x8008fa1c: 0x33, 0x800902f4: 0x33,
    }
    jal_set_xy = 0x0c012112  # jal 0x80048448
    for address, context_reg in _CATHEDRAL_JOIN_NAME_SITES:
        offset = foff(address)
        stock = struct.unpack_from("<4I", exe, offset)
        expected_move_a0 = (context_reg << 21) | (4 << 11) | 0x21
        if (stock[0] != expected_move_a0
                or stock[1] != i_type(0x09, 0, 5, stock_name_x[address])
                or stock[2] != jal_set_xy):
            raise RuntimeError(
                f"Unexpected Cathedral NAME reset at 0x{address:08x}: "
                + ", ".join(f"0x{word:08x}" for word in stock)
            )
        replacement = (
            i_type(0x25, context_reg, 5, 0x20),  # lhu a1,0x20(context)
            0,  # R3000 load-delay slot: addiu must not consume a1 yet
            i_type(0x09, 5, 5, _CATHEDRAL_PAIR_GAP),
            i_type(0x29, context_reg, 5, 0x20),  # sh a1,0x20(context)
        )
        struct.pack_into("<4I", exe, offset, *replacement)

    # Main first-demon header/row variants retain true aligned columns.
    for address in (0x8008d02c, 0x8008d290, 0x8008d378):
        patch_word(address, 0x24050033, 0x24050042,
                   "Cathedral NAME header")
    for address in (0x8008e618, 0x8008ed3c, 0x8008efac):
        patch_word(address, 0x24050033, 0x24050042,
                   "Cathedral NAME field")
    for address in (0x8008d04c, 0x8008d2b0, 0x8008d398):
        patch_word(address, 0x24050085, 0x240500ae, "Cathedral LV header")
    for address in (0x8008d068, 0x8008d3b4):
        patch_word(address, 0x24140098, 0x241400c1,
                   "Cathedral affinity-header origin")
    # Special/equipment variants use joined race/name fields rather than the
    # independently aligned first-demon columns, so 18 pixels is sufficient.
    for address in (0x8008d61c, 0x8008d910, 0x8008db50):
        patch_word(address, 0x24140098, 0x241400aa,
                   "Cathedral special affinity-header origin")

    # Main first-demon row variants: level and affinity values +41 px.
    for address in (0x8008e640, 0x8008ed64, 0x8008efd4):
        patch_word(address, 0x2405007d, 0x240500a6,
                   "Cathedral level field")
    patch_word(0x8008e5d8, 0x24170099, 0x241700c2,
               "Cathedral affinity-row origin")
    patch_word(0x8008ef68, 0x24150099, 0x241500c2,
               "Cathedral alternate affinity-row origin")

    # The special-fusion roster uses the same source pair but a different set
    # of fields.  Move only the three fields which begin before x=184; the
    # rightmost count fields at x=261/272 already have their own safe region.
    for address, expected, replacement in (
        (0x8008fa48, 0x24050074, 0x24050086),
        (0x8008fa78, 0x24050080, 0x24050092),
        (0x8008fb64, 0x240500a6, 0x240500b8),
    ):
        patch_word(address, expected, replacement,
                   "Cathedral special-fusion field")

    # Main next-demon header/result variants: RESULT starts at x=144.  The
    # equipment-fusion x=148 field is intentionally separate and unchanged.
    for address in (0x8008d1c4, 0x8008d510, 0x8008da6c, 0x8008dca8,
                    0x8008ea74, 0x8008f404):
        patch_word(address, 0x24050094, 0x24050090,
                   "Cathedral RESULT field")


def _patch_confirm_font(exe):
    """Keep the greyed YES/NO confirm options in the stock heavy style.

    The YES/NO renderers (0x8003f71c/0x8003f7a8) draw both options through
    the static text context 0x800f7484 -- the only context in the game whose
    descriptor selects the 10x10 font.  Its stock heavy capitals visually
    matched the bold selected-option overlay, but kern_font redraws A-Z as
    compact 5x7 for demon-name lists, which shrank the greyed options.
    kern_font preserves the five stock glyphs in the unused SJIS cells
    0x8259-0x825d; retarget the ＹＥＳ/ＮＯ strings (referenced only by these
    two renderers) onto those cells for a pixel-identical stock rendering.
    """
    stock_yes = bytes.fromhex("827882648272") + b"\0"  # ＹＥＳ
    stock_no = bytes.fromhex("826d826e") + b"\0"       # ＮＯ
    relocated_yes = bytes.fromhex("8259825a825b") + b"\0"
    relocated_no = bytes.fromhex("825c825d") + b"\0"
    for off, stock, relocated in ((0x1fec, stock_yes, relocated_yes),
                                  (0x1ff4, stock_no, relocated_no)):
        if bytes(exe[off:off + len(stock)]) != stock:
            raise RuntimeError(f"Unexpected YES/NO string at 0x{off:x}")
        exe[off:off + len(relocated)] = relocated


def apply_name_tables(exe, slpm, PATHS, widths10):
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
    _patch_compact_race_labels(exe)
    _patch_cathedral_race_font(exe)
    _patch_cathedral_columns(exe, widths10)
    _patch_confirm_font(exe)
    _patch_bar_drink_menu(exe)
    _patch_casino_prize_menu(exe)

def _patch_bar_drink_menu(exe):
    """Keep English drink names and prices inside the Bar's row formatter.

    The stock routine resolves each drink name twice and appends every result
    to one 256-byte name scratch buffer.  Six longer English names plus their
    price strings exhaust that buffer: the second ``Speed Cocktail`` decode
    overruns it, then corrupts the first glyph of ``Miracle Tonic``.  Measure
    the name already copied into the row instead, resetting the scratch buffer
    before resolving the price.  Widen the padded name field from 14 to 16
    fullwidth characters so the longest label still leaves a visible gap
    before the Macca symbol.  A row is 48 bytes, so the wider 32-byte field,
    symbol, three-digit price, and terminator remain within its allocation.
    """
    if max(map(len,NT.DRINKS))>16:
        raise SystemExit("Bar drink name exceeds the 16-character menu field")

    # address: (stock word, English replacement)
    patches={
        0x8005f1a8:(0x96050000,0x00000000),  # remove redundant drink-index load
        0x8005f1ac:(0x0c01445d,0x0c014450),  # second name lookup -> reset scratch
        0x8005f1b0:(0x2404000e,0x00000000),  # reset delay slot
        0x8005f1b8:(0x00402021,0x02342021),  # strlen(row) instead of strlen(v0)
        0x8005f1c0:(0x2ce2001c,0x2ce20020),  # 28-byte field -> 32 bytes
        0x8005f1fc:(0x2ce2001c,0x2ce20020),
    }
    for address,(stock,replacement) in patches.items():
        offset=foff(address)
        found=struct.unpack_from("<I",exe,offset)[0]
        if found!=stock:
            raise SystemExit(
                f"Bar drink formatter {address:#x}: {found:#010x} != {stock:#010x}"
            )
        struct.pack_into("<I",exe,offset,replacement)


def _patch_casino_prize_menu(exe):
    """Give every casino prize row a safe English name/price separator.

    Four prize inventories share one formatter and one 48-byte row layout.
    Stock pads the item name to only 13 fullwidth characters, so longer
    English names run directly into their Coin cost.  A 16-character field
    guarantees at least one fullwidth space after every translated prize in
    those inventories while retaining room for the formatter's six-digit
    fallback price, the one-character Coin suffix, and the NUL terminator.

    As in the Bar formatter, avoid resolving each compressed name twice.
    Measure the completed row and reset the shared decoder scratch buffer
    before resolving the price, preventing accumulated names from exhausting
    it when a longer prize list is shown.
    """
    prize_table = foff(0x801126f2)
    longest = (0, "")
    for inventory in range(4):
        relative = struct.unpack_from("<H", exe, prize_table + inventory * 2)[0]
        cursor = prize_table + (relative & 0xfffe)
        for _ in range(20):
            item, price = struct.unpack_from("<HH", exe, cursor)
            cursor += 4
            if item == 0xff:
                break
            if item >= 300:
                raise SystemExit(
                    f"Casino prize inventory {inventory}: invalid item {item}")
            name = NT.ITEMS[item]
            if len(name) > longest[0]:
                longest = (len(name), name)
            if price != 0xffff and price > 999999:
                raise SystemExit(
                    f"Casino prize inventory {inventory}: price {price} is too wide")
        else:
            raise SystemExit(
                f"Casino prize inventory {inventory}: missing terminator")
    if longest[0] > 15:
        raise SystemExit(
            f"Casino prize {longest[1]!r} exceeds the safe 15-character field")

    # address: (stock word, English replacement)
    patches = {
        0x80063768: (0x96050000, 0x00000000),  # remove redundant item-index load
        0x8006376c: (0x0c01445d, 0x0c014450),  # second name lookup -> reset scratch
        0x80063770: (0x00002021, 0x00000000),  # reset delay slot
        0x80063778: (0x00402021, 0x02342021),  # strlen(row) instead of strlen(v0)
        0x80063780: (0x2ca2001a, 0x2ca20020),  # 26-byte field -> 32 bytes
        0x800637b8: (0x2ca2001a, 0x2ca20020),
    }
    for address, (stock, replacement) in patches.items():
        offset = foff(address)
        found = struct.unpack_from("<I", exe, offset)[0]
        if found != stock:
            raise SystemExit(
                f"Casino prize formatter {address:#x}: "
                f"{found:#010x} != {stock:#010x}"
            )
        struct.pack_into("<I", exe, offset, replacement)


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
AB_STRUCT, AB_SYM = 0x8010130c, 0x80101978

def decode_ab_block(block, slpm):
    """Decode one byte-bounded A/B block while retaining dispatch indices."""
    def U16(address): return struct.unpack_from("<H",slpm,foff(address))[0]
    data_offset=struct.unpack_from("<H",block,0)[0]
    count=(data_offset-2)//2
    offsets=list(struct.unpack_from(f"<{count}H",block,2))
    unique=sorted(set(offsets))
    # Stock blocks use 0xCC fill; rebuilt blocks use zero fill because root
    # nibble 0 is deliberately invalid. Zero fill cannot be mistaken for a
    # real encoded suffix when the final stream happens to end in 0xCC bytes.
    fills=[pos for pattern in (b"\x00"*16,b"\xCC"*16)
           if (pos:=block.find(pattern,data_offset+unique[-1]))>=0]
    if not fills:
        raise SystemExit("could not find A/B-bank fill after final stream")
    fill=min(fills)
    end_for={
        offset:(unique[i+1] if i+1<len(unique) else fill-data_offset)
        for i,offset in enumerate(unique)
    }

    def decode_one(offset):
        pos=data_offset+offset; end=data_offset+end_for[offset]
        high_nibble=True; tokens=[]
        while pos<end:
            node=0
            for _depth in range(64):
                if pos>=end: return tokens
                byte=block[pos]
                nibble=(byte>>4) if high_nibble else (byte&0x0f)
                high_nibble=not high_nibble
                if high_nibble: pos+=1
                entry=(node&0xfffe)+nibble*2
                next_node=U16(AB_STRUCT+entry)
                if next_node==0x7fff: return tokens
                if next_node&0x8000:
                    symbol=U16(AB_SYM+entry)
                    if next_node&0x4000:
                        tokens.append((symbol,True,next_node&0x3fff))
                    else:
                        tokens.append((symbol,False))
                    break
                node=next_node
            else:
                raise SystemExit("A/B Huffman path exceeds 64 levels")
        return tokens

    cache={offset:decode_one(offset) for offset in unique}
    return [cache[offset] for offset in offsets],count

def build_ab_block(messages, count, paths):
    """Encode byte-aligned A/B fragments, interning exact duplicate streams."""
    offsets=[]; data=bytearray(); interned={}
    for message in messages:
        key=tuple(message)
        if key in interned:
            offsets.append(interned[key]); continue
        offsets.append(len(data)); interned[key]=len(data)
        nibbles=[]
        for token in message:
            if token not in paths:
                raise SystemExit(f"A/B tree lacks token {token!r}")
            nibbles.extend(paths[token])
        byte=0; high_nibble=True
        for nibble in nibbles:
            if high_nibble:
                byte=(nibble&0x0f)<<4; high_nibble=False
            else:
                data.append(byte|(nibble&0x0f)); high_nibble=True
        if not high_nibble: data.append(byte)
    data_offset=2+2*count
    out=bytearray(struct.pack("<H",data_offset))
    out+=struct.pack(f"<{count}H",*offsets)
    out+=data
    return bytes(out)

# Bank 4 needs more than its stock 15 sectors for full English negotiation
# text.  One extra sector brings it to 16 -- the proven ceiling: banks 0-5 all
# load to the fixed buffer 0x801bbe28 and live engine data begins exactly 16
# sectors later at 0x801c3e28 (stock bank 2 already reads 16 sectors).  Every
# PACKA file after bank 4 shifts by this amount; make_patch grows the ISO
# extent (PACKA.BIN is the last file on disc, followed by free sectors).
AB4_EXTRA_SECTORS = 1
FILE_TABLE = 0x800e891c            # u16 PACKA sector per file id
FILE_TABLE_ENTRIES = 0x862         # ids 0x000-0x860 + end boundary at 0x861

def _ab_source_specs(slpm):
    """Return validated stock file bounds and A/B decode specifications."""
    file_bounds=struct.unpack_from("<3H",slpm,0xda17e)
    expected_bounds=(0x65e2,0x65f1,0x65f2)
    if file_bounds!=expected_bounds:
        raise SystemExit(
            f"unexpected A/B bank file boundaries: {file_bounds!r}"
        )
    b4_start,b5_start,b5_end=file_bounds
    return file_bounds,{
        4:(b4_start*2048,(b5_start-b4_start)*2048,2432),
        5:(b5_start*2048,(b5_end-b5_start)*2048,98),
    }

def _decode_ab_sources(packa,slpm):
    """Decode pristine stock Bank 4/5 streams at their original offsets."""
    file_bounds,specs=_ab_source_specs(slpm)
    source=bytes(packa); decoded={}
    for bank,(base,allocation,expected_count) in specs.items():
        messages,count=decode_ab_block(source[base:base+allocation],slpm)
        if count!=expected_count:
            raise SystemExit(
                f"bank{bank}: expected {expected_count} entries, found {count}"
            )
        collisions=[
            index for index,message in enumerate(messages)
            if any(len(token)==3 and token[2]==BP.DICT_JT_INDEX for token in message)
        ]
        if collisions:
            raise SystemExit(
                f"bank{bank}: stock A/B control slot {BP.DICT_JT_INDEX} is not free "
                f"(messages {collisions[:8]!r})"
            )
        decoded[bank]=messages
    return file_bounds,specs,decoded

def _author_ab_messages(decoded):
    """Tokenize Bank 4/5 using the currently configured A/B dictionaries."""
    authored={}
    for bank in (4,5):
        authored[bank]=[]
        for index,original in enumerate(decoded[bank]):
            message_id=(bank<<12)|index
            if message_id in TR.TRANS:
                message=TP.ab_author_to_tokens(TR.TRANS[message_id])
            elif bank==4:
                # Japanese fallback is intentionally disabled while bank 4 is
                # being localized. Retain dispatcher operations in source order.
                controls=[token for token in original if len(token)==3]
                message=TP.ab_author_to_tokens(["UNTRANSLATED"])+controls
            else:
                message=original
            authored[bank].append(message)
    return authored

def ab_base_leaf_count(packa,slpm):
    """Count actual A/B leaves with only the shared dictionary configured.

    Adding local dictionary entries can make some base leaves disappear, so
    this is a conservative exact-corpus bound rather than a guessed repertoire.
    """
    _bounds,_specs,decoded=_decode_ab_sources(packa,slpm)
    authored=_author_ab_messages(decoded)
    return len({token for bank in (4,5) for msg in authored[bank] for token in msg})

def _unique_stored_ab_streams(authored):
    """One copy of every stream physically stored in each separate block."""
    streams=[]
    for bank in (4,5):
        # Interning is per block, so retain one copy in each bank when the same
        # token stream happens to occur in both.
        streams.extend(dict.fromkeys(tuple(message) for message in authored[bank]))
    return streams

def _shift_file_table(exe, first_sector, extra_sectors):
    """Move every file located at/after first_sector by extra_sectors."""
    previous=0
    for fid in range(FILE_TABLE_ENTRIES):
        off=foff(FILE_TABLE)+2*fid
        value=struct.unpack_from("<H",exe,off)[0]
        if value<previous:
            raise SystemExit(f"PACKA file table not monotonic at id {fid:#x}")
        previous=value
        if value>=first_sector:
            struct.pack_into("<H",exe,off,value+extra_sectors)

def verify_ab_banks(exe, packa, specs, authored):
    """Round-trip the rebuilt A/B blocks against authored intent.

    Decodes each block with the English tree now in the exe (segment ends are
    offset-bounded, so interned duplicates decode through shared streams) and
    checks the installed dictionary runtime strings byte-for-byte.
    """
    for bank,(base,allocation,expected_count) in specs.items():
        # Pad the fill probe so a block that ends flush with its allocation
        # still terminates the final stream.
        block=bytes(packa[base:base+allocation])+b"\x00"*16
        messages,count=decode_ab_block(block,exe)
        if count!=expected_count:
            raise SystemExit(f"bank{bank} verify: {count} entries != {expected_count}")
        for index,(got,want) in enumerate(zip(messages,authored[bank])):
            if got!=want:
                raise SystemExit(
                    f"bank{bank} msg {index}: decode mismatch\n  got {got!r}\n  want {want!r}"
                )
    BP.verify_ab_runtime(exe)
    MT.verify_ab_menu(exe)

def apply_ab_banks(exe, packa, slpm):
    """Rebuild English bank 4/5, growing bank 4 by AB4_EXTRA_SECTORS.

    The stock file table places bank 4 in sectors 0x65e2..0x65f1 and bank 5 in
    the single sector 0x65f1..0x65f2.  The four entries following bank 5 are
    unrelated live files and must not be treated as bank-5 padding.  Sources
    decode from the pristine PACKA at stock offsets; destinations use the
    shifted layout, and the exe's file table is rewritten to match.
    """
    file_bounds,_src_specs,decoded=_decode_ab_sources(packa,slpm)
    b4_start,b5_start,b5_end=file_bounds
    authored=_author_ab_messages(decoded)

    # build_ab_block interns exact duplicates independently within each bank.
    # Weight the Huffman tree by those physically stored streams, not by every
    # table entry that happens to point to them.
    # Negotiation choices use a separate executable-resident A/B menu table.
    # Its plain-glyph streams must participate in the same tree build before
    # the old Japanese table can be re-encoded safely.
    ab_tree_streams=(
        _unique_stored_ab_streams(authored)+MT.ab_menu_token_streams()
    )
    paths=BP.build_ab_tree(exe,ab_tree_streams)
    if BP.AB_SYM+BP.AB_TREE_USED>MT.AB_MENU_DATA:
        raise SystemExit(
            f"A/B tree overlaps relocated menu data: "
            f"{BP.AB_SYM+BP.AB_TREE_USED:#x}>{MT.AB_MENU_DATA:#x}"
        )
    BP.install_ab_runtime(exe)
    if BP.AB4_OFFTAB>=BP.AB_SYM:
        raise SystemExit(
            "A/B dictionary offset table unexpectedly occupies the symbol-table tail"
        )
    menu_used,menu_budget=MT.rebuild_ab_menu(exe,paths)
    print(f"  A/B menu: {menu_used}/{menu_budget} bytes")
    rebuilt={
        bank:build_ab_block(authored[bank],len(authored[bank]),paths)
        for bank in (4,5)
    }
    shift=AB4_EXTRA_SECTORS*2048
    packa=bytearray(packa)
    packa[b5_start*2048:b5_start*2048]=b"\x00"*shift
    _shift_file_table(exe,b5_start,AB4_EXTRA_SECTORS)
    dst_specs={
        4:(b4_start*2048,(b5_start-b4_start)*2048+shift,2432),
        5:(b5_start*2048+shift,(b5_end-b5_start)*2048,98),
    }
    for bank,(base,allocation,_count) in dst_specs.items():
        block=rebuilt[bank]
        print(f"  bank{bank}: {len(block)}/{allocation} bytes")
        if len(block)>allocation:
            raise SystemExit(f"bank{bank} OVERFLOW {len(block)}>{allocation}")
        packa[base:base+allocation]=b"\x00"*allocation
        packa[base:base+len(block)]=block

    # Capacity projection: placeholders drop out at 100%, so scale the bytes of
    # unique translated streams by the JP unique-stream token ratio.  Unique
    # streams (not raw entries) are what interning actually stores.
    translated_ids={mid&0xfff for mid in TR.TRANS if mid>>12==4}
    unique_jp={}
    for index,message in enumerate(decoded[4]):
        unique_jp.setdefault(tuple(message),[]).append(index)
    jp_translated=jp_total=0
    for key,indices in unique_jp.items():
        jp_total+=len(key)
        if any(i in translated_ids for i in indices):
            jp_translated+=len(key)
    seen=set(); translated_bytes=0
    for index,message in enumerate(authored[4]):
        key=tuple(message)
        if key in seen: continue
        seen.add(key)
        if index in translated_ids:
            translated_bytes+=(sum(len(paths[t]) for t in message)+1)//2
    if jp_translated:
        alloc4=dst_specs[4][1]
        projected=2+2*len(authored[4])+translated_bytes*jp_total/jp_translated
        print(
            f"  bank4 projection at full translation: ~{projected:,.0f}/{alloc4} bytes "
            f"({len(translated_ids)}/{len(authored[4])} entries translated)"
        )
    return packa,dst_specs,authored

CD_BANKS = None
def apply_banks(exe, packa, slpm, PATHS):
    """Rebuild A/B and C/D banks with TR.TRANS plus C/D placeholders.

    Bank allocations are unchanged except bank 4 (+AB4_EXTRA_SECTORS), so every
    PACKA bank after it sits AB4_EXTRA_SECTORS later in the rebuilt archive.
    Sources always decode from the pristine PACKA at stock offsets.
    """
    ED=(0x4544,True)
    def U16(a): return struct.unpack_from("<H", exe, foff(a))[0]
    # Source allocations only bound the JP decode (blocks self-terminate, so a generous
    # bound is harmless).  Destination allocations are the TRUE limits -- see the
    # BANK6_LIMIT / BANK7_CAVE notes at the top of this file.
    src_alloc6=BANK7_JP_BASE-BANK6_BASE            # 4948: stock bank 6 region
    src_alloc7=0x80117cc8-BANK7_JP_BASE            # 3484: bounds the decode only
    dst_alloc6=BANK6_LIMIT-BANK6_BASE              # 5632: bank 6 owns the whole region
    # The cave tail holds the dictionary handler + strings from BP.DICT_BASE
    # and the A/B continuation handler in the 64 bytes before it, so bank 7's
    # allocation ends at BP.AB4_HANDLER.
    dst_alloc7=BP.AB4_HANDLER-BANK7_CAVE
    source_packa=bytes(packa)
    packa=bytearray(packa)
    packa,ab_specs,ab_authored=apply_ab_banks(exe,packa,slpm)

    # bank: (buffer, source base, source allocation, destination base, destination allocation)
    S=AB4_EXTRA_SECTORS*2048           # PACKA tail shift from the bank-4 growth
    banks={
        0:("packa",0x32fb000,15*2048,0x32fb000+S,15*2048),
        1:("packa",0x3302800, 2*2048,0x3302800+S, 2*2048),
        2:("packa",0x3303800,16*2048,0x3303800+S,16*2048),
        3:("packa",0x330b800,13*2048,0x330b800+S,13*2048),
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
    # Validate the FINAL exe/PACKA state.  This must run after every bank is
    # written: bank 6 legitimately grows into the stock bank-7 block, so an
    # A/B runtime placed anywhere unsafe would only be clobbered by now.
    verify_ab_banks(exe,packa,ab_specs,ab_authored)
    return packa

# ============================ 5. PATCH OUTPUT ============================
def write_patched_bin(
    input_bin,
    output_bin,
    exe,
    packa,
    slpm,
    packa0,
    cmdinit=None,
    cmdinit0=None,
    rdlogo=None,
    rdlogo0=None,
    movies=None,
    overlay_files=None,
):
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
    if overlay_files is not None:
        for name, (base_sector, patched, original) in overlay_files.items():
            if len(patched) != len(original):
                raise SystemExit(f"{name}: overlay patch changed the file size")
            om = lambda f, sector=base_sector: (
                (sector + f // 2048) * 2352 + 24 + (f % 2048)
            )
            for i in range(len(original)):
                if original[i] != patched[i]:
                    edits.append((om(i), patched[i]))

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
    if movies is not None:
        expected_names = {spec.filename for spec in OM.MOVIES}
        if set(movies) != expected_names:
            raise SystemExit(
                "rebuilt movie set is incomplete: expected "
                + ", ".join(sorted(expected_names))
            )
        for spec in OM.MOVIES:
            payload = movies[spec.filename]
            expected = spec.sectors * OM.USER_DATA_SIZE
            if len(payload) != expected:
                raise SystemExit(
                    f"rebuilt {spec.filename} has invalid size {len(payload):,}; "
                    f"expected {expected:,}"
                )
            # Each movie is a video-only Form 1 stream: one 2048-byte STR
            # chunk per physical sector.  Write it in place and retain the
            # stock sector headers/submode flags so no ISO extent or seek
            # logic changes.
            for rel in range(spec.sectors):
                sec = spec.lba + rel
                src = rel * OM.USER_DATA_SIZE
                dst = sec * 2352 + 24
                bind[dst:dst+OM.USER_DATA_SIZE] = payload[src:src+OM.USER_DATA_SIZE]
                aff.add(sec)
    for sec in aff:
        so=sec*2352; s=bytearray(bind[so:so+2352]); fix_mode2form1(s); bind[so:so+2352]=s
    output_bin = Path(output_bin)
    output_bin.parent.mkdir(parents=True, exist_ok=True)
    output_bin.write_bytes(bind)
    return len(aff)

def require_pyxdelta():
    """Load the optional patch dependency only when --xdelta is requested."""
    try:
        import pyxdelta
    except ModuleNotFoundError as exc:
        if exc.name != "pyxdelta":
            raise
        raise SystemExit(
            "--xdelta requires the optional pyxdelta package. "
            "Install it with: python -m pip install pyxdelta"
        ) from exc
    return pyxdelta

def make_xdelta(pyxdelta, input_bin, output_bin, output_xdelta):
    """Create an optional xdelta patch for an already-built image."""
    # pyxdelta refuses to replace an existing output file.  Builds are
    # reproducible, so discard only the previous generated patch first.
    output_xdelta = Path(output_xdelta)
    if output_xdelta.exists():
        output_xdelta.unlink()
    ok = pyxdelta.run(str(input_bin), str(output_bin), str(output_xdelta))
    if not ok:
        raise SystemExit("pyxdelta failed to create the requested patch")
    return output_xdelta

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


def build_movies(
    input_bin,
    executable,
    widths,
    output_dir,
    *,
    requested_ffmpeg=None,
    requested_psxavenc=None,
    skip=False,
    required=False,
):
    """Best-effort movie translation; return None to keep the source movies.

    With required=True any failure aborts the build instead: release builds
    must never silently ship Japanese movies in the English-movie patch.
    """

    if skip:
        print("[3/7] leaving OPENING.STR and GAMEOVER.STR unchanged (--skip-movies)")
        return None

    print("[3/7] rebuilding English OPENING.STR and GAMEOVER.STR...")
    try:
        local_psxavenc = Path("build/psxavenc/bin") / (
            "psxavenc.exe" if sys.platform == "win32" else "psxavenc"
        )
        psxavenc = OM.find_tool(
            requested_psxavenc, "psxavenc", local_psxavenc, required=False
        )
        if psxavenc is None:
            print(
                f"  psxavenc not found; downloading v{OM.PSXAVENC_VERSION} "
                "from GitHub..."
            )
            downloaded_psxavenc = OM.download_psxavenc(Path("build/psxavenc"))
            psxavenc = str(downloaded_psxavenc.resolve())
            print(f"  installed psxavenc at {downloaded_psxavenc}")

        ffmpeg = OM.find_tool(requested_ffmpeg, "ffmpeg", required=False)
        if ffmpeg is None:
            raise RuntimeError("FFmpeg was not found on PATH or at --ffmpeg")
        movie_paths = OM.generate_movies(
            input_bin,
            executable,
            widths,
            output_dir,
            ffmpeg=ffmpeg,
            psxavenc=psxavenc,
        )
        movies = {}
        for spec in OM.MOVIES:
            payload = movie_paths[spec.filename].read_bytes()
            movies[spec.filename] = payload
            print(
                f"  {spec.filename}: {len(payload) // OM.USER_DATA_SIZE} sectors, "
                f"{spec.frames} frames"
            )
        return movies
    except Exception as exc:
        if required:
            raise SystemExit(
                f"ERROR: the movies could not be translated: {exc}\n"
                "--require-movies forbids falling back to the Japanese movies; "
                "fix FFmpeg/psxavenc availability or drop the flag."
            ) from exc
        print(f"  WARNING: the movies were not translated: {exc}")
        print("  WARNING: continuing with the original Japanese movies.")
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build the SMT2 PSX English translation."
    )
    parser.add_argument(
        "--input", metavar="BIN", help="source Japan Rev 1 MODE2/2352 BIN (default: auto-detect)"
    )
    parser.add_argument(
        "--ffmpeg",
        metavar="EXE",
        help="optional FFmpeg executable used to decode the movies",
    )
    parser.add_argument(
        "--psxavenc",
        metavar="EXE",
        help="optional psxavenc executable used to rebuild the movies",
    )
    movie_mode = parser.add_mutually_exclusive_group()
    movie_mode.add_argument(
        "--skip-movies",
        "--skip-opening",
        dest="skip_movies",
        action="store_true",
        help="leave the Japanese opening and game-over movies unchanged",
    )
    movie_mode.add_argument(
        "--require-movies",
        "--require-opening",
        dest="require_movies",
        action="store_true",
        help="fail the build if both English movies cannot be generated, "
        "instead of falling back to the Japanese movies",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=DEFAULT_OUTPUT_DIR,
        help=f"directory for generated artifacts (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--xdelta",
        action="store_true",
        help="also create SMT2_EN.xdelta (requires the optional pyxdelta package)",
    )
    args = parser.parse_args(argv)
    pyxdelta = require_pyxdelta() if args.xdelta else None
    output_dir = Path(args.output_dir).expanduser()
    if output_dir.exists() and not output_dir.is_dir():
        raise SystemExit(f"Output directory is not a directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_bin = output_dir / OUTPUT_BIN_NAME
    output_xdelta = output_dir / OUTPUT_XDELTA_NAME
    print("[1/7] mining compression dictionaries...")
    dictionary, dictionary_bytes = mine_dictionary(BP.DICT_RUNTIME_BUDGET)
    BP.configure_dictionary(dictionary)
    TP.configure_dictionary(dictionary, BP.DICT_CODE_BASE)
    estimated_nibbles = sum(weight for _text, weight in dictionary)
    print(
        f"  dictionary: {len(dictionary)} entries, "
        f"{dictionary_bytes}/{BP.DICT_RUNTIME_BUDGET} bytes, "
        f"~{estimated_nibbles / 2 / 1024:.1f} KB saved"
    )
    # A/B-local dictionary: mined from the negotiation/battle corpus.  Entries
    # already in the shared dictionary compress through their shared codes.
    ab_candidates, _ab_bytes = mine_dictionary(AB_DICT_BUDGET, ab_corpus_texts())
    cd_strings = {text for text, _weight in dictionary}
    ab_candidates = [e for e in ab_candidates if e[0] not in cd_strings]
    print(f"  A/B dictionary: {len(ab_candidates)} candidate entries")
    input_bin = find_input_bin(args.input)
    if output_bin.resolve() == input_bin.resolve():
        raise SystemExit(f"Refusing to overwrite the source BIN: {input_bin}")
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
    overlay_files = {}
    for name, (base_sector, size, patcher) in OVERLAY_FILES.items():
        original = extract_from_bin(bind, base_sector, size)
        overlay_files[name] = (base_sector, patcher(original), original)
    print("[2/7] kerning font...")
    font_slpm, widths, widths10 = kern_font(slpm)
    _validate_spell_description_widths(widths)
    movies = build_movies(
        input_bin,
        font_slpm,
        widths,
        output_dir,
        requested_ffmpeg=args.ffmpeg,
        requested_psxavenc=args.psxavenc,
        skip=args.skip_movies,
        required=args.require_movies,
    )
    print("[4/7] building exe (VWF hook + dictionary-compressed C/D tree)...")
    exe = build_exe(font_slpm, widths, widths10, slpm)
    PATHS = BR.build_paths(0x80117ec4, 0x801187a4, exe)
    # The C/D tree extent is now known, so the A/B-local dictionary can be
    # trimmed to the dead space that actually exists in this build and the
    # A/B tokenizer configured before apply_banks authors bank 4/5.
    ab_shared = select_ab_dictionary(dictionary)
    TP.configure_ab_dictionary(ab_shared)
    ab_base_leaves = ab_base_leaf_count(packa0, slpm)
    ab_local = BP.fit_ab_local_dictionary(ab_candidates, ab_base_leaves)
    BP.configure_ab_local_dictionary(ab_local)
    TP.configure_ab_dictionary(
        ab_shared, ab_local, BP.DICT_CODE_BASE + len(dictionary)
    )
    ab_string_bytes = sum(2 * len(text) + 1 for text, _weight in ab_local)
    print(
        f"  A/B dictionary: {len(ab_local)} entries fit "
        f"({ab_string_bytes} string bytes in dead exe space, "
        f"{ab_base_leaves} measured base leaves)"
    )
    print("[5/7] applying name tables")
    apply_name_tables(exe, slpm, PATHS, widths10)
    cmdinit = bytearray(cmdinit0)
    apply_cmdinit_names(cmdinit)             # REAL new-game party names (CMDINIT.BIN)
    MN.relocate_map_names(exe)               # field/location names (save list) -> English, relocated
                                             # to the rodata cave + both pointer tables repointed
    rdlogo = RD.patch_rdlogo(rdlogo0)        # boot disclaimer -> English (fullwidth, repointed)
    MT.rebuild_menu(exe, PATHS)
    SS.apply_sys(exe)                        # boot-safe system strings, kept in their original slots
    SS.patch_shop_composed_prompts(exe)      # English item/price confirmation grammar
    SS.patch_composed_prompts(exe)           # one-line "Dismiss <name>?" / "Discard <item>?" confirms
    NE.apply_name_entry(exe)                 # naming-screen kana grid -> A-Z/a-z/0-9 + specials
    NE.apply_end_button(exe)                 # END button on the Z/z row; no empty-row scrolling
    print("[6/7] applying dialogue + menu banks...")
    packa = apply_banks(exe, packa0, slpm, PATHS)
    STATUS.patch_status_texture(packa, exe)
    NE.patch_atlas(packa, slpm)              # naming-grid atlas texture -> English glyphs
    print("[7/7] writing patched BIN...")
    sectors = write_patched_bin(
        input_bin,
        output_bin,
        exe,
        packa,
        slpm,
        packa0,
        cmdinit,
        cmdinit0,
        rdlogo,
        rdlogo0,
        movies,
        overlay_files,
    )
    print(f"DONE. {output_bin}, {sectors} patched sectors, {output_bin.stat().st_size} bytes")
    if pyxdelta is not None:
        print("Generating optional xdelta patch...")
        make_xdelta(pyxdelta, input_bin, output_bin, output_xdelta)
        print(f"       {output_xdelta}, {output_xdelta.stat().st_size} bytes")
    elif output_xdelta.exists():
        print(f"NOTE: existing {output_xdelta} was not updated; use --xdelta to regenerate it.")

if __name__ == "__main__":
    main()
