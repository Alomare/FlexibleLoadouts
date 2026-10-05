"""Flexible Stratagems' code signatures (NOTES.md, "Finding the game's code"): checked against the game.dll dump
and written into flexible_stratagems.lua between the SIGNATURES markers, with the shared signature engine
(tools/sigscan.lua) between the SIGNATURE ENGINE markers.

Usage (from the workspace root): python -B mods/FlexibleStratagems/research/signatures.py [--check]
  --check   only verify: every signature matches once and the script's blocks are current (exit 1 otherwise)
"""
import sys
from pathlib import Path

MOD = Path(__file__).resolve().parents[1]
ROOT = MOD.parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import sigspec  # noqa: E402

SCRIPT = MOD / 'flexible_stratagems.lua'

SPECS = [
    # A loadout screen query: mov rax,[screen stack]; mov rcx,[rax+slot]; cmp dword [rcx+local index],-1; setne al.
    {'name': 'screen', 'start': 0x1082ef0, 'end': 0x1082f09,
     'fields': {'stack': (0x347ce38, 'rip'), 'slot': (0xb0, 'u32'), 'local_index': (0x27d0, 'u32')}},
    # The equip handler: the stratagem grid, then the menu category.
    {'name': 'category', 'start': 0x146e0bc, 'end': 0x146e0ce,
     'fields': {'category': (0x2818, 'u32')}, 'wild': (0xd2850,)},
    # The equip handler refreshing the stratagem list: list(screen + list), block(screen + base + index * stride).
    {'name': 'refresh_call', 'start': 0x146e677, 'end': 0x146e6a3,
     'fields': {'local_index': (0x27d0, 'u32'), 'list': (0xd2f20, 'u32'), 'block_stride': (0x9f0, 'u32'),
                'block_base': (0x10, 'u8'), 'refresh': (0x18d1890, 'call')}, 'wild': (0xd2850,)},
    # The list refresh: every item selectable, then per loadout entry (48 bytes) its stratagem info (+4 item id).
    {'name': 'refresh_a', 'start': 0x18d194f, 'end': 0x18d19c5,
     'fields': {'list_count': (0x92984, 'u32'), 'selectable': (0x92dc2, 'u32'), 'block_count': (0x788, 'u32'),
                'strat_table': (0x37cb600, 'rip'), 'block_entries': (0x188, 'u32')},
     'wild': (0x37cb470,)},
    # ... the item's offer among the offers table's stratagem range (24-byte entries: @4 offer, @8 item), marked.
    {'name': 'refresh_b', 'start': 0x18d19c5, 'end': 0x18d1a29,
     'fields': {'offers': (0x347cef8, 'rip'), 'first': (0xd1d0c, 'u32'), 'last': (0xd1d10, 'u32'),
                'indices': (0xd1d48, 'u32'), 'entries': (0xb9ce4, 'u32'), 'mark': (0x18d1440, 'call')}},
    # The equip handler checking the offers table count.
    {'name': 'offers_count', 'start': 0x146e1cf, 'end': 0x146e1ef,
     'fields': {'offers': (0x347cef8, 'rip'), 'offers_count': (0x1ce0, 'u32'), 'entries': (0xb9ce4, 'u32')}},
    # The marker (list, offer, selectable): looks the offer up among the list's offer ids.
    {'name': 'marker', 'start': 0x18d1440, 'end': 0x18d1488,
     'fields': {'ids': (0x92990, 'u32')}},
    # Select (list, offer): stores the selected offer.
    {'name': 'select', 'start': 0x18d10d0, 'end': 0x18d10fb,
     'fields': {'selected': (0x9298c, 'u32')}},
    # The equip handler's one-per-kind rule: the stratagem table's size, and the three kind bits of info +0x104.
    {'name': 'kind_frv', 'start': 0x146e2e0, 'end': 0x146e317,
     'fields': {'types': (0x96, 'u32'), 'flags': (0x104, 'u32')}},
    {'name': 'kind_mech', 'start': 0x146e404, 'end': 0x146e41f,
     'fields': {'flags': (0x104, 'u32')}},
    {'name': 'kind_tank', 'start': 0x146e4f5, 'end': 0x146e50b,
     'fields': {'flags': (0x104, 'u32')}},

    # Ready with fewer than 4 stratagems (optional: without these that feature is off). The screen calls the local
    # panel's (screen + 0x53a78) ready handler while the stratagem list is closed (+0x273990 == 0) ...
    {'name': 'ready_call', 'start': 0x146d9fb, 'end': 0x146da17, 'optional': True,
     'fields': {'list_open': (0x273990, 'u32'), 'panels': (0x53a78, 'u32'), 'ready_handler': (0x189c250, 'call')}},
    # ... which counts the four slot widgets (flags at panel + 0xfcc0, 0x12a8 apart, type at +4) and refuses while
    # fewer are filled than min(owned, 4 - disabled): it flashes each empty slot (byte +0x18 set to 1) and plays an
    # error sound through the UI sound function ...
    {'name': 'ready_slots', 'start': 0x189c3b8, 'end': 0x189c497, 'optional': True,
     'fields': {'slot_flags': (0xfcc0, 'u32'), 'flash': (0x18, 'u8'), 'slot_stride': (0x12a8, 'u32'),
                'ui_sound': (0x1327f50, 'call')}},
    # ... else toggles: for the local panel (+0x1ee0c), an idle timer (+0x1ee14 == -1.0) starts at 1.75 s with the
    # ready sound (the last one when every other player (count +0x84; entity [+0xe8 + i * 8] + 8, the panel's at
    # +0x1edf8) is ready: bit 3 or 11 of players + 0x3ac + i * 0x20); the panel update then sets bit 3 of the local
    # player's flags. Otherwise the timer goes back to -1.0 and that bit is cleared.
    {'name': 'ready_toggle', 'start': 0x189c4d0, 'end': 0x189c5fa, 'optional': True,
     'fields': {'player_count': (0x84, 'u32'), 'panel_entity': (0x1edf8, 'u32'), 'panel_local': (0x1ee0c, 'u32'), 'ready_timer': (0x1ee14, 'u32'), 'players': (0x3326468, 'rip'),
                'player_active': (0x88, 'u32'), 'player_entries': (0xe8, 'u32'), 'player_flags': (0x3ac, 'u32'),
                'ui_sound': (0x1327f50, 'call'), 'timer_idle': (0xbf800000, 'u32'),
                'ready_time': (0x3fe00000, 'u32'), 'sound_ready_last': (0x7947920, 'u32'),
                'sound_ready': (0x4d777731, 'u32')}},
    # The toggle's two branches tell every peer (the ready pose): cancelling sends event 0x5d1d1963 for the panel's unit
    # (+0x1edfc), readying 0x97e150a4, through the emote sender (unused, unit, event, 0.0, 0.0) ...
    {'name': 'ready_emote', 'start': 0x189c552, 'end': 0x189c5e0, 'optional': True,
     'fields': {'panel_unit': (0x1edfc, 'u32'), 'emote_cancel': (0x5d1d1963, 'u32'), 'emote_ready': (0x97e150a4, 'u32'),
                'emote': (0xbf2e20, 'call'), 'ready_timer': (0x1ee14, 'u32'), 'players': (0x3326468, 'rip'),
                'ui_sound': (0x1327f50, 'call')}},
    # ... which sends RPC 0xf24760a9 (unit and event as uints, the two floats) to all peers (-1).
    {'name': 'emote_send', 'start': 0xbf2e20, 'end': 0xbf2ebf, 'optional': True,
     'fields': {'emote_rpc': (0xf24760a9, 'u32'), 'rpc_send': (0xbde430, 'call')}},
    # The handler's start: only for the local panel (entity +0x1edf8, local flag +0x1ee0c), and only when its READY
    # prompt (+0x28b0) fires, asked of the prompt's press check (prompt, input) ...
    {'name': 'ready_entry', 'start': 0x189c25a, 'end': 0x189c28b, 'optional': True,
     'fields': {'panel_entity': (0x1edf8, 'u32'), 'panel_local': (0x1ee0c, 'u32'), 'ready_prompt': (0x28b0, 'u32'),
                'press_call': (0x1891850, 'call')}},
    # ... which only reads: the prompt's action pressed this frame, or confirm while hovered / focused, from the UI
    # input object (the global the UI frame passes down to the loadout screen and so to the handler).
    {'name': 'ready_press', 'start': 0x1891850, 'end': 0x18918a3, 'optional': True,
     'fields': {'input': (0x347cf18, 'rip')}},

    # Keep the list open after a replacement (optional). After a pick the equip handler looks for the first enabled,
    # empty slot (types at screen + 0x6373c; not in grid mode 1, +0x6f290); with one it focuses it in the panel's grid (+0x595f0) and edits it
    # (+0x281c), else it plays a sound and closes the list.
    # The pick itself ends with the slots written to the loadout block (0x189d120(panel, -1)); after the slot search,
    # the list refresh, the grid refresh and the save of the block (screen + 0x10 + index * 0x9f0).
    {'name': 'equip_tail', 'start': 0x146e5f6, 'end': 0x146e6da, 'optional': True,
     'fields': {'panels': (0x53a78, 'u32'), 'slots_changed': (0x189d120, 'call'), 'refresh': (0x18d1890, 'call'),
                'list_grid': (0xd2850, 'u32'), 'grid_refresh': (0x18d7210, 'call'), 'block_stride': (0x9f0, 'u32'),
                'block_base': (0x10, 'u8'), 'save': (0x1751350, 'call'), 'grid_mode': (0x6f290, 'u32'), 'slot_types': (0x6373c, 'u32'), 'slot_stride': (0x12a8, 'u32'), 'ui_sound': (0x1327f50, 'call'),
                'close_list': (0x146f3b0, 'call'), 'local_index': (0x27d0, 'u32'), 'list': (0xd2f20, 'u32'),
                'grid': (0x595f0, 'u32'), 'focus_call': (0x1895770, 'call'), 'edit_slot': (0x281c, 'u32')}},
    # The list opener (the game's own, for the focused slot): its start, which sets list_open.
    {'name': 'open_list', 'start': 0x146e9d0, 'end': 0x146ea64, 'optional': True,
     'fields': {'panels': (0x53a78, 'u32'), 'list_open': (0x273990, 'u32')}},
    # The slot setter (panel, slot, item): the slot widget (panel + 0x5b78 + 0x8ec0 + slot * 0x12a8) gets the item's
    # type through the widget setter (type 0: empty). The grid offset (0x5b78) stays literal: a twin setter for another
    # grid (+0x220) differs only there.
    {'name': 'set_slot', 'start': 0x189d050, 'end': 0x189d09a, 'optional': True,
     'fields': {'slot_stride': (0x12a8, 'u32'), 'widget_base': (0x8ec0, 'u32'),
                'set_widget': (0x1893600, 'call')}},
    # The list's update: its scroll (+0x92960, clamped to [0, +0x8c0]), then the layout of the rows it shows.
    {'name': 'list_update', 'start': 0x18cf84f, 'end': 0x18cf8ff, 'optional': True,
     'fields': {'scroll': (0x92960, 'u32'), 'scroll_max': (0x8c0, 'u32'), 'layout': (0x18d2b60, 'call')}},
    # The list's focus setter (list, offer): the cell holding the offer among the list's offer ids.
    {'name': 'list_focus', 'start': 0x18d1280, 'end': 0x18d12da, 'optional': True,
     'fields': {'ids': (0x92990, 'u32')}},
    # The grid's focus setter (focused slot at grid + 0xd96c).
    {'name': 'focus', 'start': 0x1895770, 'end': 0x1895787, 'optional': True,
     'fields': {'grid_focus': (0xd96c, 'u32')}},
]


def main():
    rows = sigspec.build(SPECS)
    sigspec.report(rows)
    if '--check' in sys.argv:
        problems = sigspec.check(SCRIPT, rows)
        for p in problems:
            print('STALE:', p)
        sys.exit(1 if problems else 0)
    sigspec.write(SCRIPT, rows)
    print('written to', SCRIPT.name)


if __name__ == '__main__':
    main()
