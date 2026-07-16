# Mode2/Form1 EDC+ECC (Neill Corlett ECM algorithm)
edc_table=[]
for i in range(256):
    e=i
    for _ in range(8): e=(e>>1)^(0xD8018001 if e&1 else 0)
    edc_table.append(e&0xFFFFFFFF)
def edc_compute(data):
    e=0
    for b in data: e=((e>>8)^edc_table[(e^b)&0xFF])&0xFFFFFFFF
    return e
ecc_f=[0]*256; ecc_b=[0]*256
for i in range(256):
    j=((i<<1)^(0x11D if i&0x80 else 0))&0xFF
    ecc_f[i]=j; ecc_b[i^j]=i
def ecc_block(sector, maj, mino, maj_mult, min_inc, dest_off):
    size=maj*mino
    for major in range(maj):
        index=(major>>1)*maj_mult+(major&1)
        a=b=0
        for minor in range(mino):
            t=sector[0xC+index]
            index+=min_inc
            if index>=size: index-=size
            a^=t; b^=t; a=ecc_f[a]
        a=ecc_b[ecc_f[a]^b]
        sector[dest_off+major]=a
        sector[dest_off+major+maj]=(a^b)&0xFF
def fix_mode2form1(sector):
    # EDC over offset 0x10 len 0x808 -> store at 0x818 LE
    e=edc_compute(sector[0x10:0x10+0x808])
    sector[0x818]=e&0xFF; sector[0x819]=(e>>8)&0xFF
    sector[0x81A]=(e>>16)&0xFF; sector[0x81B]=(e>>24)&0xFF
    # ECC with address zeroed
    save=bytes(sector[0xC:0x10]); sector[0xC:0x10]=b'\x00\x00\x00\x00'
    ecc_block(sector,86,24,2,86,0x81C)     # P
    ecc_block(sector,52,43,86,88,0x8C8)    # Q
    sector[0xC:0x10]=save
