"""SMT2 name-table translations + rebuild (re-encode w/ English tree, fit in place).
Single-level table: [N u16 offset table][data]; entry[i]=decode(base+u16[base+i*2]).
After ALL name tables are English, flip 0x80056e84 back to English decoder 0x80057fe4."""
import struct
import build_en_tree as ET, block_rebuild as BR

# ---- DEMONS: name-type 1, base 0x80102962, 311 entries (Atlus spellings) ----
DEMONS = [
 "Satan","Metatron","Kamael","Sariel","Kushiel","Ophanim","Raguel","Haniel","Tzaphkiel","Ramiel",
 "Amaterasu","Tsukuyomi","Takemikazuchi","Hinokagutsuchi","Omoikane","Tajikarao","Ameno Torifune",
 "Garuda","Suzaku","Yatagarasu","Phoenix","Suparna","Lakshmi","Parvati","Freyja","Sarasvati",
 "Arianrhod","Ame-no-Uzume","Ardha","Virocana","Kalki","Baal","Atavaka","Odin","Ashtar","Horus",
 "Thor","Indra","Barong","Genbu","Anubis","Narasinha","Sphinx","Nandi","Byakko","Pabilsag","Bastet",
 "Apis","Unicorn","Heqet","Salamander","Undine","Sylph","Gnome","Flamies","Aquans","Aeros","Earthies",
 "Shiva","Susano-o","Seiten Taisei","Chernobog","Ares","Ananta","Rahabh","Itzamna","Seiryuu",
 "Quetzalcoatl","Pek Young","Maya","Kali","Ishtar","Durga","Kikuri-hime","Hariti","Ta-weret",
 "Arahabaki","Takeminakata","O-namuchi","Kotoshironushi","Sarutahiko","Hitokotonushi","Sukunahikona",
 "O-Yamatsumi","Dominion","Virtue","Power","Principality","Archangel","Angel","Morrigan","Macha",
 "Nemhain","Aello","Kelaino","Ocypete","Bennu","Adept","Terminator","Gyrator","Temple Knight",
 "Executioner","Neophyte","Butcher","Yamata-no-Orochi","Vritra","Raja Naga","Oto-hime","Mizuchi",
 "Naga","Nozuchi","Hanuman","Ganesha","Djinn","Tengu","Haokah","Mercurius","Cerberus","Gdon","Selket",
 "Orthrus","Nekomata","Cu Sith","Cait Sith","Nyx","Vampire","Lilim","Nightmare","Empusa","Alp","Titan",
 "Ubelluris","Tsuchigumo","Duergar","Sudama","Knocker","Titania","Oberon","Cu Chulain","Nadja","Banshee",
 "Dark Elf","Jack O'Lantern","Jack Frost","High Pixie","Frankie","Demi-Nandi","Heracles","Slave",
 "Oracles","Spartan","Agares","Gaap","Berith","Baphomet","Eligor","Betelgeuse","Gagyson","Ukobach",
 "Yaksha","Shuten-Doji","Yakshini","Turdak","Hannya","Azumi","Ihika","Rangda","Volvo","Gorgon",
 "Cailleach Bheare","Arachne","Lamia","Hag","Kamen-Hijiri","Ashura","Onmyoji","Jiraiya","Kugutsushi",
 "Cthulhu","Pazuzu","Nyarlathotep","Tezcatlipoca","Naragiri","Hraesvelgr","Anzu","Gurr","Furiae",
 "Chon Chon","Medusa","Rabbi","Golem","Junk","Iron Maiden","Crazy Dummy","Police","Jaws","Hecatonchires",
 "Girimehkala","Ekimmu","Cyclops","Rakshasa","Ogre","Wendigo","Gremlin","Behemoth","Manticore","Scylla",
 "Black Widow","Gyu-Ki","Nue","Bicorn","Garm","Yggdrasil","Alraune","Mandrake","Audrey","Corpse",
 "Zombie Priest","Workaholic","Bodyconian","Zombie","Zombie Dog","Lucifer","Beelzebub","Mara","Bael",
 "Astaroth","Loki","Hecate","Tiamat","Kingu","Nidhoggr","Tarasque","Wyvern","Worm","Vetara","Yaka",
 "Man Eater","Ghoulette","Ghoul","Preta","Legion","Inferno","Depth","Hanged Man","Poltergeist","Old One",
 "Doppelganger","Black Ooze","Chris the Car","Jack the Ripper","Slime","Andromeda","Spider","Moebius",
 "--------","Red Bear","Mercurius","Basilisk","King Frost","Demi-Nandi","Betelgeuse","Daleth","Janus",
 "Zayin","Daleth","Baphomet","Sarutahiko","Daleth","Belphegor","Gimmel","Uriel","Raphael","Michael",
 "Lucifuge","Hecate","Atavaka","Master Therion","Abaddon","Astaroth","Kumbhira","Vajra","Mihira","Antila",
 "Majira","Santira","Indara","Pajra","Makura","Sindura","Catura","Vikarala","Tiamat","Virocana","Mara",
 "Lucifer","Kuzuryu","Sabaoth","Shaddai","Elohim","Satan","YHVH","YHVH","Beelzebub","Alice","Ghost Q",
 "Sage of Time","Hell's Angel","Matador","Gabriel","Gomory",
]

# ---- RACES: name-type 11, base 0x801043f8, 42 entries (game order -> Atlus race) ----
RACES = [
 "Godly","Herald","Amatsu","Avian","Megami","Deity","Avatar","Holy","Element","Fury",
 "Dragon","Lady","Kunitsu","Divine","Flight","Messian","Drake","Yoma","Beast","Night",
 "Jirae","Fairy","Demonoid","Fallen","Brute","Femme","Gaean","Vile","Raptor","Machine",
 "Vaccine","Jaki","Wilder","Wood","Undead","Tyrant","Snake","Haunt","Spirit","Foul",
 "Virus","Fiend",
]

# ---- SPELLS/SKILLS: type 7(+8), base 0x80113486, 321 entries (0-159 names, 160-320 descriptions) ----
SPELLS = [
 # 0-159 names
 "Agi","Agilao","Maragi","Maragion","Bufu","Bufula","Mabufu","Mabufula","Zio","Zionga",
 "Mazio","Mazionga","Zan","Zanma","Mazan","Mazanma","Tentarafoo","Megido","Megidolaon","Dormina",
 "Shibaboo","Pulinpa","Happirma","Marin Karin","Makajam","Mudo","Mudoon","Hama","Mahama","Tarunda",
 "Rakunda","Sukunda","Eltra","Dekaja","Dekunda","Tetraja","Tarukaja","Rakukaja","Sukukaja","Makakaja",
 "Tetra","Makarakarn","Tetrakarn","Dia","Diarama","Diarahan","Media","Mediarama","Mediarahan","Patra",
 "Me Patra","Posumudi","Paraladi","Petradi","Recarm","Samarecarm","Recarmdra","Mapper","Traesto","Traport",
 "Trafuri","Estoma","Sabatma","Necroma","Paral Eye","Petra Eye","Hell's Eye","Bael's Curse","Sexy Dance","Happy Dance",
 "Song of Joy","Lullaby","Panic Voice","Bind Voice","Bloodsucker","Fire Breath","Ice Breath","Poison Breath","Shock","Ice Bound",
 "Poison Mist","Holy Light","Evil Gleam","Fool's Voice","Devil Kiss","Devil Smile","Fog Breath","Power Breath","Dark Breath","Water Wall",
 "Fire Wall","Weird Wave","Divine Wrath","Death Touch","Devil Kiss","Howl","Reverse Spin","Hama Flash","God Voice","Sabaoth Voice",
 "Shaddai Eye","Elohim Light","God's Judgment","God Voice","Bite","Poison Bite","Paralyze Bite","Petrify Bite","Charm Bite","Scratch",
 "Poison Scratch","Paralyze Scratch","Poison Needle","Paralyze Needle","Coil","Hell Thrust","Scanning","Feather Dance","Flurry","Wind Strike",
 "Thunder Strike","Digest Fluid","Charm Mist","Wing Flap","99 Needles","Tackle","Rampage","Crush","Sweep","Showtime",
 "Punch","Backhand","Iron Fist","Akasha Arts","Kick","Roundhouse","Flying Kick","Aimed Shot","Rapid Fire","Buckshot",
 "Daruma Toss","Hades Blast","Spin Slash","Bodhi Palm","Bolt Kick","Heat Wave","Deathbound","Hell Fang","Belly Skewer","Substitute",
 "Absorb","Self-Destruct","Suck","Vacuum Throw","Rest","Suicide Wave","Avalanche","Guard","Flee","Call Ally",
 # 160-320 descriptions (terse)
 "Fire dmg, 1 foe","Stronger Agi","Agi, all foes","Stronger Maragi","Ice; 1 foe, may FREEZE","Stronger Bufu","Bufu, all foes","Stronger Mabufu","Bolt; 1 foe, may SHOCK","Stronger Zio",
 "Zio, all foes","Stronger Mazio","Shockwave, 1 foe","Stronger Zan","Zan, all foes","Stronger Mazan","PANIC, all foes","Almighty dmg, all foes","Stronger Megido","SLEEP, several foes",
 "BIND, several foes","PANIC, several foes","HAPPY, several foes","CHARM, 1 foe","CLOSE, several foes","Curse-kill 2 foes","Curse-kill several","Expel 2 foes","Hama, all foes","Lowers foe attack",
 "Lowers foe defense","Lowers foe hit rate","-----","Nulls all -kaja","Restores -nda stats","Nulls foe magic 1 turn","Raises party attack","Raises party defense","Raises party hit rate","Raises party magic",
 "Guards vs Drain","Reflects magic 1 turn","Reflects phys 1 turn","Minor HP heal, 1 ally","Big HP heal, 1 ally","Full HP heal, 1 ally","Dia, all allies","Diarama, all allies","Diarahan, all allies","Cures minor ailment",
 "Cures party ailments","Cures POISON, 1 ally","Cures PALYZE, 1 ally","Cures STONE, 1 ally","Revive 1/4 HP, 1 ally","Revive full HP, 1 ally","Sacrifice: full party HP","Shows map (till new moon)","Exit dungeon","Warp to last save",
 "Flee battle (not boss)","Fewer weak foes","Summon ally, no cost","Revive ally in battle","PALYZE, 1 foe","STONE, 1 foe","DEAD, 1 foe","FLY, 1 foe","CHARM, all foes","HAPPY, all foes",
 "HAPPY, all foes","SLEEP, all foes","PANIC, all foes","BIND, all foes","BAT, 1 foe","Fire, several foes","Ice, several foes","Dmg+POISON, several","Elec, several foes","Ice, 1 group",
 "POISON, all foes","CHARM, all foes","CHARM, all foes","CLOSE, all foes","Drain: -1 Lv (female)","Drain: -1 Lv (human)","Halves foe hit rate","Raises own atk/hit","Raises own def/mag","Fire shield",
 "Ice shield","PANIC, all foes","Dmg by alignment","Drains HP to self","Drain: -1 Lv (female)","Advances moon 4","Reset to battle start","Dmg to demons only","-----","-----",
 "-----","-----","-----","-----","Bite, 1 foe","Bite+POISON, 1 foe","Bite+PALYZE, 1 foe","Bite+STONE, 1 foe","Bite+CHARM, 1 foe","Scratch, 2 foes",
 "Scratch+POISON, 2","Scratch+PALYZE, 2","Needle+POISON, 1 foe","Needle+PALYZE, several","Coil+BIND, 1 foe","Dmg+CLOSE, 1 foe","Dmg+PALYZE, 2 foes","Dmg+PALYZE, 1 foe","Dmg+CLOSE, all foes","Dmg+FREEZE, all foes",
 "Dmg+SHOCK, all foes","Dmg+POISON, 1 foe","Dmg+CHARM, all foes","Dmg, all foes","Dmg, several foes","Charge dmg","Dmg, all foes","Crush, 1 foe","Dmg, all foes","Dmg, all foes + self",
 "Punch, 1 foe","Stronger Punch","Punch, several foes","Punch, all foes","Kick, 1 foe","Stronger Kick","Kick, several foes","Gun, 1 foe","Gun, several foes","Gun, all foes",
 "Dmg, 1 foe (by HP)","Dmg, several (by HP)","Dmg, several (by HP)","Dmg, 1 foe (by HP)","Dmg, 2 foes (by HP)","Dmg, 1 foe (by HP)","Dmg, several (by HP)","Dmg, several (by HP)","-----","Draws foe hits 1 turn",
 "Fuse 2 same demons","User LOST, ends battle","Heal 1/2 dmg dealt","Removes 1 foe","Heal 3x HP spent","-----","-----","-----","-----","-----",
 "Agi",
]

# ---- ITEMS/EQUIPMENT: types 0/3/6, base 0x80114952, 349 entries ----
ITEMS = [
 # 0-87 melee weapons
 "Attack Knife","Spike Rod","Queen Bute","Battle Hammer","Bollock Knife","Slicer","Scorpion Whip","Corseque",
 "Guillotine Axe","Bizen Dagger","Jet Bola","Aseimi Knife","Heat Glaive","Harakiri Saber","Shadow Needle","Cherry Sword",
 "Head Basher","Vacuum Axe","Chainsaw","Screw Lance","Light Kodachi","Crimson Whip","Rocket Hammer","Cursed Gear",
 "Thunder Whip","Crimson Nagamaki","Glamour Axe","Skip Hammer","Plasma Sword","Aqua Flail","Fire Standard","Vajra Club",
 "Sonic Blade","Thousand Needle","Vital Lance","Flying Sanko","Sun Kodachi","Scrap","Companion Axe","Charon's Staff",
 "Ankou's Scythe","Headhunt Spoon","Nine-Tails Whip","Answerer","Valhalla Sword","Magma Spear","Caduceus","Purify Fan",
 "Longinus","Fergus' Sword","Lotus Wand","Cursed Nihil","Luna Blade","Sol Blade","Lion War Fan","Crescent Blade",
 "Kuchinawa Sword","Houten Halberd","Deathbringer","Brionac","Gae Bolg","Gleipnir","Dagda's Club","Zuftaf Spear",
 "Ki Sword","Kogitsunemaru","Wind God Sword","Bolt God Sword","Bizen Osafune","Kotetsu","Kanesada","Hannya Nagamitsu",
 "Muramasa","Masamune","Kenunmaru","Konryumaru","Yatsuka Sword","Ama-Murakumo","Ama-Nuboko","Hinokagutsuchi",
 "Old Ki Staff","Bound Ki Staff","Death Ki Staff","Ai Ki Staff","Prime Ki Staff","Ame Sword","Masakado Blade","Kurikara Sword",
 # 88-127 guns + ammo
 "Beretta 92F","Desert Eagle","Miracle Glock","Gonz Pistol","Dominator","Gyro Jet","M16 Rifle","Smile Steyr",
 "M249 Minimi","SPAS 12","Oni Cannon","Reaper Colt","Bullet M90","Golden Gun","M134 Vulcan","Giga Smasher",
 "Kunitomo Gun","Railgun","Bodribin","Blaster Gun","Randal Custom","Megido Fire","Peacemaker","Brahmastra",
 "Normal Ammo","Poison Ammo","Shot Shell","Randy Shot","Nerve Ammo","Cursed Ammo","Cup Killer","Holy Ammo",
 "Seal Ammo","Plutonium Ammo","Carbo Liner","Corona Shot","Light Ammo","Dark Ammo","Corrode Ammo","Skull Ammo",
 # 128-207 armor (helm/body/gauntlet/greaves)
 "Headgear","Fritz Helm","Nap Guard","Metal Turban","Iron Bunny","Frog Helm","Dolphin Helm","Ping-Pong Hat",
 "Iron Face","Dragon Helm","Dawn Helm","Shiranui Helm","Panzer Helm","Jagd Helm","Sturm Helm","Tenma Helm",
 "Masakado Helm","Zipanium Helm","Jesus Helm","Huaton","Survival Vest","Amigo Poncho","High-Leg Armor","Kaiser Armor",
 "Sun Armor","Lion Happi","Rearguard Armor","Skull Gi","Tetra Jammer","Dragon Mail","Dawn Armor","Flame Armor",
 "Panzer Suit","Jagd Armor","Sturm Suit","Tenma Armor","Masakado Armor","Zipanium Suit","Jesus Armor","Tapsuan",
 "Leather Glove","Star Glove","Rivet Knuckle","Jamming Arm","Arm Bridge","Whirl Gauntlet","Blade Gauntlet","Power Gauntlet",
 "Revenge Gauntlet","Draupnir","Dawn Gauntlet","Blaze Gauntlet","Panzer Fist","Jagd Glove","Sturm Glove","Tenma Gauntlet",
 "Masakado Glove","Zipanium Glove","Jesus Glove","Parhurat","Leather Boots","Legger Slam","Happy Sandals","Titanium Boots",
 "Dancing Heels","Aero Jet","Crescent Greaves","Climb Shoes","Bell Greaves","Dragon Boots","Dawn Greaves","Blaze Greaves",
 "Panzer Leg","Jagd Leg","Sturm Leg","Tenma Greaves","Masakado Greaves","Zipanium Leg","Jesus Leg","Kamraiterao",
 # 208-254 consumables
 "Mazio Stone","Mabufu Stone","Maragi Stone","Spiral Bomb","Punch Gun","Poison Dish","Segaki Rice","Secret Needle",
 "Hama Arrow","Poison Arrow","Medicine","Jewel","Distone","Disparalyze","Dispoison","Recall Orb",
 "Amida Beads","React Sheet","Seal Bell","Saint's Flute","Hiranya","Magic Stone","Muscle Drinko","Soma",
 "Elixir","Revive Incense","Luck Incense","Vitality Incense","Wisdom Incense","Str Incense","Speed Incense","Magic Incense",
 "Blue Scroll","Asura's Palm","Angel Hair","Buddha Statue","Rosary","Melt Orb","Hyper Drop","Core Shield",
 "Red Scroll","Balloon Shield","Mist Jar","Bronze Box","Survey Bell","Amulet","Metal Card",
 # 255-299 key items + gems
 "-----","Invitation","Citizen ID","Laughing Doll","Crying Doll","Angry Doll","Dancing Doll","Sleeping Doll",
 "Mekata's Memo","Fickle Dew","Masakado Body","Lord's Head","Lord's Torso","Lord's R.Arm","Lord's L.Arm","Lord's R.Leg",
 "Lord's L.Leg","Sun Pillar","Moon Pillar","Mars Pillar","Mercury Pillar","Jupiter Pillar","Venus Pillar","Saturn Pillar",
 "Masakado Blade","Ain Key","Lamed Key","MAG Presser","Hagoromo","Hihiirokane","Invitation","Invitation",
 "Invitation","Amethyst","Aquamarine","Emerald","Onyx","Opal","Garnet","Sapphire","Diamond","Turquoise","Topaz","Pearl","Ruby",
 # 300-348 descriptions (terse)
 "Sacred stone:\nMazio","Sacred stone:\nMabufu","Sacred stone:\nMaragi","SLEEP,\nseveral foes","Blows 1 foe\nout of battle","Curse-kills\n2 foes","Expel 2 foes\n(Hama)","Curse-kills\nseveral foes",
 "Almighty dmg,\nall foes","POISON,\nall foes","Minor HP heal,\n1 ally","Full HP heal,\n1 ally","Cures STONE,\n1 ally","Cures PALYZE,\n1 ally","Cures POISON,\n1 ally","Revive 1/4 HP,\n1 ally",
 "Avoids Drain\n(non-Law)","Summon ally,\nno COMP","Fewer\nweak foes","Reflects DARK\nphys 1 turn","Heals HP/MP,\n1 ally","Heals 25% max\nHP, 1 ally","Big HP heal\n(side effect?)","Full HP/MP,\ncure ailments",
 "Revive 1/8 HP,\n1 ally","Revive full\nHP, 1 ally","Full heal,\n+1 Luck","Full heal,\n+1 Vitality","Full heal,\n+1 Wisdom","Full heal,\n+1 Strength","Full heal,\n+1 Speed","Full heal,\n+1 Magic",
 "Random heal\nspell effect","Heals CHAOS,\nharms others","Heals LAW,\nharms others","Auto-revive\n(non-Law)","Guards Drain,\nauto-revive Law","1/4 chance:\nslime all foes","Big HP heal\n(side effect!)","Nulls damage\nzone (1 moon)",
 "Random attack\nspell effect","Nulls foe\nattack once","Preemptive\nstrikes (1 moon)","Summons a\nregistered demon","Auto-maps\n5x5 area","Nulls floor\ndamage zone","Card for\nCode Breaker","-----","Attack Knife",
]

# ---- MISC single-level tables ----
LOCATIONS = [  # type4 base 0x801132f2, 16
 "Valhalla","Center","Holy Town","Factory","Arcadia","Shinjuku","Akasaka","Roppongi",
 "Tiferet","Yesod","Geburah","Binah","Ark","Okamoto Gym","Kongo Realm","Chokmah Twr",
]
NPCS = [  # type12 base 0x801119f2, 23. MUST fit 0x801119f2..0x80111ad8 (battle data follows!)
 "Dandy","Old Man","Madwoman","Shady Man","Templar","Center Gal","Gentleman","Vagrant",
 "Warrior","Drunk","Blond Man","Junkman","Laborer","Workwoman","Drunkard","Old Dwarf",
 "Boss Dwarf","Kobold Y.","Kobold G.","Fiend Man","Fiendess","Ghoul","Skeleton",
]
DRINKS = [  # type14 base 0x80113388, 9
 "Valhalla Sling","Intelli Dry","Magical Fizz","Muscle High","Speed Cocktail","Miracle Tonic",
 "Happirma Soda","Temple Shake","Super Milk",
]
# TRAITS: type13 OT=0x801034da DATA=0x801036da, 256 entries but 41 unique (dedup on rebuild).
# Map JP (CR shown as /) -> concise English (\n = line break).
TRAITS_MAP = {
 "破魔が無効":"Null Expel","破魔・物理に強い":"Str: Expel, Phys","魔法に強い":"Str: Magic",
 "突撃を吸収/魔法に強い":"Absorb Charge\nStr: Magic","呪殺・魔力に弱く/ガンに強い":"Wk: Death, Magic\nStr: Gun",
 "神経・呪殺/魔力・緊縛に強い":"Str: Nerve, Death,\nMagic, Bind","呪殺を反射/電撃に強い":"Reflect Death\nStr: Elec",
 "火炎吸収/打撃系技反射":"Absorb Fire\nReflect Strike","ガン以外の/物理攻撃に強い":"Str: Phys (not Gun)",
 "火炎・破魔に弱く/神経に強い":"Wk: Fire, Expel\nStr: Nerve","破魔・呪殺/魔力を反射":"Reflect Expel,\nDeath, Magic",
 "電撃反射/破魔に強い":"Reflect Elec\nStr: Expel","電撃・衝撃/物理に強い":"Str: Elec, Force,\nPhys",
 "氷結吸収/火炎に弱い":"Absorb Ice\nWk: Fire","物理に強く/魔力に弱い":"Str: Phys\nWk: Magic","物理に強い":"Str: Phys",
 "電撃に弱い":"Wk: Elec","剣に強く/他の物理無効":"Str: Sword\nNull other Phys","魔法を反射/物理に弱い":"Reflect Magic\nWk: Phys",
 "魔法吸収/物理に弱い":"Absorb Magic\nWk: Phys","電撃に強い":"Str: Elec","火炎吸収/氷結に弱い":"Absorb Fire\nWk: Ice",
 "火炎・氷結/電撃に弱い":"Wk: Fire, Ice,\nElec","全体的に強い/破魔が無効":"Str overall\nNull Expel","火炎に強い":"Str: Fire",
 "氷結反射/火炎に弱い":"Reflect Ice\nWk: Fire","物理を反射/魔法に弱い":"Reflect Phys\nWk: Magic",
 "物理に強く/電撃に弱い":"Str: Phys\nWk: Elec","破魔に弱く/物理に強い":"Wk: Expel\nStr: Phys",
 "神経・破魔/魔力が無効":"Null Nerve,\nExpel, Magic","火炎を吸収/氷結に弱い":"Absorb Fire\nWk: Ice",
 "電撃を吸収/衝撃に弱い":"Absorb Elec\nWk: Force","火炎反射/氷結に弱い":"Reflect Fire\nWk: Ice",
 "電撃に弱く/破魔に強い":"Wk: Elec\nStr: Expel","破魔・魔力/緊縛に弱い":"Wk: Expel,\nMagic, Bind",
 "精神系魔法を反射/物理に弱い":"Reflect Mind\nWk: Phys","火炎・氷結/呪殺反射/破魔に弱い":"Refl Fire,Ice\nDeath\nWk: Expel",
 "衝撃・突撃に強い":"Str: Force, Charge","氷結に強い":"Str: Ice","火炎・氷結に強く/物理に弱い":"Str: Fire, Ice\nWk: Phys",
 "呪殺が効きにくい":"Resist Death",
}

def rebuild_split(exe, ot_base, data_base, entries, alloc_end, PATHS):
    """Split OT/data (traits): offset[i] at ot_base+i*2 is DATA-relative; entry[i]=decode(data_base+offset[i]). Dedup."""
    def foff(a): return (a-0x80010000)+0x800
    blob=bytearray(); pos_of={}; offs=[]
    for s in entries:
        if s not in pos_of:
            pos_of[s]=len(blob); blob+=enc_string(s,PATHS)
        offs.append(pos_of[s])
    end=data_base+len(blob)
    if end>alloc_end: raise SystemExit(f"OVERFLOW {end:#x}>{alloc_end:#x} (+{end-alloc_end})")
    for i,o in enumerate(offs): struct.pack_into("<H",exe,foff(ot_base+i*2),o)
    for i,byte in enumerate(blob): exe[foff(data_base)+i]=byte
    return len(blob), alloc_end-data_base

def rebuild_dedup(exe, base, entries, alloc_end, PATHS):
    """Single-level with dedup: identical strings share one data offset. entry[i]=decode(base+u16[base+i*2])."""
    def foff(a): return (a-0x80010000)+0x800
    N=len(entries); ot_bytes=N*2
    blob=bytearray(); pos_of={}
    offs=[]
    for s in entries:
        if s not in pos_of:
            pos_of[s]=ot_bytes+len(blob); blob+=enc_string(s,PATHS)
        offs.append(pos_of[s])
    total=ot_bytes+len(blob)
    if base+total>alloc_end: raise SystemExit(f"OVERFLOW {base+total:#x}>{alloc_end:#x} (+{base+total-alloc_end})")
    for i,o in enumerate(offs): struct.pack_into("<H",exe,foff(base+i*2),o)
    for i,byte in enumerate(blob): exe[foff(base+ot_bytes)+i]=byte
    return total, alloc_end-base

def enc_string(s, PATHS):
    toks=[]
    for c in s:
        if c=='\n': toks.append((0x4352,True))   # CR (line break)
        else: toks.append((ET.fullwidth(c),False))
    toks.append((0x4544,True))  # ED
    nibs=[]
    for t in toks: nibs+=PATHS[t]
    data=bytearray(); b=0; hi=True
    for n in nibs:
        if hi: b=(n&0xf)<<4; hi=False
        else: data.append(b|(n&0xf)); hi=True
    if not hi: data.append(b)
    return bytes(data)

def rebuild_single(exe, base, entries, alloc_end, PATHS):
    """Rebuild single-level table [N u16 offsets][data] at base, fit within alloc_end."""
    def foff(a): return (a-0x80010000)+0x800
    N=len(entries)
    ot_bytes=N*2
    blob=bytearray(); offs=[]
    for s in entries:
        offs.append(ot_bytes+len(blob)); blob+=enc_string(s,PATHS)
    total=ot_bytes+len(blob)
    if base+total>alloc_end: raise SystemExit(f"OVERFLOW {base+total:#x}>{alloc_end:#x} (+{base+total-alloc_end})")
    for i,o in enumerate(offs): struct.pack_into("<H",exe,foff(base+i*2),o)
    for i,byte in enumerate(blob): exe[foff(base+ot_bytes)+i]=byte
    return total, alloc_end-base

def rebuild_twolevel(exe, base, entries, alloc_end, PATHS):
    """Two-level: [u16 data_off][N u16 per-entry offsets][data]. entry[i]=decode(base+data_off+u16[base+(i+1)*2])."""
    def foff(a): return (a-0x80010000)+0x800
    N=len(entries)
    data_off=(N+1)*2
    blob=bytearray(); offs=[]
    for s in entries:
        offs.append(len(blob)); blob+=enc_string(s,PATHS)
    total=data_off+len(blob)
    if base+total>alloc_end: raise SystemExit(f"OVERFLOW {base+total:#x}>{alloc_end:#x} (+{base+total-alloc_end})")
    struct.pack_into("<H",exe,foff(base),data_off)
    for i,o in enumerate(offs): struct.pack_into("<H",exe,foff(base+(i+1)*2),o)
    for i,byte in enumerate(blob): exe[foff(base+data_off)+i]=byte
    return total, alloc_end-base
