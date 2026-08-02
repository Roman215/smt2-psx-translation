# Changelog

All notable changes to the SMT2 PSX English translation are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/): while below
1.0.0, the minor version marks notable new content or features and the patch
version marks fixes and small text improvements.

Releases ship as xdelta patches only. No game data is ever distributed; see
the release notes attached to each GitHub release for how to apply a patch to
your own verified source image.

## [Unreleased]

## [0.2.1] - 2026-08-02

This patch repairs the hero's name at the reveal scene, gives the overhead map
marker the series' alignment-driven spin, and revises around 150 lines of
dialogue against the Japanese script — most of them demon negotiation.

### Added

- The player marker on the 2D overhead map now turns according to your
  alignment, as it does elsewhere in the series: clockwise for Law,
  counter-clockwise for Chaos, and a Neutral zig-zag that rocks around the
  sideways frame without ever turning past it. It reads the same alignment
  value the game itself uses, so the spin changes as your alignment shifts.
  Like the Demon Compendium this is a gameplay enhancement, and
  `--no-enhancements` leaves the map exactly as it was.

### Changed

- Revised roughly 150 lines of dialogue against the Japanese script. Most are
  demon negotiation exchanges, which now read as spoken lines instead of
  literal glosses and no longer collapse several distinct demon replies into
  one repeated phrase. The rest cover the Underworld and endgame scenes —
  the offer made after the Astaroth ambush and the plea to refuse it, YHVH's
  judgment, Ozawa, the appeal to stop Kuzuryu — plus battle and negotiation
  status messages.
- Renamed the stat called Wisdom in dialogue to Intelligence, matching the
  status screen and the shop comparison panel. It appears in the Chokmah Tower
  guardian's test, the message left outside the sealed watchtower door, and
  the rumor about the Factory's signal.
- Money messages now use the game's Macca symbol rather than the word "cash",
  so "Short on cash" and "Need more cash" read as "Not enough ћ", and the
  carrying-limit refusal reads "Macca's maxed out."
- Retitled the well-dressed Valhalla informant from "Dandy" to "Dapper Man",
  and gave Louis Cyphre his full name on the speaker label after the Astaroth
  impersonation.
- Reworked the casino's Keno pun so it lands in English: the game is spelled
  KENO but pronounced KINO, which the previous wording lost.
- Item pickups now read `Obtained "<item>" x3` instead of
  `Obtained 3 of "<item>"`.
- Gave the shopkeepers back some of their individual register — the junk
  dealer, weapon smith, and armorer no longer share the same flat phrasing —
  and reworded a handful of menu strings, including "Your item bag is full"
  to "Your inventory is full".

### Fixed

- The name-reveal scene now renames the hero to Aleph instead of アレフ. The
  game keeps its party-name template in two places and re-initializes only the
  first six of its seven slots from `CMDINIT.BIN`; the seventh, the hero's true
  name, is served from the executable's own copy, which had never been
  translated. Saves already past that scene keep the katakana name — the
  release notes carry GameShark codes that repair one.
- Restored the Cathedral's warning that a fusion result whose alignment differs
  from yours cannot be summoned. The prompt previously only noted the
  mismatch, so the demon could be lost without warning.
- Corrected the Cathedral's fusion-accident message, which read "Sorry. The
  fusion failed." although the fusion succeeds — it simply produces a demon
  other than the one predicted.
- Corrected the demon names Andira and Sandira, previously spelled Antila and
  Santira.

## [0.2.0] - 2026-07-28

This release reworks the Demon Compendium around what it is actually used for
(summoning several demons in a row) and corrects a Cathedral interface label,
five demon names, and two lines of dialogue.

### Changed

- The Demon Compendium now stays open after a summon. Previously every demon
  cost you the whole journey back: the browser closed, you reopened it from
  the Cathedral menu, chose a sort order again, and scrolled back down to
  where you were. Now the result is shown in place (the summon itself, or a
  refusal such as insufficient Macca, a full party, or a demon above your
  level), and confirming it returns you to the list on the same demon, under
  the same sort order. Cancelling still returns to the Cathedral menu.
- Machine, Vaccine, and Virus demons no longer appear in the Demon Compendium.
  None of those eleven can be recruited, fused, or otherwise registered, so
  their rows could never be filled in and only read as gaps in a collection
  that is in fact complete. They remain listed in ordinary Devil Analysis,
  which is still where you look up an enemy you are about to fight.

### Fixed

- Labelled the 10th, 11th, and 12th columns and rows of the Cathedral fusion
  compatibility matrix A, B, and C. They previously read Y, E, and S, which
  looked like a word rather than a continuation of the numbering.
- Corrected the demon names Remiel, Baek Yong, Celaeno, Otohime, and Jinn,
  previously spelled Ramiel, Pek Young, Kelaino, Oto-hime, and Djinn.
- Capitalized the start of Gabriel's self-introduction in the Elder's scene.
- Removed a line break that split "We believe in our savior, <name>, so we
  aren't worried." immediately after the name.

## [0.1.8] - 2026-07-25

This patch marks the translation as fully playable and corrects several
remaining interface, terminology, and speaker-label issues found after 0.1.7.

### Fixed

- Corrected another Dark/Gold Coin casino fragment so the dynamic coin type
  precedes "Coins" instead of incorrectly preceding "Remember."
- Translated the missing "Items" heading above Rag's Shop exchange-item panel.
- Rendered equipment-shop affinity captions and values with the compact font,
  keeping every translated affinity inside its comparison-panel row.
- Restored the omitted Warrior and Divine General race-table entries so
  special Fiends such as Alice resolve race ID 43 as "Fiend" instead of
  decoding adjacent compressed data as garbage.
- Standardized the demon and enemy names Taueret, Take-Minakata, Okuninushi,
  Hitokoto-Nushi, Sukuna-Hikona, Ouyamatsumi, Corpses, and Hell Biker.
- Identified the Pixie speaking about Puck by name instead of using the generic
  "Fairy" label.

## [0.1.7] - 2026-07-23

This release focuses on reliability and presentation fixes found after 0.1.6,
especially in the new Demon Compendium, demon negotiation, equipment details,
and Cathedral interfaces.

### Changed

- Reworked reusable demon-negotiation lines so their randomized combinations
  join into natural English.
- Polished Hiruko's request and Lord Masakado's revival dialogue against the
  Japanese, improving the connected story scene while preserving its meaning
  and formal tone.
- Renamed the ambiguous special armor affinities to "Demonic Ward,"
  "Holy Ward," and "Res All."
- Expanded the translation-audit tools to check hard-coded negotiation joins
  and generate a Japanese/English comparison for system text stored in the
  executable.

### Fixed

- Made every acquired demon eligible to appear in the Demon Compendium,
  including fusion-only Elements such as Aquans that were absent from the
  original Devil Analyzer's enemy-oriented sort tables.
- Restored the ordinary Devil Analyzer's "Analyze whom?" prompt after the
  Compendium's summon-cost display had corrupted it.
- Made the over-level Compendium rejection wait for acknowledgement before
  returning to the Cathedral menu, matching the other summon failures.
- Corrected the charm result message so it names the affected party member
  instead of claiming that the opposing demon was charmed.
- Corrected misleading shop and status text, including weapon-shop wording,
  the armor-shop greeting, and other messages whose English used the wrong
  subject or changed the Japanese meaning.
- Restored Skull Gi's "Repel Phys" affinity and verified all 16 armor
  resistance profiles against the Japanese data.
- Kept all twelve columns of the Cathedral fusion compatibility matrix inside
  the screen and centered its compact result symbols.
- Lowered compact English demon names and races to sit naturally at the bottom
  of their fields on fusion, status, and related screens.
- Corrected the casino cashier's Dark/Gold Coin balance sentence, including
  its missing space and misplaced coin type.
- Kept the post-dismissal "[demon] left." result at a one-line height instead
  of opening an unnecessary two-line message box.

## [0.1.6] - 2026-07-22

This release adds a modern Demon Compendium while retaining an explicit
original-gameplay build, and fixes presentation and text issues present in
0.1.5.

### Added

- Added a Demon Compendium to the Cathedral of Shadows. It automatically
  records recruited demons and completed fusion results, imports demons held
  by existing saves, provides race/name/level/alignment sorting, displays each
  demon's Macca cost, and summons fixed default-stat forms subject to the
  protagonist's level, roster space, and duplicate restrictions. Registration
  persists through the original save payload without changing its format.
- Added four release profiles covering English or Japanese movies with either
  the default enhancements or original gameplay mechanics.

### Changed

- Enabled gameplay enhancements by default and added `--no-enhancements` as a
  general opt-out for purist builds and future modern features.
- Clarified Cathedral fusion warnings that compare the resulting demon's
  alignment with the player's alignment.
- Expanded the translation-spacing audit to cover adjacent runtime names and
  dialogue that continues across separately stored message records.

### Fixed

- Restored the equipment-shop header's original name inset so the status icon
  no longer overwrites the first letter of the selected human's name.
- Made generated movie files inherit the build directory's permissions on
  Windows, allowing subsequent builds to read and replace them reliably.
- Prevented the widened demon-negotiation response texture from wrapping at
  the PSX texture-page boundary and showing stale player-name fragments.
- Inset the negotiation response panel's right and bottom endpoints so their
  complete beveled edges remain visible against the full-screen frame.
- Kept both the COMP demon-dismissal confirmation and the returning "Who
  leaves?" prompt at their original one-line height after choosing NO.
- Lowered the dialogue apostrophe by one pixel so it no longer collides with
  descenders on the preceding line.
- Restored missing spaces at every cross-record dialogue join identified by
  the expanded audit, including repeated words and dynamic race/demon names.
- Corrected the casual thank-you shown when leaving the Valhalla bar.

## [0.1.5] - 2026-07-22

This release substantially improves demon negotiation and makes long English
names safe and readable throughout the interface. It also translates several
missed prompts and fixes presentation problems in shops, Cathedral fusion,
battle menus, movies, and other text-heavy screens.

### Added

- Translated Charon's baked-in game-over movie dialogue while retaining its
  original fade timing and moving background.
- Translated the previously missed Center elevator prompt and floor labels.

### Changed

- Reworked demon negotiation directly from the original Japanese and audited
  every reachable combination of its interchangeable dialogue fragments.
  Questions, answers, and outcomes now join into natural English regardless of
  which route the game selects.
- Reviewed every negotiation YES/NO prompt and every prompt-specific response
  set so the available answers match the question being asked.
- Redesigned the negotiation response panel to accommodate four choices, the
  longest English response, and two-line prompts without clipping or covering
  text. Multiword responses now use sentence case.
- Renamed Jack O'Lantern to Pyro Jack.
- Generalized movie builds and release variants to cover both translated and
  original Japanese movies; the latter now use the clearer
  `_JP_movies.xdelta` filename.

### Fixed

- Fixed long demon names corrupting the following party record. Names such as
  Yamata-no-Orochi now display completely in party panels, status screens, and
  Cathedral fusion menus without wrapping over themselves or crowding nearby
  statistics.
- Widened and reorganized the Cathedral's race, demon-name, result, level, and
  affinity columns so the full English names remain readable on every fusion
  selection screen.
- Fixed missing spaces and speaker colons around inserted hero, heroine, party,
  NPC, and demon names throughout dialogue.
- Restored English text throughout weapon, armor, and item shops, including
  clerk dialogue, Buy/Sell choices, item details, and the blue comparison
  panels' stat and equipment captions.
- Translated the raw battle action prompts used by the Triangle status view
  and individual combatant selection, along with the related COMP activation
  label.
- Removed the colored flash at the start of rebuilt movies by preserving
  full-range black through the lossless encoding stage and validating the
  first encoded frame.
- Restored the first letter of long prize names in the casino minigames'
  PRIZE panel, which dropped it for any name of ten or more characters
  ("Disparalyze" showed as "isparalyze"), and centered every prize on its
  real kerned width instead of the Japanese fixed-width character grid.
- Removed the stray blank line that appeared mid-sentence when a message
  line reached the right edge of the dialogue box and the script's own line
  break then fell on the following line.
- Restored the separator between the two halves of a place name on one-line
  displays such as the Automap header, which ran them together
  ("Madam'sManor", "KeterCastle 8F").
- Removed stray roster markers that could overlap the first letter of party
  member names in Church and field interfaces.

## [0.1.4] - 2026-07-20

This maintenance release addresses text-rendering and menu-layout issues found
after 0.1.3, particularly in the Cathedral, COMP, Church, and casino interfaces.

### Changed

- Refined the compact party and demon-name font with balanced, half-width
  capitals that match its clean single-stroke lowercase letters.
- Matched the race and demon-name typography in Cathedral fusion lists.

### Fixed

- Fixed long or repeated English name inserts overflowing the stock text
  buffer, which could corrupt the final enemy name in large groups.
- Fixed dictionary-expanded text being sent to the wrong message buffer during
  streamed dialogue, which could produce garbled or overdrawn fusion-result
  boxes.
- Fixed the garbled Church menu exit option, recovery-item list and quantity
  prompts, and item purchase confirmation.
- Translated the recovery-item quantity label as "OWN" without changing its
  compact blue-box layout.
- Widened the name field in every casino prize inventory so long English item
  names remain separated from their costs, and replaced the Japanese cost
  counter with the Coin suffix "C".
- Fixed garbled demon and sword selection prompts in Cathedral fusion menus.
- Fixed excessive spacing between capital and lowercase letters in Cathedral
  party and fusion-result names.
- Fixed garbled symbol text in the COMP demon-dismissal and item-discard
  confirmation prompts, and in the casino's insufficient-Macca and code-entry
  messages. The confirmations now read as natural one-line questions:
  "Dismiss [name]?" / "Discard [item]?"
- Restored the stock look of the greyed YES/NO confirmation options: they had
  shrunk because their renderer shares the compact 10x10 font introduced for
  demon-name lists. The five stock heavy glyphs are preserved in unused font
  cells so the confirm box renders pixel-identically to the original.

## [0.1.3] - 2026-07-19

This maintenance release translates another previously missed status label
and fixes text rendering issues found in the COMP and spell menus.

### Fixed

- Translated the demon race labels shown in the upper-left corner of demon
  status screens.
- Fixed garbled result messages when summoning, returning, or dismissing demons
  through the COMP.
- Shortened spell and skill descriptions that could reach or overflow the
  right edge of their description box.

## [0.1.2] - 2026-07-19

This hotfix release addresses two issues found shortly after 0.1.1.

### Fixed

- Fixed successful demon recruitment entering the wrong choice handler, which
  could show an empty YES/NO prompt, falsely report a full demon roster, and
  corrupt the dismissal screen even when the player had no demons.
- Fixed the Bar's drink list layout so "Speed Cocktail" no longer runs into
  its price and "Miracle Tonic" no longer loses its initial M.
- Corrected suspenseful, two-part demon-negotiation messages so results such as
  "went berserk" and "calmed down" connect naturally to the demon's name.

## [0.1.1] - 2026-07-18

Thank you to arciks1192-svg who tried the first public release and reported what
they found. This maintenance release focuses on missing interface text,
cleaner early-game dialogue, and several bugs uncovered through player
feedback.

### Added

- Translated previously missed text stored in separate game overlays,
  including Automap marker instructions and prompts, casino demon-selection
  text, the bonus viewer's race and demon lists, and Rag's Earthies label
  ([#4](https://github.com/Roman215/smt2-psx-translation/issues/4)).
- Translated all 115 demon-negotiation choice labels, including responses such
  as "Friendly" and "Intimidating."

### Changed

- Reformatted Virtual Battler level choices to clearly separate each level
  from its Macca cost and display the Macca symbol
  ([#2](https://github.com/Roman215/smt2-psx-translation/issues/2)).
- Reworked STEVEN's early Virtual Battler dialogue to sound more natural and
  to clarify what the Demon Summoning Program is meant to do
  ([#3](https://github.com/Roman215/smt2-psx-translation/issues/3)).
- Polished several other early-game lines, including the shopkeepers who
  refuse service because of Okamoto's debts and the Virtual Battler
  attendant's farewell.
- Reworded item-use target prompts as the more natural "Use it on whom?"

### Fixed

- Corrected victory messages that could display the wrong number of defeated
  enemies, especially for the second enemy group
  ([#1](https://github.com/Roman215/smt2-psx-translation/issues/1)).
- Fixed demon negotiation dialogue displaying corrupted text, restored its
  choice menus, and rebuilt the negotiation text handling so dictionary
  compression no longer conflicts with the game's choice command
  ([#5](https://github.com/Roman215/smt2-psx-translation/issues/5)).
- Fixed healing items displaying corrupted text when asking which party member
  should receive the item.

## [0.1.0] - 2026-07-18

First public release.

### Added

- Variable-width English rendering across dialogue, menus, and status screens
  (kerned 12x12 and 10x10 fonts, VWF hooks on all three printer paths).
- English dialogue engine: dictionary-compressed text with rebuilt Huffman
  trees covering all dialogue banks, including the negotiation/battle banks.
- Translated name tables: demons, races, spells, items, locations, NPCs,
  traits, and drinks.
- Translated menus, system strings, boot disclaimer, map/save-list location
  names, and default party names.
- English name-entry screen: A-Z/a-z/0-9 grid with an END button.
- Translated opening movie crawl, re-rendered with the game's own font at the
  original resolution and frame layout.
- Complete story translation: all dialogue banks (0-7) are in English,
  including the negotiation/battle banks.
- Reproducible build (`build.py`) that patches a verified Japan Rev 1 image
  and emits distributable xdelta patches.

[Unreleased]: https://github.com/Roman215/smt2-psx-translation/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/Roman215/smt2-psx-translation/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Roman215/smt2-psx-translation/compare/v0.1.8...v0.2.0
[0.1.8]: https://github.com/Roman215/smt2-psx-translation/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/Roman215/smt2-psx-translation/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/Roman215/smt2-psx-translation/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/Roman215/smt2-psx-translation/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/Roman215/smt2-psx-translation/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/Roman215/smt2-psx-translation/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Roman215/smt2-psx-translation/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Roman215/smt2-psx-translation/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Roman215/smt2-psx-translation/releases/tag/v0.1.0
