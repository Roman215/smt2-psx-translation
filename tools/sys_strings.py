"""SMT2 raw-SJIS system strings (memcard/save/load, COMP menu, errors, menu help).

RENDERING (2026-07-11, RELIABLE PATH): these strings are drawn by the game's system
string printers (0x800482a4 family), which read 2 bytes/char (fullwidth SJIS) and draw
via a context whose font is the 12x12 fullwidth font 0x800d4188 -- which ALREADY CONTAINS
clean fullwidth Latin A-Z/a-z/0-9 (that's why the game's own labels MESSAGE SPEED, CONFIG,
SUMMON, YES/NO, GOOD/CURSE, etc. render, intermixed with these Japanese prompts on the
same screens). So we encode English as FULLWIDTH SJIS Latin and the STOCK printers draw
it with ZERO code changes -- deliberately NOT the ASCII-aware printer hook that garbled
things before.

Cost: fullwidth is monospace/wide (~12px fixed advance), so text must be terse. Budget
per string = its byte gap to the next string: usable fullwidth chars = gap//2 - 1 (the
original left a 2-byte NUL). apply_sys enforces len(fullwidth_bytes) < gap.

NOT translated (left as-is on purpose): printf format strings (%d/%s), debug text,
bu00:BISLPM* memcard save-file identifiers, sound/VAB/SEQ dumps, single-char name-insert
markers, already-English labels, the file-select title format strings, and the compact
race-label table (2-3 kanji, no room for English -- the shown race names come from the
translated RACES name table instead).
"""

import struct
import build_en_tree as ET


def _fw(s):
    """ASCII string -> fullwidth SJIS bytes (big-endian per char)."""
    out = bytearray()
    for ch in s:
        out += struct.pack(">H", ET.fullwidth(ch))
    return bytes(out)


# exe FILE offset -> (byte_gap_to_next_string, english).  Written FULLWIDTH.
# Keep len(fullwidth bytes) < byte_gap (>=1 byte reserved for the NUL terminator).
SYS = {
    # ===================== MEMORY CARD / SAVE / LOAD =====================
    # errors
    0x0bc0: (28, "Bad quit data"),        # 中断データは破損しています
    0x0bdc: (28, "Faulty card."),         # メモリーカードが不良です
    0x0bf8: (28, "Format failed"),        # フォーマットに失敗しました
    0x0c14: (36, "Save data damaged"),    # このセーブデータは破損しています
    0x0c38: (36, "or overwrite it."),     # か他のファイルに上書きしてください
    0x0c5c: (28, "Swap the card"),        # メモリーカードと交換する
    0x0c78: (40, "Need 2+ free blocks"),  # 最低２ブロック以上空きブロックがある
    0x0ca0: (40, "Too few free blocks"),  # メモリーカードに空きブロックが不足です
    0x0cc8: (24, "Load failed"),          # ロードに失敗しました
    0x0ce0: (24, "Save failed"),          # セーブに失敗しました
    0x0cf8: (24, "No resume"),            # 中断データがありません
    0x0d10: (28, "No save yet"),          # セーブデータがありません
    0x0d2c: (24, "SMT II:"),              # 「真・女神転生Ⅱ」の  (title prefix on load/resume boxes)
    0x0d44: (36, "Insert in slot 1."),    # 差込口１に正しく差し込んでください
    0x0d68: (40, "No card is inserted"),  # メモリーカードが差し込まれていません
    0x0d90: (20, "Need room"),            # 空き容量が必要です
    0x0da4: (40, "Saving needs 2+"),      # セーブを行うには最低２ブロック以上の
    0x0dcc: (16, "blocks."),              # 不足しています
    0x0ddc: (32, "Card free space"),      # メモリーカードの空きブロックが
    0x0dfc: (28, "No save/load"),         # セーブ　ロードができません
    0x0e18: (36, "Card must be in"),      # メモリーカードが差込口１にないと
    0x0e3c: (24, "slot 1."),              # 差し込まれていません
    0x0e54: (28, "Card in slot1"),        # メモリーカードが差込口１に
    0x0e70: (32, "stops quit save"),      # 中断セーブができなくなりますが
    0x0e90: (28, "Low on blocks"),        # 空きブロックが不足します
    0x0eac: (36, "This save may use"),    # 今回のセーブで中断セーブに必要な
    0x0ed0: (24, "Continue?"),            # ゲームを続けますか？
    0x0ee8: (24, "Format it?"),           # フォーマットしますか？
    0x0f00: (40, "Must format to save"),  # フォーマットしなければセーブできません
    0x0f28: (28, "Not formatted"),        # フォーマットされていません
    0x0f44: (28, "Slot 1 card"),          # 差込口１のメモリーカードは
    0x0f60: (36, "Resume wipes data"),    # 再開すると中断データは消去されます
    0x0f84: (24, "Load file."),           # ファイルをロードします
    0x0f9c: (32, "This overwrites"),      # 上書きすると以前の中断データは
    0x0fbc: (28, "Data exists"),          # 既に中断データがあります
    0x0fd8: (24, "Quit save?"),           # 中断セーブしますか？
    0x0ff0: (20, "Confirm?"),             # よろしいですか？
    0x1004: (20, "be erased"),            # 消えてしまいます
    0x1018: (36, "Old save will"),        # 上書きすると以前のセーブデータは
    0x103c: (44, "This file has a save"), # このファイルには既にセーブデータがあります
    0x1068: (44, "Needs 4+ free blocks"), # ４ブロック以上の空き容量が必要になります
    0x1094: (32, "To save & quit"),       # セーブと中断を両方行うには最低
    0x10b4: (32, "need more room"),       # 必要な空きブロックが不足します
    0x10d4: (44, "One save file needs"),  # セーブデータを１つ作成すると中断セーブに
    0x1100: (20, "Format..."),            # フォーマット中です
    0x1114: (16, "Loading"),              # ロード中です
    0x1124: (16, "Saving."),              # セーブ中です
    # busy-overlay warning: shown as [status line] / 0x1150 / 0x1134 for ALL of
    # Saving/Loading/Format/Checking -> the two warning lines must read standalone.
    0x1134: (28, "memory card."),         # 抜き差ししないでください
    0x1150: (32, "Do not remove"),        # メモリーカードとコントローラを
    0x1170: (32, "Now checking"),         # メモリーカードのチェック中です
    0x1190: (20, "Take care"),            # お気をつけて・・・
    0x11a4: (32, "So demons don't"),      # 悪魔に肉体を乗っ取られぬよう
    0x11c4: (20, "take you"),             # おやすみのあいだ
    0x11d8: (40, "Now power off, rest"),  # それでは電源を切っておやすみください
    0x1200: (24, "Save done."),           # セーブが終了しました
    0x1218: (40, "Load which file?"),     # ロードするファイルを選択してください
    0x1244: (40, "Save which file?"),     # セーブするファイルを選択してください

    # ===================== COMP / PARTY / DEMON MENUS =====================
    0x16f4: (28, "Summon which?"),        # どの悪魔を呼び出しますか？
    0x1718: (20, " summoned"),            # ...を呼び出しました   ([name] precedes)
    0x1730: (28, "Replace who?"),         # 誰と替えて呼び出しますか？
    0x174c: (24, "Put where?"),           # どこに呼び出しますか？
    0x1764: (24, "Return who?"),          # どの悪魔を戻しますか？
    0x1780: (20, " to COMP"),             # ...はＣＯＭＰに戻った   ([name] precedes)
    0x179c: (24, "Part with?"),           # どの悪魔と別れますか？
    0x17cc: (20, "Confirm?"),             # よろしいですか？
    0x17e8: (24, " discarded"),           # ...の死体を捨てました   ([name] precedes)
    0x1800: (16, " parted"),              # ...と別れました   ([name] precedes)
    0x182c: (28, "Analyze who?"),         # どの悪魔を解析しますか？
    0x1848: (20, "On who?"),              # 誰に使いますか？
    0x185c: (28, "Mimic whom?"),          # 誰のものまねをしますか？
    0x1878: (28, "Can't summon"),         # この仲魔は呼び出せません
    0x1894: (32, "Can't cast now"),       # 魔法を使える状態ではありません
    0x18b4: (36, "COMP unusable now"),    # ＣＯＭＰを使える状態ではありません
    0x18d8: (28, "Cursed gear!"),         # 呪いで装備が外れません！
    0x18f4: (28, "No spells"),            # 使える魔法を持っていません
    0x191c: (32, "Wrong alignment"),      # 属性が違うので呼び出せません
    0x193c: (40, "No items to reorder"),  # 並び替えられるアイテムは持っていません
    0x1974: (24, "Locked in"),            # この仲魔は外せません
    0x198c: (36, "No COMP here"),         # ここではＣＯＭＰは使用できません
    0x19b0: (24, "No spells"),            # 使える魔法がありません
    0x19c8: (24, "Not here"),             # ここでは使用できません
    0x19e0: (24, "No items."),            # アイテムがありません
    0x19f8: (32, "No one to scan"),       # アナライズできる悪魔はいません
    0x1a18: (36, "No items to drop"),     # 捨てられるアイテムは持っていません
    0x1a3c: (32, "No usable items"),      # 使えるアイテムは持っていません
    0x1a5c: (24, "No one free"),          # 外せる仲魔はいません
    0x1a74: (24, "No one back"),          # 戻せる仲魔はいません
    0x1a8c: (28, "No demons"),            # 呼び出せる仲魔はいません
    0x1ac0: (24, "Cast whose?"),          # 誰の魔法を使いますか？
    0x1ad8: (24, "Cast what?"),           # どの魔法を使いますか？
    0x1af8: (32, "Use which item?"),      # どのアイテムを　使いますか？
    0x1b1c: (36, "Pick item to move"),    # 移動元のアイテムを選択してください
    0x1b40: (36, "Pick destination"),     # 移動先のアイテムを選択してください
    0x1b64: (32, "Drop which?"),          # どのアイテムを　捨てますか？
    0x1b9c: (20, "Confirm?"),             # よろしいですか？
    0x1558: (24, "Is this OK?"),          # これでよろしいですか？ (sits after a ptr table, no NUL before)
    0x1c60: (24, "Cursed!"),              # 呪いで装備が外せません
    0x1c78: (32, "Item bag full"),        # アイテムがいっぱいで外せません
    0x1c98: (32, "No equipment"),         # 装備できるアイテムがありません
    0x1cbc: (28, "Whose stats?"),         # 誰のステータスを見ますか？

    # ===================== EQUIP-SLOT LABELS (status/equip screen) =====================
    0x1e00: (8, "Gun"),                   # 合体銃 (fusion gun)
    0x1e08: (8, "Arm"),                   # 腕防具
    0x1e10: (8, "Hlm"),                   # 頭防具
    0x1e18: (8, "Leg"),                   # 脚防具
    0x1e20: (8, "Bdy"),                   # 胴防具
    0x1e28: (8, "Swd"),                   # 合体剣 (fusion sword)

    # ===================== STAT / SHOP / CASINO =====================
    0x1d5c: (16, "Points"),               # 残りポイント (level-up points left)
    0x2308: (12, "Exit"),                 # 店を出る (leave shop)
    0x1eec: (24, "Low on £!"),       # あら　£が　足りないわ (casino: not enough money)
    0x1f0c: (20, "Code:"),                # コードを入力せよ：

    # ===================== SYSTEM-MENU / CONFIG HELP LINES =====================
    0x1e4c: (24, "Swap places"),          # 位置替えをしてください
    0x1e64: (28, "Open settings"),        # 設定メニューを起動します
    0x1e80: (28, "Load a save"),          # セーブデータをロードします
    0x1e9c: (24, "Quit save"),            # 中断セーブを行います
    0x201c: (20, "On who?"),              # 誰に使いますか？
    0x23dc: (24, "Sorted!"),              # ソートが完了しました
    0x23f4: (20, "Reorder"),              # 隊列を変更します
    0x2408: (28, "Show details"),         # 詳細ステータスを表示します
    0x2424: (20, "Equip"),                # 装備を変更します
    0x2438: (44, "Use, sort, drop items"),# アイテムを使用／整頓／並び替え／廃棄します
    0x2464: (20, "Use magic"),            # 魔法を使用します
    0x2478: (24, "Open COMP"),            # ＣＯＭＰを使用します
    0x2944: (32, "To system menu"),       # システムメニュー画面に戻ります
    0x2964: (28, "End CONFIG"),           # ＣＯＮＦＩＧ設定を終了し
    0x2980: (32, "Play in stereo"),       # サウンドをステレオで再生します
    0x29a0: (32, "Play in mono"),         # サウンドをモノラルで再生します
    0x29c0: (36, "Auto-heal: magic"),     # 魔法のみを使用して自動回復します
    0x29e4: (36, "Auto-heal: items"),     # アイテムを使用して自動回復します
    0x2a08: (32, "Face travel up"),       # 進行方向を上にして表示します
    0x2a28: (32, "North stays up"),       # 画面上を北に固定して表示します
    0x2a48: (40, "Guard if no MP/item"),  # アイテムやＭＰがなくなると防御します
    0x2a70: (44, "Attack if no MP/item"), # アイテムやＭＰがなくなると通常攻撃をします
    0x2a9c: (28, "Repeat action"),        # 前回の行動を繰り返します
    0x2ab8: (24, "Sword/gun"),            # 剣・銃・通常攻撃のみ
    0x2ad0: (40, "Battle effects off"),   # 攻撃エフェクトの表示をＯＦＦにします
    0x2af8: (28, "Show effects"),         # 攻撃エフェクトを表示します
    0x2b14: (56, "Fast battle messages"), # 戦闘時のメッセージを[δ]通常よりも速い速度で...
    0x2b4c: (44, "Battle text: normal"),  # 戦闘時のメッセージを通常の速度で表示します
    0x2b78: (44, "Show messages faster"), # メッセージを通常よりも速い速度で表示します
    0x2ba4: (36, "Normal msg speed"),     # メッセージを通常の速度で表示します
    0x2bc8: (28, "Sort by align"),        # 属性別に並べて表示します
    0x2be4: (28, "Sort by level"),        # レベル順に並べて表示します
    0x2c00: (36, "Sort by name"),         # 悪魔名の５０音順に並べて表示します
    0x2c24: (28, "Sort by race"),         # 種族別に並べて表示します
}


# Save-file LIST entries are sprintf format strings that begin with the JP game title
# 真・女神転生２ (7 fullwidth chars = 14 bytes) followed by ` ＱＵＩＴ/ＦＩＬＥ%s ...ＬＶ%s%s`.
# We swap ONLY the title -> fullwidth "SMT2", preserving the whole %s/spacing tail exactly.
_JP_TITLE = bytes.fromhex("905e81458f97905f935d90b68251")  # 真・女神転生２
TITLE_FMT_OFFS = (0x1388, 0x13cc, 0x1410, 0x1454)


def apply_sys(exe):
    """Write fullwidth-SJIS English system strings in-place. Rendered by the STOCK
    system printers (no hook). exe is a bytearray of the SLPM file."""
    for off, (gap, en) in SYS.items():
        data = _fw(en)
        if len(data) >= gap:
            raise SystemExit(
                f"sys 0x{off:x} OVERFLOW {len(data)}>={gap} bytes: {en!r}")
        for i in range(gap):
            exe[off + i] = data[i] if i < len(data) else 0
    # save-file list title: replace 真・女神転生２ -> ＳＭＴ　ＩＩ, keep the format tail intact
    new_title = _fw("SMT II")
    for off in TITLE_FMT_OFFS:
        if bytes(exe[off:off + len(_JP_TITLE)]) != _JP_TITLE:
            raise SystemExit(f"title fmt 0x{off:x}: unexpected leading bytes")
        end = exe.index(0, off)
        tail = bytes(exe[off + len(_JP_TITLE):end])
        new = new_title + tail
        gap = end - off + 1  # original string bytes + its NUL; new is shorter, fits
        if len(new) >= gap:
            raise SystemExit(f"title fmt 0x{off:x} OVERFLOW {len(new)}>={gap}")
        for i in range(len(new)):
            exe[off + i] = new[i]
        for i in range(len(new), gap):  # NUL-pad the freed bytes
            exe[off + i] = 0
