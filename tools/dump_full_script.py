"""Dump all source dialogue from a supported SMT2 Japan Rev 1 BIN image."""
import argparse
import sys
import struct
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SECTOR_SIZE = 2352
USER_DATA_OFFSET = 24
USER_DATA_SIZE = 2048
SLPM_SIZE = 2025472
PACKA_SIZE = 53948416

def extract_from_bin(bin_data, base_sector, file_size):
    """Read a contiguous MODE2/2352 file payload directly from a BIN image."""
    extracted = bytearray(file_size)
    for offset in range(file_size):
        image_offset = (base_sector + offset // USER_DATA_SIZE) * SECTOR_SIZE + USER_DATA_OFFSET + (offset % USER_DATA_SIZE)
        extracted[offset] = bin_data[image_offset]
    return bytes(extracted)

def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, metavar="BIN", help="source Japan Rev 1 MODE2/2352 BIN")
    parser.add_argument("--output", default="SMT2_full_script.txt", metavar="PATH", help="output text file")
    return parser.parse_args()

args = parse_args()
bin_path = Path(args.input)
if not bin_path.is_file():
    raise SystemExit(f"Source BIN not found: {bin_path}")
bin_data = bin_path.read_bytes()
SLPM = extract_from_bin(bin_data, 67202, SLPM_SIZE)
packa = extract_from_bin(bin_data, 68191, PACKA_SIZE)
def foff(a): return (a-0x80010000)+0x800
def U16(a): return struct.unpack_from("<H",SLPM,foff(a))[0]
TAB={"CD":(0x80117ec4,0x801187a4),"AB":(0x8010130c,0x80101978)}
def decode(buf,start,end,tab):
    S,Y=TAB[tab]; pos=start; hi=True; toks=[]
    while pos<end and len(toks)<600:
        node=0
        while True:
            b=buf[pos]; nib=(b>>4) if hi else (b&0xf)
            if hi: hi=False
            else: hi=True; pos+=1
            ea=(node&0xFFFE)+nib*2; nx=U16(S+ea)
            if nx==0x7fff: return toks
            if nx&0x8000: toks.append((U16(Y+ea),bool(nx&0x4000))); break
            node=nx
        if pos>=end: break
    return toks
def render(toks):
    s=""
    for sym,ctrl in toks:
        if sym==0x8140: s+="　"; continue
        if ctrl:
            try: s+="["+struct.pack(">H",sym).decode("ascii")+"]"
            except: s+=f"[{sym:04x}]"
        else:
            try: s+=struct.pack(">H",sym).decode("shift_jis")
            except: s+=f"[{sym:04x}]"
    return s
BLOCKS=[(0,"field/system",packa,0x32fb000,"CD"),(1,"field",packa,0x3302800,"CD"),
 (2,"town/NPC",packa,0x3303800,"CD"),(3,"story/demons",packa,0x330b800,"CD"),
 (4,"negotiation",packa,0x32f1000,"AB"),(5,"battle-cmd",packa,0x32f8800,"AB"),
 (6,"battle-msg",SLPM,foff(0x80115bd8),"CD"),(7,"system",SLPM,foff(0x80116f2c),"CD")]
hdr=["# Shin Megami Tensei II (PSX) — dialogue script dump",
 "# msg ID = (bank<<12)|index ; control codes shown in [..]; [Fe][SY][SN]=name/var inserts",
 "# Huffman tables: banks 4,5 use A/B; others use C/D",""]
lines=list(hdr); total=0; g=0
for bank,desc,buf,base,tab in BLOCKS:
    do=struct.unpack_from("<H",buf,base)[0]; n=(do-2)//2
    offs=struct.unpack_from("<%dH"%n,buf,base+2); tb=base+do
    lines.append(f"\n===== BANK {bank} ({desc}) — {n} messages, table {tab} =====")
    for i in range(n):
        end=tb+(offs[i+1] if i+1<n else offs[i]+0x400)
        t=decode(buf,tb+offs[i],end,tab)
        g+=sum(1 for s,c in t if not c and s!=0x8140)
        lines.append(f"{(bank<<12)|i:#06x}\t{render(t)}")
    total+=n
output_path = Path(args.output)
output_path.write_text("\n".join(lines)+"\n", encoding="utf-8")
print(f"{total} messages, ~{g} glyphs -> {output_path} ({output_path.stat().st_size}B)")
def one(bank,buf,base,tab,i):
    do=struct.unpack_from("<H",buf,base)[0]; o=struct.unpack_from("<H",buf,base+2+i*2)[0]
    nx=struct.unpack_from("<H",buf,base+2+(i+1)*2)[0]; tb=base+do
    return render(decode(buf,tb+o,tb+nx,tab))
print("ID 0x01c7 (bank0 455):",one(0,packa,0x32fb000,"CD",455))
print("ID 0x01c8 (bank0 456):",one(0,packa,0x32fb000,"CD",456))
print("ID 0x01c9 (bank0 457):",one(0,packa,0x32fb000,"CD",457)[:64])
