<img width="1920" height="1080" alt="thumbnail3" src="https://github.com/user-attachments/assets/ded41e14-9b4e-4086-80d2-e1c84400dc27" />

# Flexible Stratagems

A Helldivers 2 Lua mod for [Bingus Shared Loader](https://github.com/CowboyBingus/BingusSharedLoader) that lets the
Hellpod loadout take the same stratagem more than once, vehicles included. Formerly Stratagems Unleashed.

## Features

- Pick the same stratagem again in the Hellpod loadout: the game's normal pick, with its sound, sent to your team
  and saved like any loadout.
- Three rulesets in [Mod Options Menu](https://github.com/CowboyBingus/ModOptionsMenu) (escape menu > MODS > Flexible
  Stratagems):
  - **Off:** the game's own rules.
  - **Less Restricted** (default): up to two of each stratagem, vehicles included. When one copy is used, the other
    goes on a 10 second cooldown unless it already has a longer one (Eagles already share their rearm).
  - **Unleashed:** any stratagem any number of times, no extra cooldowns.
- Without Mod Options Menu the ruleset is Less Restricted.
- Only your loadout changes, and it goes out through the game's own sync: teammates don't need the mod.
- The option follows the game's Text Language (English and Brazilian Portuguese included; see
  [translating](https://github.com/CowboyBingus/ModOptionsMenu/blob/main/TRANSLATING.md)).

## Installation

1. Install [Bingus Shared Loader](https://www.nexusmods.com/helldivers2/mods/16292) (v17 or newer).
2. Optional: [Mod Options Menu](https://www.nexusmods.com/helldivers2/mods/16625) to choose the ruleset.
3. Install the ZIP from [Releases](https://github.com/Alomare/FlexibleStratagems/releases) with
   [HD2 Arsenal](https://www.nexusmods.com/helldivers2/mods/4664) (or HD2 Mod Manager) and deploy. Keep Bingus Shared
   Loader last in the mod order, so it loads first.

The verdict is the first line of `%LOCALAPPDATA%\CowboyBingus\Helldivers2\Logs\FlexibleStratagems_STATUS.log`.

## Technical Details

- **Duplicates.** The loadout screen's stratagem list marks the stratagems already in the loadout as equipped, and a
  press on an equipped item is refused. While the list is open, the mod marks the loadout's stratagems back as
  selectable through the list's own marker function (Less Restricted: only those in the loadout once), so picking one
  again runs the game's normal equip. After such a pick the list's selection is cleared through the game's select
  function, since a press on the selected item plays no pick sound.
- **Vehicles.** The equip handler allows one mech, one FRV and one tank, using three kind bits in each stratagem's
  info flags. The mod clears those bits while the list is open and restores them when it closes, when the screen
  closes, when the ruleset changes, or on any error, never overwriting a value the game changed meanwhile.
- **Copy cooldown (Less Restricted).** Every player's stratagems live in the synced loadout lists, each entry with a
  cooldown start, end and base on the scene clock. The mod finds the local player's list by its peer id and, when an
  entry's cooldown starts, gives the other copies of that stratagem a 10 second cooldown, written the way the game
  copies a shared cooldown, and keeps it for those 10 seconds in case a sync resets it. Entries of the Eagle family
  and shared-cooldown stratagems are left to the game.
- **Finding the game's code.** Every address and structure offset comes from 15 code signatures generated in one
  block by `research/signatures.py` from a game.dll dump and checked to match exactly once. Each is tried at the known
  build's address first, else game.dll's executable sections are searched over a few frames; values are read from the
  matched instructions, repeated values must agree, and the list refresh must call the marker found on its own.
  Anything else turns the mod off (the copy cooldown's signatures only turn off the copy cooldown). The search engine
  (`tools/sigscan.lua` in the author's workspace) is shared with the author's other mods.
- **Texts.** `locales/en.lua` is the English source and `locales/<tag>.lua` the bundled translations, resolved by
  CowboyBingus' `src/bingus_text.lua` against the game's Text Language; the build places both ahead of the script.
- **Memory access.** Reads and writes go through `ReadProcessMemory` / `WriteProcessMemory` on the game's own
  process, which fail instead of crashing on a bad address. Per frame it reads a few small spans into fixed buffers.
- **Tests.** `tests/test_release.py` runs the built entry under LuaJIT against a game.dll dump (not included), with
  the loadout screen, stratagem list, synced lists and Mod Options Menu simulated.

Research notes: [NOTES.md](NOTES.md). Release notes: [CHANGELOG.md](CHANGELOG.md).

## Credits

- Built on [Bingus Shared Loader](https://github.com/CowboyBingus/BingusSharedLoader) and
  [Mod Options Menu](https://github.com/CowboyBingus/ModOptionsMenu) by CowboyBingus, whose `bingus_text.lua` provides the
  translations.
- Developed with Claude Opus 5.5 and the [HD2 Lua Mod Skill](https://github.com/MrChengl11/hd2-lua-mod-skill).
