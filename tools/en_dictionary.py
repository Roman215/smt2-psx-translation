"""MTE dictionary for the SMT2 English C/D tree (mined from the real corpus).

Each entry becomes a control-flagged Huffman leaf (struct=0xC000|6, sym=0x8540+i)
whose runtime handler appends the expansion string at the text cursor via the
stock string-append routine 0x80058244 (the same path Fe/name inserts use), so
a whole word costs one Huffman code in the compressed stream.

Entries are GENERATED: `python tools/mine_dict.py` re-mines them from the
current tools/translations.py under RUNTIME_BUDGET, so re-run it after any
large translation change and rebuild. Weights are informational rank only --
the tree builder measures real usage counts (build_prod_exe._corpus_freqs).

ORDER IS SIGNIFICANT: entry i gets dict code 0x8540+i, and the runtime pointer
table is laid out in the same order.

Matching (translate_pipeline.text_tokens) is case-sensitive longest-match.
"""

DICT_CODE_BASE = 0x8540
DICT_JT_INDEX = 6            # free slot in the 205-entry control jump table

_ENTRIES = [
    (' you', 748),  # mined savings ~748 nibbles
    (' the ', 496),  # mined savings ~496 nibbles
    ('ing ', 388),  # mined savings ~388 nibbles
    ('you', 387),  # mined savings ~387 nibbles
    (' the', 327),  # mined savings ~327 nibbles
    ('the ', 300),  # mined savings ~300 nibbles
    ('Champion', 296),  # mined savings ~296 nibbles
    ('ing', 294),  # mined savings ~294 nibbles
    ('Okamoto', 273),  # mined savings ~273 nibbles
    ('ng ', 213),  # mined savings ~213 nibbles
    ('Man: ', 200),  # mined savings ~200 nibbles
    ('Center', 192),  # mined savings ~192 nibbles
    ('Champ', 190),  # mined savings ~190 nibbles
    (' will', 189),  # mined savings ~189 nibbles
    ('You ', 182),  # mined savings ~182 nibbles
    ('      ', 180),  # mined savings ~180 nibbles
    ('Valhalla', 168),  # mined savings ~168 nibbles
    ('......', 165),  # mined savings ~165 nibbles
    ('Messia', 164),  # mined savings ~164 nibbles
    ('The ', 150),  # mined savings ~150 nibbles
    ('ight', 144),  # mined savings ~144 nibbles
    ('very', 141),  # mined savings ~141 nibbles
    (' be', 139),  # mined savings ~139 nibbles
    ('You', 136),  # mined savings ~136 nibbles
    (' to ', 136),  # mined savings ~136 nibbles
    ('Thank', 136),  # mined savings ~136 nibbles
    ('What', 134),  # mined savings ~134 nibbles
    (' for', 130),  # mined savings ~130 nibbles
    (' is ', 129),  # mined savings ~129 nibbles
    ('com', 126),  # mined savings ~126 nibbles
    ('demon', 126),  # mined savings ~126 nibbles
    ('The', 124),  # mined savings ~124 nibbles
    ('Voice:', 119),  # mined savings ~119 nibbles
    ('people', 115),  # mined savings ~115 nibbles
    (' can', 114),  # mined savings ~114 nibbles
    ('Puck', 112),  # mined savings ~112 nibbles
    ('Colosseum', 112),  # mined savings ~112 nibbles
    (' with', 105),  # mined savings ~105 nibbles
    ('Arcadia', 102),  # mined savings ~102 nibbles
    ('ve ', 97),  # mined savings ~97 nibbles
    ("I'm ", 96),  # mined savings ~96 nibbles
    ('Madam', 96),  # mined savings ~96 nibbles
    ('savior', 96),  # mined savings ~96 nibbles
    ('Please', 96),  # mined savings ~96 nibbles
    ('emon', 94),  # mined savings ~94 nibbles
    (' of ', 94),  # mined savings ~94 nibbles
    ('Millennium', 90),  # mined savings ~90 nibbles
    ('Anyth', 88),  # mined savings ~88 nibbles
    ('name', 86),  # mined savings ~86 nibbles
    ("n't ", 86),  # mined savings ~86 nibbles
    (',000', 85),  # mined savings ~85 nibbles
    ('hop: ', 84),  # mined savings ~84 nibbles
    ("'s ", 83),  # mined savings ~83 nibbles
    (' this', 82),  # mined savings ~82 nibbles
    ('ack', 80),  # mined savings ~80 nibbles
    ('Hawk', 80),  # mined savings ~80 nibbles
    (' that', 80),  # mined savings ~80 nibbles
    (' again', 80),  # mined savings ~80 nibbles
    ('Factory', 80),  # mined savings ~80 nibbles
    (' wa', 76),  # mined savings ~76 nibbles
    ("I'll", 75),  # mined savings ~75 nibbles
    (' me', 73),  # mined savings ~73 nibbles
    ('again', 69),  # mined savings ~69 nibbles
    (' wh', 65),  # mined savings ~65 nibbles
    ('Macca', 65),  # mined savings ~65 nibbles
    (' I ', 64),  # mined savings ~64 nibbles
    ('buy?', 64),  # mined savings ~64 nibbles
    ("'re ", 64),  # mined savings ~64 nibbles
    (' and ', 64),  # mined savings ~64 nibbles
    ('here', 63),  # mined savings ~63 nibbles
    ('Priest: ', 63),  # mined savings ~63 nibbles
    ('ome', 61),  # mined savings ~61 nibbles
    ('appe', 60),  # mined savings ~60 nibbles
    (' like', 60),  # mined savings ~60 nibbles
    ('member', 60),  # mined savings ~60 nibbles
    ('man', 59),  # mined savings ~59 nibbles
    ('er: ', 58),  # mined savings ~58 nibbles
    ('eve', 56),  # mined savings ~56 nibbles
    (' ma', 56),  # mined savings ~56 nibbles
    ('ough', 56),  # mined savings ~56 nibbles
    ('This', 56),  # mined savings ~56 nibbles
    (' we', 55),  # mined savings ~55 nibbles
    ('already', 55),  # mined savings ~55 nibbles
    ('buy', 54),  # mined savings ~54 nibbles
    ('from', 54),  # mined savings ~54 nibbles
    ('sell?', 54),  # mined savings ~54 nibbles
    ('way', 52),  # mined savings ~52 nibbles
    ('my ', 52),  # mined savings ~52 nibbles
    ('power', 52),  # mined savings ~52 nibbles
    ('place', 52),  # mined savings ~52 nibbles
    ('Hanada', 52),  # mined savings ~52 nibbles
    ('citizen', 49),  # mined savings ~49 nibbles
    ('Terminal', 49),  # mined savings ~49 nibbles
    ('app', 48),  # mined savings ~48 nibbles
    ('suppose', 48),  # mined savings ~48 nibbles
    ('Virtual', 48),  # mined savings ~48 nibbles
    ('Red Bear', 48),  # mined savings ~48 nibbles
    ('wor', 47),  # mined savings ~47 nibbles
    ('Now', 45),  # mined savings ~45 nibbles
    ('COMP', 45),  # mined savings ~45 nibbles
    ('ly ', 44),  # mined savings ~44 nibbles
    (': H', 44),  # mined savings ~44 nibbles
    ('Choose', 44),  # mined savings ~44 nibbles
    (' think', 44),  # mined savings ~44 nibbles
    ('now', 42),  # mined savings ~42 nibbles
    ('That', 42),  # mined savings ~42 nibbles
    ('could', 42),  # mined savings ~42 nibbles
    (' has ', 42),  # mined savings ~42 nibbles
    (' are', 41),  # mined savings ~41 nibbles
    (' all', 40),  # mined savings ~40 nibbles
    ('Mekata', 40),  # mined savings ~40 nibbles
    (' look', 39),  # mined savings ~39 nibbles
    ('mor', 38),  # mined savings ~38 nibbles
    (' him', 38),  # mined savings ~38 nibbles
    ('new ', 36),  # mined savings ~36 nibbles
    ('ћ10', 35),  # mined savings ~35 nibbles
    ('ive', 34),  # mined savings ~34 nibbles
    (' any', 34),  # mined savings ~34 nibbles
    ('fin', 33),  # mined savings ~33 nibbles
    ('would', 33),  # mined savings ~33 nibbles
    ('about', 33),  # mined savings ~33 nibbles
    ('ch ', 32),  # mined savings ~32 nibbles
    (': S', 32),  # mined savings ~32 nibbles
    (' ca', 32),  # mined savings ~32 nibbles
    ('time', 32),  # mined savings ~32 nibbles
    ('must', 32),  # mined savings ~32 nibbles
    ('peace', 32),  # mined savings ~32 nibbles
    (', but', 32),  # mined savings ~32 nibbles
    ('ave', 31),  # mined savings ~31 nibbles
    ('one ', 31),  # mined savings ~31 nibbles
    ('item', 30),  # mined savings ~30 nibbles
    ('good', 30),  # mined savings ~30 nibbles
    ('first', 30),  # mined savings ~30 nibbles
    (': ...', 30),  # mined savings ~30 nibbles
    ('ble', 29),  # mined savings ~29 nibbles
    ('ake', 29),  # mined savings ~29 nibbles
    ('Not', 28),  # mined savings ~28 nibbles
    ('But ', 28),  # mined savings ~28 nibbles
    ('keep', 27),  # mined savings ~27 nibbles
    ('her ', 27),  # mined savings ~27 nibbles
    ('nce', 26),  # mined savings ~26 nibbles
    (' pr', 26),  # mined savings ~26 nibbles
    ('self', 26),  # mined savings ~26 nibbles
    ('pass', 26),  # mined savings ~26 nibbles
    ('orry', 26),  # mined savings ~26 nibbles
    ('not ', 26),  # mined savings ~26 nibbles
    ('own', 25),  # mined savings ~25 nibbles
    ('ful', 25),  # mined savings ~25 nibbles
    ('for', 25),  # mined savings ~25 nibbles
    ('Wel', 25),  # mined savings ~25 nibbles
    (' of', 25),  # mined savings ~25 nibbles
    ('tion', 25),  # mined savings ~25 nibbles
    ('gym', 24),  # mined savings ~24 nibbles
    ('get', 24),  # mined savings ~24 nibbles
    ('No ', 24),  # mined savings ~24 nibbles
    ('ver', 22),  # mined savings ~22 nibbles
    ('ong', 22),  # mined savings ~22 nibbles
    ('om?', 22),  # mined savings ~22 nibbles
    ('How', 22),  # mined savings ~22 nibbles
]

# The runtime (pointer table + fullwidth-SJIS expansion strings) lives in the tail
# of the rodata font-placeholder cave after bank 7's block (see build.py MTE_BASE).
# Entries are in descending-weight order, so trim from the tail until the runtime
# fits: each entry costs 4 B (pointer) + 2*len+1 B (string + NUL).
RUNTIME_BUDGET = 2180

def _trim(entries):
    total = 0; kept = []
    for s, w in entries:
        cost = 4 + 2*len(s) + 1
        if total + cost > RUNTIME_BUDGET: break
        total += cost; kept.append((s, w))
    return kept

_ACTIVE = _trim(_ENTRIES)

def all_entries():
    """(string, weight) list; index in this list = dict code - 0x8540."""
    return list(_ACTIVE)

def code_map():
    """string -> dict code (0x8540+i)."""
    return {s: DICT_CODE_BASE + i for i, (s, _w) in enumerate(_ACTIVE)}
