"""Rebuild both executable-resident menu/command string tables.

The 136-entry C/D table uses the C/D Huffman tree.  Demon negotiation uses a
separate 115-entry table and the A/B tree; that table must be rebuilt whenever
the English A/B tree changes or its choices decode as garbage.
"""
import struct, sys
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
# "How will you respond?". Keep the wording concise for the narrow choice box.
AB_MENU=(
 "Smile", "Pretend to Flinch", "Flatter", "Stare", "Soothe", "Laugh",
 "Approach", "Ignore", "Introduce Yourself", "Ask to Join", "Macca",
 "Magnetite", "Go Away", "Yes", "No", "Perform a Trick", "Dance",
 "Imitate", "Acrobatics", "Do It", "Stop", "Join Me",
 "Give Me Something", "A Demon", "A Girl", "Charming", "Frightening",
 "Just Prey", "Because I Like You", "It Was Fate",
 "For Everyone's Happiness", "No Reason", "I Was Captivated",
 "Because I Need You", "Frightening", "Just a Hobby", "Threaten with Gun",
 "Glare", "Chase", "Give Up", "Goodbye", "Wait", "Not Worth Mentioning",
 "Scold", "I Don't Trust You", "Come Here",
 "Humans and Demons Are Friends", "Show a Skill", "Sing", "Speed-Eat",
 "Quick Draw", "Break a Boulder", "Laugh Again", "Laugh Proudly",
 "You're Right", "You're Wrong", "Persuade", "Fight", "Chuckle",
 "Compliment", "Grin", "Angry Face", "That's Right", "Maybe", "Say It",
 "Refuse", "I'll Return the Favor", "That Won't Happen", "Yes",
 "Nothing Special", "Ask", "Smirk", "I Guess", "Not Really",
 "Warning Shot", "Let's Stay Friends", "Apologize", "I Want to Live",
 "Charming", "Useful", "A Funny Story", "A Rumor", "About Life",
 "The Messiah", "Me", "Just a Human", "Make Money", "Be Free", "Nothing",
 "Maybe So", "Absolutely Not", "What Do You Mean?", "Friendly",
 "Intimidating", "Lay Them to Rest", "Feed Them", "Something Nice",
 "Gladly", "Thank You", "More Than a Name", "Myself", "Act Affectionate",
 "You're a Champ", "Sulk", "You Got Me", "Just Saying Hello",
 "I Have Something to Say", "Don't Mess with Me", "Just Business",
 "In My Pocket", "Accept the Challenge", "Look Away", "Of Course", "Item",
 "Smile",
)
if len(AB_MENU)!=N_AB_MENU:
    raise ValueError(f"A/B menu entry count {len(AB_MENU)} != {N_AB_MENU}")

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
    verify_ab_menu(exe)
    return used,budget

def rebuild_menu(exe, PATHS):
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
    for i in range(N_MENU):
        offs.append(len(blob)); blob+=enc(MENU.get(i,""))
    budget=MENU_END-MENU_DATA
    if len(blob)>budget: raise SystemExit(f"menu table OVERFLOW {len(blob)}>{budget}")
    for i,o in enumerate(offs): struct.pack_into("<H",exe,foff(MENU_OT+i*2),o)
    for i,byte in enumerate(blob): exe[foff(MENU_DATA)+i]=byte
    return len(blob),budget
