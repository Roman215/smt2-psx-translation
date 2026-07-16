#!/usr/bin/env python3
"""SMT2 English translation — master build. Regenerates the xdelta patch from scratch.

Run from the project root:  python build.py
Outputs:  build/SMT2_EN.bin  and  SMT2_EN.xdelta

Pipeline: kern font -> build exe (VWF hook + width table + English C/D tree) ->
translate ALL name tables (demons/races/spells/items/locations/NPCs/traits/drinks) ->
translate menu table -> translate dialogue banks -> patch bin (EDC/ECC) -> xdelta.

All translation DATA lives in tools/: name_tables.py, translations.py, menu_table.py.
Add/extend translations there, then re-run this script.
"""
import argparse
import os, sys, struct, json
from pathlib import Path
sys.path.insert(0, "tools")
import build_en_tree as ET, block_rebuild as BR, build_prod_exe as BP, translate_pipeline as TP
import name_tables as NT, translations as TR, menu_table as MT, sys_strings as SS
import rdlogo as RD, map_names as MN
from cdecc import fix_mode2form1
import pyxdelta

CMDINIT_SECTOR = 67152                        # CMDINIT.BIN base sector in the bin
RDLOGO_SECTOR = 67181                         # RDLOGO.BIN base sector in the bin
DEFAULT_BIN_NAME = "Shin Megami Tensei II (Japan) (Rev 1).bin"
EXPECTED_BIN_SIZE = 222_694_416
OUT_BIN = "build/SMT2_EN.bin"
OUT_XDELTA = "build/SMT2_EN.xdelta"

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
    PUNCT = [0x8149,0x8148,0x8144,0x8143,0x8146,0x8147,0x8151,0x815e,0x8166,0x8165,0x8168,
             0x8167,0x815d,0x8169,0x816a,0x8163,0x8160,0x8192,0x817b,0x8195,0x8193]
    for c in PUNCT: widths[sidx(c)] = kern(sidx(c))
    widths[0] = 4  # space
    return bytes(exe), widths

# ============================ 2. BUILD EXE ============================
def build_exe(font_slpm, widths, slpm):
    """VWF advance hook + width table + English-only C/D tree. Returns exe bytearray."""
    exe = bytearray(font_slpm)
    def w32(a, v): struct.pack_into("<I", exe, foff(a), v)
    CAVE, WTABLE, BACK = 0x800d7254, 0x800d7300, 0x80048b88
    R = {'zero':0,'v1':3,'a0':4,'a2':6,'t6':14,'t7':15,'t8':24,'t9':25,'sp':29}
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
    BP.build_english_tree(exe, slpm)   # English C/D tree at 0x80117ec4 / 0x801187a4
    # NOTE: names are English, so the name decoder (0x80056e84 -> 0x80057fe4) uses the English
    # tree directly. No private Japanese-tree decoder is installed (that was for Japanese names).
    # --- System-message half-width layer DISABLED (2026-07-10) ---
    # The raw-SJIS system strings (memcard/config overlays) render glitchy under the ASCII-aware
    # printer (pixel/VRAM composition issues we can't crack without live debugging). Shelved for
    # now so system text reverts to original Japanese; dialogue/menus/names use a separate path
    # and are unaffected. Re-enable these two + SS.apply_sys() in main() to resume the work.
    # _install_sys_printer(exe, w32)   # ASCII-aware halfwidth printer for raw-SJIS system strings
    # _apply_lowercase_font(exe)       # add lowercase a-z to the 8x10 halfwidth font (0x800e8078)
    return exe

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

# ---- ASCII-aware system-string printer -------------------------------------------------
# The raw-SJIS system strings (memcard/save/config overlays) are drawn by string printer
# 0x800482a4, which advances the string pointer by 2 bytes/char (fullwidth only) and draws
# via blit 0x80048048. Everything (font, metrics, pen-advance) derives from *context (the
# font descriptor). We replace the printer with a version that, per char, points the context
# at a HALFWIDTH descriptor for ASCII bytes (<0x80) + advances the string by 1; fullwidth
# SJIS bytes keep the original descriptor + advance 2 (so Japanese text is unaffected). Cave
# lives in the rodata font-placeholder run (0x800d7500+, after the VWF hook+width table).
def _install_sys_printer(exe, w32):
    # ASCII-aware printer (per-char): for each char, point *ctx at a halfwidth desc for ASCII
    # bytes (else keep the caller's desc), draw, advance +1 (ascii) / +2 (fullwidth); restore
    # the original desc at the end. This is the exact version confirmed to BOOT and render the
    # memcard/config overlays in halfwidth. (KNOWN ISSUE: the RDLOGO boot disclaimer, which also
    # uses this printer, renders garbled -- to be fixed by translating it to English later.)
    PR, DESC, BLIT = 0x800d7500, 0x800d75c0, 0x80048048
    # custom halfwidth descriptor: w8 h10, xsp0, font 0x800e8078 (8x10 w/ our lowercase), sel=1
    struct.pack_into("<IIIII", exe, foff(DESC), 0x000a0008, 0, 0, 0x800e8078, 1)
    ZERO,V0,T0,T1,A0,A1,S0,S1,S2,SP,RA = 0,2,8,9,4,5,16,17,18,29,31
    def RI(op,rs,rt,imm): return ((op&0x3f)<<26)|((rs&0x1f)<<21)|((rt&0x1f)<<16)|(imm&0xffff)
    def SP_(rs,rt,rd,fn): return ((rs&0x1f)<<21)|((rt&0x1f)<<16)|((rd&0x1f)<<11)|(fn&0x3f)
    ADDIU=lambda rt,rs,i:RI(0x09,rs,rt,i); LBU=lambda rt,o,rs:RI(0x24,rs,rt,o)
    LW=lambda rt,o,rs:RI(0x23,rs,rt,o);    SW=lambda rt,o,rs:RI(0x2b,rs,rt,o)
    SLTIU=lambda rt,rs,i:RI(0x0b,rs,rt,i); BEQ=lambda rs,rt,off:RI(0x04,rs,rt,off)
    LUI=lambda rt,i:RI(0x0f,0,rt,i);       MOVE=lambda rd,rs:SP_(rs,0,rd,0x25)
    JAL=lambda t:(0x03<<26)|((t>>2)&0x03ffffff); JR=lambda rs:SP_(rs,0,0,0x08)
    J=lambda t:(0x02<<26)|((t>>2)&0x03ffffff); NOP=0
    dlo, dhi = DESC & 0xffff, (DESC>>16)+(1 if DESC & 0x8000 else 0)
    prog = [
        ADDIU(SP,SP,-0x20), SW(RA,0x18,SP), SW(S0,0x10,SP), SW(S1,0x14,SP), SW(S2,0x1c,SP),
        MOVE(S1,A0), MOVE(S0,A1), LW(S2,0,S1),          # s1=ctx s0=str s2=orig desc
        # loop @8
        LBU(V0,0,S0), BEQ(V0,ZERO,19), SLTIU(T1,V0,0x80),   # if 0 -> end@29 ; t1=ascii?
        MOVE(T0,S2), BEQ(T1,ZERO,3), NOP,                   # t0=orig; if !ascii -> sf@16
        LUI(T0,dhi), ADDIU(T0,T0,dlo),                      # t0=halfwidth desc
        # sf @16
        SW(T0,0,S1), MOVE(A0,S1), MOVE(A1,S0), JAL(BLIT), NOP,   # *ctx=font; draw glyph
        LBU(V0,0,S0), SLTIU(T1,V0,0x80), ADDIU(S0,S0,2),        # advance str: +2, then
        BEQ(T1,ZERO,-17), NOP, ADDIU(S0,S0,-1),                # if ascii -1 (net +1); loop@8
        BEQ(ZERO,ZERO,-20), NOP,
        # end @29
        SW(S2,0,S1), LW(RA,0x18,SP), LW(S0,0x10,SP), LW(S1,0x14,SP), LW(S2,0x1c,SP),
        JR(RA), ADDIU(SP,SP,0x20),
    ]
    for i,wd in enumerate(prog): w32(PR+i*4, wd)
    w32(0x800482a4, J(PR)); w32(0x800482a8, NOP)      # redirect printer entry to cave

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
    """Rebuild C/D dialogue banks with TR.TRANS (translated) + placeholders. Returns modified packa."""
    ED=(0x4544,True)
    def U16(a): return struct.unpack_from("<H", exe, foff(a))[0]
    alloc6=0x80116f2c-0x80115bd8; alloc7=0x80117cc8-0x80116f2c
    banks={0:("packa",0x32fb000,15*2048),1:("packa",0x3302800,2*2048),2:("packa",0x3303800,16*2048),
           3:("packa",0x330b800,13*2048),6:("exe",0x80115bd8,alloc6),7:("exe",0x80116f2c,alloc7)}
    def build_block(msgs,N):
        offs=[]; data=bytearray()
        for m in msgs:
            cur=[]
            for t in m: cur+=PATHS[t]
            offs.append(len(data)); b=0; hi=True
            for n in cur:
                if hi: b=(n&0xf)<<4; hi=False
                else: data.append(b|(n&0xf)); hi=True
            if not hi: data.append(b)
        do=2+2*N; out=bytearray(struct.pack("<H",do)); out+=struct.pack("<%dH"%N,*offs); out+=data
        return bytes(out)
    packa=bytearray(packa)
    for bank,(buf,base,alloc) in banks.items():
        fo=base if buf=="packa" else foff(base)
        src=packa if buf=="packa" else slpm
        msgs,N=BR.decode_all(src[fo:fo+alloc],0x80117ec4,0x801187a4,slpm)
        out=[]
        for i in range(N):
            mid=(bank<<12)|i
            if mid in TR.TRANS: out.append(TP.author_to_tokens(TR.TRANS[mid]))
            else:
                ph=TP.placeholder(msgs[i]); ph=ph+[ED] if (not ph or ph[-1]!=ED) else ph; out.append(ph)
        blk=build_block(out,N)
        if len(blk)>alloc: raise SystemExit(f"bank{bank} OVERFLOW {len(blk)}>{alloc}")
        if buf=="packa": packa[base:base+len(blk)]=blk
        else: exe[foff(base):foff(base)+len(blk)]=blk
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
    for i in range(len(packa0)):
        if packa0[i]!=packa[i]: edits.append((pm(i),packa[i]))
    if cmdinit is not None:
        for i in range(len(cmdinit0)):
            if cmdinit0[i]!=cmdinit[i]: edits.append((cm(i),cmdinit[i]))
    if rdlogo is not None:
        for i in range(len(rdlogo0)):
            if rdlogo0[i]!=rdlogo[i]: edits.append((rm(i),rdlogo[i]))
    aff=set()
    for bo,v in edits: bind[bo]=v; aff.add(bo//2352)
    for sec in aff:
        so=sec*2352; s=bytearray(bind[so:so+2352]); fix_mode2form1(s); bind[so:so+2352]=s
    os.makedirs("build", exist_ok=True)
    open(OUT_BIN,"wb").write(bytes(bind))
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
    print("[1/5] kerning font...")
    font_slpm, widths = kern_font(slpm)
    print("[2/5] building exe (VWF hook + English tree)...")
    exe = build_exe(font_slpm, widths, slpm)
    PATHS = BR.build_paths(0x80117ec4, 0x801187a4, exe)
    print("[3/5] applying name tables")
    apply_name_tables(exe, slpm, PATHS)
    cmdinit = bytearray(cmdinit0)
    apply_cmdinit_names(cmdinit)             # REAL new-game party names (CMDINIT.BIN)
    SS.apply_sys(exe)                        # memcard/save/load system strings (FULLWIDTH SJIS Latin,
                                             # stock printer -- no hook; see sys_strings.py)
    MN.relocate_map_names(exe)               # field/location names (save list) -> English, relocated
                                             # to the rodata cave + both pointer tables repointed
    rdlogo = RD.patch_rdlogo(rdlogo0)        # boot disclaimer -> English (fullwidth, repointed)
    MT.rebuild_menu(exe, PATHS)
    print("[4/5] applying dialogue + menu banks...")
    packa = apply_banks(exe, packa0, slpm, PATHS)
    print("[5/5] patching bin + xdelta...")
    ok, sectors = make_patch(input_bin, exe, packa, slpm, packa0, cmdinit, cmdinit0, rdlogo, rdlogo0)
    print(f"DONE. {OUT_XDELTA} ok={ok}, {sectors} sectors, {os.path.getsize(OUT_XDELTA)} bytes")

if __name__ == "__main__":
    main()
