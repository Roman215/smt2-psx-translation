"""Production exe: kerned font plus rebuilt C/D and A/B text trees.

The C/D tree uses the mined English dictionary. The A/B tree is rebuilt from
authored English negotiation and battle-command fragments. Unfinished bank-4
entries are represented by English markers rather than Japanese fallbacks.
Each mined dictionary entry is a control-flagged Huffman leaf (struct=0xC000|6,
symbol=0x8540+i). The slot-6 stub calls an expansion handler, which looks up the
full string and tail-jumps the shared emit gate, which routes the string the
same way the stock name-insert emitter (0x8005ab88) does: into the streaming
draw buffer during streamed dialogue, through the stock append router
otherwise. Both the common and negotiation-only slot-6 stubs enter that
handler."""
import struct
import build_en_tree as ET

STRUCT=0x80117ec4; SYM=0x801187a4; STCAP=SYM-STRUCT
AB_STRUCT=0x8010130c; AB_SYM=0x80101978; AB_STCAP=AB_SYM-AB_STRUCT
# The SYM table's tail hosts the object-compositor VWF hook and its 10px width
# table (build.py _install_obj_vwf).  build_english_tree pre-fills the whole
# table with unreachable entries, so keeping the tree below this line leaves
# the reservation never-read and never-written.
SYM_TAIL_RESERVE=0x29c

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
DISPATCH  = 0x800582f0                 # common control-index dispatcher
SCRIPT_DISPATCH_CALL = 0x8005764c      # raw common event-script dispatch call site
SCRIPT_CHOICE_INDEX = 6
# Negotiation modes 4/5 route controls through a separate dispatcher.  Its
# stock A/B trees never reference slot 6, so the rebuilt tree can safely use
# that slot for dictionary leaves as long as this second stub is hooked too.
AB_JT     = 0x8001445c
AB_DISPATCH = 0x8007d864
AB_SCRIPT_DISPATCH_CALL = 0x8005758c
AB_STUB6  = 0x8007d924
AB_EPILOGUE = 0x8007e10c
AB_STOCK6 = 0x80084720

# The stock C/D tree has two control leaves with the nominal symbol 0x5355
# ("SU").  Dispatch 113 prints the primary numeric slot at 0x801fd534, while
# dispatch 118 prints the secondary enemy-group slot at 0x801fd590.  A mapping
# keyed only by symbol necessarily collapses them.  Give the latter a synthetic
# two-byte symbol ("S2") in the rebuilt English tree; the handler ignores the
# decoded symbol, and translate_pipeline exposes the same internal alias.
SECONDARY_NUMBER_CODE = 0x5332
SECONDARY_NUMBER_INDEX = 118

# ---- A/B-local dictionary runtime -------------------------------------------------
# Negotiation/battle text (banks 4/5) carries a second mined dictionary. Codes
# extend the shared namespace: [0x8540, 0x8540+NCD) are the C/D entries (u32
# pointer table in the cave); [0x8540+NCD, 0x8540+NCD+NAB) are A/B-local
# entries (u16 offset table + strings in dead exe space). Both use control slot
# 6. The common dispatcher and the negotiation-only A/B dispatcher each need a
# slot-6 stub that calls the same cave handler, then returns through its own
# epilogue. The cave handler falls through to the continuation at AB4_HANDLER,
# which range-checks the A/B window and otherwise forwards to the stock slot-6
# routine belonging to the dispatcher that entered the shared handler.
#
# The continuation lives in the LAST 64 bytes of bank 7's cave slice (build.py
# caps bank 7 at AB4_HANDLER), so its address is a build-time constant.  The
# expansion strings live in the dead tails of the C/D tree tables; both tree
# builders pre-fill their whole tables with entries the decoder can never
# reach, and the obj-VWF reservation at the SYM table's end stays excluded.
# NOTE: the stock bank-7 block at 0x80116f2c is NOT usable for any of this --
# bank 6's English block legitimately grows into it (build.py hands bank 6 the
# whole native region up to 0x801171d8).
AB4_HANDLER = DICT_BASE-0x40           # continuation handler: 64-byte cave slot
AB4_STRBASE = STRUCT                   # u16 string offsets relative to STRUCT
# Six instructions at the end of the first dead C/D tree-table tail distinguish
# raw event-script choice op 6 from compressed-text dictionary op 6.  Keep this
# reservation out of _ab_string_regions so expansion strings cannot overwrite it.
SCRIPT_DISPATCH_WRAPPER = SYM-0x18
# The field-item target prompt is appended directly at two call sites instead
# of going through build.py's marker-aware system-string printer.  Give it a
# proper fullwidth copy immediately before the dispatch wrapper and repoint
# those calls; marker-prefixed one-byte text renders as garbage on this path.
ITEM_TARGET_PROMPT = SCRIPT_DISPATCH_WRAPPER-0x20
ITEM_TARGET_PROMPT_SIZE = 0x20
ITEM_TARGET_PROMPT_TEXT = "Use it on whom?"
ITEM_TARGET_PROMPT_STOCK = 0x8001465c
ITEM_TARGET_PROMPT_CALLS = (0x8007e9a0, 0x8007f2a8)
# The negotiation-mode event interpreter calls its own dispatcher and passes
# the raw opcode in a1 instead of a0.  It needs the same stale-symbol guard as
# the common interpreter.  Once a non-dictionary slot 6 reaches the shared
# dictionary handler, its caller context selects the correct stock fallback:
# the common choice-menu handler or the negotiation handler at AB_STOCK6.
AB_SCRIPT_DISPATCH_WRAPPER = ITEM_TARGET_PROMPT-0x18
STOCK6_SELECTOR = AB_SCRIPT_DISPATCH_WRAPPER-0x18
# Expansion strings must be emitted the way the stock name-insert emitter
# (0x8005ab88) emits names.  While a dialogue box is STREAMING (byte
# 0x801d1748 nonzero and game-state word 0x801fd8fc != 0x10 = battle), every
# control that produces text strcpys it into the shared draw buffer
# 0x801fd598 (256 B; next live global 0x801fd698) that the box renderer draws
# with VWF advance this tick; the append router 0x80058244 is only correct
# outside streaming.  Tail-jumping APPEND unconditionally queued expansions on
# the idle fixed window context 0x800eeb58, whose consumer drew them at its
# own stale cursor -- the garbled, overdrawn fusion-result box of 2026-07-20.
# The gate lives with the other glue in the dead C/D STRUCT-table tail; the
# tree-extent cap (STCAP-SYM_TAIL_RESERVE) keeps the tree clear of it.
EMIT_GATE = STOCK6_SELECTOR-0x38
STREAM_FLAG = 0x801d1748
GAME_STATE = 0x801fd8fc
DRAW_BUF = 0x801fd598
BIOS_STRCPY = 0x800d107c               # BIOS A(0x19) strcpy thunk: (dst, src)
# ---- Relocated name-insert accumulation buffer ------------------------------------
# The stock 256-byte buffer at 0x801d1458 accumulates every decoded name
# insert between page resets, and its write-cursor global at 0x801d1558 sits
# IMMEDIATELY after it.  English names are ~40% longer than katakana: six
# enemy names + race + group name overran the buffer, and the cursor
# write-back stamped a pointer into the last decoded name, drawn as ASCII
# garbage through the byte-0x20 glyph path ("Demonoid O<=  cles", 2026-07-20).
# Relocated into the STRUCT-table tail band [tree cap, EMIT_GATE) that the
# tree-extent assert (nxt <= STCAP-SYM_TAIL_RESERVE) guarantees the Huffman
# tree can never reach, and grown to 504 bytes.  The cursor global stays at
# 0x801d1558.  build.py _relocate_name_buffer patches the three code sites
# that materialize the base; _ab_string_regions excludes the band.
NAME_INSERT_BUF = STRUCT+STCAP-SYM_TAIL_RESERVE
NAME_INSERT_BUF_WORDS = 0x7e           # zero-fill loop count (504 B)
assert NAME_INSERT_BUF+NAME_INSERT_BUF_WORDS*4 <= EMIT_GATE

# ---- MIPS instruction encoders (R3000) --------------------------------------------
ZERO,V0,V1,A0,A1,T0,T1,T2=0,2,3,4,5,8,9,10
RI=lambda op,rs,rt,imm:((op&0x3f)<<26)|((rs&0x1f)<<21)|((rt&0x1f)<<16)|(imm&0xffff)
LUI=lambda rt,i:RI(0x0f,0,rt,i); LHU=lambda rt,o,rs:RI(0x25,rs,rt,o)
LBU=lambda rt,o,rs:RI(0x24,rs,rt,o)
LW=lambda rt,o,rs:RI(0x23,rs,rt,o); ADDIU=lambda rt,rs,i:RI(0x09,rs,rt,i)
ORI=lambda rt,rs,i:RI(0x0d,rs,rt,i); SLTIU=lambda rt,rs,i:RI(0x0b,rs,rt,i)
BEQ=lambda rs,rt,off:RI(0x04,rs,rt,off); BNE=lambda rs,rt,off:RI(0x05,rs,rt,off)
SH=lambda rt,o,rs:RI(0x29,rs,rt,o)
SLL=lambda rd,rt,sa:((rt&0x1f)<<16)|((rd&0x1f)<<11)|((sa&0x1f)<<6)
ADDU=lambda rd,rs,rt:((rs&0x1f)<<21)|((rt&0x1f)<<16)|((rd&0x1f)<<11)|0x21
SUBU=lambda rd,rs,rt:((rs&0x1f)<<21)|((rt&0x1f)<<16)|((rd&0x1f)<<11)|0x23
J=lambda t:(0x02<<26)|((t>>2)&0x03ffffff); JAL=lambda t:(0x03<<26)|((t>>2)&0x03ffffff)
NOP=0
lo=lambda x:x&0xffff; hi=lambda x:((x>>16)+(1 if x&0x8000 else 0))&0xffff

_DICT_ENTRIES = []
_DICT_CODE_MAP = {}
_AB_LOCAL_ENTRIES = []
CD_TREE_USED = None       # C/D tree bytes (set by build_english_tree)
AB_TREE_USED = None       # A/B tree bytes (set by build_ab_tree)
AB4_OFFTAB = None         # u16 offset-table address (set by install_ab_runtime)

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

def configure_ab_local_dictionary(entries):
    """Install the A/B-local entry list (codes 0x8540+NCD onward, in order)."""
    global _AB_LOCAL_ENTRIES
    entries = list(entries)
    strings = [s for s,_weight in entries]
    if len(strings) != len(set(strings)):
        raise ValueError("A/B dictionary entries must be unique")
    shared = [s for s in strings if s in _DICT_CODE_MAP]
    if shared:
        raise ValueError(f"A/B entries duplicate shared dictionary: {shared!r}")
    _AB_LOCAL_ENTRIES = entries

def _ab_string_regions():
    """Dead always-resident exe space that can hold A/B expansion strings.

    Both regions are C/D tree-table tails within u16 range above AB4_STRBASE.
    They are safe because build_english_tree pre-fills the whole tables with
    entries the decoder can never reach, nothing else writes them after the
    tree build, and the obj-VWF reservation at the SYM table's end is excluded.
    """
    if CD_TREE_USED is None:
        raise RuntimeError("build_english_tree must run before placing A/B strings")
    return [
        (STRUCT+CD_TREE_USED, NAME_INSERT_BUF),
        (SYM+CD_TREE_USED, SYM+STCAP-SYM_TAIL_RESERVE),
    ]

def _place_ab_strings(entries, exe=None):
    """First-fit expansion strings into the free regions.

    Returns (placed_entries, string_addrs).  Dry run when exe is None; the
    outcome depends only on the entry list and CD_TREE_USED, so a dry-run
    selection stays valid verbatim at install time.
    """
    regions=_ab_string_regions()
    cursors=[start for start,_end in regions]
    placed=[]; addrs=[]
    for s,weight in entries:
        blob=bytearray()
        for ch in s: blob+=ET.fullwidth(ch).to_bytes(2,"big")
        blob.append(0)
        for k,(_start,end) in enumerate(regions):
            if cursors[k]+len(blob)<=end:
                addr=cursors[k]; cursors[k]+=len(blob)
                break
        else:
            continue                       # no region holds this string
        assert 0 <= addr-AB4_STRBASE <= 0xffff
        if exe is not None:
            exe[_foff(addr):_foff(addr)+len(blob)]=blob
        placed.append((s,weight)); addrs.append(addr)
    return placed, addrs

def fit_ab_local_dictionary(candidates, base_leaf_count):
    """Trim mined A/B entries to what the free space provably holds.

    ``base_leaf_count`` is measured from the actual Bank 4/5 corpus tokenized
    with the shared dictionary. Each local entry can add at most one leaf;
    replacement may remove base leaves, making this bound conservative. Each
    16-ary node costs 32 B, and the u16 offset table must share a tree tail.
    """
    placed,_=_place_ab_strings(candidates)
    while True:
        leaves=base_leaf_count+len(placed)
        padded_leaves=leaves+(-(leaves-1))%15
        nodes=(padded_leaves-1)//15
        if nodes:
            nodes+=1                       # reserve invalid root nibble 0
        if 32*nodes+2*len(placed)<=AB_STCAP:
            return placed
        if not placed:
            raise SystemExit(
                f"base A/B tree cannot fit: {base_leaf_count} leaves"
            )
        placed.pop()

def install_ab_runtime(exe):
    """Write the A/B-local dictionary runtime.

    Layout: expansion strings scattered over _ab_string_regions, the u16
    offset table (string addr - AB4_STRBASE) in an A/B tree-table tail, and
    the slot-6 continuation handler at AB4_BASE.  Must run after both tree
    builders (their extents define the free space)."""
    global AB4_OFFTAB
    if AB_TREE_USED is None:
        raise RuntimeError("build_ab_tree must run before install_ab_runtime")
    def w16(a,v): struct.pack_into("<H",exe,_foff(a),v)
    def w32(a,v): struct.pack_into("<I",exe,_foff(a),v)
    entries=_AB_LOCAL_ENTRIES
    placed,addrs=_place_ab_strings(entries,exe)
    if len(placed)!=len(entries):
        raise SystemExit("A/B dictionary strings no longer fit their regions")
    ncd=len(_DICT_ENTRIES); nab=len(entries)
    for tail,limit in ((AB_STRUCT+AB_TREE_USED,AB_SYM),
                       (AB_SYM+AB_TREE_USED,AB_SYM+AB_STCAP)):
        if tail+2*nab<=limit:
            AB4_OFFTAB=tail; break
    else:
        raise SystemExit(f"A/B offset table ({2*nab} B) fits neither tree tail")
    for j,addr in enumerate(addrs):
        w16(AB4_OFFTAB+2*j,addr-AB4_STRBASE)
    # Continuation handler.  Entered from the cave handler's fallthrough with
    # t1 = decoded_sym - 0x8540 still live.  Mirrors the cave handler's
    # conventions: same clobber set before the STOCK6 forward (v0/v1/t2), a0
    # only written on the emit path, lui fills the lhu load-delay slot.
    L_STOCK=13
    handler=[
        ADDIU(T2,T1,-ncd),                       # t2 = sym - 0x8540 - NCD
        SLTIU(V0,T2,nab),                        # A/B-local code?
        BEQ(V0,ZERO,L_STOCK-3),                  # no -> stock choice-menu op
        SLL(V1,T2,1),                            # (delay slot)
        LUI(V0,hi(AB4_OFFTAB)),
        ADDIU(V0,V0,lo(AB4_OFFTAB)),
        ADDU(V0,V0,V1),
        LHU(V0,0,V0),                            # u16 string offset
        LUI(A0,hi(AB4_STRBASE)),                 # load-delay filler
        ADDIU(A0,A0,lo(AB4_STRBASE)),
        ADDU(A0,A0,V0),
        J(EMIT_GATE),
        NOP,
        J(STOCK6_SELECTOR),                      # L_STOCK
        NOP,
    ]
    assert len(handler)*4<=DICT_BASE-AB4_HANDLER
    for i,wd in enumerate(handler): w32(AB4_HANDLER+i*4,wd)

def verify_ab_runtime(exe):
    """Re-read the installed A/B dictionary from the exe and check every string."""
    def r16(a): return struct.unpack_from("<H",exe,_foff(a))[0]
    def r32(a): return struct.unpack_from("<I",exe,_foff(a))[0]
    if r32(SCRIPT_DISPATCH_CALL)!=JAL(SCRIPT_DISPATCH_WRAPPER):
        raise SystemExit("raw event-script dispatcher does not use the slot-6 guard")
    if r32(SCRIPT_DISPATCH_CALL+4)!=SH(A0,0x15dc,V1):
        raise SystemExit("raw event-script dispatcher delay-slot store is corrupt")
    for i,word in enumerate(_script_dispatch_wrapper_words()):
        if r32(SCRIPT_DISPATCH_WRAPPER+4*i)!=word:
            raise SystemExit("raw event-script slot-6 guard is corrupt")
    if r32(AB_SCRIPT_DISPATCH_CALL)!=JAL(AB_SCRIPT_DISPATCH_WRAPPER):
        raise SystemExit("raw negotiation script dispatcher does not use the slot-6 guard")
    if r32(AB_SCRIPT_DISPATCH_CALL+4)!=SH(A1,0x15dc,V1):
        raise SystemExit("raw negotiation script dispatcher delay-slot store is corrupt")
    for i,word in enumerate(_ab_script_dispatch_wrapper_words()):
        if r32(AB_SCRIPT_DISPATCH_WRAPPER+4*i)!=word:
            raise SystemExit("raw negotiation slot-6 guard is corrupt")
    for i,word in enumerate(_stock6_selector_words()):
        if r32(STOCK6_SELECTOR+4*i)!=word:
            raise SystemExit("dictionary slot-6 fallback selector is corrupt")
    prompt=_item_target_prompt_blob()
    start=_foff(ITEM_TARGET_PROMPT)
    if bytes(exe[start:start+ITEM_TARGET_PROMPT_SIZE]) != (
            prompt+bytes(ITEM_TARGET_PROMPT_SIZE-len(prompt))):
        raise SystemExit("field-item target prompt is corrupt")
    for site in ITEM_TARGET_PROMPT_CALLS:
        if (r32(site)!=LUI(A0,hi(ITEM_TARGET_PROMPT)) or
                r32(site+4)!=JAL(APPEND) or
                r32(site+8)!=ADDIU(A0,A0,lo(ITEM_TARGET_PROMPT))):
            raise SystemExit("field-item target prompt reference is corrupt")
    common_stub=STUBS+DICT_JT_INDEX*0x10
    if (r32(JT+DICT_JT_INDEX*4)!=common_stub or
            r32(common_stub)!=JAL(DICT_HANDLER) or
            r32(common_stub+4)!=ADDIU(A1,ZERO,0) or
            r32(common_stub+8)!=J(EPILOGUE) or r32(common_stub+12)!=NOP):
        raise SystemExit("common slot-6 dictionary dispatch is corrupt")
    if (r32(AB_JT+DICT_JT_INDEX*4)!=AB_STUB6 or
            r32(AB_STUB6)!=JAL(DICT_HANDLER) or
            r32(AB_STUB6+4)!=ADDIU(A1,ZERO,1) or
            r32(AB_STUB6+8)!=J(AB_EPILOGUE) or r32(AB_STUB6+12)!=NOP):
        raise SystemExit("negotiation slot-6 dictionary dispatch is corrupt")
    if r32(DICT_HANDLER+13*4)!=J(AB4_HANDLER):
        raise SystemExit("cave handler does not fall through to the A/B continuation")
    if r32(DICT_HANDLER+11*4)!=J(EMIT_GATE):
        raise SystemExit("cave handler does not emit through the streaming gate")
    if r32(AB4_HANDLER+11*4)!=J(EMIT_GATE):
        raise SystemExit("A/B continuation does not emit through the streaming gate")
    for i,word in enumerate(_emit_gate_words()):
        if r32(EMIT_GATE+4*i)!=word:
            raise SystemExit("dictionary emit gate is corrupt")
    # SLTIU(V0,T2,NAB) is the continuation's second word; its imm16 must match.
    if _AB_LOCAL_ENTRIES and r16(AB4_HANDLER+4)!=len(_AB_LOCAL_ENTRIES):
        raise SystemExit("A/B continuation handler range check is stale")
    for j,(s,_w) in enumerate(_AB_LOCAL_ENTRIES):
        addr=AB4_STRBASE+r16(AB4_OFFTAB+2*j)
        blob=bytearray()
        for ch in s: blob+=ET.fullwidth(ch).to_bytes(2,"big")
        blob.append(0)
        off=_foff(addr)
        if bytes(exe[off:off+len(blob)])!=bytes(blob):
            raise SystemExit(f"A/B dictionary string {j} corrupt at {addr:#x}: {s!r}")

def _foff(a): return (a-0x80010000)+0x800

def _script_dispatch_wrapper_words():
    """Guard raw choice op 6 from a stale decoded dictionary symbol.

    The raw event-script path dispatches an opcode without updating
    DECODED_SYM.  Slot 6 is shared with dictionary expansion, so an A/B-local
    dictionary symbol left by the preceding dialogue could otherwise make a
    choice menu expand arbitrary text instead of invoking STOCK6.

    All non-choice raw opcodes are unchanged.  Clearing DECODED_SYM for choice
    op 6 makes both dictionary range checks fail and forward to STOCK6.  Calls
    from the compressed-text decoders bypass this wrapper and retain the real
    dictionary symbol.
    """
    return [
        ADDIU(V0,ZERO,SCRIPT_CHOICE_INDEX),
        BNE(A0,V0,2),                            # non-choice -> tail dispatch
        LUI(V0,(DECODED_SYM>>16)&0xffff),        # branch delay slot
        SH(ZERO,DECODED_SYM&0xffff,V0),
        J(DISPATCH),
        NOP,
    ]

def _ab_script_dispatch_wrapper_words():
    """Guard raw negotiation choice op 6 before the A/B dispatcher.

    This interpreter passes the opcode in a1.  Compressed A/B controls bypass
    this wrapper, so clearing the decoded-symbol global here cannot affect a
    real dictionary leaf.
    """
    return [
        ADDIU(V0,ZERO,SCRIPT_CHOICE_INDEX),
        BNE(A1,V0,2),                            # non-choice -> tail dispatch
        LUI(V0,(DECODED_SYM>>16)&0xffff),        # branch delay slot
        SH(ZERO,DECODED_SYM&0xffff,V0),
        J(AB_DISPATCH),
        NOP,
    ]

def _stock6_selector_words():
    """Select the stock slot-6 routine using the dispatch stub's a1 flag."""
    return [
        BEQ(A1,ZERO,3),                          # common dispatcher -> STOCK6
        NOP,
        J(AB_STOCK6),
        NOP,
        J(STOCK6),
        NOP,
    ]

def _emit_gate_words():
    """Emit an expansion string (a0) the way the stock name emitter does.

    Streaming dialogue (STREAM_FLAG set, game state != 0x10): strcpy into the
    shared draw buffer; the streaming box renderer draws the whole buffer this
    tick with VWF advance, exactly as it draws an inserted demon name.
    Otherwise: the stock append router.  Entered by J with ra still at the
    dispatch stub's continuation, so both BIOS_STRCPY and APPEND return
    through the correct caller epilogue.  Branch delay slots are harmless on
    both paths (v1 is dead after each test; APPEND overwrites a1 first thing)
    and every load is consumed two slots later (R3000 load delay).
    """
    L_APP=11
    words=[
        LUI(V0,(STREAM_FLAG>>16)&0xffff),
        LBU(V1,STREAM_FLAG&0xffff,V0),           # v1 = streaming flag
        LUI(V0,hi(GAME_STATE)),                  # load-delay filler
        BEQ(V1,ZERO,L_APP-4),                    # not streaming -> append
        LW(V1,lo(GAME_STATE),V0),                # (delay slot) v1 = game state
        ORI(T2,ZERO,0x10),                       # load-delay filler
        BEQ(V1,T2,L_APP-7),                      # battle -> append
        ADDU(A1,A0,ZERO),                        # (delay slot) a1 = source
        LUI(T2,hi(DRAW_BUF)),
        J(BIOS_STRCPY),
        ADDIU(A0,T2,lo(DRAW_BUF)),               # (delay slot) a0 = draw buffer
        J(APPEND),                               # L_APP
        NOP,
    ]
    assert EMIT_GATE+len(words)*4<=STOCK6_SELECTOR
    return words

def _item_target_prompt_blob():
    blob=bytearray()
    for ch in ITEM_TARGET_PROMPT_TEXT:
        blob+=ET.fullwidth(ch).to_bytes(2,"big")
    blob.append(0)
    if len(blob)>ITEM_TARGET_PROMPT_SIZE:
        raise SystemExit(
            f"field-item target prompt overflow: {len(blob)}>{ITEM_TARGET_PROMPT_SIZE}"
        )
    return bytes(blob)

def control_index_map(slpm):
    def oU16(a): return struct.unpack_from("<H",slpm,_foff(a))[0]
    cidx={}; indices_by_symbol={}
    def dfs(n,d):
        if d>40: return
        for nib in range(16):
            ea=(n&0xFFFE)+nib*2; nx=oU16(STRUCT+ea)
            if nx==0x7fff: continue
            if nx&0x8000:
                if nx&0x4000:
                    symbol=oU16(SYM+ea); index=nx&0x3fff
                    cidx.setdefault(symbol,index)
                    indices_by_symbol.setdefault(symbol,set()).add(index)
            elif nx!=n: dfs(nx,d+1)
    dfs(0,0)
    if SECONDARY_NUMBER_CODE in cidx:
        raise SystemExit("synthetic S2 control collides with a stock C/D symbol")
    if indices_by_symbol.get(0x5355) != {113,SECONDARY_NUMBER_INDEX}:
        raise SystemExit("unexpected stock SU control dispatchers")
    # Index 118 is the stock formatter at 0x80062470.  Verify this revision's
    # jump-table entry before making it reachable under the synthetic alias.
    if struct.unpack_from("<I",slpm,_foff(JT+SECONDARY_NUMBER_INDEX*4))[0] != 0x80058adc:
        raise SystemExit("unexpected secondary-number dispatch entry")
    cidx[SECONDARY_NUMBER_CODE]=SECONDARY_NUMBER_INDEX
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
    for message_id,author in TR.TRANS.items():
        if message_id >> 12 not in {0,1,2,3,6,7}:
            continue
        for part in author:
            if isinstance(part,tuple): ctrls[part[0]]+=1          # raw token
            elif part in TP.CTRL_NAME:
                ctrls[TP.CTRL_NAME[part][0]]+=1
                suffix=TP.CONTROL_SUFFIX.get(part)
                if suffix:
                    for sym,is_ctl in TP.text_tokens(suffix):
                        (dicts if is_ctl else chars)[sym]+=1
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
    assert nxt<=STCAP-SYM_TAIL_RESERVE, \
        f"tree overflow into VWF reservation: {nxt}>{STCAP-SYM_TAIL_RESERVE}"
    global CD_TREE_USED; CD_TREE_USED=nxt      # tails past this hold A/B strings
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

def build_ab_tree(exe, messages):
    """Build the English A/B tree from exact bank-4/5 tokens and return paths.

    Plain tokens are ``(symbol, False)``. A/B controls are
    ``(0x8140, True, dispatch_index)`` because the stock tree assigns several
    different runtime operations the same nominal space symbol. Authored
    English may also use shared-dictionary leaves shaped as
    ``(dictionary_symbol, True, DICT_JT_INDEX)``. ``messages`` contains one
    occurrence per physically stored stream, prepared by build.py after each
    independently interned block has been deduplicated.
    """
    import heapq
    from collections import Counter, deque

    def w16(a,v): struct.pack_into("<H",exe,_foff(a),v)
    counts=Counter(token for message in messages for token in message)
    if not counts:
        raise ValueError("A/B corpus is empty")
    dict_limit=DICT_CODE_BASE+len(_DICT_ENTRIES)+len(_AB_LOCAL_ENTRIES)
    slot6_controls=[
        token for token in counts
        if (len(token)==3 and token[2]==DICT_JT_INDEX and
            not DICT_CODE_BASE<=token[0]<dict_limit)
    ]
    if slot6_controls:
        raise SystemExit(
            f"A/B control slot {DICT_JT_INDEX} collides with dictionary runtime: "
            f"{slot6_controls!r}"
        )

    # Reserve nibble 0 at the root as an invalid padding branch. A/B streams are
    # individually byte-aligned, so allowing a zero pad nibble to reach a real
    # leaf would append a spurious final glyph. Deeper nodes retain all sixteen
    # branches so the complete English repertoire still fits the stock table.
    items=list(counts.items()); pad=(-(len(items)-1))%15
    heap=[]; tree={}; nid=0
    for token,frequency in items:
        tree[nid]=('leaf',token)
        heapq.heappush(heap,(float(frequency),nid)); nid+=1
    for _ in range(pad):
        tree[nid]=('leaf',None)
        heapq.heappush(heap,(0.0,nid)); nid+=1
    while len(heap)>1:
        children=[heapq.heappop(heap) for _ in range(min(16,len(heap)))]
        tree[nid]=('node',[child[1] for child in children])
        heapq.heappush(heap,(sum(child[0] for child in children),nid)); nid+=1
    root=heap[0][1]
    if len(tree[root][1])==16:
        root_children=tree[root][1]
        tree[nid]=('node',root_children[:2])
        tree[root]=('node',[nid]+root_children[2:])
        nid+=1

    codes={}
    def walk(node,path):
        kind,value=tree[node]
        if kind=='leaf':
            if value is not None: codes[value]=path
            return
        first_nibble=1 if node==root else 0
        for nibble,child in enumerate(value,first_nibble): walk(child,path+[nibble])
    walk(root,[])

    offsets={}; next_offset=0; queue=deque([root])
    while queue:
        node=queue.popleft()
        if tree[node][0]!='node' or node in offsets: continue
        offsets[node]=next_offset; next_offset+=32
        for child in tree[node][1]:
            if tree[child][0]=='node': queue.append(child)
    if next_offset>AB_STCAP:
        raise SystemExit(f"A/B tree overflow: {next_offset}>{AB_STCAP}")
    global AB_TREE_USED; AB_TREE_USED=next_offset  # tail past this holds the offset table

    for offset in range(0,AB_STCAP,2):
        w16(AB_STRUCT+offset,0x7fff)
        w16(AB_SYM+offset,0)

    def leaf_entry(token):
        if len(token)==3:
            symbol,is_control,index=token
            if not is_control:
                raise ValueError(f"invalid A/B control token: {token!r}")
            return 0xc000|index,symbol
        symbol,is_control=token
        if is_control:
            raise ValueError(f"A/B control lacks dispatch index: {token!r}")
        return 0x8000,symbol

    for node,base in offsets.items():
        children=tree[node][1]
        for nibble in range(16):
            entry_offset=base+nibble*2
            child_index=(nibble-1) if node==root else nibble
            if child_index<0 or child_index>=len(children):
                struct_value,symbol=0x7fff,0
            else:
                child=children[child_index]; kind,value=tree[child]
                if kind=='leaf':
                    struct_value,symbol=(0x7fff,0) if value is None else leaf_entry(value)
                else:
                    struct_value,symbol=offsets[child],0
            w16(AB_STRUCT+entry_offset,struct_value)
            w16(AB_SYM+entry_offset,symbol)
    return codes

def _install_dictionary_runtime(exe):
    """Write the dict handler, pointer table, expansion strings, and stub 6."""
    def w32(a,v): struct.pack_into("<I",exe,_foff(a),v)
    def r32(a): return struct.unpack_from("<I",exe,_foff(a))[0]
    entries=_DICT_ENTRIES
    # The raw event-script interpreters and compressed-text decoders share
    # dispatch slots. Route only the two raw calls through guards that clear a
    # stale dictionary symbol for choice-menu opcode 6. The JAL delay-slot
    # stores of the raw opcode remain untouched.
    if (r32(SCRIPT_DISPATCH_CALL)!=JAL(DISPATCH) or
            r32(SCRIPT_DISPATCH_CALL+4)!=SH(A0,0x15dc,V1)):
        raise SystemExit("unexpected raw event-script dispatcher call site")
    if (r32(AB_SCRIPT_DISPATCH_CALL)!=JAL(AB_DISPATCH) or
            r32(AB_SCRIPT_DISPATCH_CALL+4)!=SH(A1,0x15dc,V1)):
        raise SystemExit("unexpected raw negotiation script dispatcher call site")
    w32(SCRIPT_DISPATCH_CALL,JAL(SCRIPT_DISPATCH_WRAPPER))
    for i,word in enumerate(_script_dispatch_wrapper_words()):
        w32(SCRIPT_DISPATCH_WRAPPER+4*i,word)
    w32(AB_SCRIPT_DISPATCH_CALL,JAL(AB_SCRIPT_DISPATCH_WRAPPER))
    for i,word in enumerate(_ab_script_dispatch_wrapper_words()):
        w32(AB_SCRIPT_DISPATCH_WRAPPER+4*i,word)
    for i,word in enumerate(_stock6_selector_words()):
        w32(STOCK6_SELECTOR+4*i,word)
    # Field healing items append their target prompt directly through APPEND,
    # bypassing the marker-aware raw-string printer.  Relocate a fullwidth copy
    # into reserved dead table space and update both item-use call sites.
    stock_hi=(ITEM_TARGET_PROMPT_STOCK>>16)&0xffff
    stock_lo=ITEM_TARGET_PROMPT_STOCK&0xffff
    for site in ITEM_TARGET_PROMPT_CALLS:
        if (r32(site)!=LUI(A0,stock_hi) or r32(site+4)!=JAL(APPEND) or
                r32(site+8)!=ADDIU(A0,A0,stock_lo)):
            raise SystemExit("unexpected field-item target prompt call site")
        w32(site,LUI(A0,hi(ITEM_TARGET_PROMPT)))
        w32(site+8,ADDIU(A0,A0,lo(ITEM_TARGET_PROMPT)))
    prompt=_item_target_prompt_blob()
    start=_foff(ITEM_TARGET_PROMPT)
    exe[start:start+ITEM_TARGET_PROMPT_SIZE] = (
        prompt+bytes(ITEM_TARGET_PROMPT_SIZE-len(prompt))
    )
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
    # event-script CHOICE-MENU op.  The raw interpreter is guarded above, but
    # keep both dictionary range checks defensive: dict codes take the emit
    # gate and anything else falls through to the caller's stock slot-6 handler.
    #   a0 = DICT_PTRS[decoded_sym - 0x8540]; tail-jump the emit gate, which
    # picks the streaming draw buffer or the stock append per context.
    # ori fills the R3000 lhu load-delay slot before v1 is consumed, and
    # subtracting DICT_CODE_BASE first keeps every immediate in range.
    # Codes past the C/D window fall through to the continuation at AB4_BASE,
    # which handles the A/B-local window and otherwise uses the caller-context
    # selector to forward to STOCK6 or AB_STOCK6.
    # t1 (sym - 0x8540) and the a1 caller-context flag stay live across that
    # jump -- the delay slot only clobbers v1.
    L_STOCK=13                       # index of the fallthrough branch target
    handler=[
        LUI(V0,(DECODED_SYM>>16)&0xffff),
        LHU(V1,DECODED_SYM&0xffff,V0),           # v1 = decoded symbol
        ORI(T0,ZERO,DICT_CODE_BASE),             # load-delay filler
        SUBU(T1,V1,T0),                          # t1 = sym - 0x8540
        SLTIU(T2,T1,len(entries)),               # C/D dict code?
        BEQ(T2,ZERO,L_STOCK-6),                  # no -> A/B continuation
        SLL(V1,T1,2),                            # (delay slot)
        LUI(V0,hi(DICT_PTRS)),
        ADDIU(V0,V0,lo(DICT_PTRS)),
        ADDU(V0,V0,V1),
        LW(A0,0,V0),
        J(EMIT_GATE),
        NOP,
        J(AB4_HANDLER),                          # L_STOCK: ra still = stub+8
        NOP,
    ]
    assert DICT_HANDLER+len(handler)*4<=DICT_PTRS
    for i,wd in enumerate(handler): w32(DICT_HANDLER+i*4,wd)
    for i,wd in enumerate(_emit_gate_words()): w32(EMIT_GATE+i*4,wd)
    # Keep the exe well-formed even before install_ab_runtime runs: a bare
    # forward to the installed stock-handler selector. install_ab_runtime
    # overwrites this with the local dictionary continuation.
    w32(AB4_HANDLER,J(STOCK6_SELECTOR)); w32(AB4_HANDLER+4,NOP)
    # Repurpose the (tree-unreferenced) dispatch stub 6.
    stub=STUBS+DICT_JT_INDEX*0x10
    w32(stub+0,JAL(DICT_HANDLER)); w32(stub+4,ADDIU(A1,ZERO,0))
    w32(stub+8,J(EPILOGUE)); w32(stub+12,NOP)
    w32(JT+DICT_JT_INDEX*4,stub)   # already points here in the stock exe; keep explicit
    # Modes 4/5 (negotiation and the small A/B battle-fragment bank) bypass the
    # common dispatcher above and use their own jump table at AB_JT.  Slot 6 is
    # absent from every stock A/B stream, so redirect that dedicated stub to
    # the same dictionary handler and retain its negotiation epilogue.
    if (r32(AB_JT+DICT_JT_INDEX*4)!=AB_STUB6 or
            r32(AB_STUB6)!=JAL(AB_STOCK6) or r32(AB_STUB6+4)!=NOP or
            r32(AB_STUB6+8)!=J(AB_EPILOGUE) or r32(AB_STUB6+12)!=NOP):
        raise SystemExit("unexpected negotiation slot-6 dispatch stub")
    w32(AB_STUB6,JAL(DICT_HANDLER))
    w32(AB_STUB6+4,ADDIU(A1,ZERO,1))
