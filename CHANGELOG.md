# Changelog

Releases are named "Flexible Stratagems V&lt;n&gt;" (tag `v<n>`); each section below is the release's notes. Internal
test builds are named after the release they lead to: `Flexible-Stratagems-3-recon-1` (new features) or
`Flexible-Stratagems-2-fix-1` (revisions), and are never published. Versions 1 and 2 were released as Stratagems
Unleashed.

## V3 (2026-10-04)

- **Renamed** to Flexible Stratagems. Mod managers update it in place (same identity); its logs are now
  `FlexibleStratagems.log` and `FlexibleStratagems_STATUS.log`.
- **Rulesets** (Mod Options Menu, escape menu > MODS > Flexible Stratagems):
  - Off: the game's own rules.
  - Less Restricted (default): up to two of each stratagem, vehicles included. When one of two copies is used, the
    other goes on a 10 second cooldown, unless it already has a longer one. Eagles already share their rearm and are
    left alone, as are stratagems whose cooldown the game already shares.
  - Unleashed: any stratagem any number of times, no extra cooldowns (version 2's behavior).
  Without Mod Options Menu the ruleset is Less Restricted.
- **Translations:** the option follows the game's Text Language (with Mod Options Menu v1.1 or later). Brazilian
  Portuguese is included, and translation packs made with CowboyBingus' translation tool work for this mod too.
- **Game updates:** the code signature block and the search that uses it are now shared with the author's other mods;
  the copy cooldown has its own signatures, so if a game update moves only that code, just the copy cooldown is off.

## V2 (2026-09-29)

- Surviving game updates: every address and structure offset is read from the game's own code, found by 11 code
  signatures at this build's addresses first, else by a search of game.dll. Anything not found, found twice or
  inconsistent turns the mod off and the loadout works as normal.

## V1

- First release (as Stratagems Unleashed): the Hellpod loadout takes the same stratagem more than once, vehicles
  included; the loadout goes out through the game's own sync, so teammates need nothing.
