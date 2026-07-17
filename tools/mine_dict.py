"""Re-mine the MTE dictionary from the CURRENT translation corpus.

Run after any significant translation change:  python tools/mine_dict.py
Rewrites the entry list in tools/en_dictionary.py between the BEGIN/END
markers, then rebuild with  python build.py --mte .

The dictionary can never "fail to fit": selection is capped by
en_dictionary.RUNTIME_BUDGET (the cave space for pointers + strings), so a
changed corpus only changes how much compression the budget buys, never
whether the build succeeds.  Bank overflow remains the build's own check.

Selection: greedy by nibble-savings per runtime byte.  Char costs come from a
16-ary Huffman over the corpus's own character frequencies (mirroring what the
tree builder will produce); each chosen entry is spliced out of the working
corpus before the next round so overlapping candidates don't double-count.
"""
import io, re, sys, heapq
from collections import Counter
sys.path.insert(0, "tools")
import build_en_tree as ET
import en_dictionary as D

MIN_LEN, MAX_LEN = 3, 16
MIN_COUNT = 3
DICT_TOKEN_NIBBLES = 3          # typical depth of a dict leaf in the final tree
ROUND_PICKS = 8                 # entries chosen per re-count round

def corpus_texts():
    import translations as TR
    parts = []
    for author in TR.TRANS.values():
        for part in author:
            if isinstance(part, str) and part not in __import__("translate_pipeline").CTRL_NAME:
                parts.append(part)
    return parts

def encodable(s):
    for ch in s:
        try: ET.fullwidth(ch)
        except KeyError: return False
    return True

def char_nibble_costs(text):
    """Approximate per-char nibble cost via a 16-ary Huffman over corpus freqs."""
    freqs = Counter(text)
    freqs.pop("\x00", None)
    items = list(freqs.items()); pad = (-(len(items)-1)) % 15
    heap = []; tree = {}; nid = 0
    for ch, fr in items: tree[nid] = ("leaf", ch); heapq.heappush(heap, (fr, nid)); nid += 1
    for _ in range(pad): tree[nid] = ("leaf", None); heapq.heappush(heap, (0.0, nid)); nid += 1
    while len(heap) > 1:
        ks = [heapq.heappop(heap) for _ in range(min(16, len(heap)))]
        tree[nid] = ("node", [k[1] for k in ks]); heapq.heappush(heap, (sum(k[0] for k in ks), nid)); nid += 1
    depth = {}
    def walk(i, d):
        kind, v = tree[i]
        if kind == "leaf":
            if v is not None: depth[v] = max(d, 1)
            return
        for c in v: walk(c, d+1)
    walk(heap[0][1], 0)
    return depth

def runtime_cost(s):
    return 4 + 2*len(s) + 1     # pointer + fullwidth string + NUL

def mine(budget):
    corpus = "\x00".join(corpus_texts())
    cost = char_nibble_costs(corpus)
    chosen = []
    spent = 0
    while spent < budget:
        counts = Counter()
        for L in range(MIN_LEN, MAX_LEN+1):
            for i in range(len(corpus)-L+1):
                sub = corpus[i:i+L]
                if "\x00" not in sub: counts[sub] += 1
        scored = []
        for s, n in counts.items():
            if n < MIN_COUNT or not encodable(s): continue
            saved = n * (sum(cost.get(c, 4) for c in s) - DICT_TOKEN_NIBBLES)
            if saved <= 0: continue
            scored.append((saved / runtime_cost(s), saved, s, n))
        scored.sort(reverse=True)
        picked = 0
        for _dens, saved, s, n in scored:
            if spent + runtime_cost(s) > budget: continue
            # skip if it overlaps an already-picked string this round
            if s not in corpus: continue
            chosen.append((s, saved))
            spent += runtime_cost(s)
            corpus = corpus.replace(s, "\x00")
            picked += 1
            if picked >= ROUND_PICKS or spent >= budget: break
        if picked == 0: break
    chosen.sort(key=lambda kv: -kv[1])
    return chosen, spent

def rewrite_en_dictionary(entries):
    path = "tools/en_dictionary.py"
    src = open(path, encoding="utf-8").read()
    lines = [f"    ({s!r}, {max(1, round(w))}),  # mined savings ~{round(w)} nibbles"
             for s, w in entries]
    body = "_ENTRIES = [\n" + "\n".join(lines) + "\n]"
    new, n = re.subn(r"_ENTRIES = \[.*?\n\]", body, src, count=1, flags=re.S)
    if n != 1: raise SystemExit("could not locate _ENTRIES block in en_dictionary.py")
    open(path, "w", encoding="utf-8").write(new)

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    entries, spent = mine(D.RUNTIME_BUDGET)
    rewrite_en_dictionary(entries)
    total = sum(w for _s, w in entries)
    print(f"mined {len(entries)} entries, runtime {spent}/{D.RUNTIME_BUDGET} B, "
          f"~{total:.0f} nibbles saved ({total/2/1024:.1f} KB)")
    for s, w in entries[:15]: print(f"  {w:7.0f}  {s!r}")
    print("rewrote tools/en_dictionary.py -- rebuild with: python build.py --mte")

if __name__ == "__main__":
    main()
