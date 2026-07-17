"""Production exe: kerned font, VWF hook, and dictionary-compressed C/D tree.

A/B (banks 4 and 5) remains untouched so Japanese negotiation still decodes.
Each mined dictionary entry is a control-flagged Huffman leaf (struct=0xC000|6,
symbol=0x8540+i). The slot-6 stub calls an expansion handler, which looks up the
full string and tail-jumps the stock append routine used by name inserts."""
import struct
import build_en_tree as ET

STRUCT=0x80117ec4; SYM=0x801187a4; STCAP=SYM-STRUCT

# ---- Dictionary runtime layout ----------------------------------------------------
# Lives in the tail of the rodata font-placeholder cave, AFTER bank 7's relocated
# block (build.py caps bank 7 at DICT_BASE). The freed JP
# map-name block at 0x80016124 was considered and rejected: it contains live
# sub-structures (a pointer table at 0x8001628c and 18 code reads of 0x800162c8).
DICT_WEIGHT_MULT = 1.5                 # dict-vs-char Huffman weight balance
NAME_CORPUS_WEIGHT = 8                 # extra weight for name/menu-table chars (char-only consumers)
DICT_CODE_BASE = 0x8540
DICT_JT_INDEX = 6
DICT_BASE  = 0x800d8880                # bank 7's allocation ends here
DICT_HANDLER = DICT_BASE               # handler code, padded to 0x40
DICT_PTRS = DICT_BASE + 0x40           # expansion-string pointer table
CAVE_END  = 0x800d9144
DICT_RUNTIME_BUDGET = CAVE_END-DICT_PTRS
JT        = 0x800132b4                 # 205-entry control dispatch jump table
STUBS     = 0x80058358                 # 16-byte dispatch stubs (slot i = STUBS+i*0x10)
APPEND    = 0x80058244                 # stock append: a0 = null-terminated SJIS
EPILOGUE  = 0x80059044                 # stock dispatch epilogue
DECODED_SYM = 0x801d15de               # decoder's just-decoded symbol global
STOCK6    = 0x80059ce4                 # stock slot-6 handler = event-script choice-menu op

_DICT_ENTRIES = []
_DICT_CODE_MAP = {}

def configure_dictionary(entries):
    """Install the one build-wide mined entry list without writing generated files."""
    global _DICT_ENTRIES, _DICT_CODE_MAP
    entries = list(entries)
    strings = [s for s,_weight in entries]
    if len(strings) != len(set(strings)):
        raise ValueError("dictionary entries must be unique")
    runtime_bytes = sum(4 + 2*len(s) + 1 for s in strings)
    if runtime_bytes > DICT_RUNTIME_BUDGET:
        raise ValueError(
            f"dictionary runtime overflow: {runtime_bytes}>{DICT_RUNTIME_BUDGET}"
        )
    _DICT_ENTRIES = entries
    _DICT_CODE_MAP = {s:DICT_CODE_BASE+i for i,s in enumerate(strings)}

def _foff(a): return (a-0x80010000)+0x800

def control_index_map(slpm):
    def oU16(a): return struct.unpack_from("<H",slpm,_foff(a))[0]
    cidx={}
    def dfs(n,d):
        if d>40: return
        for nib in range(16):
            ea=(n&0xFFFE)+nib*2; nx=oU16(STRUCT+ea)
            if nx==0x7fff: continue
            if nx&0x8000:
                if nx&0x4000: cidx.setdefault(oU16(SYM+ea),nx&0x3fff)
            elif nx!=n: dfs(nx,d+1)
    dfs(0,0)
    return cidx

def _corpus_freqs(cidx):
    """Huffman weights measured from the dictionary-tokenized corpus.

    Chars and dict tokens are counted by tokenizing every authored translation;
    the name/menu tables (char-only consumers with tight per-table byte budgets)
    contribute their chars at NAME_CORPUS_WEIGHT so capitals and other name-heavy
    chars keep short codes. ET.build_freqs supplies a small floor so the full
    char repertoire always has a leaf.
    """
    from collections import Counter
    import translations as TR, translate_pipeline as TP
    import name_tables as NT, menu_table as MT
    chars=Counter(); dicts=Counter(); ctrls=Counter()
    for author in TR.TRANS.values():
        for part in author:
            if isinstance(part,tuple): ctrls[part[0]]+=1          # raw token
            elif part in TP.CTRL_NAME: ctrls[TP.CTRL_NAME[part][0]]+=1
            else:
                for sym,is_ctl in TP.text_tokens(part):
                    (dicts if is_ctl else chars)[sym]+=1
    K=NAME_CORPUS_WEIGHT
    name_texts=list(NT.DEMONS)+list(NT.RACES)+list(NT.NPCS)+list(NT.LOCATIONS) \
        +list(NT.DRINKS)+list(NT.SPELLS)+list(NT.ITEMS) \
        +list(NT.TRAITS_MAP.values())+[s for s in MT.MENU.values() if s]
    for s in name_texts:
        if not s: continue
        for ch in s:
            try: chars[ET.fullwidth(ch)]+=K
            except KeyError: pass
    freqs={}
    base=ET.build_freqs(150000)
    total=sum(chars.values()) or 1
    for k,v in base.items():
        if isinstance(k,int):
            freqs[k]=0.5+v*total/150000.0*0.02        # repertoire floor
    for sym,n in chars.items(): freqs[sym]=freqs.get(sym,0.5)+n
    for code in cidx:                                  # controls: ('C',code)
        freqs[('C',code)]=ET.CONTROLS.get(code,1)+ctrls.get(code,0)
    for s,_weight in _DICT_ENTRIES:                    # dict: ('D',code)
        code=_DICT_CODE_MAP[s]
        freqs[('D',code)]=max(dicts.get(code,0)*DICT_WEIGHT_MULT,0.1)
    return freqs

def build_english_tree(exe, slpm):
    """Lay out the dictionary-compressed English-only C/D tree."""
    import heapq
    from collections import deque
    def w16(a,v): struct.pack_into("<H",exe,_foff(a),v)
    if not _DICT_ENTRIES:
        raise RuntimeError("compression dictionary was not configured")
    cidx=control_index_map(slpm)
    if DICT_JT_INDEX in cidx.values():
        raise SystemExit(f"jump-table index {DICT_JT_INDEX} is not free after all")
    freqs=_corpus_freqs(cidx)
    # d-ary huffman
    items=list(freqs.items()); L=len(items); pad=(-(L-1))%15
    heap=[]; tree={}; nid=0
    for s,fr in items: tree[nid]=('leaf',s); heapq.heappush(heap,(fr,nid)); nid+=1
    for _ in range(pad): tree[nid]=('leaf',None); heapq.heappush(heap,(0.0,nid)); nid+=1
    while len(heap)>1:
        ks=[heapq.heappop(heap) for _ in range(min(16,len(heap)))]
        tree[nid]=('node',[k[1] for k in ks]); heapq.heappush(heap,(sum(k[0] for k in ks),nid)); nid+=1
    root=heap[0][1]
    codes={}
    def walk(i,acc):
        t=tree[i]
        if t[0]=='leaf':
            if t[1] is not None: codes[t[1]]=acc
            return
        for k,c in enumerate(t[1]): walk(c,acc+[k])
    walk(root,[])
    for i in range(0,STCAP,2): w16(STRUCT+i,0x7fff); w16(SYM+i,0)
    off={}; nxt=0; q=deque([root])
    while q:
        i=q.popleft()
        if tree[i][0]!='node' or i in off: continue
        off[i]=nxt; nxt+=32
        for c in tree[i][1]:
            if tree[c][0]=='node': q.append(c)
    assert nxt<=STCAP, f"tree overflow {nxt}>{STCAP}"
    def entry(sym):
        if isinstance(sym,tuple):
            if sym[0]=='C':  # control
                return (0xC000|cidx[sym[1]], sym[1])
            return (0xC000|DICT_JT_INDEX, sym[1])  # ('D', dict code)
        return (0x8000, sym)
    for i,base in off.items():
        for nib in range(16):
            ea=base+nib*2
            if nib<len(tree[i][1]):
                c=tree[i][1][nib]; t=tree[c]
                if t[0]=='leaf':
                    st,sy=(0x7fff,0) if t[1] is None else entry(t[1])
                else: st,sy=off[c],0
            else: st,sy=0x7fff,0
            w16(STRUCT+ea,st); w16(SYM+ea,sy)
    _install_dictionary_runtime(exe)
    return codes, cidx

def _install_dictionary_runtime(exe):
    """Write the dict handler, pointer table, expansion strings, and stub 6."""
    def w32(a,v): struct.pack_into("<I",exe,_foff(a),v)
    entries=_DICT_ENTRIES
    # Expansion strings (fullwidth SJIS, single-0 terminated) + pointer table.
    strs_base=DICT_PTRS+4*len(entries)
    ptrs=[]; blob=bytearray()
    for s,_w in entries:
        ptrs.append(strs_base+len(blob))
        for ch in s: blob+=ET.fullwidth(ch).to_bytes(2,"big")
        blob.append(0)
    end=strs_base+len(blob)
    if end>CAVE_END:
        raise SystemExit(f"dictionary strings overflow cave: {end:#x} > {CAVE_END:#x}")
    for i,p in enumerate(ptrs): w32(DICT_PTRS+i*4,p)
    exe[_foff(strs_base):_foff(strs_base)+len(blob)]=blob
    # Handler.  CRITICAL: jump-table slot 6 is NOT free at runtime -- it is the
    # event-script CHOICE-MENU op.  The interpreter's synthetic dispatcher
    # (0x80057634: lbu from the script cursor *0x801d15e0 -> sh 0x801d15dc ->
    # jal 0x800582f0) feeds raw script bytes into the same jump table, and the
    # first YES/NO choice dispatches index 6 with 0x801d15de still holding the
    # ED symbol (proven live: choice save state has 15dc=6, 15de=0x4544).  So
    # the handler must range-check the symbol: dict codes take the append path,
    # anything else falls through to the stock slot-6 handler unchanged.
    #   a0 = DICT_PTRS[decoded_sym - 0x8540]; tail-jump the stock append.
    # ori fills the R3000 lhu load-delay slot before v1 is consumed, and
    # subtracting DICT_CODE_BASE first keeps every immediate in range.
    ZERO,V0,V1,A0,T0,T1,T2=0,2,3,4,8,9,10
    RI=lambda op,rs,rt,imm:((op&0x3f)<<26)|((rs&0x1f)<<21)|((rt&0x1f)<<16)|(imm&0xffff)
    LUI=lambda rt,i:RI(0x0f,0,rt,i); LHU=lambda rt,o,rs:RI(0x25,rs,rt,o)
    LW=lambda rt,o,rs:RI(0x23,rs,rt,o); ADDIU=lambda rt,rs,i:RI(0x09,rs,rt,i)
    ORI=lambda rt,rs,i:RI(0x0d,rs,rt,i); SLTIU=lambda rt,rs,i:RI(0x0b,rs,rt,i)
    BEQ=lambda rs,rt,off:RI(0x04,rs,rt,off)
    SLL=lambda rd,rt,sa:((rt&0x1f)<<16)|((rd&0x1f)<<11)|((sa&0x1f)<<6)
    ADDU=lambda rd,rs,rt:((rs&0x1f)<<21)|((rt&0x1f)<<16)|((rd&0x1f)<<11)|0x21
    SUBU=lambda rd,rs,rt:((rs&0x1f)<<21)|((rt&0x1f)<<16)|((rd&0x1f)<<11)|0x23
    J=lambda t:(0x02<<26)|((t>>2)&0x03ffffff); JAL=lambda t:(0x03<<26)|((t>>2)&0x03ffffff)
    NOP=0
    lo=lambda x:x&0xffff; hi=lambda x:((x>>16)+(1 if x&0x8000 else 0))&0xffff
    L_STOCK=13                       # index of the fallthrough branch target
    handler=[
        LUI(V0,(DECODED_SYM>>16)&0xffff),
        LHU(V1,DECODED_SYM&0xffff,V0),           # v1 = decoded symbol
        ORI(T0,ZERO,DICT_CODE_BASE),             # load-delay filler
        SUBU(T1,V1,T0),                          # t1 = sym - 0x8540
        SLTIU(T2,T1,len(entries)),               # dict code?
        BEQ(T2,ZERO,L_STOCK-6),                  # no -> stock choice-menu op
        SLL(V1,T1,2),                            # (delay slot)
        LUI(V0,hi(DICT_PTRS)),
        ADDIU(V0,V0,lo(DICT_PTRS)),
        ADDU(V0,V0,V1),
        LW(A0,0,V0),
        J(APPEND),
        NOP,
        J(STOCK6),                               # L_STOCK: ra still = stub+8
        NOP,
    ]
    assert DICT_HANDLER+len(handler)*4<=DICT_PTRS
    for i,wd in enumerate(handler): w32(DICT_HANDLER+i*4,wd)
    # Repurpose the (tree-unreferenced) dispatch stub 6.
    stub=STUBS+DICT_JT_INDEX*0x10
    w32(stub+0,JAL(DICT_HANDLER)); w32(stub+4,NOP); w32(stub+8,J(EPILOGUE)); w32(stub+12,NOP)
    w32(JT+DICT_JT_INDEX*4,stub)   # already points here in the stock exe; keep explicit
