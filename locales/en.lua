-- Flexible Stratagems: English texts, the source of every translation.
-- Translators: see TRANSLATING.md in Mod Options Menu's repository (the same files and tool work for this mod).
-- These show in Mod Bindings Menu (Options > Controls > MODS), which upper-cases them.
return {
    mod = 'flexible_stratagems',
    title = 'Flexible Stratagems',
    language = 'en',
    strings = {
        -- The mod's name: its section in Mod Bindings Menu.
        ['option.mod'] = 'Flexible Stratagems',
        -- A Mod Bindings Menu key (Options > Controls > MODS): empties the four stratagem slots of the Hellpod loadout.
        ['binding.clear'] = 'Clear Stratagems',
    },
    -- Mod Bindings Menu's limits, in characters.
    limits = {['option.mod'] = 40, ['binding.clear'] = 64},
}
