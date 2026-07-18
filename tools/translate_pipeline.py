"""SMT2 translation token helpers. C/D dialogue uses named two-byte controls and
the mined English dictionary; A/B battle fragments use named dispatcher indices
and plain character tokens. build.py owns block decoding, packing, and allocation
checks.

Translated messages are authored as lists mixing text strings and control names:
  TRANS[msgid] = ["Okamoto: Hi", 'CR', "Hawk!", 'WT','PG', ...JP-insert names..., 'ED']
Control names: CR WT PG ED SY SN Fe TI IT FI FO NI AG SU MN KO OT ZK ZO MG MH PP AL SE
Insert codes (SY/SN/Fe/...) must be kept where they were in the original.
"""
import struct, sys
sys.path.insert(0, "tools")
import build_en_tree as ET, block_rebuild as BR, build_prod_exe as BP

CTRL_NAME={n:(struct.unpack(">H",n.encode("ascii"))[0],True) for n in
  "CR WT PG ED SY SN Fe TI IT FI FO NI AG SU MN KO OT ZK ZO MG MH PP AL SE TW".split()}

# Banks 4/5 use the older A/B tree. Its dynamic inserts and layout operations
# all decode to the same nominal 0x8140 symbol, but the control-dispatch index
# in the tree leaf distinguishes their runtime behavior. Keep those indices
# explicit rather than flattening them into ordinary spaces.
AB_CTRL_INDEX={f"A{i:02X}":i for i in
  (0x0E,0x0F,0x14,0x61,0x63,0x65,0x66,0x67,0x68,0x6B,0x6E)}

# Dictionary matching configured by build.py after mining the current corpus.
# Matching is case-sensitive and greedy-longest: buckets are per first char,
# longest first. Only dialogue goes through text_tokens; name/menu tables build
# their character tokens directly.
_DCODE={}
_DBYFIRST={}

def configure_dictionary(entries, code_base):
    _DCODE.clear(); _DBYFIRST.clear()
    _DCODE.update({s:code_base+i for i,(s,_weight) in enumerate(entries)})
    for s in sorted(_DCODE, key=len, reverse=True):
        _DBYFIRST.setdefault(s[0], []).append(s)

def text_tokens(s):
    out=[]; i=0
    while i<len(s):
        for cand in _DBYFIRST.get(s[i],()):
            if s.startswith(cand,i):
                out.append((_DCODE[cand],True)); i+=len(cand); break
        else:
            try: out.append((ET.fullwidth(s[i]),False))
            except KeyError: out.append((ET.fullwidth(' '),False))
            i+=1
    return out

def author_to_tokens(author):
    toks=[]
    for part in author:
        if isinstance(part,tuple): toks.append(part)               # raw token
        elif part in CTRL_NAME:   toks.append(CTRL_NAME[part])     # control name
        else:                     toks+=text_tokens(part)          # text
    return toks

def ab_author_to_tokens(author):
    """Convert an A/B-bank author list without using the C/D dictionary."""
    toks=[]
    for part in author:
        if isinstance(part,tuple):
            toks.append(part)
        elif part in AB_CTRL_INDEX:
            toks.append((0x8140,True,AB_CTRL_INDEX[part]))
        else:
            toks.extend((ET.fullwidth(ch),False) for ch in part)
    return toks

def placeholder(orig_tokens):
    """Keep only control/insert tokens (drop Japanese text) so flow is preserved."""
    return [t for t in orig_tokens if t[1]]

# ---- C/D bank locations (bank -> (buffer_name, STOCK base, alloc_bytes)) ----
# PACKA banks 0-3 ; exe banks 6,7. Allocations: PACKA from file table; exe from layout.
#
# UNUSED -- build.py owns the live bank table; this records the STOCK layout only.
# Do NOT size an exe bank as "next known symbol - base": bank 7's block ends at exactly
# 0x801171d8, where a live bitmask table begins, so the apparent gap up to the file-ID
# table at 0x80117cc8 is NOT free.  build.py relocates bank 7 into the rodata cave and
# documents the real boundaries; see BANK6_LIMIT / BANK7_CAVE there.
CD_BANKS = {
 0:("packa",0x32fb000,15*2048), 1:("packa",0x3302800,2*2048),
 2:("packa",0x3303800,16*2048), 3:("packa",0x330b800,13*2048),
 6:("exe",0x80115bd8,4948), 7:("exe",0x80116f2c,684),
}
