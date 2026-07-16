"""SMT2 translation pipeline. Decodes all C/D banks with the original Japanese
tree, applies English translations (control codes preserved), placeholders the
untranslated remainder (controls only), re-encodes with the English tree, rebuilds
every C/D block, verifies each fits its allocation, and emits a bin xdelta patch.

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

def text_tokens(s):
    out=[]
    for ch in s:
        try: out.append((ET.fullwidth(ch),False))
        except KeyError: out.append((ET.fullwidth(' '),False))
    return out

def author_to_tokens(author):
    toks=[]
    for part in author:
        if isinstance(part,tuple): toks.append(part)               # raw token
        elif part in CTRL_NAME:   toks.append(CTRL_NAME[part])     # control name
        else:                     toks+=text_tokens(part)          # text
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
