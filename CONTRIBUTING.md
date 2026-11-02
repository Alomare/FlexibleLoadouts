# Contributing to Flexible Loadouts

Thanks for your interest in Flexible Loadouts. This guide is for anyone who wants to help: players reporting a bug, translators, and Lua or reverse-engineering developers. You don't need to know how the game works inside to report a bug or translate a text.

## Contents

- [How the mod is built](#how-the-mod-is-built)
- [Reporting a bug](#reporting-a-bug)
- [Translating](#translating)
- [Changing the code](#changing-the-code)
- [Rules the code follows](#rules-the-code-follows)
- [Notes for this mod](#notes-for-this-mod)
- [Sharing a research finding](#sharing-a-research-finding)
- [License of contributions](#license-of-contributions)

## How the mod is built

Flexible Loadouts is a Lua mod for Helldivers 2 that runs under [Bingus Shared Loader](https://github.com/CowboyBingus/BingusSharedLoader). It also uses [Mod Bindings Menu](https://github.com/CowboyBingus/ModBindingsMenu) (optional, for the Action key).

- `flexible_loadouts.lua` is the whole mod: one plain Lua script, run by the game's LuaJIT.
- The game's logic is C++ in `game.dll`, not Lua. The mod finds the game functions, globals and structure offsets it needs with **code signatures**: byte patterns that must match exactly once in `game.dll`. The addresses in comments and in [RESEARCH.md](RESEARCH.md) are for game build 25480438. When a game update breaks a signature, the feature that needs it turns itself off; it never guesses.
- [README.md](README.md) explains what the mod does; [RESEARCH.md](RESEARCH.md) explains how it works in the game's code. Read both before changing code.

**What you can and can't do locally.** The release ZIP is built with the maintainer's own packaging tools. They assemble the texts and the script into the archive Bingus Shared Loader reads. The offline tests run the script against a copy of the game's code that can't be shared. So you can't build a ZIP or run the tests from this repository alone, and you don't need to: send your change as a pull request, and the maintainer runs the tests and builds a test version for you to try in the game (see [Pull requests](#pull-requests)).

## Reporting a bug

Open an [issue](https://github.com/Alomare/FlexibleLoadouts/issues) with:

1. **What happened,** what you expected, and the steps to make it happen again.
2. **The logs,** from `%LOCALAPPDATA%\CowboyBingus\Helldivers2\Logs\` (paste the text or attach the files):
   - `FlexibleLoadouts_STATUS.log`: its first line is the mod's verdict (running, or which part turned off and why).
   - `FlexibleLoadouts.log`: what the mod did.
   - `BingusSharedLoader.log`: the loader's view, including errors from other mods.
3. **Whether the game updated** shortly before. An update can move the code the mod looks for; the STATUS log then says which signature failed.
4. **Your other mods** and their order in your mod manager.
5. **Solo or in a squad,** and if in a squad, whether you were the host.

Crash dumps can contain personal paths from your PC: don't post them publicly. Mention the crash and the time it happened; the maintainer will ask if a dump is needed.

## Translating

Translations are the easiest way to contribute, and they need no programming.

- `locales/en.lua` is the English source of every text. `locales/<tag>.lua` holds one language (for example `pt-BR.lua`, `zh-Hans.lua`). The game's Text Language setting picks the file.
- To fix a translation, edit its file. To add a language, copy `en.lua` to the new tag's name, set `language`, and translate the values. Keep every key (`['option.mod']`) and every placeholder in braces (`{name}`) exactly as they are.
- Some texts have a length limit, listed under `limits` in `en.lua`, because the game's menus cut longer ones.
- The files follow CowboyBingus' translation format. [TRANSLATING.md](https://github.com/CowboyBingus/ModOptionsMenu/blob/main/TRANSLATING.md) explains it, and its `scripts/translations.py check <this repo>/locales <tag>` checks a file (missing keys, placeholders, limits).
- Send the file as a pull request, or attach it to an issue if you don't use git. Say if you'd like to be credited, and under which name.

## Changing the code

For anything bigger than a small fix, **open an issue first** and describe what you want to change. Some ideas were already tried and dropped for reasons that aren't obvious from the code, and an issue saves you that time.

### The files

| Path | What it is |
| --- | --- |
| `flexible_loadouts.lua` | The mod. |
| `locales/` | The texts (see [Translating](#translating)). Every text a player sees goes here, never directly into the script. |
| `src/bingus_text.lua` | CowboyBingus' translation module, an exact copy. Don't edit it. |
| `research/signatures.py` | The list of code signatures. It generates two blocks in the script (below). |
| `tests/test_release.py` | The offline tests: they run the script under LuaJIT with the game's code mapped as fake memory; the Hellpod loadout screen, the stratagem list and the synced loadout are simulated. |
| `mod.json` | The manifest. Never change `guid`. |
| `CHANGELOG.md`, `releases/` | Release notes and release ZIPs, written by the maintainer at release time. |

**Generated blocks: don't edit them by hand.** The script contains blocks that tools write:

- `-- BEGIN SIGNATURES` ... `-- END SIGNATURES` and `-- BEGIN SIGNATURE ENGINE` ... `-- END SIGNATURE ENGINE`: written by `research/signatures.py` against the game's code.

If your change needs a game function or offset the mod doesn't find yet, write in the pull request what you need and how you found it (the function, its address on build 25480438, what it does). The maintainer adds the signature.

### Pull requests

1. Fork the repository and make your change on a branch.
2. Keep to one topic per pull request.
3. In the description, write:
   - what changes for players;
   - how you tested it, if you could;
   - for game findings: the game build and how you found them.
4. Leave the version, `CHANGELOG.md` and `releases/` alone, and don't commit built ZIPs. The maintainer does those at release time.
5. If you have LuaJIT, `luajit -b flexible_loadouts.lua out.bc` catches syntax errors before you push.

What happens next: the maintainer reviews the change and runs the offline tests. For anything you can see in the game, they build a test version named like `Flexible-Loadouts-<n>-recon-<k>.zip` and attach a short test checklist. Tests that need a squad or a specific situation may be asked of you or of other players.

### Style

Match the code around your change:

- 4-space indentation and lines up to 120 characters;
- `local` functions and tables, no new globals;
- comments that say what the game does and why, not what the next line does.

No new dependencies: the mod is one script plus what [How the mod is built](#how-the-mod-is-built) lists.

## Rules the code follows

These come from crashes, anti-cheat and other mods sharing the same game. A pull request that breaks one won't be merged, so ask in an issue if one is in your way.

1. **Never change the game's code.** No patched instructions, hooks, executable memory or swapped function pointers. The anti-cheat (GameGuard) detects code changes, and `game.dll` is packed so its code can't be read from disk anyway. The mod reads memory, writes game data, and calls the game's own functions.
2. **Every address comes from a signature** that matches exactly once, and each feature turns itself off when a check fails. Hard-coded addresses only stay in comments.
3. **Engine asserts crash the game, and `pcall` can't catch them.** A unit kept from an earlier frame may have been destroyed (a world unloading, a death): check `Unit.alive` before every call on it, and drop units and worlds when the world changes. Before calling an engine function you haven't used before, log a line first, so a crash log names it.
4. **All mods share one LuaJIT FFI namespace.** A function name keeps the first declaration any mod made. Declare Windows functions under this mod's prefix, bound to the real export: `int flo_ReadProcessMemory(...) __asm__("ReadProcessMemory");`. RESEARCH.md of [One Click Armor Set](https://github.com/Alomare/OneClickArmorSet/blob/main/RESEARCH.md) has the full story.
5. **Don't touch other players' game.** No feature may give an advantage or change gameplay for the rest of a public squad. That isn't fair to them, and Nexus Mods won't host such mods.
6. **Logs are capped.** The mod logs what it found and why a part turned off, with a limit on how many lines each part writes, so a log never grows without end.

## Notes for this mod

- **Version 8 is in development** on `main`: the mod was renamed from Flexible Stratagems, and new buttons are being tested. Some README text still describes version 7.
- **Duplicate stratagems won't return.** Other mods already offer them, and a public-lobby advantage is out of scope. Please don't open pull requests for them.
- **Keep the key's id `alomare.flexible_stratagems.clear`** even though the mod was renamed: players' saved key bindings use it. Never change `guid` in `mod.json` either.
- **The loadout is synced to the squad.** Anything that changes it has to work for the host and for a client. Test both, or say which one you tested. RESEARCH.md, "The Hellpod loadout screen", explains the synced loadout.
- **Native UI only:** the buttons are the game's own widgets. A drawn overlay is fine as a test aid in a draft, never in a release.

## Sharing a research finding

Findings about the game are welcome even without code: a structure, a function, why something crashes. Open an issue or a pull request against [RESEARCH.md](RESEARCH.md), and include:

- the game build (Steam's build id, or the date of the game update);
- the address or signature;
- whether you saw it in the running game or only in a disassembler.

Never paste the game's decompiled code or files from its archives: describe what they do. The same goes for other mods without a compatible license. Their facts can be credited, but their code can't be copied.

## License of contributions

This mod is licensed under the [MIT License](LICENSE). By contributing, you agree that your contribution is licensed the same way. Contributors are credited in the release notes, and in the README for larger contributions.
