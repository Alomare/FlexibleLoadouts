"""Offline test of the Flexible Stratagems release under LuaJIT, with the real game.dll dump as process memory.

The dump (_research/game_25480438.dll, offsets == RVAs) is mapped at a fake base, so the code signatures are
matched against the game's own code; the globals they lead to (screen stack, loadout screen, stratagem list, offers
table, stratagem table) and the two native functions (the list's marker and select) are simulated, and so is Mod
Options Menu where a test sets the copy limit. "Other builds"
are made by moving signatures' code elsewhere in the image (rip-relative and call operands fixed up), changing a
structure offset inside moved code, or breaking code.

Run from the mod folder:  python -B tests/test_release.py
"""
import re
import sys
import tempfile
import time
from pathlib import Path

from lupa.luajit21 import LuaRuntime

MOD = Path(__file__).resolve().parent.parent
ROOT = MOD.parents[1]
MAIN = (MOD / 'flexible_stratagems.lua').read_text(encoding='utf-8')
DUMP = ROOT / '_research' / 'game_25480438.dll'
sys.path.insert(0, str(MOD / 'research'))
sys.path.insert(0, str(ROOT / 'tools'))
import signatures  # noqa: E402
import sigspec  # noqa: E402
from entry import entry_text  # noqa: E402

SOURCE = entry_text(MOD, 'flexible_stratagems.lua')  # what ships: the texts ahead of the script

HARNESS = r'''
local logdir, image = ...
local ffi = require('ffi')
BASE = 0x40000000
STACK, SCREEN, SYS, PLAYERS, SELF, CLK, INFO = 0x20000000, 0x21000000, 0x22000000, 0x23000000, 0x24000000, 0x25000000, 0x26000000

fake = {down = {}, frame = 0}
CowboyBingusModLoader = {api = 1, log_directory = logdir, open_log = function(name)
    if type(name) ~= 'string' or not name:match('^[%w_-]+%.log$') then return nil end
    return io.open(logdir .. '/' .. name, 'w')
end}

local patches, heap = {}, {}
local function le64(v) return ffi.string(ffi.new('uint64_t[1]', v), 8) end
local function le32(v) return ffi.string(ffi.new('uint32_t[1]', v), 4) end
local function f32(v) return ffi.string(ffi.new('float[1]', v), 4) end
fake.le32, fake.le64 = le32, le64
local function read_mem(a, n)
    if a >= BASE and a + n <= BASE + #image then
        local s = image:sub(a - BASE + 1, a - BASE + n)
        for _, p in ipairs(patches) do
            local lo, hi = math.max(a, p[1]), math.min(a + n, p[1] + #p[2])
            if lo < hi then s = s:sub(1, lo - a) .. p[2]:sub(lo - p[1] + 1, hi - p[1]) .. s:sub(hi - a + 1) end
        end
        return s
    end
    for k, v in pairs(heap) do
        if k <= a and a + n <= k + #v then return v:sub(a - k + 1, a - k + n) end
    end
end
local function write_mem(a, bytes)
    for k, v in pairs(heap) do
        if k <= a and a + #bytes <= k + #v then
            heap[k] = v:sub(1, a - k) .. bytes .. v:sub(a - k + #bytes + 1)
            fake.writes = (fake.writes or 0) + 1
            return true
        end
    end
    return false
end
fake.patch = function(rva, bytes) patches[#patches + 1] = {BASE + rva, bytes} end
fake.heap = function(a, bytes) heap[a] = bytes end
fake.read, fake.write = read_mem, write_mem

local k32 = {
    GetCurrentProcess = function() return nil end,
    GetModuleHandleA = function(name) return ffi.cast('void *', BASE) end,
    ReadProcessMemory = function(p, addr, buf, size, got)
        fake.reads = (fake.reads or 0) + 1
        local s = read_mem(tonumber(ffi.cast('uint64_t', addr)), tonumber(size))
        if not s then return 0 end
        ffi.copy(buf, s, #s); got[0] = #s; return 1
    end,
    WriteProcessMemory = function(p, addr, buf, size, got)
        fake.game_writes = (fake.game_writes or 0) + 1
        if not write_mem(tonumber(ffi.cast('uint64_t', addr)), ffi.string(buf, tonumber(size))) then return 0 end
        got[0] = size; return 1
    end,
}
-- Native functions: a cast of a game.dll address to a function type returns its simulation (fake.natives).
fake.natives, fake.calls = {}, {}
local fake_ffi = setmetatable({load = function(name) return k32 end}, {__index = ffi})
fake_ffi.cast = function(ctype, value)
    if type(ctype) == 'string' and ctype:find('%(%*%)') and type(value) == 'number' and value >= BASE then
        local rva = value - BASE
        return function(...)
            fake.calls[#fake.calls + 1] = string.format('0x%x', rva)
            local f = fake.natives[rva]
            if not f then error(string.format('unsimulated native call 0x%x', rva)) end
            return f(...)
        end
    end
    return ffi.cast(ctype, value)
end
package.loaded.ffi = fake_ffi

stingray = {Keyboard = {button_id = function(n) return n end, pressed = function(id) return fake.down[id] == true end}}
update = function(dt)
    fake.base_updates = (fake.base_updates or 0) + 1
end

-- Globals.
fake.patch(0x347ce38, le64(STACK))
fake.patch(0x347ce50, le64(SYS))
fake.patch(0x3326468, le64(PLAYERS))
fake.patch(0x347cef0, le64(SELF))
fake.patch(0x3326348, le64(CLK))
fake.heap(STACK, le32(0) .. string.rep('\0', 172) .. le64(SCREEN) .. string.rep('\0', 0x400 - 184))
fake.heap(SCREEN, string.rep('\0', 0x166000))
fake.heap(SCREEN + 0x72868, le64(0))
fake.heap(PLAYERS, string.rep('\0', 0x84) .. le32(1) .. le32(1) .. string.rep('\0', 0x400 - 0x8c))
fake.heap(SCREEN + 0x273980, string.rep('\0', 0x40))   -- the list-open byte (+0x273990)
fake.heap(SELF + 0xb398, le64(0x1111))
fake.heap(CLK + 0x18, le64(50000000))
fake.heap(SYS, string.rep('\0', 0x1690 * 2))
fake.heap(SYS + 0x2d200, le32(0))

-- Stratagem infos: type -> name.
local NAMES = {[5] = 'ORBITAL. RAILCANNON STRIKE', [9] = 'EAGLE. 500KG BOMB', [12] = 'SUPPORT. QUASAR', [20] = 'BACKPACK. SHIELD', [3] = 'REINFORCE'}
for t, name in pairs(NAMES) do
    local info = INFO + t * 0x200
    fake.patch(0x37cb600 + t * 8, le64(info))
    -- type, item id, debug name pointer (+0x10, name at +0x110), flags at +0x104
    fake.heap(info, le32(t) .. le32(0x1000 + t) .. string.rep('\0', 8) .. le64(info + 0x110)
                    .. string.rep('\0', 0x110 - 0x18) .. name .. string.rep('\0', 64))
end

local function entry(t, uses, cd_end)
    return le32(t) .. le32(uses or 1) .. '\0\1' .. string.rep('\0', 14) .. le64(cd_end or 0) .. string.rep('\0', 16)
end
fake.entry = entry
function fake.set_block(index, types)
    local a = SCREEN + 0x10 + index * 0x9f0
    write_mem(a, le32(101)); write_mem(a + 0x60, le32(102)); write_mem(a + 0xc0, le32(103))
    local s = ''
    for _, t in ipairs(types) do s = s .. entry(t, 2) end
    write_mem(a + 0x188, s .. string.rep('\0', 0x600 - #s))
    write_mem(a + 0x788, le32(#types))
end
function fake.block_types(index)
    local a = SCREEN + 0x10 + index * 0x9f0
    local out = {}
    local n = ffi.new('uint32_t[1]'); ffi.copy(n, read_mem(a + 0x788, 4), 4)
    for i = 0, tonumber(n[0]) - 1 do
        local v = ffi.new('uint32_t[1]'); ffi.copy(v, read_mem(a + 0x188 + i * 0x30, 4), 4)
        out[#out + 1] = tostring(tonumber(v[0]))
    end
    return table.concat(out, ',')
end
function fake.open_screen(local_index)
    write_mem(STACK, le32(11)); write_mem(SCREEN + 0x27d0, le32(local_index or 0))
end
function fake.close_screen() write_mem(STACK, le32(0)) end
function fake.set_players(n) write_mem(PLAYERS + 0x84, le32(n)) end
-- Offers table: the stratagem range lists entries 10..14; entry k: offer id 0xb000 + type, item id 0x1000 + type.
local OFFERS = 0x27000000
fake.patch(0x347cef8, le64(OFFERS))
fake.heap(OFFERS, string.rep('\0', 0xd2000))
write_mem(OFFERS + 0x1ce0, le32(200))
write_mem(OFFERS + 0xd1d0c, le32(10) .. le32(15))
local offer_types = {5, 9, 12, 20, 3}
for k, t in ipairs(offer_types) do
    local index = 9 + k
    write_mem(OFFERS + 0xd1d48 + index * 4, le32(index))
    write_mem(OFFERS + 0xb9ce4 + index * 0x18, le32(index) .. le32(0xb000 + t) .. le32(0x1000 + t))
end
local LIST = SCREEN + 0xd2f20
function fake.set_list(types, selectable)
    write_mem(LIST + 0x92984, le32(#types))
    local ids, sel = '', ''
    for i, t in ipairs(types) do ids = ids .. le32(0xb000 + t); sel = sel .. string.char(selectable[i]) end
    write_mem(LIST + 0x92990, ids)
    write_mem(LIST + 0x92dc2, sel)
end
function fake.list_selectable()
    local n = ffi.new('uint32_t[1]'); ffi.copy(n, read_mem(LIST + 0x92984, 4), 4)
    local s = read_mem(LIST + 0x92dc2, tonumber(n[0]))
    local out = {}
    for i = 1, #s do out[i] = tostring(s:byte(i)) end
    return table.concat(out, ',')
end
-- The category is 10 (stratagems) only while the list is open (the opener sets it, the closer clears it).
function fake.set_category(c) write_mem(SCREEN + 0x2818, le32(c)); write_mem(SCREEN + 0x273990, string.char(c == 10 and 1 or 0)) end
-- The game's marker (0x18d1440): sets the offer's selectable byte to the flag.
-- The game's select (0x18d10d0): sets the list's selected offer.
fake.natives[0x18d10d0] = function(list, offer)
    fake.selects = (fake.selects or 0) + 1
    write_mem(list + 0x9298c, le32(offer))
    return 1
end
function fake.set_selected(offer) write_mem(LIST + 0x9298c, le32(offer)) end
function fake.selected() local v = ffi.new('uint32_t[1]'); ffi.copy(v, read_mem(LIST + 0x9298c, 4), 4); return tonumber(v[0]) end
fake.natives[0x18d1440] = function(list, offer, flag)
    fake.marked = (fake.marked or 0) + 1
    local n = ffi.new('uint32_t[1]'); ffi.copy(n, read_mem(list + 0x92984, 4), 4)
    for i = 0, tonumber(n[0]) - 1 do
        local v = ffi.new('uint32_t[1]'); ffi.copy(v, read_mem(list + 0x92990 + i * 4, 4), 4)
        if tonumber(v[0]) == offer then write_mem(list + 0x92dc2 + i, string.char(flag)) end
    end
end
function fake.set_flags(t, v) write_mem(INFO + t * 0x200 + 0x104, le32(v)) end
function fake.flags(t)
    local v = ffi.new('uint32_t[1]'); ffi.copy(v, read_mem(INFO + t * 0x200 + 0x104, 4), 4); return tonumber(v[0])
end
function fake.frame_step(n)
    for _ = 1, n or 1 do
        fake.frame = fake.frame + 1
        update(0.016)
    end
end
function fake.press(key) fake.down[key] = true; fake.frame_step(1); fake.down[key] = false end
-- Mod Options Menu (version 2 unless given): records the registration; fake.menu_set(v) applies a value like the
-- player's APPLY does.
function fake.install_menu(value, version)
    local menu = {api = 1, version = version or 2, values = {}, callbacks = {}}
    function menu.register_option(id, spec)
        menu.spec, menu.id = spec, id
        if menu.values[id] == nil then menu.values[id] = value or spec.default end
        return true
    end
    function menu.get(id) return menu.values[id] end
    function menu.on_change(id, fn) menu.callbacks[id] = fn end
    ModOptionsMenu = menu
    fake.menu = menu
end
function fake.menu_set(value)
    local m = fake.menu
    m.values[m.id] = value
    m.callbacks[m.id](value, m.id)
end
-- The local panel (screen + 0x53a78): its slots' flags (+0xfcc0, 0x12a8 apart; flash byte +0x18), ready timer
-- (+0x1ee14, -1.0 idle), local flag (+0x1ee0c), entity (+0x1edf8). Players: count +0x84, active +0x88, entries
-- +0xe8 (entity at +8, local flag byte +0x14), flags +0x3ac (0x20 apart; bit 3 ready).
local PANEL, PENTRIES = SCREEN + 0x53a78, 0x28000000
function fake.set_list_open(v) write_mem(SCREEN + 0x273990, string.char(v and 1 or 0)) end
function fake.set_flash(k, v) write_mem(PANEL + 0xfcc0 + k * 0x12a8 + 0x18, string.char(v)) end
function fake.set_timer(bits) write_mem(PANEL + 0x1ee14, le32(bits)) end
function fake.timer() local v = ffi.new('uint32_t[1]'); ffi.copy(v, read_mem(PANEL + 0x1ee14, 4), 4); return tonumber(v[0]) end
function fake.setup_panel(players)  -- players: {{entity, ready}...}, the first one local
    write_mem(PANEL + 0x1ee0c, '\1'); write_mem(PANEL + 0x1edf8, le32(players[1][1])); fake.set_timer(0xbf800000)
    fake.heap(PENTRIES, string.rep('\0', 0x400))
    write_mem(PLAYERS + 0x84, le32(#players)); write_mem(PLAYERS + 0x88, le32(1));
    for i, pl in ipairs(players) do
        local e = PENTRIES + 0x100 + i * 0x20
        write_mem(PLAYERS + 0xe8 + (i - 1) * 8, le64(e))
        write_mem(e + 8, le32(pl[1])); write_mem(e + 0x14, string.char(i == 1 and 1 or 0))
        write_mem(PLAYERS + 0x3ac + (i - 1) * 0x20, le32(pl[2] and 8 or 0))
    end
end
function fake.player_flags(i) local v = ffi.new('uint32_t[1]'); ffi.copy(v, read_mem(PLAYERS + 0x3ac + i * 0x20, 4), 4); return tonumber(v[0]) end
function fake.set_edit_slot(k) write_mem(SCREEN + 0x281c, le32(k)) end
function fake.set_grid_mode(v) write_mem(SCREEN + 0x6f290, le32(v)) end
-- The UI sound (0x1327f50), the grid's focus setter (0x1895770) and the list opener (0x146e9d0).
fake.sounds = {}
fake.natives[0x1327f50] = function(_, id) fake.sounds[#fake.sounds + 1] = string.format('0x%x', tonumber(id)) end
fake.natives[0x1895770] = function(grid, slot)
    fake.focused = string.format('0x%x %d', tonumber(grid) - SCREEN, tonumber(slot))
    write_mem(tonumber(grid) + 0xd96c, le32(slot))
end
fake.natives[0x146e9d0] = function(screen)
    fake.opened = (fake.opened or 0) + 1
    fake.set_list_open(true)
    write_mem(SCREEN + 0xd2f20 + 0x92960, f32(0))   -- the opener rebuilds the list: scroll back at the top
end
-- The list: its scroll (+0x92960), focus setter (0x18d1280) and layout (0x18d2b60).
function fake.set_scroll(v) write_mem(SCREEN + 0xd2f20 + 0x92960, f32(v)) end
function fake.scroll() local v = ffi.new('float[1]'); ffi.copy(v, read_mem(SCREEN + 0xd2f20 + 0x92960, 4), 4); return tonumber(v[0]) end
fake.natives[0x18d1280] = function(list, offer) fake.list_focused = tonumber(offer); return 1 end
fake.natives[0x18d2b60] = function(list) fake.laid_out = (fake.laid_out or 0) + 1 end
-- The slots: flags (byte) and type at panel + 0xfcc0 + k * 0x12a8 (+4).
function fake.set_slot(k, t, flags) write_mem(PANEL + 0xfcc0 + k * 0x12a8, string.char(flags or 0) .. '\0\0\0' .. le32(t)) end
function fake.slot_flags(k) return read_mem(PANEL + 0xfcc0 + k * 0x12a8, 1):byte() end
function fake.slot_type(k) local v = ffi.new('uint32_t[1]'); ffi.copy(v, read_mem(PANEL + 0xfcc4 + k * 0x12a8, 4), 4); return tonumber(v[0]) end
-- Clear: the widget setter (0x1893600: type at widget + 0x128c), the slots written to the block (0x189d120), the save
-- (0x1751350) and the list's closer (0x146f3b0).
fake.natives[0x1893600] = function(widget, t) write_mem(tonumber(widget) + 0x128c, le32(t)) end
fake.natives[0x189d120] = function(panel, all)
    fake.slots_written = string.format('0x%x %d', tonumber(panel) - SCREEN, tonumber(all))
    local types = {}
    for k = 0, 3 do if fake.slot_type(k) ~= 0 then types[#types + 1] = fake.slot_type(k) end end
    fake.set_block(0, types)
end
fake.natives[0x1751350] = function(block) fake.saved = string.format('0x%x', tonumber(block) - SCREEN) end
fake.natives[0x146f3b0] = function(screen) fake.closed = (fake.closed or 0) + 1; fake.set_list_open(false) end
'''

results = []


def check(cond, what):
    results.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + what)


def new_game(image, prepare=''):
    logdir = tempfile.mkdtemp(prefix='fs_rel_')
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS, logdir, image)
    if callable(prepare):
        prepare(lua)
    else:
        lua.execute(prepare)
    lua.execute(SOURCE)
    return lua, Path(logdir)


SIG_ROWS = {}  # name -> (rva, pattern text, fields)
FREE = 0x500000  # code overwritten to hold moved signatures (no signature is near it)


def moved(image, name, to, changes=None, call_targets=None):
    """The bytes of signature `name` relocated to rva `to`: rip / call operands keep their targets (or take the
    ones in call_targets), u32 / u8 fields take the values in changes."""
    rva, text, fields = SIG_ROWS[name]
    code = bytearray(image[rva:rva + len(text.split())])
    for field, (kind, offs, nxts) in fields.items():
        for k, off in enumerate(offs):
            if kind in ('rip', 'call'):
                target = rva + nxts[k] + int.from_bytes(code[off:off + 4], 'little', signed=True)
                target = (call_targets or {}).get(field, target)
                code[off:off + 4] = (target - (to + nxts[k])).to_bytes(4, 'little', signed=True)
            elif field in (changes or {}):
                size = 1 if kind == 'u8' else 4
                code[off:off + size] = changes[field].to_bytes(size, 'little')
    return bytes(code)


def broken(name):
    rva, text, _ = SIG_ROWS[name]
    return rva, b'\xcc' * len(text.split())


def text(path):
    return path.read_text(encoding='utf-8') if path.exists() else ''


def reads_per_frame(f, frames):
    before = f.reads or 0
    f.frame_step(frames)
    return ((f.reads or 0) - before) / frames


def main():
    for pattern in (r'//', r'\bgoto\b', r'&(?!&)', r'~(?!=)', r'<<', r'>>', r'math\.type', r'string\.pack'):
        check(not re.search(pattern, MAIN.split('\n', 1)[1].replace('-->', '')), f'no Lua 5.3+ construct {pattern!r}')
    check(SOURCE.startswith('-- HD2-Addon: mods/alomare/flexible_stratagems\n'), 'declaration line first')
    version = re.search(r"local M = \{version = '([^']+)'", MAIN).group(1)
    check(not re.search(r'f10|snapshot|save_raw|recon|DuplicateStratagems|StratagemsUnleashed',
                        MAIN.replace(version, ''), re.I), 'no research leftovers or old names')
    image = DUMP.read_bytes()
    for name, rva, text_, fields, _optional in sigspec.build(signatures.SPECS):
        SIG_ROWS[name] = (rva, text_, fields)
    in_script = re.findall(r"name = '(\w+)', rva = (0x[0-9a-f]+),(?: optional = true,)? text = '([^']+)'", MAIN)
    check([(n, int(r, 16), t) for n, r, t in in_script] == [(n, v[0], v[1]) for n, v in SIG_ROWS.items()],
          'the script carries the signatures research/signatures.py builds (%d)' % len(in_script))
    check(not sigspec.check(MOD / 'flexible_stratagems.lua', sigspec.build(signatures.SPECS)),
          'the script carries the current signature engine (tools/sigscan.lua)')

    # 1. This build, no Mod Options Menu: 2 copies; idle outside the loadout screen.
    lua, logs = new_game(image)
    f = lua.globals().fake
    f.frame_step(1)
    status = text(logs / 'FlexibleStratagems_STATUS.log')
    check(status.startswith('OK - up to 2 of each stratagem') and 'Flexible Stratagems %s' % version in status
          and 'Copies per stratagem: 2 (default; Mod Options Menu not found)' in status
          and "Game code found at this game version's addresses" in status and 'ooldown' not in status,
          'status OK on this build, 2 copies by default: %r' % status)
    check(f.base_updates == 1, 'update chained')
    rate = reads_per_frame(f, 120)
    check(rate <= 1 and not f.game_writes, 'outside the loadout screen: %.2f reads per frame, no writes' % rate)

    # 2. 4 copies (Mod Options Menu). Loadout screen, another category: a few reads per frame, nothing written.
    lua, logs = new_game(image, 'fake.install_menu(4)')
    f = lua.globals().fake
    f.frame_step(1)
    status = text(logs / 'FlexibleStratagems_STATUS.log')
    check(status.startswith('OK - up to 4 of each stratagem')
          and 'Copies per stratagem: 4 (Mod Options Menu)' in status, '4 copies from Mod Options Menu: %r' % status.splitlines()[:3])
    f.set_flags(12, 0x00200021)
    f.set_flags(9, 0x80100000)
    f.set_flags(20, 0x0000000a)
    f.set_block(0, lua.table(5, 9, 12, 3))
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(1, 1, 1, 1, 1, 1))
    f.set_category(3)
    f.open_screen(0)
    f.frame_step(10)
    rate = reads_per_frame(f, 20)
    # List closed: the screen (3), the list-open byte and the four flash bytes.
    check(rate <= 8 and not f.game_writes and f.flags(12) == 0x00200021, 'other category: %.1f reads per frame, nothing written' % rate)

    # 3. The stratagem list opens: vehicle bits cleared; steady state costs one list read.
    f.set_category(10)
    f.frame_step(1)
    check(f.flags(12) == 0x21 and f.flags(9) == 0x80000000 and f.flags(20) == 0xa,
          'list open: only the vehicle bits cleared: %x %x %x' % (f.flags(12), f.flags(9), f.flags(20)))
    writes = f.game_writes
    rate = reads_per_frame(f, 20)
    # List open: the screen (3), the list-open byte, the list span, the loadout block and the scroll.
    check(rate <= 7 and f.game_writes == writes, 'list open, nothing refused: %.1f reads per frame, no writes' % rate)

    # 4. The game's refresh refuses the loadout's stratagems (and one item for another reason): the loadout's are
    #    marked back through the game's marker, the other stays refused and costs nothing more afterwards.
    f.set_selected(0xb009)  # a controller's focus on a loadout stratagem, no pick
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(0, 0, 0, 1, 0, 0))
    f.frame_step(1)
    check(f.list_selectable() == '1,1,1,1,1,0' and f.marked == 4, 'loadout stratagems marked selectable: %s' % f.list_selectable())
    rate = reads_per_frame(f, 20)
    check(rate <= 7 and f.marked == 4, 'an unrelated refused item: %.1f reads per frame, not marked again' % rate)
    check(not f.selects and f.selected() == 0xb009, 'no pick yet: the selection (focus) is left alone')

    # 5. A pick (Railcannon again): the refresh refuses the loadout's stratagems again; the selection left on the
    #    Railcannon is cleared once, so its next pick plays the sound. Two Railcannons stay pickable (limit 4).
    f.set_selected(0xb005)
    f.set_block(0, lua.table(5, 5, 12, 3))
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(0, 1, 0, 1, 0, 0))
    f.frame_step(1)
    check(f.selects == 1 and f.selected() == 0 and f.list_selectable() == '1,1,1,1,1,0',
          'after a pick: selection cleared, loadout marked again (two copies still selectable under 4)')
    f.set_selected(0xb005)
    f.frame_step(5)
    check(f.selects == 1 and f.selected() == 0xb005, 'the selection is cleared once per pick (controller focus kept)')
    f.set_selected(0xb04d)
    f.set_block(0, lua.table(5, 5, 12, 20))
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(0, 1, 0, 0, 1, 0))
    f.frame_step(1)
    check(f.selects == 1 and f.selected() == 0xb04d, 'a selection outside the loadout is left alone')
    check(all(c in ('0x18d1440', '0x18d10d0') for c in f.calls.values()), 'only the marker and select are called')

    # 6. The list closes, then the category changes, then the screen closes: the vehicle bits come back each time.
    f.set_list(lua.table(), lua.table())
    f.frame_step(1)
    check(f.flags(12) == 0x00200021 and f.flags(9) == 0x80100000, 'list closed: vehicle bits restored')
    f.set_list(lua.table(5, 9), lua.table(1, 1))
    f.frame_step(1)
    check(f.flags(12) == 0x21, 'list open again: cleared again')
    f.set_category(3)
    f.frame_step(1)
    check(f.flags(12) == 0x00200021, 'category changed: restored')
    f.set_category(10)
    f.frame_step(1)
    f.set_flags(12, 0x99)  # the game changes it meanwhile
    f.close_screen()
    f.frame_step(1)
    check(f.flags(12) == 0x99 and f.flags(9) == 0x80100000, 'screen closed: restored, a value changed meanwhile left alone')
    # Another visit: the vehicle list is found again when the table changed.
    f.set_flags(12, 0x00400001)
    f.open_screen(0)
    f.frame_step(10)
    check(f.flags(12) == 0x1 and f.flags(9) == 0x80000000, 'a changed table is scanned again')
    f.close_screen()
    f.frame_step(10)
    check(f.flags(12) == 0x00400001, 'and restored')

    # 7. 2 copies (the default): a stratagem in the loadout once is marked back, one already there twice stays
    #    refused; vehicles are lifted too (a second copy of a vehicle).
    lua, logs = new_game(image, 'fake.install_menu(2)')
    f = lua.globals().fake
    f.frame_step(1)
    f.set_flags(12, 0x00200021)
    f.set_block(0, lua.table(5, 12, 9, 3))
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(0, 0, 0, 1, 0, 0))
    f.set_category(10)
    f.open_screen(0)
    f.frame_step(10)
    check(f.list_selectable() == '1,1,1,1,1,0' and f.flags(12) == 0x21,
          '2 copies, one of each: all marked back, vehicle bits lifted: %s' % f.list_selectable())
    f.set_block(0, lua.table(5, 5, 12, 12))
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(0, 1, 0, 1, 1, 0))
    f.frame_step(2)
    check(f.list_selectable() == '0,1,0,1,1,0', 'two Railcannons and two of a vehicle: both stay refused: %s' % f.list_selectable())
    marked = f.marked
    f.frame_step(20)
    check(f.marked == marked, 'refused by the copy limit: not marked again every frame')
    f.set_block(0, lua.table(5, 12, 12, 3))
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(0, 1, 0, 1, 0, 0))
    f.frame_step(2)
    check(f.list_selectable() == '1,1,0,1,1,0', 'a copy replaced: the Railcannon is pickable again: %s' % f.list_selectable())

    # 8. The limit changes in game: at 3 the two-copy stratagems are marked back, a third copy stays refused; at 4 it
    #    is marked back too. Out-of-range values are clamped.
    f.menu_set(3)
    f.set_block(0, lua.table(5, 5, 12, 12))
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(0, 1, 0, 1, 1, 0))
    f.frame_step(2)
    status = text(logs / 'FlexibleStratagems_STATUS.log')
    check(f.list_selectable() == '1,1,1,1,1,0' and status.startswith('OK - up to 3 of each stratagem'),
          '3 copies: two Railcannons and two vehicles stay pickable: %s' % f.list_selectable())
    f.set_block(0, lua.table(5, 5, 5, 12))
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(0, 1, 0, 1, 1, 0))
    f.frame_step(2)
    check(f.list_selectable() == '0,1,1,1,1,0', '3 copies: a third Railcannon stays refused: %s' % f.list_selectable())
    f.menu_set(4)
    f.frame_step(2)
    check(f.list_selectable() == '1,1,1,1,1,0' and f.flags(12) == 0x21, '4 copies: marked back: %s' % f.list_selectable())
    f.menu_set(9)
    f.frame_step(1)
    status = text(logs / 'FlexibleStratagems_STATUS.log')
    check(status.startswith('OK - up to 4 of each'), 'a value above the slider is clamped to 4: %r' % status.splitlines()[:1])

    # 9. Mod Options Menu: an integer slider from 2 to 4 (default 2), texts as functions (version 2) within the limits.
    spec = f.menu.spec
    check(f.menu.id == 'alomare.flexible_stratagems.max_copies' and spec.type == 'slider' and spec.min == 2
          and spec.max == 4 and spec.step == 1 and spec.default == 2 and callable(spec.label)
          and spec.label() == 'Copies per Stratagem' and spec.mod() == 'Flexible Stratagems'
          and len(spec.description()) <= 400,
          'option: slider 2-4, default 2, texts as functions, description %d characters' % len(spec.description()))
    lua, logs = new_game(image, 'fake.install_menu(nil, 1)')
    f = lua.globals().fake
    f.frame_step(1)
    spec = f.menu.spec
    check(spec.label == 'Copies per Stratagem' and spec.mod == 'Flexible Stratagems', 'Mod Options Menu v1.0: plain strings')

    # 12. Errors: the vehicle bits are restored; five errors stop the mod.
    lua, logs = new_game(image, "fake.install_menu(4); fake.natives[0x18d1440] = function() error('boom') end")
    f = lua.globals().fake
    f.frame_step(1)
    f.set_flags(12, 0x00200021)
    f.set_block(0, lua.table(5, 9))
    f.set_list(lua.table(5, 9), lua.table(0, 0))
    f.set_category(10)
    f.open_screen(0)
    f.frame_step(20)
    status = text(logs / 'FlexibleStratagems_STATUS.log')
    check(f.flags(12) == 0x00200021 and status.startswith('STOPPED - repeated errors') and 'boom' in text(logs / 'FlexibleStratagems.log'),
          'errors restore the vehicle bits and stop the mod after five: %r' % status.splitlines()[:1])
    before = f.base_updates
    f.frame_step(3)
    check(f.base_updates == before + 3, 'update still chained after stopping')

    # 13. Another build where code moved: the marker, select and the screen query are elsewhere (the refresh calls the
    #     moved marker), and the screen slot is +0xb8 instead of +0xb0. The mod finds them by search, follows the new
    #     slot, and calls the natives at their new addresses.
    # select starts 16 bytes into the second search chunk: inside the first chunk's overlap too, counted once.
    new = {'marker': FREE, 'select': 0x1000 + 0x400000 + 0x10, 'screen': FREE + 0x200}

    def moved_build(lua):
        f = lua.globals().fake
        lua.execute('fake.install_menu(4)')
        for name in new:
            rva, garbage = broken(name)
            f.patch(rva, garbage)
        f.patch(new['marker'], moved(image, 'marker', new['marker']))
        f.patch(new['select'], moved(image, 'select', new['select']))
        f.patch(new['screen'], moved(image, 'screen', new['screen'], {'slot': 0xb8}))
        rb = SIG_ROWS['refresh_b'][0]
        f.patch(rb, moved(image, 'refresh_b', rb, call_targets={'mark': new['marker']}))
        lua.execute("""fake.natives[%d] = fake.natives[0x18d1440]; fake.natives[%d] = fake.natives[0x18d10d0]
            fake.natives[0x18d1440], fake.natives[0x18d10d0] = nil, nil
            fake.heap(STACK, string.rep('\\0', 0xb8) .. fake.le64(SCREEN) .. string.rep('\\0', 0x400 - 0xc0))"""
                    % (new['marker'], new['select']))
    lua, logs = new_game(image, moved_build)
    f = lua.globals().fake
    started = time.perf_counter()
    frames = 0
    while not text(logs / 'FlexibleStratagems_STATUS.log') and frames < 60:
        f.frame_step(1)
        frames += 1
    elapsed = time.perf_counter() - started
    status = text(logs / 'FlexibleStratagems_STATUS.log')
    print('INFO search of game.dll: %d frames, %.2f s in this LuaJIT (%.0f ms per frame)' % (frames, elapsed, elapsed * 1000 / frames))
    check(status.startswith('OK - up to 4 of each') and 'Game code found by search (3 moved: screen, marker, select)' in status,
          'moved code found by search: %r' % status.splitlines()[-1:])
    f.set_flags(12, 0x00200021)
    f.set_block(0, lua.table(5, 5, 12))
    f.set_list(lua.table(5, 12, 20), lua.table(0, 0, 1))
    f.set_selected(0xb005)
    f.set_category(10)
    f.open_screen(0)
    f.frame_step(10)
    f.set_block(0, lua.table(5, 5, 5))
    f.set_list(lua.table(5, 12, 20), lua.table(0, 1, 1))
    f.frame_step(2)
    calls = set(f.calls.values())
    check(f.list_selectable() == '1,1,1' and f.flags(12) == 0x21 and calls == {hex(new['marker']), hex(new['select'])},
          'the loadout is served through the moved screen slot, marker and select: %s %s' % (f.list_selectable(), sorted(calls)))

    # 14. Builds the mod can't trust: nothing runs, the status says why.
    def build(*edits):
        def prepare(lua):
            f = lua.globals().fake
            for rva, data in edits:
                f.patch(rva, data)
        return prepare
    kind_mech = SIG_ROWS['kind_mech']
    flags_at = kind_mech[0] + kind_mech[2]['flags'][1][0]
    cases = (
        (build(broken('marker')), 'code "marker" not found'),
        (build(broken('select'), (FREE, moved(image, 'select', FREE)), (FREE + 0x100, moved(image, 'select', FREE + 0x100))),
         'code "select" found 2 times'),
        (build((flags_at, (0x108).to_bytes(4, 'little'))), '"flags" differs between signatures'),
        (build(broken('marker'), (FREE, moved(image, 'marker', FREE))), 'the refresh does not call the marker'),
        (build((SIG_ROWS['refresh_a'][0] + SIG_ROWS['refresh_a'][2]['list_count'][1][1], (0x92988).to_bytes(4, 'little'))),
         'code "refresh_a" field "list_count" occurrences disagree'),
    )
    for prepare, why in cases:
        lua, logs = new_game(image, prepare)
        f = lua.globals().fake
        f.set_block(0, lua.table(5, 9))
        f.set_list(lua.table(5, 9), lua.table(0, 0))
        f.set_category(10)
        f.open_screen(0)
        f.frame_step(40)
        status = text(logs / 'FlexibleStratagems_STATUS.log')
        check(status.startswith('NOT AVAILABLE - this game version is not supported (%s)' % why) and not f.game_writes
              and not len(f.calls) and f.list_selectable() == '0,0', 'another build (%s): nothing written or called: %r'
              % (why, status.splitlines()[:1]))


    # 15. Ready with empty slots: a flash starting on the local panel's slots (the handler's refusal) toggles the ready
    #     the handler's way; a flash still showing, or one while the list is open, does nothing.
    lua, logs = new_game(image)
    f = lua.globals().fake
    f.frame_step(1)
    f.setup_panel(lua.table(lua.table(77, False), lua.table(88, False)))
    f.set_block(0, lua.table(5, 9))
    f.open_screen(0)
    f.frame_step(12)
    f.set_flash(2, 1); f.set_flash(3, 1)
    f.frame_step(1)
    log = lambda: text(logs / 'FlexibleStratagems.log')
    check(f.timer() == 0x3fe00000 and list(f.sounds.values()) == ['0x4d777731'] and 'Ready with 2 empty slot(s)' in log(),
          'refused ready: the timer starts at 1.75 s with the ready sound: 0x%x %r' % (f.timer(), list(f.sounds.values())))
    f.frame_step(30)
    check(f.timer() == 0x3fe00000 and len(f.sounds) == 1, 'a flash still showing: nothing more')
    f.set_flash(2, 0); f.set_flash(3, 0)
    f.set_timer(0xbd000000)                                 # the panel update ran the timer out ...
    lua.execute('fake.write(%d, fake.le32(8))' % (0x23000000 + 0x3ac))  # ... and set the ready bit
    f.frame_step(2)
    f.set_flash(2, 1)
    f.frame_step(1)
    check(f.timer() == 0xbf800000 and f.player_flags(0) == 0 and len(f.sounds) == 1 and 'Ready cancelled' in log(),
          'refused again while ready: cancelled (timer idle, ready bit cleared, the refusal played the sound)')
    f.set_flash(2, 0); f.frame_step(1)
    lua.execute('fake.write(%d, fake.le32(8))' % (0x23000000 + 0x3ac + 0x20))  # the other player is ready
    f.set_flash(3, 1); f.frame_step(1)
    check(f.timer() == 0x3fe00000 and list(f.sounds.values())[-1] == '0x7947920',
          'the last player to ready: the last ready sound: %r' % list(f.sounds.values()))
    f.set_flash(3, 0); f.set_timer(0xbf800000); f.set_list_open(True); f.frame_step(1)
    f.set_flash(3, 1); f.frame_step(2)
    check(f.timer() == 0xbf800000, 'a flash while the list is open: nothing')
    f.set_list_open(False); f.set_flash(3, 0); f.frame_step(1)
    lua.execute("fake.write(%d, '\\0')" % (0x21000000 + 0x53a78 + 0x1ee0c))  # not the local panel
    f.set_flash(3, 1); f.frame_step(1)
    check(f.timer() == 0xbf800000, 'not the local panel: nothing')
    status = text(logs / 'FlexibleStratagems_STATUS.log')
    check('Ready with empty slots: on' in status and 'List kept open after a replacement: on' in status,
          'status: both list extras on: %r' % status.splitlines()[-2:])

    # 16. A replacement in a full loadout closes the list: it opens again on the next slot (through the grid's focus
    #     setter and the game's opener). Escape (no change), the last slot, a fill of an empty slot and grid mode 1:
    #     closed as the game leaves it.
    lua, logs = new_game(image)
    f = lua.globals().fake
    f.frame_step(1)
    f.open_screen(0)
    f.frame_step(12)

    def pick(slot, before, after, close=True, mode=0):
        f.focused, f.opened = None, 0
        f.set_grid_mode(mode)
        f.set_block(0, lua.table(*before)); f.set_list(lua.table(5, 9, 12, 20, 3), lua.table(1, 1, 1, 1, 1))
        f.set_category(10); f.set_edit_slot(slot); f.set_list_open(True)
        f.frame_step(2)
        f.set_scroll(321.5)
        f.frame_step(1)
        f.set_block(0, lua.table(*after))
        f.set_slot(slot, after[slot] if slot < len(after) else 0)
        if close:
            f.set_category(0); f.set_list_open(False)
        f.frame_step(2)
        result = (f.focused, f.opened)
        f.set_category(0); f.set_list_open(False); f.frame_step(2)
        return result

    f.list_focused, f.laid_out = None, 0
    check(pick(1, (5, 9, 12, 3), (5, 20, 12, 3)) == ('0x595f0 2', 1),
          'replaced slot 2 of 4: the list opens again on slot 3')
    check(f.list_focused == 0xb000 + 20 and f.scroll() == 321.5 and f.laid_out == 1,
          'the list focuses the stratagem just picked and keeps its scroll: %r %r %r' % (f.list_focused, f.scroll(), f.laid_out))
    check(pick(0, (5, 9, 12, 3), (5, 9, 12, 3)) == (None, 0), 'closed without a change (Escape): stays closed')
    check(pick(3, (5, 9, 12, 3), (5, 9, 12, 20)) == (None, 0), 'replaced slot 4: closes as the game does')
    check(pick(1, (5, 12, 3), (5, 20, 12, 3)) == (None, 0), 'filled the last empty slot: closes as the game does')
    check(pick(1, (5, 9, 12, 3), (5, 20, 12, 3), mode=1) == (None, 0), 'grid mode 1: left alone')
    check(pick(1, (5, 9, 12, 3), (5, 20, 12, 3), close=False) == (None, 0), 'the list still open: nothing')
    check('Replaced slot 2: list opened on slot 3' in text(logs / 'FlexibleStratagems.log'), 'logged')

    # 17. Clear Stratagems: a Mod Bindings Menu key empties the four slots, writes the block from them and saves it;
    #     with the list open it closes it first; not while ready.
    def clear_game():
        lua, logs = new_game(image, "ModBindingsMenu = {api = 1, version = 3, register_binding = function(id, label, slot, o) "
                                    "fake.bound = id .. '|' .. label() .. '|' .. o.category(); return true end, "
                                    "is_down = function(id) return fake.clear_down == true end}")
        f = lua.globals().fake
        f.frame_step(1)
        f.setup_panel(lua.table(lua.table(77, False)))
        f.set_slot(0, 5); f.set_slot(1, 9); f.set_slot(2, 12); f.set_slot(3, 0)
        f.set_block(0, lua.table(5, 9, 12))
        f.open_screen(0)
        f.frame_step(12)
        return lua, logs, f

    lua, logs, f = clear_game()
    check(f.bound == 'alomare.flexible_stratagems.clear|Clear Stratagems|Flexible Stratagems', 'the clear key: %r' % f.bound)
    f.clear_down = True; f.frame_step(1); f.clear_down = False; f.frame_step(1)
    check([f.slot_type(k) for k in range(4)] == [0, 0, 0, 0] and f.block_types(0) == '' and f.slots_written == '0x53a78 -1'
          and f.saved == '0x10' and not f.closed and 'Clear Stratagems: 3 slot(s) emptied' in text(logs / 'FlexibleStratagems.log'),
          'clear: the slots emptied, the block written from them and saved: %r %r' % (f.block_types(0), f.saved))
    lua, logs, f = clear_game()
    f.set_category(10)
    f.clear_down = True; f.frame_step(1); f.clear_down = False
    check(f.closed == 1 and f.slot_type(0) == 0, 'clear with the list open: closed first')
    lua, logs, f = clear_game()
    f.set_timer(0x3fe00000)
    f.clear_down = True; f.frame_step(1); f.clear_down = False
    check(f.slot_type(0) == 5 and not f.saved and 'not while ready' in text(logs / 'FlexibleStratagems.log'), 'not while ready')
    lua, logs, f = clear_game()
    f.close_screen(); f.frame_step(12)
    f.clear_down = True; f.frame_step(1); f.clear_down = False; f.frame_step(12)
    check(f.slot_type(0) == 5 and not f.saved, 'outside the loadout screen: nothing')

    # 18. Without the ready code only that extra is off; the picker and the other extra still work.
    lua, logs = new_game(image, build(broken('ready_slots')))
    f = lua.globals().fake
    f.frame_step(40)
    status = text(logs / 'FlexibleStratagems_STATUS.log')
    check(status.startswith('OK - up to 2') and 'Ready with empty slots: NOT AVAILABLE (code "ready_slots" not found)' in status
          and 'List kept open after a replacement: on' in status,
          'ready code missing: only that extra is off: %r' % status.splitlines()[-2:])
    lua, logs = new_game(image, build((SIG_ROWS['equip_tail'][0] + SIG_ROWS['equip_tail'][2]['focus_call'][1][0],
                                       (0x10).to_bytes(4, 'little'))))
    f = lua.globals().fake
    f.frame_step(40)
    status = text(logs / 'FlexibleStratagems_STATUS.log')
    check('List kept open after a replacement: NOT AVAILABLE (the equip handler does not focus with the setter found)'
          in status, 'the equip handler calling another focus setter: that extra is off: %r' % status.splitlines()[-1:])

    passed = sum(results)
    print(f'{passed}/{len(results)} passed')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
