"""SMT2 raw-SJIS system strings.

English strings begin with marker 0x1f and store one ASCII byte per character.  The
printer wrapper in build.py maps each byte back to the game's existing fullwidth SJIS
glyph before drawing, preserving the established font and proportional advances.
Text appended to an already encoded demon name, and Cathedral prompts drawn through
the object renderer, stay in fullwidth SJIS because those paths cannot recognize the
one-byte marker.

Every translation remains in its original executable slot.  This keeps the boot-time
memory layout untouched; apply_sys validates every encoded string against the Japanese
slot size before writing it.

This covers the executable-resident save/load UI, COMP and party prompts, menu help,
healing and shop interfaces, and other short messages that do not live in the dialogue
banks.  The original executable contains a second, file-number-specific load-confirmation
table near the map names; those strings are live and must be translated independently of
the generic memory-card messages.

NOT translated (left as-is on purpose): debug text, bu00:BISLPM* memcard save-file
identifiers, sound/VAB/SEQ dumps, single-character name-insert markers, already-English
labels, the file-select title format tails, the superseded map-name pool (its pointer tables
are repointed by map_names.py).  The compact race-label pool used by demon status screens
is translated alongside the other name tables in build.py.
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

# Marker-prefixed ASCII works only when the common system-string wrapper receives the
# marker at the beginning of a draw string.  The COMP concatenates its suffix after a
# fullwidth name, while the Cathedral prompts use the object renderer directly.  Keep
# both groups in compact, fitting fullwidth English on their stock paths.
# The same applies to every slot the prompt composer (append fn 0x8002ad00) adds after
# a leading marker slot (ζ/γ/δ/name-insert): the marker byte lands mid-string, the
# stock per-byte glyph lookup maps ASCII into fullwidth symbol slots, and the text
# renders as '＝≦｝￥' garbage.  All composed slots were found by auditing every
# jal 0x8002ad00 call site.  The demon-dismiss and item-discard confirmations are
# handled separately by patch_composed_prompts, which restructures them into
# single-line questions.
FULLWIDTH_SYSTEM_TEXT = {
    0x1718,  # [name] appears.
    0x1780,  # [name] returned
    0x17e8,  # [name] removed.
    0x1800,  # [name] left.
    0x1eec,  # casino, short on Macca (あら　£が　足りないわ; follows γ marker)
    0x1f0c,  # casino code entry prompt (コードを入力せよ：; follows ζ marker)
    0x2308,  # church/shop leave option (drawn by the object compositor)
    0x3f78,  # shop comparison: Strength (appended to a composed text stream)
    0x3f80,  # shop comparison: Intelligence
    0x3f88,  # shop comparison: Magic
    0x3f90,  # shop comparison: Stamina
    0x3f98,  # shop comparison: Speed
    0x3fa0,  # shop comparison: Luck
    0x3df0,  # Church exit label (copied as a fixed nine-byte object string)
    0x4138,  # Elevator basement prefix (prepended to a generated floor label)
    0x3fd8,  # casino prize-cost suffix (appended to a fullwidth row)
    0x4b68,  # battle status-view action prompt (fixed 15-byte copy)
    0x4b78,  # per-combatant action suffix (appended after a fullwidth name)
    0x52bc,  # First demon?
    0x52d8,  # Next demon?
    0x52f0,  # Final demon?
    0x5310,  # Sword 1?
    0x5324,  # Fuse with whom?
    0x5344,  # Pick sword?
    0x535c,  # Demon to fuse?
    0x537c,  # Second sword?
    0x53e4,  # This one?
    0x53fc,  # Fuse now!
    0x5708,  # church recovery-item prompt (composed after control markers)
    0x5820,  # Church recovery-item quantity prompt (object compositor)
    0x5854,  # Church recovery-item prompt used by the Messian item seller
    0x61ac,  # Church purchase-confirmation suffix (appended after item/price)
    0x66cc,  # shop quantity-owned label (object compositor; stock αβγ glyph aliases)
}


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
    # 0x17cc よろしいですか？ is rebuilt by patch_composed_prompts (demon dismissal)
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
    # 0x1b9c よろしいですか？ is rebuilt by patch_composed_prompts (item discard)
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
    # The original 0x2fb8 "Repel Phys" entry shares its final 物理 glyphs with
    # a suffix at 0x2fc0. Translating that suffix independently creates a mixed
    # SJIS/marker-ASCII stream. Translate only the complete pointer target.
    0x2fb8: (16, "Repel Phys"),            # 反物理
    0x2fc8: (16, "Repel Mind"),            # 反精神
    0x2fd8: (16, "Res Fire/Ice"),          # 対火炎・氷結
    0x2fe8: (16, "Res Elec/Force"),        # 対電撃・衝撃
    0x2ff8: (16, "Res Phys"),              # 対物理
    0x3008: (16, "Res Mind"),              # 対精神
    0x3018: (16, "Res Force"),             # 対衝撃
    0x3028: (16, "Res Elec"),              # 対電撃
    0x3038: (16, "Res Ice"),               # 対氷結
    0x3048: (16, "Res Fire"),              # 対火炎
    0x3058: (16, "Normal"),                # ノーマル

    # ===================== ELEVATOR =====================
    # Raw executable duplicate of compressed message 0x0025.  The elevator
    # calls this literal directly, so translating bank 0 did not affect it.
    0x4118: (32, "Voice: Select a floor."),
    0x4138: (8, "B"),                    # basement + generated number/F -> B1F

    # ===================== STAT / SHOP / CASINO =====================
    0x1d5c: (16, "Points"),               # 残りポイント (level-up points left)
    0x22f8: (8, "Buy"),                  # 買う
    0x2300: (8, "Sell"),                 # 売る
    0x2308: (12, "Exit"),                 # 店を出る (leave shop)
    0x1eec: (24, "Oh, you're short on ћ."),  # あら　ћが　足りないわ (not enough Macca)
    0x1f0c: (20, "Code:"),                # コードを入力せよ：

    # The shop comparison panel requests these through the message append
    # router, not either marker-aware screen printer, so they must stay
    # fullwidth.  Three-letter captions fit their original eight-byte cells.
    0x3f78: (8, "Str"),                  # 力
    0x3f80: (8, "Int"),                  # 知恵
    0x3f88: (8, "Mag"),                  # 魔力
    0x3f90: (8, "Sta"),                  # 体力
    0x3f98: (8, "Spd"),                  # 速さ
    0x3fa0: (8, "Lck"),                  # 運

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
    0x17e8: " removed.",                  # [name]の死体を捨てました
    0x1800: " left.",                     # [name]と別れました
    0x182c: "Analyze whom?",              # どの悪魔を解析しますか？
    0x1848: "Use it on whom?",            # 誰に使いますか？
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
    0x1eec: "Short on ћ.",                # あら ћが足りないわ (fullwidth; 24-byte slot)
    0x1f0c: "Enter:",                     # コードを入力せよ： (fullwidth; follows ζ)
    0x22f8: "Buy",                        # 買う
    0x2300: "Sell",                       # 売る
    0x201c: "Use it on whom?",            # 誰に使いますか？
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
    0x0f84: "Load this file.",
    0x0fbc: "Suspend data exists.",
    0x0ff0: "Proceed?",
    0x1094: "For save and suspend data,",
    0x10b4: "there are too few free blocks.",
    0x1878: "Cannot summon this demon.",
    0x1894: "Magic cannot be used now.",
    0x18d8: "Curse prevents removal!",
    0x18f4: "No usable magic available.",
    0x191c: "Wrong alignment. Can't summon.",
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
    0x23f4: "Change formation.",
    0x2a08: "Keep your heading at map top.",
    0x2a28: "Keep north at map top.",
    0x2a9c: "Repeat the last action.",
    0x2ab8: "Swords/guns/basic only",
}

for _off, _english in ASCII_FIT_ENGLISH.items():
    _gap, _old_english = SYS[_off]
    SYS[_off] = (_gap, _english)


# Additional player-facing strings found by auditing every executable-resident SJIS
# string and its pointer tables.  These are ordinary, NUL-terminated, four-byte-aligned
# slots, so apply_sys derives their safe allocation from the untouched Japanese source.
# Keeping this separate from SYS makes the original hand-measured table above stable.
AUDITED_SYSTEM_TEXT = {
    # Missed short error and the remainder of the System/Config help tables.
    # (0x17bc/0x1b8c, the composed-confirm suffixes, are rebuilt by
    # patch_composed_prompts.)
    0x1964: "Short on cash",
    0x231c: "Spirits",
    0x2c40: "Analyze defeated demons.",
    0x2c60: "Auto-Recover the entire party.",
    0x2c88: "View maps of places visited.",
    0x2cb0: "Remove a demon from party.",
    0x2ccc: "Return a demon to COMP.",
    0x2ce8: "Summon a demon from COMP.",
    0x2d08: "Discard an item.",
    0x2d20: "Reorder your items.",
    0x2d38: "Sort your items.",
    0x2d50: "Use an item.",
    0x2d68: "Configure Auto-Battle.",
    0x2d88: "Set battle message speed.",
    0x2db0: "Configure attack effects.",
    0x2dd0: "Repeat last action; defend if resources run out.",
    0x2e10: "Repeat last action; attack if resources run out.",
    0x2e58: "Use basic attacks, then repeat last action.",
    0x2e88: "Battle settings.",
    0x2e9c: "Return a demon to COMP.",
    0x2eb8: "Use a skill.",
    0x2ecc: "Basic attack.",
    0x2ee0: "Defend.",
    0x2eec: "Attack: Gun",
    0x2efc: "Attack: Sword",
    0x2f0c: "Start Auto-Battle.",
    0x2f28: "Escape from battle.",
    0x2f40: "Talk to the demon.",
    0x2f54: "Start battle.",
    0x2f68: "All Types",
    0x2f78: "Holy Armor",
    0x2f88: "Demon Armor",
    0x2f98: "Drain Elec",
    0x2fa8: "Drain Fire",
    0x3068: "Sorry... Your level is too low.",
    # Fusion result versus player; the stock text warns it cannot be summoned.
    0x3094: "Its alignment differs from yours. Fuse anyway?",
    0x30d4: "Your item bag is full.",
    0x30f0: "That demon is with you.",
    0x310c: "Sorry. The fusion failed.",
    0x31d0: "Battle settings.",
    0x31e4: "Effect settings.",
    0x3200: "Message speed settings.",
    0x3224: "Auto-Battle settings.",
    0x3a90: "Which slot?",
    0x3df0: "Exit",
    0x3f2c: "Lucky Khan",
    0x3f40: "Mr. DNA",
    0x3f50: "Timing X",
    0x3fd8: "C",                           # Coins; stock Japanese counter is 枚

    # Battle prompts stored as raw executable literals rather than compressed
    # bank messages.  The second is appended after the combatant's name.
    0x4b68: "Action?",                     # どうしますか？
    0x4b78: ": Action?",                   # [name]は　どうしますか？
    0x4bb0: "COMP Active",                 # ＣＯＭＰ作動

    # The third field-item target prompt at file offset 0x4e5c is not listed
    # here: its callers append SJIS directly and bypass the marker-aware system
    # printer. build_prod_exe relocates a fullwidth English copy and repoints
    # both callers instead.

    # Cathedral/fusion selection and equipment-detail labels.
    0x5230: "F.Swd",
    0x5288: "F.Swd",
    0x5294: "F.Gun",
    0x529c: "Arms",
    0x52a4: "Head",
    0x52ac: "Legs",
    0x52b4: "Body",
    0x52bc: "First demon?",
    0x52d8: "Next demon?",
    0x52f0: "Final demon?",
    0x5310: "Sword 1?",
    0x5324: "Fuse with whom?",
    0x5344: "Pick sword?",
    0x535c: "Demon to fuse?",
    0x537c: "Second sword?",
    0x53e4: "This one?",
    0x53fc: "Fuse now!",

    # Healing interfaces. Leading spaces complete a dynamically printed name.
    0x5410: "Cost",
    0x546c: "'s curse is gone!",
    0x5480: " was revived!",
    0x5490: " recovered HP and MP!",
    0x54ac: " was cured!",
    0x54c0: " fully healed!",
    0x54d0: "Uncurse whom?",
    0x54ec: "Revive whom?",
    0x5504: "Treat whom?",
    0x551c: "Restore whom?",
    0x5534: "Whose curse shall I lift?",
    0x5554: "Whom shall I revive?",
    0x5570: "Whom shall I treat?",
    0x558c: "Whom shall I restore?",
    0x55a8: "Uncurse whom?",
    0x55c0: "Revive whom?",
    0x55d8: "Treat whom?",
    0x55ec: "Restore whom?",
    0x5604: "Whose curse shall we lift?",
    0x5620: "Whom shall we revive?",
    0x563c: "Whom shall we treat?",
    0x5658: "Whom shall we restore?",
    0x5674: "Need more cash",

    # Shop transaction text. Several shopkeeper personalities share the same
    # mechanics but retain distinct registers in their greetings and replies.
    0x5684: "You're short on cash.",
    0x569c: "You can't carry more.",
    0x56b4: "That's the total. Okay?",
    0x56d0: "How many?",
    0x56e4: "For healing, try items too!",
    0x5708: "Choose:",

    0x571c: "You're short on cash.",
    0x5734: "You can't carry any more.",
    0x5750: "Total okay?",
    0x5764: "How many?",
    0x5774: "Come by anytime!",
    0x5790: "Which one, then?",

    0x57a8: "Not enough.",
    0x57b8: "You can't carry more.",
    0x57d0: "Come back if you want more.",
    0x57f0: "Which one?",

    0x5804: "Your offering is lacking.",
    0x5820: "How many?",
    0x5834: "Return whenever you have need.",
    0x5854: "Choose:",

    0x5868: "Can't equip it. Still buy?",
    0x5884: "You aren't in any state to shop.",
    0x58a8: "You can't carry more cash.",
    0x58c8: "You're short on cash.",
    0x58e0: "Inventory is full.",
    0x58f8: "Equip it now?",
    0x5908: "Total is... OK?",
    0x591c: "How many?",
    0x5930: "Thanks a bunch!",
    0x5944: "Selling what?",
    0x5958: "I can't buy anything you have. Sorry.",
    0x5984: "So, what will you buy?",
    0x59a0: "Junk Shop: Step right up!",

    0x59c0: "Equip it right away?",
    0x59d8: "Total okay?",
    0x59f0: "How many?",
    0x5a04: "Thanks.",
    0x5a10: "Sell what?",
    0x5a20: "I can't buy any of that. Bring me something worthwhile.",
    0x5a64: "Buy what?",
    0x5a74: "Armor Shop: Need something tough?",

    0x5a98: "Can't equip it. Still buy?",
    0x5ab4: "You're unfit to shop. Come back later.",
    0x5ae0: "You can't carry more cash.",
    0x5b00: "Inventory is full.",
    0x5b18: "Total okay?",
    0x5b2c: "Thanks. Come again.",
    0x5b44: "Got something to sell?",
    0x5b60: "Nothing I can buy. Bring me something good next time.",
    0x5b9c: "All fine weapons here.",
    0x5bb4: "Weapon Shop: Good gear",

    0x5bcc: "Can't equip it. Still purchase?",
    0x5bf0: "You are in no state to shop.",
    0x5c10: "You cannot carry any more cash.",
    0x5c34: "You lack the funds.",
    0x5c4c: "Your inventory is full.",
    0x5c68: "Equip it immediately?",
    0x5c84: "That is the total. Proceed?",
    0x5ca4: "How many?",
    0x5cb4: "Thank you very much.",
    0x5cd0: "What would you like to sell?",
    0x5cf0: "I cannot buy any of that. Bring me other goods.",
    0x5d24: "What would you like?",
    # 防具屋 is the speaker label; the gear, not the shopkeeper, stops attacks.
    0x5d3c: "Armor Shop: Gear stops any attack!",

    0x5d60: "You can't equip it. Is that okay?",
    0x5d84: "You can't shop right now.",
    0x5da0: "You can't carry so much cash.",
    0x5dc0: "Sorry, but I can't lower the price any further.",
    0x5df4: "Inventory is full.",
    0x5e0c: "That is the total. Proceed?",
    0x5e2c: "Thank you. Please come again.",
    0x5e50: "Which item will you sell me?",
    0x5e70: "What will you buy?",
    # 武器 is generic and includes guns; 業物 must not become blade-specific here.
    0x5e84: "Weapon Shop: Finest weapons here.",

    0x5ea8: "Y-You can't carry that much cash.",
    0x5ecc: "Y-You need more cash.",
    0x5ee4: "Y-You can't carry more.",
    0x5f00: "Th-That's the total. Is it okay?",
    0x5f24: "H-How many?",
    0x5f3c: "Th-Thank you very much.",
    0x5f58: "Wh-What will you sell?",
    0x5f78: "I-I can't buy that. Please bring something else.",
    0x5fac: "Wh-What will you buy?",
    0x5fc8: "Hanoun: O-Oh! Welcome.",

    0x5fec: "Can't equip it. Still buy?",
    0x6008: "No shopping until you heal up.",
    0x602c: "No more cash. Don't be greedy.",
    0x6054: "Not enough cash. Bring more.",
    0x607c: "Bag's full. Don't be greedy.",
    0x609c: "Equip it now?",
    0x60b0: "Total okay?",
    0x60c4: "How many?",
    0x60d0: "Much obliged.",
    0x60e4: "Sell what?",
    0x60f0: "Nothing I can buy. Bring me goods.",
    0x6118: "Buy what?",
    0x6128: "Armor Shop: Welcome.",

    0x6140: "You can't carry so much cash.",
    0x6160: "You need more cash.",
    0x617c: "Inventory is full.",
    0x6194: "Equip it right away?",
    0x61ac: " Is that OK?",
    0x61c8: "How many?",
    0x61dc: "Thank you very much.",
    0x61f4: "What will you sell?",
    0x6210: "I can't buy that. Please bring other goods.",
    0x6240: "What would you like?",
    0x625c: "Researcher: See our latest work.",

    0x6280: "Can't equip it. Still buy?",
    0x629c: "Can't shop right now.",
    0x62b4: "You can't carry so much cash.",
    0x62d4: "Not enough cash.",
    0x62e8: "Inventory is full.",
    0x6300: "Equip it right away?",
    0x6318: "Total okay?",
    0x6330: "How many?",
    0x6344: "Thanks.",
    0x6350: "What are you selling me?",
    0x636c: "Nothing I can buy. Bring me goods.",
    0x6394: "What will you buy?",
    0x63a8: "Junk Shop: Need something?",

    0x63c4: "Can't equip it. Still want it?",
    0x63e8: "You can't shop right now.",
    0x6404: "You can't carry so much cash.",
    0x6424: "You're short on cash.",
    0x643c: "Inventory is full.",
    0x6454: "Equip it right away, dear?",
    0x6470: "That's the total. All right?",
    0x6490: "How many would you like?",
    0x64ac: "Thanks! Come again, dear.",
    0x64cc: "What would you like to sell?",
    0x64ec: "Nothing I can buy, dear. Bring me something else.",
    0x6520: "What would you like, dear?",
    0x653c: "Armor Shop: Welcome, dear!",

    0x655c: "Can't equip it. Still buy?",
    0x6578: "You can't shop right now.",
    0x6594: "You can't carry so much cash.",
    0x65b4: "Not enough money.",
    0x65c8: "Inventory is full.",
    0x65e0: "Equip it now?",
    0x65f8: "Total okay?",
    0x6610: "How many?",
    0x6624: "Thanks. Come again.",
    0x663c: "Anything to sell me?",
    0x6658: "Nothing I can buy. Please bring me something.",
    0x6694: "What will you buy?",
    0x66a8: "Weapon Shop: Welcome.",
    0x66cc: "OWN",                        # αβγ aliases render as 所持数 (quantity owned)

    # Equipment comparison and a small shop reward sequence.
    0x6700: "Attack",
    0x6708: "Hit",
    0x6710: "Hits",
    0x671c: "DEF",
    0x6724: "Evade",
    0x672c: "Affin.",
    0x6734: "Effect",
    0x6740: "Align",
    0x6778: "What now?",
    0x67c8: "Curse prevents removal!",
    0x6800: " ",
    0x6840: "...Wait a moment.",
    0x685c: "You came all this way. Take this.",
    0x6884: "Keep coming back, all right?",
    0x68b0: '>Obtained the "Mercury Pillar."',

    # Live file-specific load confirmation table. map_names.py intentionally
    # leaves these four entries in place because they are not map names.
    0x6a20: "Load File 1.",
    0x6a3c: "Proceed?",
    0x6a54: "Load File 2.",
    0x6a70: "Load File 3.",

    # Direct event literal outside the compressed dialogue banks.
    0x75a8: ">An earthquake struck!",
}


# Armor record byte +3 indexes this executable pointer table. Keep the English
# in pointer order so the build can verify all 16 profiles semantically and
# catch missing or overlapping translations.
_EQUIPMENT_AFFINITY_POINTER_TABLE = 0xE8220
_EQUIPMENT_AFFINITY_TEXT = (
    (0x3058, "Normal"),         # ノーマル
    (0x3048, "Res Fire"),       # 対火炎
    (0x3038, "Res Ice"),        # 対氷結
    (0x3028, "Res Elec"),       # 対電撃
    (0x3018, "Res Force"),      # 対衝撃
    (0x3008, "Res Mind"),       # 対精神
    (0x2ff8, "Res Phys"),       # 対物理
    (0x2fe8, "Res Elec/Force"), # 対電撃・衝撃
    (0x2fd8, "Res Fire/Ice"),   # 対火炎・氷結
    (0x2fc8, "Repel Mind"),     # 反精神
    (0x2fb8, "Repel Phys"),     # 反物理
    (0x2fa8, "Drain Fire"),     # 吸火炎
    (0x2f98, "Drain Elec"),     # 吸電撃
    (0x2f88, "Demon Armor"),    # 魔性防具
    (0x2f78, "Holy Armor"),     # 神聖防具
    (0x2f68, "All Types"),      # 全対応
)


# Save-file LIST entries are sprintf format strings that begin with the JP game title
# 真・女神転生２ (7 fullwidth chars = 14 bytes) followed by ` ＱＵＩＴ/ＦＩＬＥ%s ...ＬＶ%s%s`.
# We swap ONLY the title -> fullwidth "SMT2", preserving the whole %s/spacing tail exactly.
_JP_TITLE = bytes.fromhex("905e81458f97905f935d90b68251")  # 真・女神転生２
TITLE_FMT_OFFS = (0x1388, 0x13cc, 0x1410, 0x1454)

def apply_sys(exe):
    """Write English system text into the original fixed slots."""
    for off, (gap, en) in SYS.items():
        data = _fw(en) + b"\0" if off in FULLWIDTH_SYSTEM_TEXT else _ascii(en)
        if len(data) > gap:
            raise SystemExit(
                f"sys 0x{off:x} OVERFLOW {len(data)}>{gap} bytes: {en!r}")
        exe[off:off + gap] = data + bytes(gap - len(data))
    for off, en in AUDITED_SYSTEM_TEXT.items():
        if off in SYS:
            raise SystemExit(f"audited sys 0x{off:x}: duplicate SYS entry")
        end = exe.index(0, off) + 1
        gap = ((end - off + 3) // 4) * 4
        if any(exe[end:off + gap]):
            raise SystemExit(f"audited sys 0x{off:x}: nonzero slot padding")
        data = _fw(en) + b"\0" if off in FULLWIDTH_SYSTEM_TEXT else _ascii(en)
        if len(data) > gap:
            raise SystemExit(
                f"audited sys 0x{off:x} OVERFLOW {len(data)}>{gap} bytes: {en!r}")
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

    # A build-time assertion for every audited player-facing slot. This catches a
    # future patch ordering change that might restore Japanese data after this pass.
    for off in (*SYS, *AUDITED_SYSTEM_TEXT):
        if off in FULLWIDTH_SYSTEM_TEXT:
            english = SYS[off][1] if off in SYS else AUDITED_SYSTEM_TEXT[off]
            expected = _fw(english) + b"\0"
            if bytes(exe[off:off + len(expected)]) != expected:
                raise SystemExit(f"sys audit: 0x{off:x} is not fullwidth English")
        elif exe[off] != ASCII_MARKER:
            raise SystemExit(f"sys audit: 0x{off:x} is not marker-prefixed English")

    for index, (target_off, english) in enumerate(_EQUIPMENT_AFFINITY_TEXT):
        pointer = struct.unpack_from(
            "<I", exe, _EQUIPMENT_AFFINITY_POINTER_TABLE + index * 4
        )[0]
        expected_pointer = 0x8000F800 + target_off
        if pointer != expected_pointer:
            raise SystemExit(
                f"equipment affinity {index}: pointer {pointer:#x} != "
                f"{expected_pointer:#x}"
            )
        expected = _ascii(english)
        actual = bytes(exe[target_off:target_off + len(expected)])
        if actual != expected:
            raise SystemExit(
                f"equipment affinity {index} at 0x{target_off:x} is not "
                "intact marker-prefixed English"
            )


# The demon-dismissal and item-discard confirmations are composed by dedicated
# functions that append fixed exe slots around the name:
#   dismiss (0x80030614): ζ, name-marker 0x8762, roster name, と別れます, δ, よろしいですか？
#   discard (0x80033190): ζ, item name, を捨てます, δ, よろしいですか？
# Japanese puts the name first, so a natural one-line English question needs its
# verb BEFORE the name.  The composer references every slot with its own
# lui/addiu pair, so the first append is repointed at the roomy 20-byte
# よろしいですか？ slot, rebuilt as the ζ marker plus the fullwidth verb; the old
# 12-byte suffix slot keeps only the closing "？"; and the δ line break plus the
# second-line append are removed.  Result: "Dismiss <name>?" / "Discard <item>?"
#
# The stock dismiss-only 0x8762 marker is also no longer needed: the routine
# appends the roster name itself at 0x80030664.  Its display handler changes the
# active window's bottom coordinate by five pixels, and the confirmation-exit
# path appends the same marker again before returning to "Who leaves?".  Drop both
# copies and restore the live rectangle's bottom from the configured one-line
# rectangle on every invocation, including when loading a save state whose RAM
# was already expanded.
_RAM_BASE = 0x8000f800  # exe file offset 0 loads at this address
_APPEND_JAL = 0x0C00AB40  # jal 0x8002ad00
_NOP = 0x00000000

def _composed(marker, verb):
    return bytes(marker) + _fw(verb) + b"\0"

_JP_SUFFIX_WAKARE = bytes.fromhex("82c695ca82ea82dc82b7") + b"\0"  # と別れます
_JP_SUFFIX_SUTERU = bytes.fromhex("82f08ecc82c482dc82b7") + b"\0"  # を捨てます
_JP_YOROSHII = bytes.fromhex("82e682eb82b582a282c582b782a98148") + b"\0"  # よろしいですか？

# (slot file offset, slot byte gap, expected untouched Japanese, replacement)
_COMPOSED_SLOTS = (
    (0x17bc, 12, _JP_SUFFIX_WAKARE, _fw("?") + b"\0"),
    (0x17cc, 20, _JP_YOROSHII, _composed(b"\x83\xc4", "Dismiss ")),  # ζ + verb
    (0x1b8c, 12, _JP_SUFFIX_SUTERU, _fw("?") + b"\0"),
    (0x1b9c, 20, _JP_YOROSHII, _composed(b"\x83\xc4", "Discard ")),  # ζ + verb
)

# (instruction address, expected stock word, replacement word)
_COMPOSED_CODE = (
    # demon dismissal: first append ζ 0x17b4 -> combo slot 0x17cc; drop the
    # geometry-changing marker, δ, and line 2; reset the one-line frame.
    (0x8003061c, 0x24840FB4, 0x24840FCC),  # addiu a0, a0, 0xfb4 -> 0xfcc
    (0x8003063C, _APPEND_JAL, _NOP),       # append 0x8762 name marker
    (0x80030678, 0x3C048001, 0x3C02800F),  # lui v0, 0x800f
    (0x8003067C, _APPEND_JAL, 0x2442EB7C),  # addiu v0, v0, -0x1484
    (0x80030680, 0x24840FC8, 0x94430006),  # lhu v1, 6(v0): configured bottom
    (0x80030684, 0x3C048001, _NOP),        # R3000 load-delay slot
    (0x80030688, _APPEND_JAL, 0xA4430016),  # sh v1, 0x16(v0): live bottom
    (0x8003068C, 0x24840FCC, _NOP),        # old second-line pointer delay slot
    (0x800307D8, _APPEND_JAL, _NOP),       # exit-time 0x8762 marker
    # item discard: first append ζ 0x1b88 -> combo slot 0x1b9c; drop δ + line 2
    (0x800331C4, 0x24841388, 0x2484139C),  # addiu a0, a0, 0x1388 -> 0x139c
    (0x80033200, _APPEND_JAL, _NOP),       # append δ
    (0x8003320C, _APPEND_JAL, _NOP),       # append よろしいですか？
)


def patch_composed_prompts(exe):
    """Rebuild the dismiss/discard confirmations as one-line questions."""
    for off, gap, expected_jp, data in _COMPOSED_SLOTS:
        if bytes(exe[off:off + len(expected_jp)]) != expected_jp:
            raise SystemExit(f"composed prompt 0x{off:x}: unexpected slot content")
        if len(data) > gap:
            raise SystemExit(f"composed prompt 0x{off:x} OVERFLOW {len(data)}>{gap}")
        exe[off:off + gap] = data + bytes(gap - len(data))
    for address, expected, replacement in _COMPOSED_CODE:
        off = address - _RAM_BASE
        actual = struct.unpack_from("<I", exe, off)[0]
        if actual != expected:
            raise SystemExit(
                f"composed prompt code at 0x{address:08x}: "
                f"expected 0x{expected:08x}, found 0x{actual:08x}")
        struct.pack_into("<I", exe, off, replacement)


_JP_SHOP_TOPIC_PARTICLE = bytes.fromhex("82cd0000")  # は + slot padding


def patch_shop_composed_prompts(exe):
    """Remove Japanese grammar left between an English item name and price.

    The purchase-confirmation composer builds: ζ, item name, は, δ, currency,
    price, space, and a shopkeeper-specific suffix.  English does not need the
    topic particle; the suffix itself is kept fullwidth because it is appended
    after the control and dynamic fields.
    """
    off = 0x67ac
    actual = bytes(exe[off:off + len(_JP_SHOP_TOPIC_PARTICLE)])
    if actual != _JP_SHOP_TOPIC_PARTICLE:
        raise SystemExit(
            f"shop confirmation 0x{off:x}: unexpected topic-particle slot")
    exe[off:off + len(_JP_SHOP_TOPIC_PARTICLE)] = bytes(
        len(_JP_SHOP_TOPIC_PARTICLE))
