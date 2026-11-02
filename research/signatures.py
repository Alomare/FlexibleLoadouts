"""Flexible Loadouts' code signatures (RESEARCH.md, "Signatures"): checked against the game.dll dump
and written into flexible_loadouts.lua between the SIGNATURES markers, with the shared signature engine
(tools/sigscan.lua) between the SIGNATURE ENGINE markers.

Usage (from the workspace root): python -B mods/FlexibleLoadouts/research/signatures.py [--check]
  --check   only verify: every signature matches once and the script's blocks are current (exit 1 otherwise)
"""
import sys
from pathlib import Path

MOD = Path(__file__).resolve().parents[1]
ROOT = MOD.parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import sigspec  # noqa: E402

SCRIPT = MOD / 'flexible_loadouts.lua'

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
    # The list refresh: every item selectable (count +0x92984), then per loadout entry (48 bytes) its stratagem info
    # (+4 item id).
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
    # The pick itself ends with the slots written to the loadout block (0x189d120(panel, -1)); after the slot search
    # (a slot's type - 1 is at most 0x94: the stratagem table's last type but one), the list refresh, the grid refresh
    # and the save of the block (screen + 0x10 + index * 0x9f0).
    {'name': 'equip_tail', 'start': 0x146e5f6, 'end': 0x146e6da, 'optional': True,
     'fields': {'panels': (0x53a78, 'u32'), 'slots_changed': (0x189d120, 'call'), 'refresh': (0x18d1890, 'call'),
                'list_grid': (0xd2850, 'u32'), 'grid_refresh': (0x18d7210, 'call'), 'block_stride': (0x9f0, 'u32'),
                'block_base': (0x10, 'u8'), 'save': (0x1751350, 'call'), 'grid_mode': (0x6f290, 'u32'), 'slot_types': (0x6373c, 'u32'), 'slot_stride': (0x12a8, 'u32'), 'ui_sound': (0x1327f50, 'call'),
                'close_list': (0x146f3b0, 'call'), 'local_index': (0x27d0, 'u32'), 'list': (0xd2f20, 'u32'),
                'grid': (0x595f0, 'u32'), 'focus_call': (0x1895770, 'call'), 'edit_slot': (0x281c, 'u32'),
                'type_last': (0x94, 'u32')}},
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
    # Field names of the buttons' own (cross-checked by the script against the core's and each other's): a button
    # signature that disagrees turns off the buttons alone.
    # The clear buttons (optional: without these the buttons are off). A red X on each filled stratagem slot of the
    # local panel, made of the game's own widgets (research: RESEARCH.md, "The clear buttons").
    # The slot hover test (0x1893550(slot)): a disabled slot (flags +0x1288 bit 2) is unhovered (bit 0 cleared, then
    # the slot redraw 0x18932F0); a slot with pending widget changes (header bit 2, literal in the pattern) skips the
    # test; else the game's hit test (cursor widget = [UI manager = the screen stack global] + 0x5F0, widget, 0) goes to
    # the slot's set-hover (0x18936D0(slot, on): on a change, the hover sound when turning on, bit 0, the redraw).
    {'name': 'slot_hover', 'start': 0x1893550, 'end': 0x18935d2, 'optional': True,
     'fields': {'hover_stack': (0x347ce38, 'rip'), 'cursor_widget': (0x5f0, 'u32'), 'hit_test': (0x178f970, 'call'),
                'widget_flags': (0x1288, 'u32'), 'slot_redraw': (0x18932f0, 'call'),
                'slot_set_hover': (0x18936d0, 'call')}},
    # widget_mark_dirty (0x144D200(w)): header bit 2 on w and up its parent chain (+0xF0) until one has it. Optional:
    # without it the slot keeps its hover highlight while its X is hovered.
    {'name': 'widget_mark_dirty', 'start': 0x144d200, 'end': 0x144d22d, 'optional': True,
     'fields': {'dirty_parent': (0xf0, 'u32')}},
    # The game's fade helper (0x1450DD0(w, u8 out, float seconds, float alpha, float delay)): from the current opacity
    # (+0x44), cancelling a running fade (the opacity-tween slots +0xB0), then its tail calls opacity_set and the
    # opacity tween (0x1448870: once, smoothstep). Optional: without it the X shows and hides at once.
    {'name': 'widget_fade', 'start': 0x1450dd0, 'end': 0x1450e2f, 'optional': True,
     'fields': {'fade_opacity': (0x44, 'u8'), 'fade_slots': (0xb0, 'u32')}},
    {'name': 'widget_fade_tail', 'start': 0x1450f47, 'end': 0x1450f9c, 'optional': True,
     'fields': {'fade_opacity_set': (0x1448ad0, 'call'), 'fade_tween': (0x1448870, 'call')}},
    # The slot grid's mouse click (in 0x18950B0): with the grid active (+0xD978) and confirm pressed this frame (the
    # literal action 0xA00000000 mapped to an index by 0x585B80; press bytes input + 0x328 + index * 0x20), in mouse
    # mode (input + 0xE1AD4) a hovered slot (+0xD968 < 5) gets the click sound, the focus, and the stratagem list.
    {'name': 'grid_click', 'start': 0x18952fe, 'end': 0x1895374, 'optional': True,
     'fields': {'grid_active': (0xd978, 'u32'), 'action_index': (0x585b80, 'call'), 'press_base': (0x328, 'u32'),
                'hovered': (0xd968, 'u32'), 'click_input': (0x347cf18, 'rip'), 'mouse_mode': (0xe1ad4, 'u32'),
                'click_sound': (0xa31d0645, 'u32'), 'click_ui_sound': (0x1327f50, 'call'),
                'click_focus': (0x1895770, 'call'), 'click_grid_focus': (0xd96c, 'u32')}},
    # The loadout screen's input (0x146D370) before it hands the input to the panels (0x146D9B0): nothing while the
    # launch byte (+0x2808) is set, the input delay (+0x27399C, a float set to 3 s) runs, the bytes +0x27FC / +0x273998
    # / +0x27F9 are set, or the states +0x27398C (0 or 7) / +0xD1F94 (0 or 3) differ; then the panels with the list
    # closed (+0x273990) while the screen's state (+8) is 1.
    {'name': 'screen_gates', 'start': 0x146d443, 'end': 0x146d58c, 'optional': True,
     'fields': {'launching': (0x2808, 'u32'), 'input_delay': (0x27399c, 'u32'), 'busy_a': (0x27fc, 'u32'),
                'busy_b': (0x273998, 'u32'), 'state_a': (0x27398c, 'u32'), 'state_b': (0xd1f94, 'u32'),
                'busy_c': (0x27f9, 'u32'), 'gates_list_open': (0x273990, 'u32'), 'screen_state': (0x8, 'u8'),
                'gates_ui_sound': (0x1327f50, 'call'), 'screen_input': (0x146d9b0, 'call')}},
    # ... which (in 0x146D9B0) gives the click to the active group's panel (+0x2739C8; panels 0x1EE18 apart) only when
    # its byte +0x1EE0E is 0, it is the local panel (+0x1EE0C) and its ready timer (+0x1EE14) is idle; then in grid
    # mode 0 (+0x6F290) to the slot grid (+0x595F0) through 0x18950B0, in mode 1 (the literal `cmp eax, 1`) to the
    # equipment view (+0x66F70: armour, weapons, throwable) through 0x1898400.
    {'name': 'grid_gates', 'start': 0x146da3c, 'end': 0x146db39, 'optional': True,
     'fields': {'active_group': (0x2739c8, 'u32'), 'panel_stride': (0x1ee18, 'u32'), 'panel_busy': (0x72886, 'u32'),
                'panel_local_at': (0x72884, 'u32'), 'timer_at': (0x7288c, 'u32'), 'gates_grid_mode': (0x6f290, 'u32'),
                'gates_grid': (0x595f0, 'u32'), 'grid_input': (0x18950b0, 'call'),
                'gates_view': (0x66f70, 'u32'), 'view_input': (0x1898400, 'call')}},
    # The Leave Out toggles (optional: without these only they are off; they also need the clear buttons' code).
    # Research: RESEARCH.md, "Leave Out toggles". Field names of their own, cross-checked.
    # The equipment view's mouse hover (in its update 0x18980B0): unless the last device is a pad (input + 0xE1AD5),
    # hovered (+0x8310) = -1, then per slot (view + 0x110 + k * 0x1558; flags u16 at slot + 0x1548, here view +
    # 0x1658) the game's hit test; on a change bit 0, the hover sound 0x56FA2864 turning on, and the slot redraw
    # (0x1897300). No header bit-2 skip: the slot is hit-tested every frame.
    {'name': 'view_hover', 'start': 0x18980fd, 'end': 0x189821a, 'optional': True,
     'fields': {'vh_input': (0x347cf18, 'rip'), 'vh_pad_mode': (0xe1ad5, 'u32'), 'vh_pad_hover': (0x1898350, 'call'),
                'vh_flags_at': (0x1658, 'u32'), 'view_hovered': (0x8310, 'u32'), 'vh_stack': (0x347ce38, 'rip'),
                'vh_cursor': (0x5f0, 'u32'), 'vh_hit': (0x178f970, 'call'), 'vh_sound': (0x56fa2864, 'u32'),
                'view_slot_redraw': (0x1897300, 'call'), 'view_slot_stride': (0x1558, 'u32')}},
    # The view's mouse click (the tail of 0x1898400): with the view active (+0x831C), confirm pressed this frame and a
    # hovered slot (+0x8310 != -1, no upper bound) in mouse mode: the click sound, the focus (0x1898910, also sent to
    # every peer) and the list for the focused slot (+0x8314).
    {'name': 'view_click', 'start': 0x1898631, 'end': 0x18986c1, 'optional': True,
     'fields': {'view_active': (0x831c, 'u32'), 'vc_action_index': (0x585b80, 'call'), 'vc_press_base': (0x328, 'u32'),
                'vc_hovered': (0x8310, 'u32'), 'vc_input': (0x347cf18, 'rip'), 'vc_mouse_mode': (0xe1ad4, 'u32'),
                'vc_sound': (0xd91e3ea6, 'u32'), 'vc_ui_sound': (0x1327f50, 'call'), 'vc_focus': (0x1898910, 'call'),
                'view_focus': (0x8314, 'u32')}},
    # The view's record setter (0x18991A0(view, block, active)): each slot gets its item (0x18975D0): the primary at
    # view + 0x4118 (block + 0), the secondary at + 0x5670 (block + 0x60), the throwable at + 0x6BC8 (block + 0xC0).
    {'name': 'view_slots', 'start': 0x18991b4, 'end': 0x189928b, 'optional': True,
     'fields': {'view_block': (0x8308, 'u32'), 'vs_active': (0x831c, 'u32'), 'slot_primary': (0x4118, 'u32'),
                'block_secondary': (0x60, 'u8'), 'slot_secondary': (0x5670, 'u32'),
                'block_throwable': (0xc0, 'u32'), 'slot_throwable': (0x6bc8, 'u32'),
                'vs_set_item': (0x18975d0, 'call'), 'vs_focus': (0x1898910, 'call')}},
    # The view slot's redraw (0x1897300(slot), from its first instruction): opacity 0.5 when disabled (flags u16
    # +0x1548 bit 2), the plate (+0x110) grey or focus yellow (bit 1), the frame (+0xBB0, class 0x17909F0: grey 0.4 /
    # 2 units, white / 3 units when hovered, bit 0; its colour at frame + 0x48).
    {'name': 'view_slot_redraw', 'start': 0x1897300, 'end': 0x18973cf, 'optional': True,
     'fields': {'vr_flags': (0x1548, 'u32'), 'vr_opacity_set': (0x1448ad0, 'call'), 'vr_plate': (0x110, 'u32'),
                'vr_color_set': (0x1448690, 'call'), 'vr_frame': (0xbb0, 'u32')}},
    # The panel's loadout section update (0x18999F0, from its first instruction): nothing while its transition byte
    # (+0x15EC4, set for about 0.1 s after a mode switch: the view still invisible while its hover and click run) is
    # clear... then the mode (+0x15EC0). The section is at screen + gates_grid_mode - sec_mode.
    {'name': 'view_transition', 'start': 0x18999f0, 'end': 0x1899a3c, 'optional': True,
     'fields': {'sec_transition': (0x15ec4, 'u32'), 'sec_mode': (0x15ec0, 'u32')}},
    # The toggles' REMOVE label (research: RESEARCH.md, "Leave Out toggles"), made the way the game
    # makes the slot grid's "MISSION STRATAGEMS" title from scratch (in the grid init 0x1893F30): label_init(w),
    # set_label(w, its text id; literal), anchor / pivot (0, 0.5), position (12, 0), font_set(w, 4, 0, 0, 1.0, 0),
    # font size (22.0), layer 14, opacity, colour (0.694 grey, three literals), attach(grid, w), then the parent's
    # child-flag refresh (0x144C2C0). Its calls name the label functions; the shared widget calls must equal the mod's.
    {'name': 'label_title', 'start': 0x189433d, 'end': 0x189442d, 'optional': True,
     'fields': {'title_offset': (0x5a0, 'u32'), 'call_label_init': (0x143afa0, 'call'),
                'call_set_label': (0x143bf90, 'call'), 'title_anchor_set': (0x144f160, 'call'),
                'title_pivot_set': (0x144f0d0, 'call'), 'title_x': (0x23c757c, 'rip'),
                'title_position_set': (0x14476a0, 'call'), 'title_font': (4, 'u32'),
                'call_font_set': (0x11f79b0, 'call'), 'title_size': (0x23c75f8, 'rip'),
                'call_font_size_set': (0x143c0b0, 'call'), 'title_layer': (0xe, 'u32'),
                'title_layer_set': (0x14491f0, 'call'), 'title_opacity_set': (0x1448ad0, 'call'),
                'title_grey': (0x3f31b1b2, 'u32'), 'title_color_set': (0x1448690, 'call'),
                'title_attach': (0x144c5c0, 'call'), 'call_children_refresh': (0x144c2c0, 'call')}},
    # label_init(w) (0x143AFA0): widget_init(w, 7), then the label's own fields up to a byte at +0x2B4 (the label is
    # 0x2B8 bytes, as the game's arrays of labels step).
    {'name': 'label_init', 'start': 0x143afa0, 'end': 0x143b025, 'optional': True,
     'fields': {'label_type': (7, 'u32'), 'label_text_id': (0x110, 'u32'), 'label_arg_count': (0x268, 'u32'),
                'label_cache': (0x270, 'u32'), 'label_handle': (0x278, 'u32'), 'label_font_size': (0x27c, 'u32'),
                'label_font_material': (0x2a8, 'u32'), 'label_last': (0x2b4, 'u32')}},
    # A game label getting its text from a template and one string argument (0x190A7A2): set_label(w, id; literal),
    # then set_string_arg(w, key, char *) with the COUNT key 0xAB2A7B35 (the #COUNT template's tag; the template id
    # 0xC67C7FAF is a pure tag, so the label shows the string). The label keeps the string's pointer.
    {'name': 'label_text_call', 'start': 0x190a7a2, 'end': 0x190a7c3, 'optional': True,
     'fields': {'text_set_label': (0x143bf90, 'call'), 'text_count_key': (0xab2a7b35, 'u32'),
                'call_set_string_arg': (0x143c950, 'call')}},
    # font_set(w, font, variant, style, scale, force) (0x11F79B0): the font records and their material sets.
    {'name': 'font_set', 'start': 0x11f79b0, 'end': 0x11f79ef, 'optional': True,
     'fields': {'font_records': (0x37c49e0, 'u32'), 'font_materials': (0x37c5470, 'u32')}},
    # widget_measure(w) (0x144E1A0): a label laid out to its text (+0x0C: width, line height, in its parent's units).
    {'name': 'widget_measure', 'start': 0x144e1a0, 'end': 0x144e1bc, 'optional': True},
    # The widget functions, as Helmet Passives Reborn checks them (its NOTES, "Native UI toolbox"). The game building
    # one of its solid fill pictures (0x11F51E0): picture_init, material_set(w, gui_fill, 0) with
    # content/ui/shared/material/gui_fill (e819a58401ff619f, literal in the pattern), size, opacity, colour, layer,
    # attach(parent, w). Its calls name seven widget functions; the prologue signatures below must agree.
    {'name': 'gui_fill_build', 'start': 0x11f5236, 'end': 0x11f52b1, 'optional': True,
     'fields': {'call_picture_init': (0x143eab0, 'call'), 'call_material_set': (0x144f800, 'call'),
                'call_size_set': (0x1447160, 'call'), 'call_opacity_set': (0x1448ad0, 'call'),
                'call_color_set': (0x1448690, 'call'), 'call_layer_set': (0x14491f0, 'call'),
                'call_attach': (0x144c5c0, 'call')}},
    # The widget functions by their first instructions: picture_init(w); material_set(w, u64 material, u8 0); size /
    # position / anchor / pivot (w, u64: x float bits low, y high); color_set(w, const float[3]); opacity_set(w, float);
    # layer_set(w, i16); rotation_set(w, float degrees); attach(parent, child); destroy(w).
    {'name': 'picture_init', 'start': 0x143eab0, 'end': 0x143ead8, 'optional': True},
    {'name': 'widget_material_set', 'start': 0x144f800, 'end': 0x144f82a, 'optional': True},
    {'name': 'widget_size_set', 'start': 0x1447160, 'end': 0x144718d, 'optional': True},
    {'name': 'widget_position_set', 'start': 0x14476a0, 'end': 0x14476cd, 'optional': True},
    {'name': 'widget_anchor_set', 'start': 0x144f160, 'end': 0x144f188, 'optional': True},
    {'name': 'widget_pivot_set', 'start': 0x144f0d0, 'end': 0x144f0f8, 'optional': True},
    {'name': 'widget_color_set', 'start': 0x1448690, 'end': 0x14486bc, 'optional': True},
    {'name': 'widget_opacity_set', 'start': 0x1448ad0, 'end': 0x1448afb, 'optional': True},
    {'name': 'widget_layer_set', 'start': 0x14491f0, 'end': 0x144921a, 'optional': True},
    {'name': 'widget_rotation_set', 'start': 0x1448ef0, 'end': 0x1448f1b, 'optional': True},
    {'name': 'widget_attach', 'start': 0x144c5c0, 'end': 0x144c5ea, 'optional': True},
    {'name': 'widget_destroy', 'start': 0x144dd70, 'end': 0x144dd96, 'optional': True},
    # widget_init (0x1446840) up to where it stores the widget's GUI context: the context stack global, the stack's
    # top (i32) and slots (u8), the context stride, and the widget's context (+0xF8) and parent (+0xF0) fields.
    # context = base + stack[top] * stride (slot 0 when top < 0): a widget is made inside its parent's context.
    {'name': 'widget_init', 'start': 0x1446840, 'end': 0x14469b5, 'optional': True,
     'fields': {'gui_contexts': (0x347ce90, 'rip'), 'context_top': (0x2c5bc, 'u32'), 'context_stack': (0x2c5b8, 'u32'),
                'context_stride': (0x3698, 'u32'), 'widget_context': (0xf8, 'u32'), 'widget_parent': (0xf0, 'u32')}},
    # ui_context_push(base, u8 slot) (0x12EF4B0: stack[top + 1] = slot, top + 1) and ui_context_pop() (0x12EF4D0, right
    # after it: top - 1 on the global). The match is push; pop is 0x20 further (literal padding in between).
    {'name': 'ui_context', 'start': 0x12ef4b0, 'end': 0x12ef4dd, 'optional': True,
     'fields': {'push_contexts': (0x347ce90, 'rip'), 'push_top': (0x2c5bc, 'u32'), 'context_stack_next': (0x2c5b9, 'u32')}},
    # widget_attach's child list: the parent's first child (+0xE0), each child's next sibling (+0xE8), its parent (+0xF0).
    {'name': 'widget_children', 'start': 0x144c5c0, 'end': 0x144c647, 'optional': True,
     'fields': {'first_child': (0xe0, 'u32'), 'next_sibling': (0xe8, 'u32'), 'children_parent': (0xf0, 'u32')}},

    # Weapons left behind (optional: without these the weapon options are off). Research:
    # RESEARCH.md, "Weapons left behind". Field names of their own, cross-checked by the script.
    # The game's "is this the local avatar" check (0xA40070, as Ragdoll On Command uses it): the players global, its
    # local-player word (+0x88) and network id (+0x3A8), the network id -> entity lookup (0xFD9BA0), the no-entity
    # value, the avatar manager and its entity -> index map.
    {'name': 'local_avatar', 'start': 0xa40076, 'end': 0xa40124, 'optional': True,
     'fields': {'la_players': (0x3326468, 'rip'), 'la_active': (0x88, 'u32'), 'la_unit': (0x3a8, 'u32'),
                'la_unit_entity': (0xfd9ba0, 'call'), 'la_no_entity': (0x3483c20, 'rip'),
                'la_avatars': (0x3326d20, 'rip'), 'la_avatar_cap': (0x100, 'u32'), 'la_avatar_mult': (0x108, 'u32'),
                'la_avatar_map': (0xf8, 'u32'), 'la_avatar_empty': (0x104, 'u32')}},
    # The network id -> entity lookup (0xFD9BA0): the entity owner global, the "no unit" id, its map, the entity
    # records (24 bytes each, the id at +8; their base as a qword index).
    {'name': 'unit_lookup', 'start': 0xfd9ba0, 'end': 0xfd9c5b, 'optional': True,
     'fields': {'ul_owner': (0x346bf98, 'rip'), 'ul_no_unit': (0x7fff, 'u32'), 'ul_cap': (0xf22ed0, 'u32'),
                'ul_mult': (0xf22ed8, 'u32'), 'ul_map': (0xf22ec8, 'u32'), 'ul_empty': (0xf22ed4, 'u32'),
                'ul_entity_ids': (0x1e65e4, 'u32')}},
    # The inventory's selection getter (0x9A84A0): the inventory global, its entity -> row map (capacity +0x30; the
    # data +0x28, empty key +0x34 and multiplier +0x38 stay literal: a twin at 0x59A9A0 differs only there), the rows
    # (+0x50, 48 bytes each: the stride is literal) and a row's selection (+0x1C).
    {'name': 'inv_selection', 'start': 0x9a84a0, 'end': 0x9a853e, 'optional': True,
     'fields': {'is_no_entity': (0x3483c20, 'rip'), 'is_inventory': (0x3326738, 'rip'), 'is_cap': (0x30, 'u8'),
                'is_rows': (0x50, 'u8'), 'is_selection': (0x1c, 'u8')}},
    # The grenade refill's tail (0x9ADAB0): the counts (+0x58, 8 bytes per row), the count event 0xD92082F9 posted to
    # the row owner's descriptor (+0x40 array, its network id +0x10) through the entity event function (0xFD97E0).
    {'name': 'throw_count', 'start': 0x9adc79, 'end': 0x9adc9d, 'optional': True,
     'fields': {'tc_counts': (0x58, 'u8'), 'tc_event': (0xd92082f9, 'u32'), 'tc_owners': (0x40, 'u8'),
                'tc_goid': (0x10, 'u8'), 'tc_entity_event': (0xfd97e0, 'call')}},
    # A weapon-selection request of the game's (in 0xA95F30): the avatar's selection controller (avatar manager +
    # 0x53DCD0 + index * 0x1238: entity, requested, previous and last weapon slots) and the request (0xA93E90).
    {'name': 'select_request', 'start': 0xa96209, 'end': 0xa96224, 'optional': True,
     'fields': {'sr_stride': (0x1238, 'u32'), 'sr_ctrl': (0x53dcd0, 'u32'), 'sr_request': (0xa93e90, 'call')}},
    # The way back after a throw (in 0xA97A40): after a stratagem the request for the controller's previous slot
    # (+0x53DCD8); after a grenade another grenade while the count (inventory +0x58) holds one, else the last weapon
    # slot (+0x53DCDC).
    {'name': 'throw_return', 'start': 0xa98006, 'end': 0xa980ce, 'optional': True,
     'fields': {'tr_previous': (0x53dcd8, 'u32'), 'tr_last_weapon': (0x53dcdc, 'u32'), 'tr_ctrl': (0x53dcd0, 'u32'),
                'tr_inventory': (0x3326738, 'rip'), 'tr_request': (0xa93e90, 'call')}},
    # "May switch weapons now" (0xA92BC0(controller)): the avatar manager, the flag words (+0x53E880), the stride.
    {'name': 'can_switch', 'start': 0xa92bc0, 'end': 0xa92ca9, 'optional': True,
     'fields': {'cs_avatars': (0x3326d20, 'rip'), 'cs_flags': (0x53e880, 'u32'), 'cs_stride': (0x1238, 'u32')}},
    # The death test (0x927050(health manager, entity)): life state (record + 0x19C) of 2 or more.
    {'name': 'is_dead', 'start': 0x927050, 'end': 0x9270ff, 'optional': True,
     'fields': {'dead_records': (0x1058, 'u32'), 'dead_stride': (0x1b8, 'u32'), 'dead_life': (0x19c, 'u32')}},
    # The health manager global (HD2Runtime's pin, in its record getter 0x4A4410).
    {'name': 'health', 'start': 0x4a441a, 'end': 0x4a4440, 'optional': True,
     'fields': {'health_global': (0x3326688, 'rip'), 'health_cap': (0x1038, 'u32')}},
    # The game state test in the inventory's avatar removal (0x9AA940): [game] + 0xAC21C == 4 in a mission.
    {'name': 'game_state', 'start': 0x9aa9ec, 'end': 0x9aaa00, 'optional': True,
     'fields': {'gs_game': (0x3326340, 'rip'), 'gs_state': (0xac21c, 'u32'), 'gs_mission': (4, 'u8')}},
    # The wielder (0x785D10): its entity -> instance map and the hands (+0x60 + index * 0x1D0, 0x50 per hand; hand 0
    # holds the weapon in hand).
    {'name': 'wielder', 'start': 0x785d28, 'end': 0x785db6, 'optional': True,
     'fields': {'wd_no_entity': (0x3483c20, 'rip'), 'wd_global': (0x3326420, 'rip'), 'wd_cap': (0x38, 'u8'),
                'wd_mult': (0x40, 'u8'), 'wd_map': (0x30, 'u8'), 'wd_empty': (0x3c, 'u8'), 'wd_stride': (0x1d0, 'u32'),
                'wd_slots': (0x60, 'u8')}},
    # The wielder's hand release (0x785D10(unused, avatar, entity, send), from its first instruction): the hand of the
    # avatar's five (0x50 apart) holding the entity is released by 0x785C10 (send = 1 also tells every peer); returns
    # the hand, or -1. The drop (0x9A8840) calls it with send 0.
    {'name': 'hand_release', 'start': 0x785d10, 'end': 0x785dda, 'optional': True,
     'fields': {'hr_global': (0x3326420, 'rip'), 'hr_stride': (0x1d0, 'u32'), 'hr_hands': (5, 'u8'),
                'hr_hand_stride': (0x50, 'u8'), 'hr_release': (0x785c10, 'call')}},
    # The inventory replication sender (0xBE3F40(target, avatar, primary, secondary, support, backpack, melee,
    # throwable resource)): RPC 0x42729286, each entity sent as its network record (0xFD9A40; none = 0x7FFF).
    {'name': 'inv_rpc', 'start': 0xbe3f40, 'end': 0xbe4062, 'optional': True,
     'fields': {'ir_net_record': (0xfd9a40, 'call'), 'ir_id': (0x42729286, 'u32'), 'ir_send': (0xbde430, 'call')}},
    # The selection sender (0xBEB660(target, avatar, slot)): RPC 0xA4617570 (the id literal; the shape is shared by
    # about 20 senders).
    {'name': 'sel_rpc', 'start': 0xbeb660, 'end': 0xbeb6bb, 'optional': True,
     'fields': {'sel_net_record': (0xfd9a40, 'call'), 'sel_send': (0xbde430, 'call')}},
    # The entity -> descriptor lookup (0xFD9D40(entity), NULL once the entity is gone).
    {'name': 'entity_lookup', 'start': 0xfd9d40, 'end': 0xfd9dea, 'optional': True,
     'fields': {'el_no_slot': (0x3483c4c, 'rip'), 'el_owner': (0x346bf98, 'rip'), 'el_cap': (0xf1aeb8, 'u32'),
                'el_mult': (0xf1aec0, 'u32'), 'el_map': (0xf1aeb0, 'u32'), 'el_empty': (0xf1aebc, 'u32'),
                'el_desc_base': (0x1e65e3, 'u32')}},
    # The inventory's destroy-all (0x9AE530) destroying the primary: the entity manager's destroy (0xFDC310(entities,
    # entity); a client's request goes to the host). Optional: only the recon build's test key uses it.
    {'name': 'weapon_destroy', 'start': 0x9ae5c2, 'end': 0x9ae5e6, 'optional': True,
     'fields': {'ds_rows': (0x50, 'u8'), 'ds_lookup': (0xfd9d40, 'call'), 'ds_owner': (0x346bf98, 'rip'),
                'ds_destroy': (0xfdc310, 'call')}},

    # Pinned stratagems (optional: without these the pins are off). Research: _research/flexible_loadouts/pins/notes.md.
    # Offsets are from the stratagem list (screen + 0xd2f20) unless noted; field names of their own, cross-checked.
    # The list's add (0x18d43a0(list, offer, hud_type, selectable, byte2)), opening a group: its first position (+0x927d0
    # [g]) is the item count (+0x92984), then the group count (+0x92748) goes up; then per position the selectable byte
    # (+0x92dc2), the second byte (+0x92ec2: the online-override flag) and the offer id (+0x92990).
    {'name': 'list_add', 'start': 0x18d4410, 'end': 0x18d4462, 'optional': True,
     'fields': {'lg_count': (0x92748, 'u32'), 'la_count': (0x92984, 'u32'), 'lg_start': (0x927d0, 'u32'),
                'la_selectable': (0x92dc2, 'u32'), 'lg_byte2': (0x92ec2, 'u32'), 'la_ids': (0x92990, 'u32')}},
    # The layout (0x18d2b60) placing page p (row widget: list + 0xb00 + p * 0xaed0; pages in use +0x91f0c), then
    # rebinding it only when its cached row (+0x92718[p]) differs from the row it now shows.
    {'name': 'list_pages', 'start': 0x18d2fb3, 'end': 0x18d2fed, 'optional': True,
     'fields': {'lc_pages': (0x91f0c, 'u32'), 'lc_page_stride': (0xaed0, 'u32'), 'lc_page_base': (0xb00, 'u32'),
                'lc_cache': (0x92718, 'u32')}},
    # The list's hover (0x18d0690(list, cursor)), per page: hovered col (page + 0xb9bc) = -1, then each of the page's
    # cells (count page + 0xb9b4; cell = list + 0xc10 + p * 0xaed0 + col * 0x2b68) through the game's hit test.
    {'name': 'list_cells', 'start': 0x18d0700, 'end': 0x18d0751, 'optional': True,
     'fields': {'lc_page_stride': (0xaed0, 'u32'), 'lp_hover_col': (0xb9bc, 'u32'), 'lc_page_cells': (0xb9b4, 'u32'),
                'lc_cell_stride': (0x2b68, 'u32'), 'lc_cell0': (0xc10, 'u32')}},
    # The list's mouse press (0x18cf930): only when the last device is not a pad (input [0x347cf18] + 0xe1ad5) and the
    # input is in mouse mode (+0xe1ad4) ...
    {'name': 'list_mode', 'start': 0x18cf99d, 'end': 0x18cf9be, 'optional': True,
     'fields': {'lp_pad': (0xe1ad5, 'u32'), 'lp_mouse': (0xe1ad4, 'u32')}},
    # ... with confirm pressed: the hovered page (+0x928dc, -1: none), its row (first visible row +0x928d8 + page) and
    # the page's hovered col go to the selectable read 0x18d2690(list, row, col).
    {'name': 'list_press', 'start': 0x18cf9ff, 'end': 0x18cfa39, 'optional': True,
     'fields': {'lp_hover_page': (0x928dc, 'u32'), 'lc_first_row': (0x928d8, 'u32'),
                'lc_page_stride': (0xaed0, 'u32'), 'lp_hover_col': (0xb9bc, 'u32')}},
    # The cell bind (0x18cafb0(cell, offer)), from its first instruction: the cell's offer id (+0x2b5c).
    {'name': 'list_bind', 'start': 0x18cafb0, 'end': 0x18cafd6, 'optional': True,
     'fields': {'lc_offer': (0x2b5c, 'u32')}},
    # The focus setter (0x18d1280) storing the focused offer (+0x92988 = ids[position]) before scrolling it into view.
    {'name': 'list_focused', 'start': 0x18d1400, 'end': 0x18d1423, 'optional': True,
     'fields': {'la_ids': (0x92990, 'u32'), 'lf_offer': (0x92988, 'u32')}},
    # The list grid's update (0x18d5770, grid = screen + 0xd2850 = list - 0x6d0): not on a pad (input + 0xe1ad5), the
    # cursor ([stack] + 0x5f0) over the list and the details panel state (grid + 0x178c8c) 0: the hover (0x18d0690),
    # else the hover clear (0x18d0900).
    {'name': 'list_grid_hover', 'start': 0x18d58a0, 'end': 0x18d58f6, 'optional': True,
     'fields': {'lp_pad': (0xe1ad5, 'u32'), 'lu_panel': (0x178c8c, 'u32'), 'lu_hover': (0x18d0690, 'call'),
                'lu_unhover': (0x18d0900, 'call')}},
    # The list grid's input (0x18d5a90) in its browse state: the press (0x18cf930(list)); a pick (4) sets the grid
    # state (grid + 0x178c88) to 3.
    {'name': 'list_grid_input', 'start': 0x18d5af2, 'end': 0x18d5b19, 'optional': True,
     'fields': {'lu_press': (0x18cf930, 'call'), 'lu_state': (0x178c88, 'u32')}},
    # A pad pick in the browse (0x18d5d10): select (0x18d10d0), the focus setter (0x18d1280(list, offer)), then the
    # details preview (0x18d7210(grid)).
    {'name': 'list_preview', 'start': 0x18d5e62, 'end': 0x18d5e96, 'optional': True,
     'fields': {'lm_list_focus': (0x18d1280, 'call'), 'lv_preview': (0x18d7210, 'call')}},

    # Randomize Lineup (optional: without these it is off). Research: _research/flexible_loadouts/randomize/notes.md.
    # The list rebuild (0x18d8710) filling a record for an owned stratagem: its override byte from the offers table's
    # record (offers + 0x1d99 + entry[0] * 0xb8) ...
    {'name': 'pick_ban', 'start': 0x18d8b92, 'end': 0x18d8bb7, 'optional': True,
     'fields': {'ban_stride': (0xb8, 'u32'), 'ban_base': (0x1d99, 'u32')}},
    # ... then the offer, the StratagemInfo's hud_type (+0xb8: the colour), type and sort key (+0x188).
    {'name': 'pick_record', 'start': 0x18d8bf1, 'end': 0x18d8c1a, 'optional': True,
     'fields': {'info_hud': (0xb8, 'u32')}},
    # The slot widget setter (0x1893600) colouring the slot by hud_type: the colour table (16 bytes per hud_type).
    {'name': 'hud_colour', 'start': 0x189363f, 'end': 0x1893688, 'optional': True,
     'fields': {'info_hud': (0xb8, 'u32'), 'hud_colours': (0x331b610, 'rip')}},
    # The equip handler's one-per-kind vehicle rule (in 0x146e0a0): StratagemInfo info_flags (+0x104) tested for the
    # FRV (0x200000), mech (0x100000) and tank (0x400000) kinds, each followed by the slot search (screen + 0x6373c).
    {'name': 'kind_frv', 'start': 0x146e306, 'end': 0x146e324, 'optional': True,
     'fields': {'info_flags': (0x104, 'u32'), 'kind_frv': (0x200000, 'u32')}},
    {'name': 'kind_mech', 'start': 0x146e411, 'end': 0x146e42c, 'optional': True,
     'fields': {'info_flags': (0x104, 'u32'), 'kind_mech': (0x100000, 'u32')}},
    {'name': 'kind_tank', 'start': 0x146e4f8, 'end': 0x146e518, 'optional': True,
     'fields': {'info_flags': (0x104, 'u32'), 'kind_tank': (0x400000, 'u32')}},
    # The ready handler (0x189c250) counting owned stratagems: the owned check (0x136fc20(offers, type)) for types 1 up
    # to the loop's end 0x96 (exclusive: the last type is 0x95).
    {'name': 'ready_owned', 'start': 0x189c345, 'end': 0x189c371, 'optional': True,
     'fields': {'offers': (0x347cef8, 'rip'), 'owned_call': (0x136fc20, 'call'), 'owned_end': (0x96, 'u32')}},
    # The slot grid's focus setter (0x1895770(grid, index)) unfocusing the booster (index 4): its flags (grid + 0x8eb8,
    # bit 1 focused) and the booster widget (grid + 0x8af8, the slot grid at panel + 0x5b78).
    {'name': 'booster_focus', 'start': 0x1895785, 'end': 0x18957d3, 'optional': True,
     'fields': {'booster_grid_flags': (0x8eb8, 'u32'), 'booster_at': (0x8af8, 'u32')}},
    # The booster redraw (0x1893bf0(booster)), from its first instruction: the flags (booster + 0x3c0: bit 0 hovered,
    # bit 1 focused).
    {'name': 'booster_redraw', 'start': 0x1893bf0, 'end': 0x1893c1c, 'optional': True,
     'fields': {'booster_flags': (0x3c0, 'u32')}},
    # The list's equip sound (0x18d0210) for a stratagem: by hud_type, Defensive (3), Supply (2) and Offensive (0)
    # sound ids, each played through the UI sound function.
    {'name': 'pick_sound', 'start': 0x18d0311, 'end': 0x18d0366, 'optional': True,
     'fields': {'info_hud': (0xb8, 'u32'), 'pick_green': (0x2d36b8b8, 'u32'), 'pick_blue': (0x7200dc32, 'u32'),
                'pick_red': (0x1a077fd1, 'u32'), 'ui_sound': (0x1327f50, 'call')}},
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
