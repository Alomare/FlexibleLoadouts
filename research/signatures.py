"""Stratagems Unleashed's code signatures (NOTES.md, "Finding the game's code"): checked against the game.dll dump
and written into stratagems_unleashed.lua between the SIGNATURES markers.

Usage (from the workspace root): python -B StratagemsUnleashed/research/signatures.py [--check]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import sigspec  # noqa: E402

SCRIPT = ROOT / 'StratagemsUnleashed' / 'stratagems_unleashed.lua'

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
]


def main():
    rows = sigspec.build(SPECS)
    sigspec.report(rows)
    if '--check' not in sys.argv:
        sigspec.write(SCRIPT, rows)
        print('written to', SCRIPT.name)


if __name__ == '__main__':
    main()
