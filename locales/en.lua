-- Flexible Stratagems: English texts, the source of every translation.
-- Translators: see TRANSLATING.md in Mod Options Menu's repository (the same files and tool work for this mod).
-- These show in Mod Options Menu (escape menu > MODS), which upper-cases the mod name and the choices.
return {
    mod = 'flexible_stratagems',
    title = 'Flexible Stratagems',
    language = 'en',
    strings = {
        -- The mod's name: its category button in Mod Options Menu.
        ['option.mod'] = 'Flexible Stratagems',
        -- The ruleset choice: its name, then its two choices besides OFF (OFF is the game's own word).
        ['option.ruleset.label'] = 'Ruleset',
        ['option.ruleset.less'] = 'Less Restricted',
        ['option.ruleset.unleashed'] = 'Unleashed',
        -- Shown beside the choice.
        ['option.ruleset.description'] = 'Off: the game\'s own rules. Less Restricted: up to two of each stratagem, vehicles included; using one puts its copy on a 10 second cooldown (Eagles already share theirs). Unleashed: any stratagem any number of times, no extra cooldowns.',
    },
    -- Mod Options Menu's limits, in characters.
    limits = {['option.mod'] = 40, ['option.ruleset.label'] = 64, ['option.ruleset.less'] = 48,
              ['option.ruleset.unleashed'] = 48, ['option.ruleset.description'] = 400},
}
