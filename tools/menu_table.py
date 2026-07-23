"""Rebuild both executable-resident menu/command string tables.

The 136-entry C/D table uses the C/D Huffman tree.  Demon negotiation uses a
separate 115-entry table and the A/B tree; that table must be rebuilt whenever
the English A/B tree changes or its choices decode as garbage.
"""
import re, struct, sys
sys.path.insert(0,"tools")
import build_en_tree as ET, block_rebuild as BR

MENU_OT=0x80101fe6; MENU_DATA=0x801020f6; MENU_END=0x801025d8  # A/B OT starts here
N_MENU=(MENU_DATA-MENU_OT)//2   # 136

AB_MENU_OT=0x801025d8
AB_MENU_STOCK_DATA=0x801026be
N_AB_MENU=(AB_MENU_STOCK_DATA-AB_MENU_OT)//2   # 115
# The English table is larger than the stock 674-byte allocation.  Its u16
# offsets may address non-adjacent storage, so use both the unused tail of the
# rebuilt A/B symbol table and the original data area.  Individual strings
# never cross the gap.  build.py checks that the tree ends before the first
# region; 0x80101e00 also leaves a small guard band after the current tree.
AB_MENU_DATA=0x80101e00
AB_MENU_REGIONS=(
    (AB_MENU_DATA,0x80101fe4),
    (AB_MENU_STOCK_DATA,0x80102960),
)
# Both negotiation menu readers form the stock data address with addiu.  Their
# high half remains 0x8010, so only the validated low immediate changes.
AB_MENU_DATA_REFS={
    0x800670d4:0x24b026be,
    0x800671bc:0x24a626be,
}
AB_MENU_END_TOKEN=(0x8140,True,0x0f)

# Demon negotiation uses the first group of the common 1-4-row choice-window
# descriptors.  Stock presents it as a small floating box, which both clips
# long English responses and leaves an awkward amount of the underlying full
# dialogue box visible.  Restyle it as a fixed lower response panel aligned to
# that dialogue box's inner rectangle.  This mirrors the
# battle UI's illusion of a short prompt panel sitting above a covering overlay;
# menus with fewer than four choices simply leave unused space in the response
# panel instead of changing its outer height.
#
# Some reachable prompts occupy two dialogue rows, so the panel begins one 13px
# row below stock.  Move its frame, text surface, glyphs, and highlight together.
# The window renderer draws its left/top bevel inward but extends its right/bottom
# bevel four pixels beyond the supplied endpoint.  End the fill at x=300/y=220
# so the complete visible bevel lands at x=304/y=224 instead of disappearing
# beneath the full-screen frame.  Keep the response rows four pixels inside it.
AB_MENU_WINDOW_LEFT=16
AB_MENU_WINDOW_RIGHT=300
AB_MENU_WINDOW_TOP=166
AB_MENU_WINDOW_BOTTOM=220
AB_MENU_TEXT_X=20
AB_MENU_TEXT_WIDTH=276
AB_MENU_TEXT_Y0=168
AB_MENU_STOCK_WINDOW_LEFT=96
AB_MENU_STOCK_WINDOW_RIGHT=224
AB_MENU_STOCK_WINDOW_TOP=153
AB_MENU_STOCK_TEXT_X=100
AB_MENU_STOCK_TEXT_WIDTH=120
AB_MENU_STOCK_TEXT_Y0=155
# The labels are rendered into a separate 128x52 object surface whose stock
# screen origin is (96,153).  Each row begins with a raw ``mu 4,y`` position
# command, so the visible glyph origin is surface_x+4.  Move and enlarge the
# surface along with the window, but stop at the texture-page boundary.  Its
# source begins at U=24 and PSX texture U coordinates are 8-bit, leaving 232px
# before they wrap to U=0.  A 256px sprite sampled those preceding 24px again
# at screen x=248..271; stale text there could expose the start of a player
# name (such as "Th" from "Theodore") at the panel's lower right.  The widest
# English label is well below the remaining 228px glyph area.
AB_MENU_SURFACE_X=AB_MENU_WINDOW_LEFT
AB_MENU_TEXTURE_U=24
AB_MENU_SURFACE_WIDTH=256-AB_MENU_TEXTURE_U
AB_MENU_SURFACE_Y=AB_MENU_WINDOW_TOP
AB_MENU_STOCK_SURFACE_X=AB_MENU_STOCK_WINDOW_LEFT
AB_MENU_STOCK_SURFACE_WIDTH=AB_MENU_STOCK_WINDOW_RIGHT-AB_MENU_STOCK_WINDOW_LEFT
AB_MENU_STOCK_SURFACE_Y=AB_MENU_STOCK_WINDOW_TOP
AB_MENU_WINDOW_RECTS=(
    (0x800eeee0,166), (0x800eeee8,153),  # one-row open and closed
    (0x800eef1c,179), (0x800eef24,153),  # two rows
    (0x800eef58,192), (0x800eef60,153),  # three rows
    (0x800eef94,205), (0x800eef9c,153),  # four rows
)
AB_MENU_TEXT_ROWS=tuple(0x800f7bbc+8*row for row in range(4))
AB_MENU_SURFACE_X_FIELDS=(0x800ef03a,0x800ef048,0x800ef05c)
AB_MENU_SURFACE_Y_FIELDS=(0x800ef03c,0x800ef04a,0x800ef05e)
AB_MENU_SURFACE_WIDTH_FIELDS=(0x800eefe4,0x800ef050,0x800ef064,0x800ef090)
AB_MENU_TEXTURE_U_FIELDS=(0x800ef04c,0x800ef060)
VWF_WIDTH_TABLE=0x800d7300

# index -> English (Atlus-style). "" = keep empty. Keep under data budget.
MENU={
 0:"", 1:"Call Ally", 2:"Return Ally", 3:"Dismiss Ally", 4:"Analyze Spell",
 5:"Auto-Map", 6:"Devil Analysis", 7:"Config", 8:"Analyze Item", 9:"Set Marker",
 10:"Use", 11:"Sort", 12:"Arrange", 13:"Discard", 14:"Equip", 15:"Unequip",
 16:"Buy", 17:"Sell", 18:"Explain", 19:"View Status", 20:"Leave Shop",
 21:"RAM Check", 22:"Item", 23:"Equipment", 24:"Drink", 25:"Listen",
 26:"Restore HP/MP", 27:"Buy Item", 28:"Heal Status", 29:"View Status",
 30:"Revive", 31:"Exit", 32:"Uncurse", 33:"Save", 34:"Training",
 35:"Plasma Sword", 36:"Gyro Jet", 37:"Giga Smasher", 38:"Railgun", 39:"Blaster Gun",
 40:"Haggle", 41:"Threaten", 42:"Give Up", 43:"Drag Out", 44:"Enter Name",
 45:"Destroy COMP", 46:"Virtual Battle", 47:"LEVEL 1", 48:"LEVEL 2", 49:"LEVEL 3",
 50:"Fuse 2 Demons", 51:"Fuse 3 Demons", 52:"Fuse 2 Swords", 53:"LEVEL 4",
 54:"Cathedral", 55:"LAW", 56:"CHAOS", 57:"Battle", 58:"BGM1", 59:"BGM2", 60:"BGM3",
 61:"Friendly", 62:"Threatening", 63:"Game Start", 64:"Hear Advice", 65:"Teleport",
 66:"Sword-Demon Fuse", 67:"2 Sword-Demon", 68:"Trade for Coins",
 69:"Trade for Items", 70:"Trade for Spirits", 71:"Code Breaker",
 72:"Slot 1", 73:"Slot 2", 74:"Slot 3", 75:"KENO", 76:"Baccarat",
 77:"Big or Small", 78:"Russian Roulette", 79:"Slot Check 1", 80:"Slot Check 2",
 81:"Slot Check 3", 82:"Casino Call 0", 83:"Casino Call 1", 84:"Tiferet",
 85:"Netzach", 86:"Hod", 87:"Yesod", 88:"Machine 1", 89:"Machine 2", 90:"Machine 3",
 91:"Machine 4", 92:"Go Back", 93:"Repair Garage", 94:"Use Terminal", 95:"Return",
 96:"Gaia Temple",
 97:"Level 1 - 20ћ", 98:"Level 2 - 30ћ", 99:"Level 3 - 40ћ", 100:"Level 4 - 50ћ",
 101:"Level 1 - 45ћ", 102:"Level 2 - 55ћ", 103:"Level 3 - 65ћ", 104:"Level 4 - 75ћ",
 105:"Level 1 - 80ћ", 106:"Level 2 - 100ћ", 107:"Level 3 - 120ћ", 108:"Level 4 - 140ћ",
 109:"Level 1 - 100ћ", 110:"Level 2 - 150ћ", 111:"Level 3 - 200ћ", 112:"Level 4 - 250ћ",
 113:"Level 1 - 200ћ", 114:"Level 2 - 300ћ", 115:"Level 3 - 400ћ", 116:"Level 4 - 500ћ",
 117:"BGM4", 118:"BGM5", 119:"BGM6", 120:"BGM7", 121:"BGM8", 122:"BGM9", 123:"BGM10",
 124:"BGM11", 125:"BGM12", 126:"BGM13", 127:"BGM14", 128:"BGM15", 129:"BGM16",
 130:"BGM17", 131:"BGM18", 132:"BGM19", 133:"NORMAL", 134:"EXPERT", 135:"",
}

# Negotiation response labels.  These are indexed independently from MENU;
# for example, entries 92/93 are the Friendly/Intimidating pair shown after
# "How will you respond?". The layout verifier below ensures every label fits.
AB_MENU=(
 "Smile", "Pretend to flinch", "Flatter", "Stare", "Soothe", "Laugh",
 "Approach", "Ignore", "Introduce yourself", "Ask to join", "Macca",
 "Magnetite", "Go away", "Yes", "No", "Perform a trick", "Dance",
 "Imitate", "Acrobatics", "Do it", "Stop", "Join me",
 "Give me something", "A demon", "A girl", "Charming", "Frightening",
 "Just prey", "Because I like you", "It was fate",
 "For everyone's happiness", "Nothing in particular", "I was captivated",
 "Because I need you", "Frightening", "Just a hobby", "Threaten with gun",
 "Glare", "Chase", "Give up", "Goodbye", "Wait", "Not worth mentioning",
 "Scold", "I don't trust you", "Come here",
 "Humans and demons are friends", "Show a skill", "Sing", "Speed-eat",
 "Quick draw", "Break a boulder", "Laugh again", "Laugh proudly",
 "You're right", "You're wrong", "Persuade", "Fight", "Chuckle",
 "Compliment", "Grin", "Angry face", "That's right", "Maybe", "Say it",
 "Refuse", "I'll make it worth your while", "That won't happen", "That's right",
 "Nothing special", "Ask", "Smirk", "I guess", "Not really",
 "Warning shot", "Let's stay friends", "Apologize", "I want to live",
 "Charming", "Useful", "A funny story", "A rumor", "About life",
 "The Messiah", "Me", "Just a human", "Make money", "Be free", "Nothing",
 "Maybe so", "Absolutely not", "What do you mean?", "Friendly",
 "Intimidating", "Put it to rest", "Let it eat", "Something nice",
 "Gladly", "Thank you", "More than a name", "Myself", "Act affectionate",
 "You're a champ", "Sulk", "You got me", "Just saying hello",
 "I need to talk", "Don't mess with me", "Just business",
 "In my pocket", "Accept the challenge", "Look away", "Of course", "An item",
 "Smile",
)
if len(AB_MENU)!=N_AB_MENU:
    raise ValueError(f"A/B menu entry count {len(AB_MENU)} != {N_AB_MENU}")

def _foff(address):
    return address-0x80010000+0x800

def _width_index(code):
    """Mirror the dialogue VWF hook's ``(lead-0x81)*256 + trail`` lookup."""
    return ((code>>8)-0x81)*256+(code&0xff)

def ab_menu_text_width(exe,text):
    """Measure a label with the installed 12x12 dialogue VWF table."""
    total=0
    for char in text:
        index=_width_index(ET.fullwidth(char))
        if not 0<=index<512:
            raise ValueError(f"A/B menu character outside VWF table: {char!r}")
        total+=exe[_foff(VWF_WIDTH_TABLE)+index]
    return total

def widest_ab_menu_entry(exe):
    return max(
        ((ab_menu_text_width(exe,text),index,text) for index,text in enumerate(AB_MENU)),
        key=lambda entry:entry[0],
    )

def _verify_ab_menu_sentence_case():
    proper_words={"I","Messiah"}
    for index,text in enumerate(AB_MENU):
        words=re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?",text)
        unexpected=[word for word in words[1:] if word[0].isupper() and word not in proper_words]
        if unexpected:
            raise SystemExit(
                f"A/B menu {index} is not sentence case: {text!r} ({unexpected!r})"
            )

def verify_ab_menu_layout(exe):
    def u16(address): return struct.unpack_from("<H",exe,_foff(address))[0]
    for address,stock_bottom in AB_MENU_WINDOW_RECTS:
        got=tuple(u16(address+2*field) for field in range(4))
        bottom=(
            AB_MENU_WINDOW_TOP
            if stock_bottom==AB_MENU_STOCK_WINDOW_TOP
            else AB_MENU_WINDOW_BOTTOM
        )
        want=(
            AB_MENU_WINDOW_LEFT,
            AB_MENU_WINDOW_TOP,
            AB_MENU_WINDOW_RIGHT,
            bottom,
        )
        if got!=want:
            raise SystemExit(f"A/B choice window {address:#x}: {got!r} != {want!r}")
    for row,address in enumerate(AB_MENU_TEXT_ROWS):
        got=tuple(u16(address+2*field) for field in range(4))
        want=(AB_MENU_TEXT_X,AB_MENU_TEXT_Y0+12*row,AB_MENU_TEXT_WIDTH,12)
        if got!=want:
            raise SystemExit(f"A/B choice row {address:#x}: {got!r} != {want!r}")
    for address in AB_MENU_SURFACE_X_FIELDS:
        got=u16(address)
        if got!=AB_MENU_SURFACE_X:
            raise SystemExit(
                f"A/B text surface origin {address:#x}: "
                f"{got} != {AB_MENU_SURFACE_X}"
            )
    for address in AB_MENU_SURFACE_Y_FIELDS:
        got=u16(address)
        if got!=AB_MENU_SURFACE_Y:
            raise SystemExit(
                f"A/B text surface y origin {address:#x}: "
                f"{got} != {AB_MENU_SURFACE_Y}"
            )
    for address in AB_MENU_SURFACE_WIDTH_FIELDS:
        got=u16(address)
        if got!=AB_MENU_SURFACE_WIDTH:
            raise SystemExit(
                f"A/B text surface width {address:#x}: "
                f"{got} != {AB_MENU_SURFACE_WIDTH}"
            )
    for address in AB_MENU_TEXTURE_U_FIELDS:
        got=exe[_foff(address)]
        if got!=AB_MENU_TEXTURE_U:
            raise SystemExit(
                f"A/B text surface texture U {address:#x}: "
                f"{got} != {AB_MENU_TEXTURE_U}"
            )
    if AB_MENU_TEXTURE_U+AB_MENU_SURFACE_WIDTH>256:
        raise SystemExit("A/B text surface wraps across its texture-page boundary")
    widest,index,text=widest_ab_menu_entry(exe)
    available=min(AB_MENU_TEXT_WIDTH,AB_MENU_SURFACE_WIDTH-4)
    if widest>available:
        raise SystemExit(
            f"A/B menu {index} {text!r} is {widest}px, wider than "
            f"the {available}px choice-text region"
        )
    _verify_ab_menu_sentence_case()

def patch_ab_menu_layout(exe):
    """Widen and lower the shared dialogue-choice response box."""
    def u16(address): return struct.unpack_from("<H",exe,_foff(address))[0]
    def w16(address,value): struct.pack_into("<H",exe,_foff(address),value)
    for address,stock_bottom in AB_MENU_WINDOW_RECTS:
        got=tuple(u16(address+2*field) for field in range(4))
        want=(
            AB_MENU_STOCK_WINDOW_LEFT,
            AB_MENU_STOCK_WINDOW_TOP,
            AB_MENU_STOCK_WINDOW_RIGHT,
            stock_bottom,
        )
        if got!=want:
            raise SystemExit(f"A/B stock choice window {address:#x}: {got!r} != {want!r}")
        w16(address,AB_MENU_WINDOW_LEFT)
        w16(address+2,AB_MENU_WINDOW_TOP)
        w16(address+4,AB_MENU_WINDOW_RIGHT)
        w16(
            address+6,
            AB_MENU_WINDOW_TOP
            if stock_bottom==AB_MENU_STOCK_WINDOW_TOP
            else AB_MENU_WINDOW_BOTTOM,
        )
    for row,address in enumerate(AB_MENU_TEXT_ROWS):
        got=tuple(u16(address+2*field) for field in range(4))
        want=(AB_MENU_STOCK_TEXT_X,AB_MENU_STOCK_TEXT_Y0+12*row,AB_MENU_STOCK_TEXT_WIDTH,12)
        if got!=want:
            raise SystemExit(f"A/B stock choice row {address:#x}: {got!r} != {want!r}")
        w16(address,AB_MENU_TEXT_X)
        w16(address+2,AB_MENU_TEXT_Y0+12*row)
        w16(address+4,AB_MENU_TEXT_WIDTH)
    for address in AB_MENU_SURFACE_X_FIELDS:
        got=u16(address)
        if got!=AB_MENU_STOCK_SURFACE_X:
            raise SystemExit(
                f"A/B stock text surface origin {address:#x}: "
                f"{got} != {AB_MENU_STOCK_SURFACE_X}"
            )
        w16(address,AB_MENU_SURFACE_X)
    for address in AB_MENU_SURFACE_Y_FIELDS:
        got=u16(address)
        if got!=AB_MENU_STOCK_SURFACE_Y:
            raise SystemExit(
                f"A/B stock text surface y origin {address:#x}: "
                f"{got} != {AB_MENU_STOCK_SURFACE_Y}"
            )
        w16(address,AB_MENU_SURFACE_Y)
    for address in AB_MENU_SURFACE_WIDTH_FIELDS:
        got=u16(address)
        if got!=AB_MENU_STOCK_SURFACE_WIDTH:
            raise SystemExit(
                f"A/B stock text surface width {address:#x}: "
                f"{got} != {AB_MENU_STOCK_SURFACE_WIDTH}"
            )
        w16(address,AB_MENU_SURFACE_WIDTH)
    for address in AB_MENU_TEXTURE_U_FIELDS:
        got=exe[_foff(address)]
        if got!=AB_MENU_TEXTURE_U:
            raise SystemExit(
                f"A/B stock text surface texture U {address:#x}: "
                f"{got} != {AB_MENU_TEXTURE_U}"
            )
    if AB_MENU_TEXTURE_U+AB_MENU_SURFACE_WIDTH>256:
        raise SystemExit("A/B text surface wraps across its texture-page boundary")
    verify_ab_menu_layout(exe)

def _ab_menu_tokens(text):
    return tuple((ET.fullwidth(ch),False) for ch in text)+(AB_MENU_END_TOKEN,)

def ab_menu_token_streams():
    """Return the physically unique plain-glyph streams for A/B tree mining.

    The two stock menu decoders copy nominal leaf symbols directly rather than
    invoking control handlers, so dictionary leaves cannot be used here.
    """
    return list(dict.fromkeys(_ab_menu_tokens(text) for text in AB_MENU))

def verify_ab_menu(exe):
    """Decode every rebuilt negotiation label with the installed A/B tree."""
    def foff(address): return (address-0x80010000)+0x800
    def u16(address): return struct.unpack_from("<H",exe,foff(address))[0]
    def u32(address): return struct.unpack_from("<I",exe,foff(address))[0]

    for site,stock_word in AB_MENU_DATA_REFS.items():
        expected=(stock_word&0xffff0000)|(AB_MENU_DATA&0xffff)
        if u32(site)!=expected:
            raise SystemExit(
                f"A/B menu data reference {site:#x}: {u32(site):#010x} != {expected:#010x}"
            )

    for index,want in enumerate(map(_ab_menu_tokens,AB_MENU)):
        pos=AB_MENU_DATA+u16(AB_MENU_OT+2*index)
        high=True; node=0; got=[]
        for _step in range(1000):
            if not any(start<=pos<end for start,end in AB_MENU_REGIONS):
                raise SystemExit(f"A/B menu {index}: decode escaped its allocation")
            byte=exe[foff(pos)]
            nibble=(byte>>4) if high else (byte&0x0f)
            high=not high
            if high: pos+=1
            entry=(node&0xfffe)+2*nibble
            struct_value=u16(0x8010130c+entry)
            if struct_value==0x7fff:
                raise SystemExit(f"A/B menu {index}: invalid Huffman branch")
            if struct_value&0x8000:
                symbol=u16(0x80101978+entry)
                token=(symbol,True,struct_value&0x3fff) if struct_value&0x4000 else (symbol,False)
                got.append(token)
                if struct_value&0x4000: break
                node=0
            else:
                node=struct_value
        else:
            raise SystemExit(f"A/B menu {index}: unterminated Huffman stream")
        if tuple(got)!=want:
            raise SystemExit(f"A/B menu {index}: decode mismatch {got!r} != {want!r}")
    verify_ab_menu_layout(exe)

def rebuild_ab_menu(exe, paths):
    """Encode the English negotiation labels with plain A/B-tree leaves."""
    def foff(address): return (address-0x80010000)+0x800
    def u32(address): return struct.unpack_from("<I",exe,foff(address))[0]
    encoded_entries=[]
    for index,text in enumerate(AB_MENU):
        tokens=_ab_menu_tokens(text)
        nibbles=[]
        for token in tokens:
            if token not in paths:
                raise SystemExit(f"A/B menu {index}: tree lacks token {token!r}")
            nibbles.extend(paths[token])
        encoded=bytearray(); byte=0; high=True
        for nibble in nibbles:
            if high:
                byte=(nibble&0x0f)<<4; high=False
            else:
                encoded.append(byte|(nibble&0x0f)); high=True
        if not high: encoded.append(byte)
        encoded_entries.append(bytes(encoded))

    offsets=[]; interned={}; cursors=[start for start,_end in AB_MENU_REGIONS]
    used=0
    for index,encoded in enumerate(encoded_entries):
        if encoded in interned:
            offsets.append(interned[encoded]-AB_MENU_DATA)
            continue
        for region,(start,end) in enumerate(AB_MENU_REGIONS):
            if cursors[region]+len(encoded)<=end:
                address=cursors[region]
                cursors[region]+=len(encoded)
                break
        else:
            budget=sum(end-start for start,end in AB_MENU_REGIONS)
            raise SystemExit(f"A/B menu table OVERFLOW near entry {index} ({used}>{budget})")
        interned[encoded]=address
        offsets.append(address-AB_MENU_DATA)
        used+=len(encoded)

    budget=sum(end-start for start,end in AB_MENU_REGIONS)
    for index,offset in enumerate(offsets):
        struct.pack_into("<H",exe,foff(AB_MENU_OT+2*index),offset)
    for site,stock_word in AB_MENU_DATA_REFS.items():
        found=u32(site)
        if found!=stock_word:
            raise SystemExit(
                f"A/B menu data reference {site:#x}: stock word "
                f"{found:#010x} != {stock_word:#010x}"
            )
        patched=(stock_word&0xffff0000)|(AB_MENU_DATA&0xffff)
        struct.pack_into("<I",exe,foff(site),patched)
    for start,end in AB_MENU_REGIONS:
        exe[foff(start):foff(end)]=bytes(end-start)
    for encoded,address in interned.items():
        exe[foff(address):foff(address)+len(encoded)]=encoded
    patch_ab_menu_layout(exe)
    verify_ab_menu(exe)
    return used,budget

def rebuild_menu(exe, PATHS, overrides=None):
    def foff(a): return (a-0x80010000)+0x800
    ED=(0x4544,True)
    def enc(s):
        toks=[(ET.fullwidth(c),False) for c in s]+[ED]
        nibs=[]
        for t in toks: nibs+=PATHS[t]
        data=bytearray(); b=0; hi=True
        for n in nibs:
            if hi: b=(n&0xf)<<4; hi=False
            else: data.append(b|(n&0xf)); hi=True
        if not hi: data.append(b)
        return bytes(data)
    offs=[]; blob=bytearray()
    overrides = overrides or {}
    for i in range(N_MENU):
        offs.append(len(blob)); blob+=enc(overrides.get(i, MENU.get(i,"")))
    budget=MENU_END-MENU_DATA
    if len(blob)>budget: raise SystemExit(f"menu table OVERFLOW {len(blob)}>{budget}")
    for i,o in enumerate(offs): struct.pack_into("<H",exe,foff(MENU_OT+i*2),o)
    for i,byte in enumerate(blob): exe[foff(MENU_DATA)+i]=byte
    return len(blob),budget
