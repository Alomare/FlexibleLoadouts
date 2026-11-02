-- Flexible Loadouts: English texts, the source of every translation.
-- Translators: see TRANSLATING.md in Mod Options Menu's repository (the same files and tool work for this mod).
-- These show in Mod Bindings Menu (Options > Controls > MODS), which upper-cases them, and on the Hellpod loadout.
return {
    mod = 'flexible_loadouts',
    title = 'Flexible Loadouts',
    language = 'en',
    strings = {
        -- The mod's name: its section in Mod Bindings Menu.
        ['option.mod'] = 'Flexible Loadouts',
        -- A Mod Bindings Menu key (Options > Controls > MODS) for the Hellpod loadout. One key, several jobs: it
        -- empties the hovered or selected stratagem slot, flips the REMOVE box of the hovered or selected weapon or
        -- grenade slot, pins or unpins the hovered or selected stratagem in the stratagem list, and on the booster
        -- slot fills the four stratagem slots at random. Translate as a short, general word for "action".
        ['binding.action'] = 'Action',
        -- A small toggle button on the primary weapon, secondary weapon and grenade slots of the Hellpod loadout,
        -- with a check box beside it: checked, the Helldiver goes on the mission without that weapon or grenades.
        -- Keep it short: the button is small. The game shows it in capitals.
        ['button.remove'] = 'Remove',
    },
    -- Mod Bindings Menu's limits and the button's room, in characters.
    limits = {['option.mod'] = 40, ['binding.action'] = 64, ['button.remove'] = 12},
}
