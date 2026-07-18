"""SMT2 raw-SJIS system strings (memcard/save/load, COMP menu, errors, menu help).

English strings begin with marker 0x1f and store one ASCII byte per character.  The
printer wrapper in build.py maps each byte back to the game's existing fullwidth SJIS
glyph before drawing, preserving the established font and proportional advances.

Every translation remains in its original executable slot.  This keeps the boot-time
memory layout untouched; apply_sys validates every encoded string against the Japanese
slot size before writing it.

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


ASCII_MARKER = 0x1f


def _ascii(s):
    """Marker-prefixed one-byte English plus NUL; 0x7f represents Macca (ћ)."""
    out = bytearray([ASCII_MARKER])
    for ch in s:
        if ch == "ћ":
            out.append(0x7f)
        elif 0x20 <= ord(ch) <= 0x7e:
            out.append(ord(ch))
        else:
            raise SystemExit(f"unsupported one-byte system character: {ch!r} in {s!r}")
    out.append(0)
    return bytes(out)


# Original exe file offset -> (original byte gap, English translation).
SYS = {
    # ===================== MEMORY CARD / SAVE / LOAD =====================
    # errors
    0x0bc0: (28, "Suspend data is corrupted."),              # 中断データは破損しています
    0x0bdc: (28, "The Memory Card is damaged."),              # メモリーカードが不良です
    0x0bf8: (28, "Could not format the Memory Card."),        # フォーマットに失敗しました
    0x0c14: (36, "This save data is corrupted."),             # このセーブデータは破損しています
    0x0c38: (36, "or overwrite another file."),               # か他のファイルに上書きしてください
    0x0c5c: (28, "that has at least two free blocks,"),       # メモリーカードと交換する
    0x0c78: (40, "Replace it with a Memory Card"),            # 最低２ブロック以上空きブロックがある
    0x0ca0: (40, "The Memory Card lacks free space."), # メモリーカードに空きブロックが不足です
    0x0cc8: (24, "Could not load the data."),                 # ロードに失敗しました
    0x0ce0: (24, "Could not save the data."),                 # セーブに失敗しました
    0x0cf8: (24, "suspend data was found."),                  # 中断データがありません
    0x0d10: (28, "save data was found."),                     # セーブデータがありません
    0x0d2c: (24, "No Shin Megami Tensei II"),                 # 「真・女神転生Ⅱ」の
    0x0d44: (36, "Insert the Memory Card correctly in slot 1."), # 差込口１に正しく差し込んでください
    0x0d68: (40, "No Memory Card is inserted."),              # メモリーカードが差し込まれていません
    0x0d90: (20, "Free space is required."),                  # 空き容量が必要です
    0x0da4: (40, "Saving requires at least two free blocks."), # セーブを行うには最低２ブロック以上の
    0x0dcc: (16, "There is not enough free space."),           # 不足しています
    0x0ddc: (32, "The Memory Card lacks free blocks."), # メモリーカードの空きブロックが
    0x0dfc: (28, "to save or load."),                          # セーブ　ロードができません
    0x0e18: (36, "A Memory Card must be inserted in slot 1"),  # メモリーカードが差込口１にないと
    0x0e3c: (24, "in slot 1."),                               # 差し込まれていません
    0x0e54: (28, "No Memory Card is inserted"),               # メモリーカードが差込口１に
    0x0e70: (32, "Suspend saving will be unavailable."),       # 中断セーブができなくなりますが
    0x0e90: (28, "There will not be enough free blocks."),     # 空きブロックが不足します
    0x0eac: (36, "This save may prevent suspend saving."), # 今回のセーブで中断セーブに必要な
    0x0ed0: (24, "Continue playing?"),                         # ゲームを続けますか？
    0x0ee8: (24, "Format it?"),                               # フォーマットしますか？
    0x0f00: (40, "Format the Memory Card before saving."), # フォーマットしなければセーブできません
    0x0f28: (28, "is not formatted."),                         # フォーマットされていません
    0x0f44: (28, "The Memory Card in slot 1"),                 # 差込口１のメモリーカードは
    0x0f60: (36, "Loading will erase the suspend data."),      # 再開すると中断データは消去されます
    0x0f84: (24, "Load this file?"),                           # ファイルをロードします
    0x0f9c: (32, "Overwriting will erase"),                    # 上書きすると以前の中断データは
    0x0fbc: (28, "Suspend data already exists."),              # 既に中断データがあります
    0x0fd8: (24, "Create suspend data?"),                      # 中断セーブしますか？
    0x0ff0: (20, "Is that okay?"),                             # よろしいですか？
    0x1004: (20, "the previous data."),                        # 消えてしまいます
    0x1018: (36, "Overwriting will erase"),                    # 上書きすると以前のセーブデータは
    0x103c: (44, "This file already contains save data."),     # このファイルには既にセーブデータがあります
    0x1068: (44, "At least four free blocks are required."),   # ４ブロック以上の空き容量が必要になります
    0x1094: (32, "To create both save and suspend data,"),     # セーブと中断を両方行うには最低
    0x10b4: (32, "there are not enough free blocks."),         # 必要な空きブロックが不足します
    0x10d4: (44, "A save may prevent suspend saving."), # セーブデータを１つ作成すると中断セーブに
    0x1100: (20, "Formatting..."),                             # フォーマット中です
    0x1114: (16, "Loading..."),                                # ロード中です
    0x1124: (16, "Saving..."),                                 # セーブ中です
    # busy-overlay warning: shown as [status line] / 0x1150 / 0x1134 for ALL of
    # Saving/Loading/Format/Checking -> the two warning lines must read standalone.
    0x1134: (28, "Memory Card or controller."),                # 抜き差ししないでください
    0x1150: (32, "Do not insert or remove the"),               # メモリーカードとコントローラを
    0x1170: (32, "Checking Memory Card..."),                   # メモリーカードのチェック中です
    0x1190: (20, "your body..."),                              # お気をつけて・・・
    0x11a4: (32, "beware of demons possessing"),               # 悪魔に肉体を乗っ取られぬよう
    0x11c4: (20, "While you sleep,"),                          # おやすみのあいだ
    0x11d8: (40, "You may now turn off the power."),           # それでは電源を切っておやすみください
    0x1200: (24, "Save complete."),                            # セーブが終了しました
    0x1218: (40, "Select a file to load."),                    # ロードするファイルを選択してください
    0x1244: (40, "Select a file to save."),                    # セーブするファイルを選択してください

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

    # ===================== EQUIPMENT AFFINITIES =====================
    # Armor 相性 values. This is damage affinity/resistance, distinct from
    # the 属性 equip-alignment row whose values are ALL/L/N/C. Each entry is
    # kept in its original fixed slot and within the equipment detail pane.
    0x2fc0: (8,  "Phys"),                  # 物理
    0x2fc8: (16, "Repel Mind"),            # 反精神
    0x2fd8: (16, "Fire/Ice"),              # 対火炎・氷結
    0x2fe8: (16, "Elec/Force"),            # 対電撃・衝撃
    0x2ff8: (16, "Res Phys"),              # 対物理
    0x3008: (16, "Res Mind"),              # 対精神
    0x3018: (16, "Res Force"),             # 対衝撃
    0x3028: (16, "Res Elec"),              # 対電撃
    0x3038: (16, "Res Ice"),               # 対氷結
    0x3048: (16, "Res Fire"),              # 対火炎
    0x3058: (16, "Normal"),                # ノーマル

    # ===================== STAT / SHOP / CASINO =====================
    0x1d5c: (16, "Points"),               # 残りポイント (level-up points left)
    0x2308: (12, "Exit"),                 # 店を出る (leave shop)
    0x1eec: (24, "Oh, you're short on ћ."),  # あら　ћが　足りないわ (not enough Macca)
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

# Fresh translations made from the original Japanese strings.  Keeping these
# overrides separate from the old provisional wording above makes the source
# constraints visible while ensuring none of that wording reaches the build.
RETRANSLATED = {
    # COMP / party / demon menus
    0x1558: "Is this OK?",                # これでよろしいですか？
    0x16f4: "Summon whom?",               # どの悪魔を呼び出しますか？
    0x1718: " appears.",                   # [name]を呼び出しました
    0x1730: "Replace whom?",              # 誰と替えて呼び出しますか？
    0x174c: "Which slot?",                # どこに呼び出しますか？
    0x1764: "Send back?",                 # どの悪魔を戻しますか？
    0x1780: " returned",                  # [name]はCOMPに戻った
    0x179c: "Who leaves?",                # どの悪魔と別れますか？
    0x17cc: "Proceed?",                   # よろしいですか？
    0x17e8: " removed.",                  # [name]の死体を捨てました
    0x1800: " left.",                     # [name]と別れました
    0x182c: "Analyze whom?",              # どの悪魔を解析しますか？
    0x1848: "Use on?",                    # 誰に使いますか？
    0x185c: "Mimic whom?",                # 誰のものまねをしますか？
    0x1878: "This demon cannot be summoned.",
    0x1894: "Magic cannot be used right now.",
    0x18b4: "The COMP cannot be used right now.",
    0x18d8: "The curse prevents you from removing it!",
    0x18f4: "You do not have any usable magic.",
    0x191c: "Its alignment prevents summoning.",
    0x193c: "You have no items that can be reordered.",
    0x1974: "This demon cannot leave the party.",
    0x198c: "The COMP cannot be used here.",
    0x19b0: "No usable magic.",
    0x19c8: "You cannot use that here.",
    0x19e0: "You have no items.",
    0x19f8: "There are no demons you can analyze.",
    0x1a18: "You have no items that can be discarded.",
    0x1a3c: "You have no usable items.",
    0x1a5c: "No demons can leave the party.",
    0x1a74: "No demons can be returned to the COMP.",
    0x1a8c: "There are no demons you can summon.",
    0x1ac0: "Who casts?",                 # 誰の魔法を使いますか？
    0x1ad8: "Cast what?",                 # どの魔法を使いますか？
    0x1af8: "Which item?",                # どのアイテムを使いますか？
    0x1b1c: "Move which item?",           # 移動元のアイテムを選択してください
    0x1b40: "Move it where?",             # 移動先のアイテムを選択してください
    0x1b64: "Discard what?",              # どのアイテムを捨てますか？
    0x1b9c: "Proceed?",                   # よろしいですか？
    0x1c60: "The curse prevents you from removing it.",
    0x1c78: "Inventory full. It cannot be removed.",
    0x1c98: "You have nothing this character can equip.",
    0x1cbc: "Whose stats?",               # 誰のステータスを見ますか？

    # Fixed-width labels and short shop/casino prompts
    0x1d5c: "Points",                     # 残りポイント
    0x1e00: "Gun",                        # 合体銃
    0x1e08: "Arm",                        # 腕防具
    0x1e10: "Hlm",                        # 頭防具
    0x1e18: "Leg",                        # 脚防具
    0x1e20: "Bdy",                        # 胴防具
    0x1e28: "Swd",                        # 合体剣
    0x1e4c: "Reposition",                 # 位置替えをしてください
    0x1e64: "Open the Config menu.",       # 設定メニューを起動します
    0x1e80: "Load save data.",             # セーブデータをロードします
    0x1e9c: "Create suspend data.",        # 中断セーブを行います
    0x1eec: "Oh, you're short on ћ.",       # あら ћが足りないわ
    0x1f0c: "Enter:",                     # コードを入力せよ：
    0x201c: "Use on?",                    # 誰に使いますか？
    0x2308: "Leave",                      # 店を出る

    # System-menu and Config help
    0x23dc: "Sorting complete.",
    0x23f4: "Change the party formation.",
    0x2408: "View detailed stats.",
    0x2424: "Change equipment.",
    0x2438: "Use, organize, reorder, or discard items.",
    0x2464: "Use magic.",
    0x2478: "Access the COMP.",
    0x2944: "Return to the System menu.",
    0x2964: "Exit the Config menu.",
    0x2980: "Play sound in stereo.",
    0x29a0: "Play sound in mono.",
    0x29c0: "Use only magic for Auto-Recover.",
    0x29e4: "Use items for Auto-Recover.",
    0x2a08: "Show your heading at the top of the map.",
    0x2a28: "Display the map with north at the top.",
    0x2a48: "Defend if the item or MP runs out.",
    0x2a70: "Attack if the item or MP runs out.",
    0x2a9c: "Repeat the previous action.",
    0x2ab8: "Use only swords, guns, and basic attacks.",
    0x2ad0: "Hide attack effects.",
    0x2af8: "Show attack effects.",
    0x2b14: "Show battle messages faster than normal.",
    0x2b4c: "Display battle messages at normal speed.",
    0x2b78: "Display messages faster than normal.",
    0x2ba4: "Display messages at normal speed.",
    0x2bc8: "Sort demons by alignment.",
    0x2be4: "Sort demons by level.",
    0x2c00: "Sort demons alphabetically.",
    0x2c24: "Sort demons by race.",
}

for _off, _english in RETRANSLATED.items():
    _gap, _old_english = SYS[_off]
    SYS[_off] = (_gap, _english)

# Shorten only the entries that still exceed their original slots after switching to
# one byte per English character.
ASCII_FIT_ENGLISH = {
    0x0bdc: "Memory Card is damaged.",
    0x0bf8: "Could not format card.",
    0x0c5c: "with at least 2 blocks",
    0x0cc8: "Could not load data.",
    0x0ce0: "Could not save data.",
    0x0cf8: "No suspend data found.",
    0x0d10: "No save data was found.",
    0x0d2c: "Shin Megami Tensei II",
    0x0d44: "Insert Memory Card in slot 1.",
    0x0d90: "Free space needed.",
    0x0da4: "Saving needs at least 2 free blocks.",
    0x0dcc: "is too low.",
    0x0ddc: "Memory Card free space",
    0x0e18: "Memory Card must be in slot 1",
    0x0e70: "Suspend save will be disabled.",
    0x0e90: "Not enough free blocks.",
    0x0eac: "This save may prevent suspending.",
    0x0f60: "Loading erases suspend data.",
    0x0fbc: "Suspend data exists.",
    0x1094: "For save and suspend data,",
    0x10b4: "there are too few free blocks.",
    0x1878: "Cannot summon this demon.",
    0x1894: "Magic cannot be used now.",
    0x18d8: "Curse prevents removal!",
    0x18f4: "No usable magic available.",
    0x191c: "Cannot summon this alignment.",
    0x193c: "No items can be reordered.",
    0x1974: "Demon cannot leave.",
    0x19c8: "Cannot use that here.",
    0x19f8: "No demons can be analyzed.",
    0x1a18: "No items can be discarded.",
    0x1a5c: "No demons can leave.",
    0x1a74: "No demons can return.",
    0x1a8c: "No demons can be summoned.",
    0x1c60: "Cannot remove: cursed",
    0x1c78: "Inventory full; cannot remove.",
    0x1c98: "Nothing available to equip.",
    0x23f4: "Change formation",
    0x2a08: "Keep your heading at map top.",
    0x2a28: "Keep north at map top.",
    0x2a9c: "Repeat the last action.",
    0x2ab8: "Swords/guns/basic only",
}

for _off, _english in ASCII_FIT_ENGLISH.items():
    _gap, _old_english = SYS[_off]
    SYS[_off] = (_gap, _english)


# Save-file LIST entries are sprintf format strings that begin with the JP game title
# 真・女神転生２ (7 fullwidth chars = 14 bytes) followed by ` ＱＵＩＴ/ＦＩＬＥ%s ...ＬＶ%s%s`.
# We swap ONLY the title -> fullwidth "SMT2", preserving the whole %s/spacing tail exactly.
_JP_TITLE = bytes.fromhex("905e81458f97905f935d90b68251")  # 真・女神転生２
TITLE_FMT_OFFS = (0x1388, 0x13cc, 0x1410, 0x1454)

def apply_sys(exe):
    """Write marker-prefixed one-byte English into the original fixed slots."""
    for off, (gap, en) in SYS.items():
        data = _ascii(en)
        if len(data) > gap:
            raise SystemExit(
                f"sys 0x{off:x} OVERFLOW {len(data)}>{gap} bytes: {en!r}")
        exe[off:off + gap] = data + bytes(gap - len(data))
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
