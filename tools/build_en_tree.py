"""Build an English-only 16-ary Huffman tree for the SMT2 C/D dialogue codec and
lay it out in the existing STRUCT/SYM table format (in place, no relocation).

Tree format (per decoder 0x80057fe4): node = byte offset into STRUCT. child nib:
  entry = struct_u16[node+nib*2]; 0x7fff=none; bit15=leaf (bit14=control,
  symbol = sym_u16[node+nib*2]); else entry = child node byte offset.
"""
import heapq, struct

CONTROLS = {  # code -> weight (measured counts across C/D banks)
 0x4352:2883,0x5754:2405,0x4544:2093,0x5047:912,0x5359:218,0x4d47:213,0x5449:193,
 0x4954:70,0x4649:67,0x464f:66,0x4665:62,0x534e:22,0x5a4b:20,0x4e49:12,0x4147:9,
 0x5355:7,0x4d4e:7,0x4b4f:5,0x4f54:3,0x5050:1,0x414c:1,0x4d48:1,0x5345:1,0x5a4f:5,
}
# English letter frequencies (per 1000), plus space + structural chars
_LET = dict(zip("etaoinshrdlcumwfgypbvkjxqz",
  [111,85,78,72,73,69,63,60,58,37,40,28,27,24,20,22,20,21,18,15,10,8,1.5,1.5,1,0.7]))

def fullwidth(ch):
    o=ord(ch)
    if ch==' ': return 0x8140
    if 'A'<=ch<='Z': return 0x8260+o-65
    if 'a'<=ch<='z': return 0x8281+o-97
    if '0'<=ch<='9': return 0x824f+o-48
    return {'!':0x8149,'?':0x8148,'.':0x8144,',':0x8143,':':0x8146,';':0x8147,
            "'":0x8166,'"':0x8168,'-':0x815d,'(':0x8169,')':0x816a,'…':0x8163,
            '/':0x815e,'>':0x8184,'~':0x8160,'£':0x8192,'ћ':0x8192,
            '+':0x817b,'&':0x8195,'%':0x8193}[ch]

def build_freqs(total_chars=150000):
    f={}
    # space ~ 1 per 5.5 chars
    f[fullwidth(' ')] = total_chars*0.17
    letters_total = total_chars*0.75
    s=sum(_LET.values())
    for ch,w in _LET.items():
        f[fullwidth(ch)] = letters_total*w/s
        up=ch.upper()
        f[fullwidth(up)] = letters_total*w/s*0.04   # capitals ~4% of letters
    # punctuation / digits
    for ch,w in {'.':22,',':20,"'":8,'!':6,'?':5,'-':4,'…':6,':':3,';':1,'"':4,'>':1,'£':3,'+':3,'&':1,'%':1,
                 '(':1,')':1,'0':2,'1':3,'2':2,'3':1.5,'4':1,'5':1,'6':1,'7':1,'8':1,'9':1,'/':1}.items():
        f[fullwidth(ch)] = total_chars*w/1000.0
    # controls (measured, control flag)
    for c,w in CONTROLS.items(): f[('C',c)] = float(w)
    return f

def dary_huffman(freqs, d=16):
    # pad leaves so (L-1) % (d-1) == 0
    items=list(freqs.items())
    L=len(items)
    pad=(-(L-1))%(d-1)
    nodes=[]  # heap of (freq, id)
    tree={}   # id -> ('leaf',sym) or ('node',[child ids])
    nid=0
    for sym,fr in items:
        tree[nid]=('leaf',sym); heapq.heappush(nodes,(fr,nid)); nid+=1
    for _ in range(pad):
        tree[nid]=('leaf',None); heapq.heappush(nodes,(0.0,nid)); nid+=1  # dummy
    while len(nodes)>1:
        kids=[heapq.heappop(nodes) for _ in range(min(d,len(nodes)))]
        fr=sum(k[0] for k in kids)
        tree[nid]=('node',[k[1] for k in kids]); heapq.heappush(nodes,(fr,nid)); nid+=1
    root=nodes[0][1]
    # assign codes
    codes={}
    def walk(i,acc):
        t=tree[i]
        if t[0]=='leaf':
            if t[1] is not None: codes[t[1]]=acc
            return
        for k,ch in enumerate(t[1]): walk(ch,acc+[k])
    walk(root,[])
    return codes,tree,root

def layout(tree,root,STRUCT_BASE,SYM_BASE,exe):
    """Assign byte offsets to internal nodes; write STRUCT/SYM into exe (bytearray)."""
    # collect internal nodes in BFS order from root; root gets offset 0
    order=[]; off={}; nextoff=0
    from collections import deque
    q=deque([root])
    while q:
        i=q.popleft()
        if tree[i][0]!='node' or i in off: continue
        off[i]=nextoff; nextoff+=32; order.append(i)
        for ch in tree[i][1]:
            if tree[ch][0]=='node': q.append(ch)
    def foff(a): return (a-0x80010000)+0x800
    for i in order:
        base=off[i]
        for nib in range(16):
            ea=base+nib*2
            if nib<len(tree[i][1]):
                ch=tree[i][1][nib]; t=tree[ch]
                if t[0]=='leaf':
                    if t[1] is None:
                        st=0x7fff; sy=0
                    elif isinstance(t[1],tuple) and t[1][0]=='C':
                        st=0xC000; sy=t[1][1]
                    else:
                        st=0x8000; sy=t[1]
                else:
                    st=off[ch]; sy=0
            else:
                st=0x7fff; sy=0
            struct.pack_into("<H",exe,foff(STRUCT_BASE+ea),st)
            struct.pack_into("<H",exe,foff(SYM_BASE+ea),sy)
    return nextoff  # bytes used
