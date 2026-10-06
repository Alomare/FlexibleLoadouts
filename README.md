<img width="1920" height="1080" alt="thumbnail3" src="https://github.com/user-attachments/assets/ded41e14-9b4e-4086-80d2-e1c84400dc27" />

# Flexible Stratagems

A Helldivers 2 Lua mod for [Bingus Shared Loader](https://github.com/CowboyBingus/BingusSharedLoader) that lets the Hellpod loadout take more than one vehicle of a kind and lets you ready up with fewer than four stratagems. Formerly Stratagems Unleashed.

## Features

- Bring more than one vehicle of a kind in the Hellpod loadout, such as two different mechs: the game's normal pick, sent to your team and saved like any loadout.
- Ready up with fewer than four stratagems. The empty slots flash once, as in the base game, then you're ready.
- Replacing a stratagem in a full loadout keeps the list open on the next slot, where you scrolled, as when filling an empty loadout.
- A **Clear Stratagems** key in [Mod Bindings Menu](https://github.com/CowboyBingus/ModBindingsMenu) (Options > Controls > MODS) empties all four stratagem slots. It starts unbound.
- Only your loadout changes, and it goes out through the game's own sync: teammates don't need the mod.
- The texts follow the game's Text Language.

## Installation

1. Install [Bingus Shared Loader](https://www.nexusmods.com/helldivers2/mods/16292) (v17 or newer).
2. Optional: [Mod Bindings Menu](https://www.nexusmods.com/helldivers2/mods/16478) for the Clear Stratagems key.
3. Install the ZIP from [Releases](https://github.com/Alomare/FlexibleStratagems/releases) with [HD2 Arsenal](https://www.nexusmods.com/helldivers2/mods/4664) (or HD2 Mod Manager) and deploy. Keep Bingus Shared Loader last in the mod order, so it loads first.

The verdict is the first line of `%LOCALAPPDATA%\CowboyBingus\Helldivers2\Logs\FlexibleStratagems_STATUS.log`.

## Technical Details

- **Vehicles.** The equip handler allows one mech, one FRV and one tank, using three kind bits in each stratagem's info flags. The mod clears those bits while the list is open and restores them when it closes, when the screen closes, or on any error, never overwriting a value the game changed meanwhile.
- **Ready with empty slots.** The ready handler refuses while fewer slots are filled than min(owned, 4), flashing the empty ones. The game's UI update runs before the mod's in a frame, so the mod watches the local panel's flash bytes and, when a flash starts, runs the handler's own toggle: the ready timer and sound, or the cancel.
- **List kept open.** After a replacement in a full loadout (slots 1 to 3) the equip handler closes the list. The mod then focuses the next slot and calls the game's list opener, as the handler does while slots are empty. The opener rebuilds the list on the slot's current stratagem, so the mod focuses the stratagem just picked and writes the list's scroll back.
- **Clear Stratagems.** The key sets each filled slot widget to empty through the game's widget setter, then writes the loadout from the slots and saves it the way a pick does. It closes the list first if it is open, and does nothing while you are ready.
- **Finding the game's code.** Every address and structure offset comes from 22 code signatures generated in one block by `research/signatures.py` from a game.dll dump and checked to match exactly once. Each is tried at the known build's address first, else game.dll's executable sections are searched over a few frames; values are read from the matched instructions, repeated values must agree, and calls must reach the functions found on their own. Anything else turns the mod off; the signatures of the ready, list and clear features only turn off that feature. The search engine (`tools/sigscan.lua` in the author's workspace) is shared with the author's other mods.
- **Texts.** `locales/en.lua` is the English source and `locales/<tag>.lua` the bundled translations, resolved by CowboyBingus' `src/bingus_text.lua` against the game's Text Language; the build places both ahead of the script.
- **Memory access.** Reads and writes go through `ReadProcessMemory` / `WriteProcessMemory` on the game's own process, which fail instead of crashing on a bad address. Per frame it reads a few small spans into fixed buffers.
- **Tests.** `tests/test_release.py` runs the built entry under LuaJIT against a game.dll dump (not included), with the loadout screen, stratagem list, ready panel and Mod Bindings Menu simulated.

Research notes: [NOTES.md](NOTES.md). Release notes: [CHANGELOG.md](CHANGELOG.md).

## Credits

- Built on [Bingus Shared Loader](https://github.com/CowboyBingus/BingusSharedLoader) and [Mod Bindings Menu](https://github.com/CowboyBingus/ModBindingsMenu) by CowboyBingus, whose `bingus_text.lua` provides the translations.
- Developed with Claude Opus 5.5 and the [HD2 Lua Mod Skill](https://github.com/MrChengl11/hd2-lua-mod-skill).
