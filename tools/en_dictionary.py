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
    (' you', 1560),  # mined savings ~1560 nibbles
    (' the ', 1380),  # mined savings ~1380 nibbles
    (' the', 884),  # mined savings ~884 nibbles
    ('Underworld', 840),  # mined savings ~840 nibbles
    ('you', 827),  # mined savings ~827 nibbles
    ('the ', 815),  # mined savings ~815 nibbles
    ('ing ', 792),  # mined savings ~792 nibbles
    (' yo', 781),  # mined savings ~781 nibbles
    ('ing', 605),  # mined savings ~605 nibbles
    (' will', 567),  # mined savings ~567 nibbles
    ('Man: ', 560),  # mined savings ~560 nibbles
    ('You ', 524),  # mined savings ~524 nibbles
    ('Lucifer', 497),  # mined savings ~497 nibbles
    ('Millennium', 486),  # mined savings ~486 nibbles
    ('an: ', 434),  # mined savings ~434 nibbles
    ('will', 400),  # mined savings ~400 nibbles
    ('The ', 394),  # mined savings ~394 nibbles
    ('Center', 388),  # mined savings ~388 nibbles
    (' to ', 383),  # mined savings ~383 nibbles
    ('Valhalla', 378),  # mined savings ~378 nibbles
    ('Lucif', 370),  # mined savings ~370 nibbles
    ('You', 351),  # mined savings ~351 nibbles
    (' for', 340),  # mined savings ~340 nibbles
    ('Messia', 328),  # mined savings ~328 nibbles
    (' be', 321),  # mined savings ~321 nibbles
    ('Voice:', 315),  # mined savings ~315 nibbles
    ('ight', 306),  # mined savings ~306 nibbles
    ('emon', 306),  # mined savings ~306 nibbles
    ('Okamoto', 301),  # mined savings ~301 nibbles
    (' was ', 291),  # mined savings ~291 nibbles
    (' is ', 290),  # mined savings ~290 nibbles
    ('ve ', 285),  # mined savings ~285 nibbles
    ('me ', 280),  # mined savings ~280 nibbles
    ('Champion', 280),  # mined savings ~280 nibbles
    (' my ', 273),  # mined savings ~273 nibbles
    ('com', 264),  # mined savings ~264 nibbles
    ('What', 262),  # mined savings ~262 nibbles
    ('underground', 261),  # mined savings ~261 nibbles
    ('very', 258),  # mined savings ~258 nibbles
    ("'s ", 257),  # mined savings ~257 nibbles
    (' and ', 256),  # mined savings ~256 nibbles
    ('Kuzuryu', 252),  # mined savings ~252 nibbles
    (' ca', 245),  # mined savings ~245 nibbles
    ("n't ", 242),  # mined savings ~242 nibbles
    ('my ', 224),  # mined savings ~224 nibbles
    ('Thank', 224),  # mined savings ~224 nibbles
    ('from', 222),  # mined savings ~222 nibbles
    ("I'm ", 216),  # mined savings ~216 nibbles
    ('here', 215),  # mined savings ~215 nibbles
    ('ver', 212),  # mined savings ~212 nibbles
    ('Factory', 208),  # mined savings ~208 nibbles
    ('place', 204),  # mined savings ~204 nibbles
    ('again', 204),  # mined savings ~204 nibbles
    (' of', 202),  # mined savings ~202 nibbles
    (',000', 200),  # mined savings ~200 nibbles
    (', but', 200),  # mined savings ~200 nibbles
    ('people', 200),  # mined savings ~200 nibbles
    ('Please', 200),  # mined savings ~200 nibbles
    ('Lord ', 198),  # mined savings ~198 nibbles
    ('ack', 194),  # mined savings ~194 nibbles
    ('with', 194),  # mined savings ~194 nibbles
    (' this', 192),  # mined savings ~192 nibbles
    ('er: ', 186),  # mined savings ~186 nibbles
    ('......', 186),  # mined savings ~186 nibbles
    ('app', 180),  # mined savings ~180 nibbles
    ('ough', 180),  # mined savings ~180 nibbles
    ('      ', 180),  # mined savings ~180 nibbles
    (' I ', 175),  # mined savings ~175 nibbles
    ('Masakado', 175),  # mined savings ~175 nibbles
    ('power', 168),  # mined savings ~168 nibbles
    (' wo', 157),  # mined savings ~157 nibbles
    ('Keter Castle', 156),  # mined savings ~156 nibbles
    (' that', 152),  # mined savings ~152 nibbles
    ('Colosseum', 152),  # mined savings ~152 nibbles
    (' me', 148),  # mined savings ~148 nibbles
    ('Puck', 145),  # mined savings ~145 nibbles
    (' ma', 139),  # mined savings ~139 nibbles
    ('way', 138),  # mined savings ~138 nibbles
    ('ly ', 138),  # mined savings ~138 nibbles
    ('return', 138),  # mined savings ~138 nibbles
    ('Arcadia', 138),  # mined savings ~138 nibbles
    ('savior', 136),  # mined savings ~136 nibbles
    ("I'll", 135),  # mined savings ~135 nibbles
    (' we', 132),  # mined savings ~132 nibbles
    ('This', 132),  # mined savings ~132 nibbles
    ('STEVEN', 130),  # mined savings ~130 nibbles
    (' wh', 129),  # mined savings ~129 nibbles
    ('ake', 128),  # mined savings ~128 nibbles
    ('Wom', 128),  # mined savings ~128 nibbles
    ('efeat', 126),  # mined savings ~126 nibbles
    ('They', 120),  # mined savings ~120 nibbles
    ('Anyth', 120),  # mined savings ~120 nibbles
    ('already', 120),  # mined savings ~120 nibbles
    ('buy?', 116),  # mined savings ~116 nibbles
    ("'re ", 116),  # mined savings ~116 nibbles
    ('Hiruko', 115),  # mined savings ~115 nibbles
    ('trength', 115),  # mined savings ~115 nibbles
    ('ong', 114),  # mined savings ~114 nibbles
    ('Tiferet', 114),  # mined savings ~114 nibbles
    ('Madam', 108),  # mined savings ~108 nibbles
    ('Abaddon', 108),  # mined savings ~108 nibbles
    ('must', 106),  # mined savings ~106 nibbles
    ('now', 105),  # mined savings ~105 nibbles
    ('btained', 105),  # mined savings ~105 nibbles
    ('like', 104),  # mined savings ~104 nibbles
    ('one ', 102),  # mined savings ~102 nibbles
    ('body', 102),  # mined savings ~102 nibbles
    (' God', 102),  # mined savings ~102 nibbles
    ('ave', 99),  # mined savings ~99 nibbles
    ('Satan', 99),  # mined savings ~99 nibbles
    ('But', 96),  # mined savings ~96 nibbles
    ('Bishop', 96),  # mined savings ~96 nibbles
    (' are', 95),  # mined savings ~95 nibbles
    ('Shady ', 95),  # mined savings ~95 nibbles
    ('final', 93),  # mined savings ~93 nibbles
    (' Coins', 92),  # mined savings ~92 nibbles
    ('ive', 90),  # mined savings ~90 nibbles
    ('not ', 90),  # mined savings ~90 nibbles
    (' has ', 90),  # mined savings ~90 nibbles
    ('nce', 89),  # mined savings ~89 nibbles
    ('own', 88),  # mined savings ~88 nibbles
    ('acc', 88),  # mined savings ~88 nibbles
    (': W', 88),  # mined savings ~88 nibbles
    (': H', 88),  # mined savings ~88 nibbles
    ('Then', 88),  # mined savings ~88 nibbles
    (' all', 88),  # mined savings ~88 nibbles
    ('sell?', 87),  # mined savings ~87 nibbles
    ('ome', 85),  # mined savings ~85 nibbles
    ('man', 84),  # mined savings ~84 nibbles
    ('EVE', 84),  # mined savings ~84 nibbles
    (' co', 84),  # mined savings ~84 nibbles
    ('That', 84),  # mined savings ~84 nibbles
    ('ange', 82),  # mined savings ~82 nibbles
    ('mber', 81),  # mined savings ~81 nibbles
    ('ther', 80),  # mined savings ~80 nibbles
    ('pass', 80),  # mined savings ~80 nibbles
    ('even', 80),  # mined savings ~80 nibbles
    ('mor', 77),  # mined savings ~77 nibbles
    ('My ', 76),  # mined savings ~76 nibbles
    ('open', 76),  # mined savings ~76 nibbles
    ('judg', 76),  # mined savings ~76 nibbles
    (' any', 76),  # mined savings ~76 nibbles
    ('Now', 74),  # mined savings ~74 nibbles
    ('e...', 74),  # mined savings ~74 nibbles
    (' wa', 72),  # mined savings ~72 nibbles
    ('work', 72),  # mined savings ~72 nibbles
    ('I am', 72),  # mined savings ~72 nibbles
    ('COMP', 72),  # mined savings ~72 nibbles
    ('and ', 71),  # mined savings ~71 nibbles
    (' him', 70),  # mined savings ~70 nibbles
    ('ch ', 69),  # mined savings ~69 nibbles
    ('for', 67),  # mined savings ~67 nibbles
    ('ћ10', 66),  # mined savings ~66 nibbles
    ('ble', 65),  # mined savings ~65 nibbles
    ('par', 60),  # mined savings ~60 nibbles
    ('exp', 60),  # mined savings ~60 nibbles
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
