<img width="1920" height="1080" alt="thumbnail" src="https://github.com/user-attachments/assets/fcefa852-d75b-4de4-9d37-4d6b428b21d6" />

# Flexible Loadouts

A Helldivers 2 Lua mod for [Bingus Shared Loader](https://github.com/CowboyBingus/BingusSharedLoader) that makes the Hellpod loadout easier to work with: ready up with empty stratagem slots, empty a slot with one click, pin your favourite stratagems, roll a random lineup, and go on missions without your primary, secondary or grenades. Formerly Flexible Stratagems, first released as Stratagems Unleashed.

## Features

- **Ready with empty slots.** Ready up with fewer than four stratagems. The empty slots flash once, as in the base game, then you're ready, with the ready pose your squad sees.
- **The list stays open.** Replacing a stratagem in a full loadout keeps the list open on the next slot, where you scrolled, as when filling an empty loadout.
- **A red X on each filled stratagem slot** empties that slot. It fades in and out like the game's own buttons. A slot emptied in the middle stays empty.
- **REMOVE buttons** at the top of your primary, secondary and grenade slots: checked, your Helldiver goes on missions without that weapon or the grenades, while your loadout keeps them. The choice stays until you change it.
- **Pinned stratagems.** A pin shows on the stratagem under your cursor (or selected with a controller) in the stratagem list. Click it to pin: pinned stratagems come first in their group (offensive, supply, defensive). Pins stay between game sessions.
- **Randomize Lineup.** A small button between your 4th stratagem slot and the booster fills the four slots, one by one, with one of three lineups: red, an expendable or support weapon without a backpack, a backpack, green; red, red, an expendable or a support weapon with its own backpack, green; an Exosuit or FRV, red, green, green. Only stratagems you own, no repeats. The button hides when you own too few stratagems for a real choice.
- **An Action key** in [Mod Bindings Menu](https://github.com/CowboyBingus/ModBindingsMenu) (Options > Controls > MODS), for keyboard and controller. It empties the hovered or selected stratagem slot, flips the REMOVE box of the hovered or selected weapon or grenade slot, pins or unpins the hovered or selected stratagem in the list, and on the booster slot rolls a random lineup. With a controller, the selected slot shows its X or REMOVE button. It starts unbound.
- Only your loadout and your Helldiver change, through the game's own sync and messages: teammates don't need the mod.
- The texts follow the game's Text Language.

## Installation

1. Install [Bingus Shared Loader](https://www.nexusmods.com/helldivers2/mods/16292) (v17 or newer).
2. Optional: [Mod Bindings Menu](https://www.nexusmods.com/helldivers2/mods/16478) for the Action key.
3. Install the ZIP from [Releases](https://github.com/Alomare/FlexibleLoadouts/releases) with [HD2 Arsenal](https://www.nexusmods.com/helldivers2/mods/4664) (or HD2 Mod Manager) and deploy. Keep Bingus Shared Loader last in the mod order, so it loads first.

Coming from Flexible Stratagems: the mod updates in place and your key stays bound.

The verdict is the first line of `%LOCALAPPDATA%\CowboyBingus\Helldivers2\Logs\FlexibleLoadouts_STATUS.log`.

## Technical Details

- **Ready with empty slots.** The ready handler refuses while fewer slots are filled than min(owned, 4), flashing the empty ones. The game's UI update runs before the mod's in a frame, so the mod watches the local panel's flash bytes and, when a flash starts (or, while one still shows, when the game's own press check says Ready fired), runs the handler's own toggle: the ready pose sent to every peer, the ready timer and sound, or the cancel.
- **List kept open.** After a replacement in a full loadout (slots 1 to 3) the equip handler closes the list. The mod then focuses the next slot and calls the game's list opener, as the handler does while slots are empty. The opener rebuilds the list on the slot's current stratagem, so the mod focuses the stratagem just picked and writes the list's scroll back.
- **The buttons are the game's own widgets.** The X, REMOVE, pin and reroll buttons are pictures, fills and a text label of the game's widget kinds, made in the slot's GUI context and attached under the slot, so the game places and draws them like its own UI. They show only when the game would take a click on the slot, fade with the game's fade helper, and take the click by hiding the slot's hover from the game for that frame.
- **Emptying a slot** sets its widget to empty through the game's widget setter, then writes the loadout from the slots and saves it the way a pick does.
- **Pinned stratagems.** The game builds the stratagem list once per opening, sorted and grouped by colour. Right after each build the mod moves the pinned stratagems to the front of their group, inside the list's own arrays, then has the game lay the list out again and put the focus back. The pins are the game's waypoint icon, attached to the list's cells. While a pin is under the cursor, the game's own "can't pick" state on that stratagem keeps the click for the pin. Pins are kept in `FlexibleLoadouts.settings`.
- **Randomize Lineup.** The stratagem classes come from the game's own stratagem data (colour, and for blue stratagems the support weapon, backpack, vehicle and expendable flags), among the stratagems the game counts as owned. Each slot is set through the game's own slot setter, which also tells your teammates, with the game's pick sound of its colour.
- **Weapons left behind.** The loadout can't hold "no weapon", so the mod acts in the mission on your Helldiver only: it switches away with the game's own selection request, empties the slot in the mission inventory, keeps the way back after a throw on a weapon you still carry, sets the grenade count to zero, and sends the game's own inventory and selection messages to the other players. The choices are kept in `FlexibleLoadouts.settings` in the Logs folder.
- **Finding the game's code.** Every address and structure offset comes from code signatures generated in one block by `research/signatures.py` from a game.dll dump and checked to match exactly once. Each is tried at the known build's address first, else game.dll's executable sections are searched over a few frames; values are read from the matched instructions, repeated values must agree, and calls must reach the functions found on their own. Missing core signatures turn the mod off; each feature's own signatures only turn off that feature. The search engine (`tools/sigscan.lua` in the author's workspace) is shared with the author's other mods.
- **Texts.** `locales/en.lua` is the English source and `locales/<tag>.lua` the bundled translations, resolved by CowboyBingus' `src/bingus_text.lua` against the game's Text Language; the build places both ahead of the script.
- **Memory access.** Reads and writes go through `ReadProcessMemory` / `WriteProcessMemory` on the game's own process, which fail instead of crashing on a bad address. Windows functions are declared under the mod's own names, so other mods' declarations can't change them. Per frame it reads a few small spans into fixed buffers.
- **Tests.** `tests/test_release.py` runs the built entry under LuaJIT against a game.dll dump (not included), with the loadout screen, stratagem list (groups, pages and cells), ready panel, widgets, mission inventory and Mod Bindings Menu simulated.

How it works in the game's code: [RESEARCH.md](RESEARCH.md). Contributing: [CONTRIBUTING.md](CONTRIBUTING.md). Release notes: [CHANGELOG.md](CHANGELOG.md).

## Credits

- Built on [Bingus Shared Loader](https://github.com/CowboyBingus/BingusSharedLoader) and [Mod Bindings Menu](https://github.com/CowboyBingus/ModBindingsMenu) by CowboyBingus, whose `bingus_text.lua` provides the translations.
- Uses research from HD2Runtime by SkyeShade, https://github.com/SkyeShade/HD2Runtime: the health manager the mod reads to tell when your Helldiver is dead.
- [Holster](https://github.com/OnlyTanks/HD2-Holster) by OnlyTanks showed that a Helldiver can be made unarmed mid-mission with the game's own inventory switch, and that teammates see it. [HD2-Transmog](https://github.com/tyrypyrking/HD2-Transmog) by tyrypyrking mapped the loadout screen's player cards. Facts from both; no code of theirs is used.
- Developed with Claude Opus 5.5 and the [HD2 Lua Mod Skill](https://github.com/MrChengl11/hd2-lua-mod-skill).

## License

Copyright (c) 2026 Alomare. Licensed under the [MIT License](LICENSE). `src/bingus_text.lua` is CowboyBingus's, under the Zero-Clause BSD license.
