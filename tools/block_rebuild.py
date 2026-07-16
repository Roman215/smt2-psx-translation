"""SMT2 dialogue block rebuilder — repack a block with a new offset table so
messages can change size. Block layout: [u16 data_off][u16 offs[N]][streams].
Decoder self-terminates at [ED] and uses offs only for START positions, so we
may freely re-lay-out the block; only constraint is total size <= allocation.

Usage: rebuild_block(block_bytes, {msg_index: [tokens...]}, STRUCT, SYM, exe)
Tokens are (sym, ctrl_bool) as produced by the decoder helpers.
"""
import struct

def _mk(exe):
    def U16(a): return struct.unpack_from("<H", exe, (a-0x80010000)+0x800)[0]
    return U16

def build_paths(STRUCT, SYM, exe):
    U16=_mk(exe); PATHS={}
    def dfs(node,acc,d):
        if d>40: return
        for nib in range(16):
            ea=(node&0xFFFE)+nib*2; nx=U16(STRUCT+ea)
            if nx==0x7fff: continue
            if nx&0x8000: PATHS.setdefault((U16(SYM+ea),bool(nx&0x4000)),acc+[nib])
            elif nx!=node: dfs(nx,acc+[nib],d+1)
    dfs(0,[],0)
    return PATHS

def decode_all(block, STRUCT, SYM, exe):
    """Decode every message in the block. Returns list of token-lists (each ends with ED)."""
    U16=_mk(exe)
    do=struct.unpack_from("<H",block,0)[0]; N=(do-2)//2
    offs=list(struct.unpack_from("<%dH"%N,block,2))
    ED=(0x4544,True)
    msgs=[]
    for i in range(N):
        pos=do+offs[i]; hi=True; toks=[]
        for _ in range(4000):
            node=0
            while True:
                b=block[pos]; nib=(b>>4) if hi else (b&0xf); hi=not hi
                if hi: pos+=1
                ea=(node&0xFFFE)+nib*2; nx=U16(STRUCT+ea)
                if nx==0x7fff: toks.append(None); break
                if nx&0x8000: toks.append((U16(SYM+ea),bool(nx&0x4000))); break
                node=nx
            if toks[-1]==ED or toks[-1] is None: break
        msgs.append([t for t in toks if t is not None])
    return msgs, N

def rebuild_block(block, replacements, STRUCT, SYM, exe, PATHS=None):
    """Return new block bytes with replacements applied (msg_index -> token list)."""
    if PATHS is None: PATHS=build_paths(STRUCT,SYM,exe)
    msgs,N=decode_all(block,STRUCT,SYM,exe)
    for idx,toks in replacements.items(): msgs[idx]=toks
    ED=(0x4544,True)
    new_offs=[]; data=bytearray(); cur=[]  # cur = pending nibble accumulator
    def flush_bytes():
        # pack cur nibbles (hi-first) into data, byte-aligned
        pos_hi=True; b=0
        for n in cur:
            if pos_hi: b=(n&0xf)<<4; pos_hi=False
            else: data.append(b|(n&0xf)); b=0; pos_hi=True
        if not pos_hi: data.append(b)  # trailing pad nibble
        cur.clear()
    for m in msgs:
        if not m or m[-1]!=ED: m=m+[ED]  # guarantee terminator
        new_offs.append(len(data))
        for t in m:
            if t not in PATHS: raise KeyError(f"no path for token {t} ({t[0]:#06x})")
            cur.extend(PATHS[t])
        flush_bytes()  # each message byte-aligned
    do=2+2*N
    out=bytearray(struct.pack("<H",do))
    out+=struct.pack("<%dH"%N,*new_offs)
    out+=data
    return bytes(out)
