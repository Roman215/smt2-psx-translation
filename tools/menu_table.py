"""Rebuild the C/D menu/command string table (offset table 0x80101fe6, data
0x801020f6, 136 entries, 1250-byte data region) with English, using the English
tree. Also rebuilds the A/B menu table? No -- A/B tree is untouched (Japanese)."""
import struct, sys
sys.path.insert(0,"tools")
import build_en_tree as ET, block_rebuild as BR

MENU_OT=0x80101fe6; MENU_DATA=0x801020f6; MENU_END=0x801025d8  # A/B OT starts here
N_MENU=(MENU_DATA-MENU_OT)//2   # 136

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
 97:"Level 1 20", 98:"Level 2 30", 99:"Level 3 40", 100:"Level 4 50",
 101:"Level 1 45", 102:"Level 2 55", 103:"Level 3 65", 104:"Level 4 75",
 105:"Level 1 80", 106:"Level 2 100", 107:"Level 3 120", 108:"Level 4 140",
 109:"Level 1 100", 110:"Level 2 150", 111:"Level 3 200", 112:"Level 4 250",
 113:"Level 1 200", 114:"Level 2 300", 115:"Level 3 400", 116:"Level 4 500",
 117:"BGM4", 118:"BGM5", 119:"BGM6", 120:"BGM7", 121:"BGM8", 122:"BGM9", 123:"BGM10",
 124:"BGM11", 125:"BGM12", 126:"BGM13", 127:"BGM14", 128:"BGM15", 129:"BGM16",
 130:"BGM17", 131:"BGM18", 132:"BGM19", 133:"NORMAL", 134:"EXPERT", 135:"",
}

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
