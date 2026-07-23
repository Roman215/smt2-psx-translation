"""Cathedral Demon Compendium gameplay enhancement.

The normal translation build applies this enhancement by default.  Passing
``--no-enhancements`` leaves the executable and save behavior unchanged.

Persistence reuses bit 7 of the game's existing 256-byte, per-demon analysis
counter at 0x801fc128.  That byte is already included in the stock 0x3260-byte
save payload, so the patch does not enlarge, relocate, or otherwise alter the
memory-card format.  The remaining seven bits continue to be available to the
stock counter.  Existing saves migrate demons already held in the roster when
the Cathedral menu is rendered.

The stock save writer RLE-compresses this payload but falls back to the raw
0x3260 bytes whenever compression would be larger; its record capacity is
0x32fb bytes.  Registration can therefore never overflow a save record.
"""

import hashlib
import struct


EXE_BASE = 0x8000F800

# The unused tail of Shift-JIS font row 0x84 (Greek/Cyrillic glyphs).  The
# English build never emits these characters, and unlike executable padding
# this atlas is immutable after the EXE is loaded.  Mednafen snapshots from
# both ordinary play and the Cathedral confirm that the complete reservation
# remains byte-for-byte identical to the disc image at runtime.
#
# The first implementation used zero-filled space at 0x8011be00.  That looked
# like a conventional code cave on disc but is actually runtime workspace;
# entering the Cathedral after it had been populated executed a BREAK word.
CAVE = 0x800D6D20
CAVE_CODE_END = 0x800D7208
PROMPT = 0x800D7208
ORIGINAL_PROMPT = 0x800D7224
FLAG = 0x800D7240
RESULT = 0x800D7244
OLD_SELECTION = 0x800D7248
MENU_COUNT = 0x800D724C
# End on glyph 694 exactly, immediately before the established VWF cave.
CAVE_END = 0x800D7254
CAVE_SOURCE_SHA256 = "95df4aea925f93f1dd3fd7276523231c66155450416e054016b24347d97ba74d"

# The Compendium map-name layout ends four bytes after its last current string
# at 0x800d7fec.  Reserve the aligned tail through the next established cave
# for the selection-aware price formatter.  This second span remains immutable
# font data at runtime and receives the same pristine-source guard as CAVE.
EXTRA_CAVE = 0x800D7FF0
EXTRA_CAVE_END = 0x800D8100
EXTRA_CAVE_SOURCE_SHA256 = "84279fe81250071f4ae1c9e00a4c403bdd34f6797013e94549af8f27e2098565"
# The supplemental cave contains the Cathedral UI guards and dynamic price
# formatter.
RETIRE_CATHEDRAL_DIALOGUE = EXTRA_CAVE + 52
DYNAMIC_PROMPT = EXTRA_CAVE + 68

# The demon-selection browser keeps one shared bottom-panel prompt slot per
# situation.  Runtime tracing (savestate 12) shows the mode flag 0x800ea3b8 is
# already set when the analysis window draws its prompt, so with command 0xfb
# the string it prints is the item-target slot at file 0x1848 ("Use it on
# whom?"), not the Analyze slot at 0x182c.  The Summon prompt therefore has to
# be swapped into 0x1848 while the browser is open.  The 28-byte copy window
# spills 8 bytes into the following "Mimic whom?" slot at 0x185c; that prompt
# cannot be displayed while the compendium browser is running, and the exit
# path restores the original bytes.
PROMPT_SLOT = EXE_BASE + 0x1848

# The Cathedral has a three-entry menu early in the game and switches to a
# six-entry form once the additional fusion modes are unlocked.
MENU_SCRIPT_EARLY = 0x80107DFA
MENU_SCRIPT_FULL = 0x80107E0C
# This shared lead-in writes message 0x014c ("What is your desire?") and then
# selects the progression-appropriate choice table above.
CATHEDRAL_MENU_REENTRY = 0x80107DF0
MENU_ENTRY = 135
EXIT_ENTRY = 31
CATHEDRAL_EXIT_BRANCH = 0x08BE
SENTINEL = 0xFFFF

PARTY = 0x801FC8A8
DEMON_FLAGS = 0x801FC128
# Verified against savestates: the user's 448 Macca is the word at 0x801fc354
# and the 9999 Magnetite is the word right after it at 0x801fc358.  The first
# implementation used 0x801fc358 and therefore charged Magnetite.
MACCA = 0x801FC354
DEMON_BASE_STATS = 0x801046DE
# Byte count of demons currently in the packed roster (slots 2..count+1).
# Every party list iterates exactly this many records, so a demon record
# created without updating it is invisible everywhere.
ROSTER_DEMON_COUNT = 0x800D256A
# Stock "give the party demon ID a0" helper: appends the record at the packed
# roster tail, copies the demon's display name into the per-slot name array,
# increments both roster counters, and refreshes the derived slot index.  Used
# by the game's own demon-granting flows (e.g. the Virtual Battle roster).
GRANT_DEMON = 0x8001975C
# The legacy check address remains only so the savestate migration helper can
# remove the prototype's sort-menu bypass hook before installing current code.
LEGACY_SORT_MENU_CHECK = 0x8002EF98
SORTED_DEMON_IDS = 0x80124090
# Devil Analysis' list-window object.  The stock selection handler reads the
# absolute highlighted index at +0x8e (unlike +0x80, which is only the cursor's
# visible row and would become wrong after scrolling a longer list).
ANALYSIS_LIST_WINDOW = 0x800EC484
SORT_UI_SELECTION = ANALYSIS_LIST_WINDOW + 0x8E
ANALYSIS_LIST_UPDATE_CALL = 0x80031174
# The Cathedral's event choices and persistent room-dialogue compositor share
# UI texture storage with Devil Analysis' blue sort chooser.  Both must be
# suppressed while the browser is active or the sort labels appear in the
# lower dialogue panel as well.
CATHEDRAL_CHOICE_WINDOW = 0x800EDE60
CATHEDRAL_DIALOGUE_UPDATE_CALL = 0x80041264
LEGACY_LOWER_SORT_RENDER = 0x80043964
PROMPT_RENDER_CALL = 0x80030E6C
PROMPT_RENDER = 0x8002F124


def prepare_translations(translations):
    """Make the stock summoning rejection valid for every enhanced check.

    The Compendium reuses message 0x0008 for both the original alignment
    restriction and its protagonist-level restriction.  Keep the
    no-enhancements translation build untouched, but use a neutral explanation
    in the default enhanced build so both situations read correctly.
    """
    previous = translations[0x0008]
    translations[0x0008] = ["That demon can't be summoned.", "ED"]
    return previous


def restore_translations(translations, previous):
    """Undo :func:`prepare_translations` for in-process build callers."""
    translations[0x0008] = previous


def _foff(address):
    return address - EXE_BASE


class _Asm:
    """Tiny label-aware assembler for the handful of R3000A ops used here."""

    R = {
        "zero": 0, "at": 1, "v0": 2, "v1": 3,
        "a0": 4, "a1": 5, "a2": 6, "a3": 7,
        "t0": 8, "t1": 9, "t2": 10, "t3": 11,
        "t4": 12, "t5": 13, "t6": 14, "t7": 15,
        "s0": 16, "s1": 17, "s2": 18, "s3": 19,
        "s4": 20, "s5": 21, "s6": 22, "s7": 23,
        "t8": 24, "t9": 25, "k0": 26, "k1": 27,
        "gp": 28, "sp": 29, "fp": 30, "ra": 31,
    }

    def __init__(self, base):
        self.base = base
        self.items = []
        self.labels = {}

    @property
    def pc(self):
        return self.base + 4 * len(self.items)

    def label(self, name):
        if name in self.labels:
            raise ValueError(f"duplicate label {name}")
        self.labels[name] = self.pc

    def word(self, value):
        self.items.append(value & 0xFFFFFFFF)

    def _i(self, op, rs, rt, imm):
        self.word((op << 26) | (self.R[rs] << 21) | (self.R[rt] << 16) | (imm & 0xFFFF))

    def _r(self, rs, rt, rd, sa, fn):
        self.word((self.R[rs] << 21) | (self.R[rt] << 16) |
                  (self.R[rd] << 11) | (sa << 6) | fn)

    def nop(self): self.word(0)
    def lui(self, rt, imm): self._i(0x0F, "zero", rt, imm)
    def addiu(self, rt, rs, imm): self._i(0x09, rs, rt, imm)
    def andi(self, rt, rs, imm): self._i(0x0C, rs, rt, imm)
    def ori(self, rt, rs, imm): self._i(0x0D, rs, rt, imm)
    def sltiu(self, rt, rs, imm): self._i(0x0B, rs, rt, imm)
    def lw(self, rt, off, rs): self._i(0x23, rs, rt, off)
    def sw(self, rt, off, rs): self._i(0x2B, rs, rt, off)
    def lbu(self, rt, off, rs): self._i(0x24, rs, rt, off)
    def lhu(self, rt, off, rs): self._i(0x25, rs, rt, off)
    def sb(self, rt, off, rs): self._i(0x28, rs, rt, off)
    def sh(self, rt, off, rs): self._i(0x29, rs, rt, off)
    def sll(self, rd, rt, sa): self._r("zero", rt, rd, sa, 0)
    def addu(self, rd, rs, rt): self._r(rs, rt, rd, 0, 0x21)
    def subu(self, rd, rs, rt): self._r(rs, rt, rd, 0, 0x23)
    def sltu(self, rd, rs, rt): self._r(rs, rt, rd, 0, 0x2B)
    def multu(self, rs, rt): self._r(rs, rt, "zero", 0, 0x19)
    def divu(self, rs, rt): self._r(rs, rt, "zero", 0, 0x1B)
    def mfhi(self, rd): self._r("zero", "zero", rd, 0, 0x10)
    def mflo(self, rd): self._r("zero", "zero", rd, 0, 0x12)
    def move(self, rd, rs): self.addu(rd, rs, "zero")
    def jr(self, rs): self._r(rs, "zero", "zero", 0, 8)

    def j(self, target):
        self.word((0x02 << 26) | ((target >> 2) & 0x03FFFFFF))

    def jal(self, target):
        self.word((0x03 << 26) | ((target >> 2) & 0x03FFFFFF))

    def beq(self, rs, rt, label):
        self.items.append(("branch", 0x04, rs, rt, label, self.pc))

    def bne(self, rs, rt, label):
        self.items.append(("branch", 0x05, rs, rt, label, self.pc))

    def blob(self):
        out = bytearray()
        for item in self.items:
            if isinstance(item, tuple):
                _kind, op, rs, rt, label, pc = item
                target = self.labels[label]
                delta = (target - (pc + 4)) >> 2
                if not -0x8000 <= delta <= 0x7FFF:
                    raise ValueError(f"branch to {label} is out of range")
                word = (op << 26) | (self.R[rs] << 21) | (self.R[rt] << 16) | (delta & 0xFFFF)
            else:
                word = item
            out += struct.pack("<I", word)
        return bytes(out)


def _hi(address):
    return ((address >> 16) + (1 if address & 0x8000 else 0)) & 0xFFFF


def _lo(address):
    return address & 0xFFFF


def _load_addr(a, reg, address):
    a.lui(reg, _hi(address))
    a.addiu(reg, reg, _lo(address))


def _expect(exe, address, expected, description):
    actual = bytes(exe[_foff(address):_foff(address) + len(expected)])
    if actual != expected:
        raise SystemExit(
            f"compendium: {description} at {address:#x}: expected "
            f"{expected.hex()}, got {actual.hex()}"
        )


def _patch_jump(exe, address, target):
    struct.pack_into("<I", exe, _foff(address),
                     (0x02 << 26) | ((target >> 2) & 0x03FFFFFF))
    struct.pack_into("<I", exe, _foff(address + 4), 0)


def _patch_call(exe, address, target):
    struct.pack_into("<I", exe, _foff(address),
                     (0x03 << 26) | ((target >> 2) & 0x03FFFFFF))


def _emit_code():
    a = _Asm(CAVE)

    # The event menu encodes count-minus-one.  Identify either progression
    # form of the Cathedral menu, remember its live entry count, then expose
    # one synthetic final entry.
    a.label("menu_start")
    a.lbu("a2", 1, "a1")
    _load_addr(a, "t0", MENU_SCRIPT_EARLY)
    a.beq("a1", "t0", "menu_start_cathedral")
    # Preserve the renderer's return address in a register untouched by the
    # leaf roster migrator. This delay slot runs for both Cathedral layouts.
    a.move("t5", "ra")
    _load_addr(a, "t0", MENU_SCRIPT_FULL)
    a.bne("a1", "t0", "menu_start_other")
    a.nop()
    a.label("menu_start_cathedral")
    # Register the held roster as soon as the enhanced Cathedral menu is
    # rendered, before the player can enter fusion and consume ingredients.
    a.jal(0)  # fixed to migrate_roster
    migrate_call_index = len(a.items) - 1
    a.nop()
    a.move("ra", "t5")
    a.addiu("t3", "a2", 1)
    _load_addr(a, "t0", FLAG)
    a.sw("t3", MENU_COUNT - FLAG, "t0")
    a.addiu("a2", "a2", 1)
    a.addiu("t1", "zero", 1)
    a.sw("t1", 0, "t0")
    a.j(0x8005B920)
    a.move("s6", "v1")
    a.label("menu_start_other")
    _load_addr(a, "t0", FLAG)
    a.sw("zero", 0, "t0")
    a.j(0x8005B920)
    a.move("s6", "v1")

    # The real progression-dependent entries have been consumed when s0
    # reaches the saved count. Their original Exit row is patched into Demon
    # Compendium below, so synthesize Exit as the new final row and retain its
    # stock branch offset without reading into the following script command.
    a.label("menu_loop")
    _load_addr(a, "t0", FLAG)
    a.lw("t1", 0, "t0")
    a.addiu("t2", "zero", 1)
    a.bne("t1", "t2", "menu_loop_stock")
    a.nop()
    a.lw("t2", MENU_COUNT - FLAG, "t0")
    a.nop()
    a.bne("s0", "t2", "menu_loop_stock")
    a.nop()
    a.lui("t0", 0x8010)
    a.addiu("t0", "t0", -0x7B7C)
    a.sll("t1", "s0", 2)
    a.addu("t0", "t0", "t1")
    a.lw("a0", 0, "t0")
    a.addiu("a1", "zero", EXIT_ENTRY)
    a.jal(0x80067168)
    a.nop()
    a.addiu("t1", "zero", CATHEDRAL_EXIT_BRANCH)
    # s3 has advanced once per real row and now addresses this synthetic
    # row's branch-offset slot.
    a.sh("t1", 0, "s3")
    a.addiu("s0", "s0", 1)
    a.j(0x8005BA28)
    a.nop()
    a.label("menu_loop_stock")
    a.lbu("v0", 0x17A8, "a1")
    a.j(0x8005B984)
    a.nop()

    # Choice resolution is deferred until after the Cathedral script has
    # restarted, so the menu callback is not the point which consumes this
    # row.  Instead, intercept the main event update immediately before it
    # executes the unique target produced by base + 0xffff.  Requiring our
    # Cathedral flag as well makes the otherwise-valid address harmless in
    # every stock event script.
    a.label("event_update")
    a.lw("a0", 0x15E0, "v0")
    _load_addr(a, "t0", FLAG)
    a.lw("t1", 0, "t0")
    # The stock Analysis browser yields through the normal frame updater while
    # it remains on this call stack.  Suppress recursive event interpretation
    # for that interval or the synthetic pointer is executed as field script.
    a.addiu("t2", "zero", 1)
    # ADDIU also fills the load-delay slot for t1.  FLAG is written only as
    # 0 (inactive), 1 (Cathedral menu) or 2 (Analysis browser active).
    a.beq("t1", "t2", "event_update_active")
    a.nop()
    a.bne("t1", "zero", "event_update_done")
    a.nop()
    a.label("event_update_stock")
    a.jal(0x800574EC)
    a.nop()
    a.j(0x800545BC)
    a.nop()
    a.label("event_update_active")
    _load_addr(a, "t0", 0x80107568 + SENTINEL)
    a.bne("a0", "t0", "event_update_stock")
    a.nop()
    a.jal(0)  # fixed to compendium after labels are known
    compendium_call_index = len(a.items) - 1
    a.nop()
    # Replay the shared Cathedral prompt before rebuilding the menu. Returning
    # directly to either choice table leaves Analysis' sort text in the shared
    # dialogue texture in place of "What is your desire?".
    _load_addr(a, "v1", CATHEDRAL_MENU_REENTRY)
    a.lui("t0", 0x801D)
    a.sw("v1", 0x15E0, "t0")
    a.sw("v1", 0x15E8, "t0")
    a.label("event_update_done")
    a.j(0x800545BC)
    a.nop()

    # Reuse Devil Analysis as a blocking, scrollable browser.  Its normal
    # setup and teardown are much safer than maintaining a second list UI.
    a.label("compendium")
    compendium_address = a.labels["compendium"]
    a.addiu("sp", "sp", -0x20)
    a.sw("ra", 0x1C, "sp")
    a.sw("s0", 0x18, "sp")
    _load_addr(a, "s0", FLAG)
    a.addiu("v0", "zero", 2)
    a.sw("v0", 0, "s0")
    # Close the Cathedral event-choice layer and present one clean frame before
    # Devil Analysis captures the Cathedral scene as its background.
    a.jal(EXTRA_CAVE)
    a.nop()
    _load_addr(a, "t0", RESULT)
    a.sw("zero", 0, "t0")
    a.lui("t0", 0x8020)
    a.lhu("v0", -0x2700, "t0")
    _load_addr(a, "t1", OLD_SELECTION)
    a.sh("v0", 0, "t1")
    # 0xfb is the system dispatcher's internal Devil Analysis command.  This
    # is deliberately not MENU[6]: that 6 is only the translated label's
    # string-table index, while dispatching command 6 runs an unrelated UI
    # teardown path and silently returns to the field.
    a.addiu("v0", "zero", 0xFB)
    a.sh("v0", -0x2700, "t0")
    _load_addr(a, "a0", PROMPT)
    a.jal(0)  # fixed to copy_prompt
    prompt_install_call_index = len(a.items) - 1
    a.nop()
    a.jal(0x8007ED40)
    a.nop()
    _load_addr(a, "a0", ORIGINAL_PROMPT)
    a.jal(0)  # fixed to copy_prompt
    prompt_restore_call_index = len(a.items) - 1
    a.nop()
    a.lui("t0", 0x8020)
    _load_addr(a, "t1", OLD_SELECTION)
    a.lhu("v0", 0, "t1")
    a.sh("v0", -0x2700, "t0")
    # Retire the contaminated room-dialogue surface before making its updater
    # visible again. This also skips the stock close delay which otherwise
    # exposes copied sort labels before a rejection message is written.
    a.jal(RETIRE_CATHEDRAL_DIALOGUE)
    a.sw("zero", 0, "s0")
    _load_addr(a, "t0", RESULT)
    a.lw("a0", 0, "t0")
    a.nop()
    a.beq("a0", "zero", "compendium_done")
    a.nop()
    a.jal(0x80056840)
    a.nop()
    a.label("compendium_done")
    a.lw("ra", 0x1C, "sp")
    a.lw("s0", 0x18, "sp")
    a.jr("ra")
    a.addiu("sp", "sp", 0x20)

    # This stock call runs at the end of Devil Analysis' own list-update task,
    # after it has recomputed +0x8e from the scroll offset and visible cursor.
    # Preserve its list-object argument and caller return address, refresh the
    # prompt, then tail-call the displaced stock state test so its return value
    # reaches the original caller unchanged.
    a.label("price_update")
    a.addiu("sp", "sp", -8)
    a.sw("ra", 4, "sp")
    a.sw("a0", 0, "sp")
    a.jal(DYNAMIC_PROMPT)
    a.nop()
    a.lw("a0", 0, "sp")
    a.lw("ra", 4, "sp")
    a.j(0x8004BD34)
    a.addiu("sp", "sp", 8)

    # Mark every normal demon already present in the fourteen-record roster.
    # Slots zero and one are the human protagonist/partner and are skipped.
    a.label("migrate_roster")
    migrate_address = a.labels["migrate_roster"]
    _load_addr(a, "t0", PARTY + 2 * 0x70)
    a.addiu("t1", "zero", 2)
    a.label("migrate_loop")
    # Empty roster records have demon ID zero.  The real demon table's entry
    # zero is Satan (never a recruitable party member), so the ID is a safer
    # presence test here than transient roster status flags while a facility
    # is changing modes.
    a.lhu("t2", 8, "t0")
    # Advance the slot counter in the load-delay slot.  It now describes the
    # next record, which is exactly what the loop test below needs.
    a.addiu("t1", "t1", 1)
    a.beq("t2", "zero", "migrate_next")
    a.sltiu("t3", "t2", 0xFF)
    a.beq("t3", "zero", "migrate_next")
    a.nop()
    _load_addr(a, "t3", DEMON_FLAGS)
    a.addu("t3", "t3", "t2")
    a.lbu("t4", 0, "t3")
    a.nop()
    a.ori("t4", "t4", 0x80)
    a.sb("t4", 0, "t3")
    a.label("migrate_next")
    a.sltiu("t2", "t1", 14)
    a.bne("t2", "zero", "migrate_loop")
    a.addiu("t0", "t0", 0x70)
    a.jr("ra")
    a.nop()

    # Availability predicate used by the Devil Analysis list builders.
    a.label("availability")
    _load_addr(a, "t0", FLAG)
    a.lw("t1", 0, "t0")
    a.addiu("t2", "zero", 2)
    a.bne("t1", "t2", "availability_stock")
    a.andi("v0", "a0", 0xFFFF)
    a.sltiu("v1", "v0", 0xFF)
    a.beq("v1", "zero", "availability_false")
    a.nop()
    _load_addr(a, "t0", DEMON_FLAGS)
    a.addu("t0", "t0", "v0")
    a.lbu("v1", 0, "t0")
    # MOVE fills the load-delay slot; the JR delay then commits the Boolean
    # return value without increasing the routine's size.
    a.move("v0", "zero")
    a.andi("v1", "v1", 0x80)
    a.jr("ra")
    a.sltu("v0", "zero", "v1")
    a.label("availability_false")
    a.move("v0", "zero")
    a.jr("ra")
    a.nop()
    a.label("availability_stock")
    a.addiu("sp", "sp", -0x18)
    a.sw("s0", 0x10, "sp")
    a.j(0x801FADBC)
    a.nop()

    # Devil Analysis has one direct pre-scan which bypasses the predicate.
    a.label("initial_scan")
    _load_addr(a, "t0", FLAG)
    a.lw("t1", 0, "t0")
    a.addiu("t2", "zero", 2)
    a.bne("t1", "t2", "initial_scan_stock")
    a.nop()
    _load_addr(a, "t0", DEMON_FLAGS)
    # Demon ID zero is Satan and is never a valid recruit.  The stock party
    # constructor also uses ID zero while initializing empty UI records, so it
    # must not become the browser's first apparent registration.
    a.addiu("s0", "zero", 1)
    a.label("initial_scan_loop")
    a.addu("t1", "t0", "s0")
    a.lbu("t2", 0, "t1")
    # Test the current ID's successor while the byte load settles.  ID 254 is
    # the last valid entry, so a miss there advances s0 to the 0xff sentinel.
    a.sltiu("t3", "s0", 0xFE)
    a.andi("t2", "t2", 0x80)
    a.bne("t2", "zero", "initial_scan_done")
    a.nop()
    a.addiu("s0", "s0", 1)
    a.bne("t3", "zero", "initial_scan_loop")
    a.nop()
    a.label("initial_scan_done")
    a.j(0x8007F3B0)
    a.nop()
    a.label("initial_scan_stock")
    a.lui("v1", 0x8020)
    a.j(0x8007F37C)
    a.lbu("v0", -0x3ED8, "v1")

    # While the compendium browser is active, the analysis-window prompt gate
    # (mode flag plus command 0xfb) resolves to the item-target prompt slot.
    # Temporarily replace that fixed 28-byte text slot; copying text is safer
    # than substituting the browser's runtime UI-object pointer.
    a.label("copy_prompt")
    copy_prompt_address = a.labels["copy_prompt"]
    _load_addr(a, "t0", PROMPT_SLOT)
    a.addiu("t1", "zero", 7)
    a.label("copy_prompt_loop")
    a.lw("t2", 0, "a0")
    a.addiu("a0", "a0", 4)
    a.sw("t2", 0, "t0")
    a.addiu("t1", "t1", -1)
    a.bne("t1", "zero", "copy_prompt_loop")
    a.addiu("t0", "t0", 4)
    a.jr("ra")
    a.nop()

    # Register demons at the common committed roster-grant function.  Demon
    # negotiation and completed fusion both append through this function,
    # whereas the party-record constructor also services fusion previews and
    # therefore cannot reliably distinguish an acquired demon.  IDs 1..254
    # become 0..253 and pass one unsigned range test; zero and the 0xff
    # sentinel both continue through the stock function without registering.
    a.label("grant")
    a.addiu("sp", "sp", -0x20)
    a.addiu("t0", "a0", -1)
    a.sltiu("t0", "t0", 0xFE)
    a.beq("t0", "zero", "grant_continue")
    a.lui("t1", 0x8020)
    a.addu("t1", "t1", "a0")
    a.lbu("t2", DEMON_FLAGS & 0xFFFF, "t1")
    a.nop()
    a.ori("t2", "t2", 0x80)
    a.sb("t2", DEMON_FLAGS & 0xFFFF, "t1")
    a.label("grant_continue")
    a.j(GRANT_DEMON + 8)
    a.lui("a2", 0x8020)

    # Selecting a registered demon purchases a default-stat copy immediately.
    # The browser prompt states the deterministic price formula.  Errors use
    # existing localized messages and are shown after the browser closes.
    a.label("selection")
    _load_addr(a, "t0", FLAG)
    a.lw("t1", 0, "t0")
    a.addiu("t2", "zero", 2)
    a.bne("t1", "t2", "selection_stock")
    a.nop()
    # a0 is still the nonnegative demon ID returned by the Analysis UI.  The
    # first overwritten stock instruction would replace it with the UI object
    # pointer, so purchase before entering the browser's normal cancel/close
    # cleanup.  Continuing down the stock successful-Analysis path would try
    # to describe the selected demon and can display an unrelated stale
    # system message before the browser ever returns to the Cathedral.
    a.jal(0)  # fixed to purchase
    purchase_call_index = len(a.items) - 1
    a.nop()
    a.addiu("a0", "s4", -0x1C80)
    a.j(0x8007F4F4)
    a.addiu("a1", "s3", -0x5C6C)
    a.label("selection_stock")
    a.addiu("a0", "s4", -0x1C80)
    # Both stock setup instructions were replaced by the two-word hook.
    a.addiu("a1", "s3", -0x5C6C)
    a.j(0x8007F5A4)
    a.nop()

    a.label("purchase")
    purchase_address = a.labels["purchase"]
    a.addiu("sp", "sp", -0x28)
    a.sw("ra", 0x24, "sp")
    a.sw("s0", 0x20, "sp")
    a.sw("s1", 0x1C, "sp")
    a.sw("s2", 0x18, "sp")
    # The duplicate scan reads only its a0 argument, so the ID can be kept in
    # the call's delay slot.
    a.jal(0x801FAB6C)
    a.move("s0", "a0")
    a.bne("v0", "zero", "purchase_duplicate")
    a.nop()
    _load_addr(a, "t0", DEMON_BASE_STATS)
    a.sll("t1", "s0", 5)
    a.addu("t0", "t0", "t1")
    a.lbu("s1", 0, "t0")
    _load_addr(a, "t0", PARTY)
    a.lhu("t1", 0x0E, "t0")
    a.nop()
    a.sltu("t2", "t1", "s1")
    a.bne("t2", "zero", "purchase_level")
    a.nop()
    a.jal(0x801FAE4C)
    a.nop()
    # Starting the multiplier early is harmless on the error path; LO is only
    # read after the branch falls through.
    a.bne("v0", "zero", "purchase_full")
    a.multu("s1", "s1")
    a.mflo("s2")
    a.sll("t0", "s2", 4)
    a.sll("t1", "s2", 2)
    a.addu("s2", "t0", "t1")
    _load_addr(a, "t0", MACCA)
    a.lw("t1", 0, "t0")
    a.nop()
    a.sltu("t2", "t1", "s2")
    # The subtraction result is dead when the branch is taken.
    a.bne("t2", "zero", "purchase_money")
    a.subu("t1", "t1", "s2")
    a.sw("t1", 0, "t0")
    # The stock grant helper appends at the packed roster tail, so the new
    # record's physical slot is the pre-grant demon count plus the two human
    # slots.  Keep that count in s1 (the base level is no longer needed).
    # MOVE both fills the count byte's load-delay slot and sets the helper's
    # argument inside the call's delay slot.
    _load_addr(a, "t0", ROSTER_DEMON_COUNT)
    a.lbu("s1", 0, "t0")
    a.jal(GRANT_DEMON)
    a.move("a0", "s0")
    # The message token used by 0x60ad indexes the physical roster, including
    # the two human slots.
    a.addiu("t1", "s1", 2)
    a.lui("t0", 0x8020)
    a.sh("t1", -0x2716, "t0")
    # The grant helper writes only the ID, presence bit, display name and
    # counters.  The stock demon constructor performs the base-stat fill; its
    # a0 is the demon-area index (physical slot minus the two human slots).
    a.move("a0", "s1")
    a.jal(0x801FAAC8)
    a.move("a1", "s0")
    a.lui("t0", 0x800D)
    # Give the stock cleanup/message path a success result as well.  Besides
    # confirming the purchase, that final message lets the normal renderer
    # retire the Analysis browser's remaining prompt layer cleanly.
    a.addiu("t1", "zero", 0x60AD)
    a.sw("t1", RESULT & 0xFFFF, "t0")
    a.j(0)  # fixed to purchase_done
    purchase_done_jumps = [len(a.items) - 1]
    a.nop()
    a.label("purchase_duplicate")
    a.j(0)
    purchase_done_jumps.append(len(a.items) - 1)
    # Message 0x0195 has the same authored English wording as 0x005d, but it
    # belongs to a context-selected event tree.  The global system-message
    # renderer used after the Analysis browser resolves 0x005d directly.
    a.addiu("t1", "zero", 0x5D)
    a.label("purchase_level")
    a.j(0)
    purchase_done_jumps.append(len(a.items) - 1)
    a.addiu("t1", "zero", 8)
    a.label("purchase_full")
    a.j(0)
    purchase_done_jumps.append(len(a.items) - 1)
    a.addiu("t1", "zero", 0x194)
    a.label("purchase_money")
    a.j(0)
    purchase_done_jumps.append(len(a.items) - 1)
    a.addiu("t1", "zero", 0x76)
    a.label("purchase_error_store")
    a.lui("t0", 0x800D)
    a.sw("t1", RESULT & 0xFFFF, "t0")
    a.label("purchase_done")
    purchase_done_address = a.labels["purchase_done"]
    a.lw("ra", 0x24, "sp")
    a.lw("s0", 0x20, "sp")
    a.lw("s1", 0x1C, "sp")
    a.lw("s2", 0x18, "sp")
    a.jr("ra")
    a.addiu("sp", "sp", 0x28)

    # Resolve forward J/JAL placeholders (absolute jumps do not need labels in
    # the minimal assembler itself).
    def set_jump(index, opcode, target):
        a.items[index] = (opcode << 26) | ((target >> 2) & 0x03FFFFFF)

    set_jump(compendium_call_index, 0x03, compendium_address)
    set_jump(migrate_call_index, 0x03, migrate_address)
    set_jump(prompt_install_call_index, 0x03, copy_prompt_address)
    set_jump(prompt_restore_call_index, 0x03, copy_prompt_address)
    set_jump(purchase_call_index, 0x03, purchase_address)
    # Success returns directly; errors first store their message ID.
    set_jump(purchase_done_jumps[0], 0x02, purchase_done_address)
    for index in purchase_done_jumps[1:]:
        set_jump(index, 0x02, a.labels["purchase_error_store"])

    return a, a.blob()


def _emit_extra_code():
    """Build the Cathedral UI guards and prompt formatter."""
    a = _Asm(EXTRA_CAVE)

    # Suppress the Cathedral choice renderer while Analysis owns the screen.
    # Do not advance full frames here: doing so recursively progresses the
    # facility state and corrupts Analysis' return address during teardown.
    a.label("hide_cathedral_choices")
    a.lui("t0", 0x800F)
    a.addiu("t1", "zero", 3)
    a.jr("ra")
    a.sh("t1", (CATHEDRAL_CHOICE_WINDOW + 0x8C) & 0xFFFF, "t0")

    # The room dialogue compositor remains active even after the event-choice
    # object closes.  Its bottom-panel sprite maps the same VRAM text area that
    # Analysis uses for the blue sort chooser, so it displays a second copy of
    # those labels.  Skip only that compositor's per-frame update while the
    # Compendium is active; Analysis' own prompt uses a separate UI object.
    a.label("cathedral_dialogue_update")
    a.lui("t0", 0x800D)
    a.lw("t1", FLAG & 0xFFFF, "t0")
    a.addiu("t2", "zero", 2)
    a.bne("t1", "t2", "cathedral_dialogue_stock")
    a.nop()
    a.jr("ra")
    a.nop()
    a.label("cathedral_dialogue_stock")
    a.j(0x8003E690)
    a.nop()

    # State 5 makes the room-dialogue text surface fully inactive. The stock
    # message setup will open and repaint it with either a rejection or the
    # Cathedral prompt, without first exposing Analysis' old texture.
    a.label("retire_cathedral_dialogue")
    a.lui("t0", 0x800F)
    a.addiu("t1", "zero", 5)
    a.jr("ra")
    a.sb("t1", 0xE825, "t0")

    a.label("dynamic_prompt")
    a.lui("t0", 0x800D)
    a.lw("t1", FLAG & 0xFFFF, "t0")
    a.addiu("t2", "zero", 2)
    a.bne("t1", "t2", "dynamic_prompt_stock")
    a.nop()

    # The list callback stores its highlighted row at the stock Analysis UI
    # object.  The race/name/level/alignment sorters all materialize their
    # resulting demon IDs in the same byte table, so this remains correct if
    # another stock context changes the chosen ordering in the future.
    a.lui("t0", 0x800F)
    a.lhu("t1", SORT_UI_SELECTION & 0xFFFF, "t0")
    a.lui("t0", 0x8012)
    a.addu("t0", "t0", "t1")
    a.lbu("t1", SORTED_DEMON_IDS & 0xFFFF, "t0")
    a.lui("t0", 0x8010)  # sorted-ID load-delay filler

    # Base-stat records are 32 bytes and begin with the demon's level.  The
    # summoning price uses that immutable default level, matching purchase().
    a.sll("t1", "t1", 5)
    a.addu("t0", "t0", "t1")
    a.lbu("t1", DEMON_BASE_STATS & 0xFFFF, "t0")
    a.addiu("t4", "zero", 10)  # level load-delay filler and divisor
    a.multu("t1", "t1")
    a.mflo("t1")
    a.sll("t2", "t1", 4)
    a.sll("t3", "t1", 2)
    a.addu("t0", "t2", "t3")  # t0 = level * level * 20

    # Produce decimal digits backward in the prompt's six-byte maximum field,
    # right-aligned with leading spaces.  Level 99 is the stock maximum,
    # giving a six-digit maximum price of 196020.
    _load_addr(a, "t2", PROMPT_SLOT + 20)
    a.move("t5", "t2")
    a.addiu("t3", "zero", ord(" "))
    for offset in range(-6, 0):
        a.sb("t3", offset, "t2")
    a.label("price_digit_loop")
    a.divu("t0", "t4")
    a.mfhi("t3")
    a.mflo("t0")
    a.addiu("t2", "t2", -1)
    a.addiu("t3", "t3", ord("0"))
    a.sb("t3", 0, "t2")
    a.bne("t0", "zero", "price_digit_loop")
    a.nop()

    a.addiu("a0", "t5", -20)
    a.label("dynamic_prompt_stock")
    a.j(PROMPT_RENDER)
    a.nop()

    return a, a.blob()


def apply(exe):
    """Install the Compendium enhancement into a translated executable."""

    # These checks make a wrong revision or collision with another patch fail
    # at build time rather than producing a subtly damaged disc image.
    cave_source = bytes(exe[_foff(CAVE):_foff(CAVE_END)])
    cave_digest = hashlib.sha256(cave_source).hexdigest()
    if cave_digest != CAVE_SOURCE_SHA256:
        raise SystemExit(
            "compendium: reserved font range is not pristine at "
            f"{CAVE:#x}..{CAVE_END:#x}: expected SHA-256 "
            f"{CAVE_SOURCE_SHA256}, got {cave_digest}"
        )
    extra_cave_source = bytes(exe[_foff(EXTRA_CAVE):_foff(EXTRA_CAVE_END)])
    extra_cave_digest = hashlib.sha256(extra_cave_source).hexdigest()
    if extra_cave_digest != EXTRA_CAVE_SOURCE_SHA256:
        raise SystemExit(
            "compendium: reserved price-formatter range is not pristine at "
            f"{EXTRA_CAVE:#x}..{EXTRA_CAVE_END:#x}: expected SHA-256 "
            f"{EXTRA_CAVE_SOURCE_SHA256}, got {extra_cave_digest}"
        )
    _expect(
        exe, MENU_SCRIPT_EARLY,
        bytes.fromhex("2b 02 32 00 cb 08 33 00 d0 08 1f 00 be 08"),
        "unexpected early-game Cathedral menu",
    )
    _expect(
        exe, MENU_SCRIPT_FULL,
        bytes.fromhex(
            "2b 05 32 00 cb 08 33 00 d0 08 34 00 d6 08 "
            "42 00 dc 08 43 00 e2 08 1f 00 be 08"
        ),
        "unexpected fully unlocked Cathedral menu",
    )
    # Replace the existing final Exit row with Demon Compendium. The renderer
    # hook appends a fresh Exit row carrying this original 0x08be branch.
    for menu, entries in ((MENU_SCRIPT_EARLY, 3), (MENU_SCRIPT_FULL, 6)):
        final_entry = menu + 2 + (entries - 1) * 4
        struct.pack_into(
            "<BBH", exe, _foff(final_entry), MENU_ENTRY, 0, SENTINEL
        )
    expected = {
        0x8005B918: bytes.fromhex("01 00 a6 90 21 b0 60 00"),
        0x8005B97C: bytes.fromhex("a8 17 a2 90 00 00 00 00"),
        0x800545B0: bytes.fromhex("e0 15 44 8c 3b 5d 01 0c"),
        0x801FADB4: bytes.fromhex("e8 ff bd 27 10 00 b0 af"),
        0x8007F374: bytes.fromhex("20 80 03 3c 28 c1 62 90"),
        GRANT_DEMON: bytes.fromhex("e0 ff bd 27 20 80 06 3c"),
        0x8007F59C: bytes.fromhex("80 e3 84 26 94 a3 65 26"),
        ANALYSIS_LIST_UPDATE_CALL: bytes.fromhex("4d 2f 01 0c 28 d7 65 ac"),
        CATHEDRAL_DIALOGUE_UPDATE_CALL: bytes.fromhex("a4 f9 00 0c 1d 80 12 3c"),
        PROMPT_RENDER_CALL: bytes.fromhex("49 bc 00 0c 48 10 84 24"),
    }
    for address, data in expected.items():
        _expect(exe, address, data, "unexpected hook instructions")

    asm, code = _emit_code()
    if CAVE + len(code) > CAVE_CODE_END:
        raise SystemExit(
            f"compendium: code cave overflow ({len(code)} bytes; "
            f"limit {CAVE_CODE_END - CAVE})"
        )
    exe[_foff(CAVE):_foff(CAVE) + len(code)] = code

    extra_asm, extra_code = _emit_extra_code()
    if extra_asm.labels["retire_cathedral_dialogue"] != RETIRE_CATHEDRAL_DIALOGUE:
        raise SystemExit("compendium: Cathedral dialogue helper layout drifted")
    if extra_asm.labels["dynamic_prompt"] != DYNAMIC_PROMPT:
        raise SystemExit("compendium: supplemental-cave layout drifted")
    if EXTRA_CAVE + len(extra_code) > EXTRA_CAVE_END:
        raise SystemExit(
            f"compendium: price formatter cave overflow ({len(extra_code)} bytes; "
            f"limit {EXTRA_CAVE_END - EXTRA_CAVE})"
        )
    exe[_foff(EXTRA_CAVE):_foff(EXTRA_CAVE) + len(extra_code)] = extra_code

    levels = exe[_foff(DEMON_BASE_STATS):_foff(DEMON_BASE_STATS) + 255 * 32:32]
    if not levels or max(levels) > 99:
        raise SystemExit("compendium: dynamic price field supports demon levels through 99")

    prompt = b"\x1fSummon Cost:        Macca\x00\x00"
    _expect(
        exe, PROMPT_SLOT, b"\x1fUse it on whom?\x00",
        "translated item-target prompt",
    )
    # The restore copy must reproduce the slot exactly, including the tail of
    # the following "Mimic whom?" slot covered by the 28-byte copy window, so
    # capture the original bytes instead of assuming their wording.
    original_prompt = bytes(exe[_foff(PROMPT_SLOT):_foff(PROMPT_SLOT) + 28])
    exe[_foff(PROMPT):_foff(PROMPT) + 28] = prompt
    exe[_foff(ORIGINAL_PROMPT):_foff(ORIGINAL_PROMPT) + 28] = original_prompt

    labels = asm.labels
    hooks = {
        0x8005B918: labels["menu_start"],
        0x8005B97C: labels["menu_loop"],
        0x800545B0: labels["event_update"],
        0x801FADB4: labels["availability"],
        0x8007F374: labels["initial_scan"],
        GRANT_DEMON: labels["grant"],
        0x8007F59C: labels["selection"],
    }
    for address, target in hooks.items():
        _patch_jump(exe, address, target)
    _patch_call(exe, ANALYSIS_LIST_UPDATE_CALL, labels["price_update"])
    _patch_call(
        exe, CATHEDRAL_DIALOGUE_UPDATE_CALL,
        extra_asm.labels["cathedral_dialogue_update"],
    )
    _patch_call(exe, PROMPT_RENDER_CALL, extra_asm.labels["dynamic_prompt"])

    # State is static executable padding, not part of the save payload.
    for address in (FLAG, RESULT, OLD_SELECTION, MENU_COUNT):
        struct.pack_into("<I", exe, _foff(address), 0)

    return {
        "code_bytes": len(code) + len(extra_code),
        "code_capacity": (CAVE_CODE_END - CAVE) + (EXTRA_CAVE_END - EXTRA_CAVE),
        "main_code_bytes": len(code),
        "price_code_bytes": len(extra_code),
        "persistent_bytes_added": 0,
        "save_payload_size": 0x3260,
    }
