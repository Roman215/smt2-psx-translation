"""Production exe: kerned font + VWF advance hook + English-only C/D Huffman tree
(chars + control codes with correct dispatch indices). No dictionary/MTE.
A/B tree (banks 4,5) left untouched so Japanese negotiation still decodes.
Writes exe_prod.bin. Reusable: import build_prod() ."""
import struct, json
import build_en_tree as ET

STRUCT=0x80117ec4; SYM=0x801187a4; STCAP=SYM-STRUCT
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

def build_english_tree(exe, slpm):
    """Lay out an English-only C/D tree (chars + controls) into exe (bytearray)."""
    import heapq
    from collections import deque
    def w16(a,v): struct.pack_into("<H",exe,_foff(a),v)
    cidx=control_index_map(slpm)
    freqs=ET.build_freqs(150000)                      # char symbols (int keys)
    for code,idx in cidx.items():                     # controls: ('C',code)
        freqs[('C',code)]=ET.CONTROLS.get(code,1)
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
        if isinstance(sym,tuple):  # control
            return (0xC000|cidx[sym[1]], sym[1])
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
    return codes, cidx
