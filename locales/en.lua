-- Flexible Stratagems: English texts, the source of every translation.
-- Translators: see TRANSLATING.md in Mod Options Menu's repository (the same files and tool work for this mod).
-- These show in Mod Options Menu (escape menu > MODS), which upper-cases the mod name, and in Mod Bindings Menu
-- (Options > Controls > MODS), which upper-cases them.
return {
    mod = 'flexible_stratagems',
    title = 'Flexible Stratagems',
    language = 'en',
    strings = {
        -- The mod's name: its category button in Mod Options Menu and its section in Mod Bindings Menu.
        ['option.mod'] = 'Flexible Stratagems',
        -- A slider (2 to 4): how many copies of one stratagem the loadout may hold.
        ['option.copies.label'] = 'Copies per Stratagem',
        -- Shown beside the slider.
        ['option.copies.description'] = 'How many times the same stratagem can be in your Hellpod loadout, vehicles included. At 4, there is no limit.',
        -- A Mod Bindings Menu key (Options > Controls > MODS): empties the four stratagem slots of the Hellpod loadout.
        ['binding.clear'] = 'Clear Stratagems',
    },
    -- Mod Options Menu's and Mod Bindings Menu's limits, in characters.
    limits = {['option.mod'] = 40, ['option.copies.label'] = 64, ['option.copies.description'] = 400,
              ['binding.clear'] = 64},
}
