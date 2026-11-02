"""Offline test of the Flexible Loadouts release under LuaJIT, with the real game.dll dump as process memory.

The test runs the assembled entry (tools/entry.py), the script with its texts ahead of it.

The dump (_research/game_25480438.dll, offsets == RVAs) is mapped at a fake base, so the code signatures are
matched against the game's own code; the globals they lead to (screen stack, loadout screen, stratagem list, offers
table, stratagem table), the native functions (the ready, slot and list functions) and Mod Bindings Menu are
simulated. "Other builds"
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
MAIN = (MOD / 'flexible_loadouts.lua').read_text(encoding='utf-8')
DUMP = ROOT / '_research' / 'game_25480438.dll'
sys.path.insert(0, str(MOD / 'research'))
sys.path.insert(0, str(ROOT / 'tools'))
import signatures  # noqa: E402
import sigspec  # noqa: E402
from entry import entry_text  # noqa: E402

# What ships: the texts ahead of the script.
SOURCE = entry_text(MOD, 'flexible_loadouts.lua')

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

local patches, heap, real = {}, {}, {}
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
    for _, r in ipairs(real) do
        if r[1] <= a and a + n <= r[1] + r[2] then return ffi.string(ffi.cast('const char *', a), n) end
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
    for _, r in ipairs(real) do
        if r[1] <= a and a + #bytes <= r[1] + r[2] then ffi.copy(ffi.cast('void *', a), bytes, #bytes); return true end
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
        if fake.trace then fake.trace[#fake.trace + 1] = tonumber(ffi.cast('uint64_t', addr)) end
        if fake.fail_at and tonumber(ffi.cast('uint64_t', addr)) == fake.fail_at then error('boom') end
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
-- The libraries as the mod sees them: a name is found only through its declaration, bound to its export by __asm__.
-- Another mod loaded first declared the Windows functions under their bare names, with other types (all addons share
-- one FFI namespace, where a name keeps its first declaration).
local declared = {}
local function cdef(text)
    ffi.cdef(text)
    local name, rest = text:match('([%w_]+)%s*%b()%s*([^;]*);%s*$')
    if name and not declared[name] then declared[name] = rest:match('__asm__%("([%w_]+)"%)') or name end
end
for _, decl in ipairs({'uintptr_t GetCurrentProcess(void);', 'uintptr_t GetModuleHandleA(const char *name);',
                       'int ReadProcessMemory(uintptr_t process, uintptr_t address, uintptr_t buffer, size_t size, '
                           .. 'size_t *read);',
                       'int WriteProcessMemory(uintptr_t process, uintptr_t address, const char *buffer, size_t size, '
                           .. 'size_t *written);'}) do
    ffi.cdef(decl)
end
local library = setmetatable({}, {__index = function(_, name)
    return assert(k32[assert(declared[name], 'missing declaration for ' .. name)], 'no stand-in for ' .. name)
end})
-- Native functions: a cast of a game.dll address to a function type returns its simulation (fake.natives).
fake.natives, fake.calls = {}, {}
local fake_ffi = setmetatable({load = function(name) return library end, cdef = cdef}, {__index = ffi})
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
fake_ffi.new = function(ct, ...)
    local o = ffi.new(ct, ...)
    if ct == 'uint8_t[?]' then real[#real + 1] = {tonumber(ffi.cast('uint64_t', o)), (...)} end
    return o
end
package.loaded.ffi = fake_ffi

stingray = {Keyboard = {button_id = function(n) return n end, pressed = function(id) return fake.down[id] == true end},
            Application = {can_get = function(kind, name)
                fake.can_get = kind .. ' ' .. name
                return fake.mark_loaded ~= false
            end}}
update = function(dt)
    fake.base_updates = (fake.base_updates or 0) + 1
end

-- Globals.
fake.patch(0x347ce38, le64(STACK))
fake.patch(0x347ce50, le64(SYS))
fake.patch(0x3326468, le64(PLAYERS))
fake.patch(0x347cef0, le64(SELF))
fake.patch(0x3326348, le64(CLK))
fake.heap(STACK, le32(0) .. string.rep('\0', 172) .. le64(SCREEN) .. string.rep('\0', 0x1000 - 184))
fake.heap(SCREEN, string.rep('\0', 0x166000))
fake.heap(SCREEN + 0x72868, le64(0))
fake.heap(PLAYERS, string.rep('\0', 0x84) .. le32(1) .. le32(1) .. string.rep('\0', 0x400 - 0x8c))
fake.heap(SCREEN + 0x273980, string.rep('\0', 0x60))   -- the list-open byte (+0x273990) .. the active group (+0x2739c8)
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
function fake.set_flags(t, v) write_mem(INFO + t * 0x200 + 0x104, le32(v)) end
function fake.flags(t)
    local v = ffi.new('uint32_t[1]'); ffi.copy(v, read_mem(INFO + t * 0x200 + 0x104, 4), 4); return tonumber(v[0])
end
function fake.frame_step(n)
    for _ = 1, n or 1 do
        fake.frame = fake.frame + 1
        if fake.game_frame then fake.game_frame() end   -- the game's update runs before the mod's
        update(0.016)
    end
end
function fake.press(key) fake.down[key] = true; fake.frame_step(1); fake.down[key] = false end
-- Mod Options Menu: records the registrations; fake.set_option applies a value as the player would.
fake.options, fake.option_specs, fake.option_change, fake.option_values = {}, {}, {}, {}
function fake.install_menu()
    local menu = {api = 1, version = 3}
    function menu.register_option(id, spec)
        fake.options[#fake.options + 1] = id; fake.option_specs[id] = spec; return true
    end
    function menu.get(id) return fake.option_values[id] end
    function menu.on_change(id, fn) fake.option_change[id] = fn end
    ModOptionsMenu = menu
end
function fake.set_option(id, v)
    fake.option_values[id] = v
    local fn = fake.option_change[id]
    if fn then fn(v, id) end
end
function fake.option_text(id, field)
    local v = fake.option_specs[id][field]
    if type(v) == 'function' then return v() end
    return v
end
-- The local panel (screen + 0x53a78): its slots' flags (+0xfcc0, 0x12a8 apart; flash byte +0x18), ready timer
-- (+0x1ee14, -1.0 idle), local flag (+0x1ee0c), entity (+0x1edf8), unit (+0x1edfc). Players: count +0x84, active +0x88, entries
-- +0xe8 (entity at +8, local flag byte +0x14), flags +0x3ac (0x20 apart; bit 3 ready).
local PANEL, PENTRIES = SCREEN + 0x53a78, 0x28000000
function fake.set_list_open(v) write_mem(SCREEN + 0x273990, string.char(v and 1 or 0)) end
function fake.set_flash(k, v) write_mem(PANEL + 0xfcc0 + k * 0x12a8 + 0x18, string.char(v)) end
function fake.set_timer(bits) write_mem(PANEL + 0x1ee14, le32(bits)) end
function fake.set_unit(v) write_mem(PANEL + 0x1edfc, le32(v)) end
function fake.timer() local v = ffi.new('uint32_t[1]'); ffi.copy(v, read_mem(PANEL + 0x1ee14, 4), 4); return tonumber(v[0]) end
function fake.setup_panel(players)  -- players: {{entity, ready}...}, the first one local
    write_mem(PANEL + 0x1ee0c, '\1'); write_mem(PANEL + 0x1edf8, le32(players[1][1])); fake.set_timer(0xbf800000)
    fake.set_unit(0x4242)
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
-- The READY prompt's press check (0x1891850: prompt, input object [0x347cf18]): fake.ready_pressed for one frame.
local INPUT = 0x29000000
fake.heap(INPUT, string.rep('\0', 0xe2000))
fake.patch(0x347cf18, le64(INPUT))
fake.natives[0x1891850] = function(prompt, input)
    fake.press_args = string.format('0x%x 0x%x', tonumber(prompt) - PANEL, tonumber(input))
    return fake.ready_pressed and 1 or 0
end
-- The emote sender (0xbf2e20: unused, unit, event, 0.0, 0.0): the ready pose told to every peer.
fake.poses = {}
fake.natives[0xbf2e20] = function(_, unit, event, a, b)
    fake.poses[#fake.poses + 1] = string.format('0x%x 0x%x %s %s', tonumber(unit), tonumber(event), tostring(a), tostring(b))
end
-- The clear buttons. GUI contexts [0x347ce90]: 13 slots 0x3698 apart (byte 1: live), the stack's top (i32 +0x2c5bc,
-- -1 when empty) and slots (u8 +0x2c5b8). Widgets: header +0, first child +0xe0, next sibling +0xe8, parent +0xf0,
-- context +0xf8. The slot widgets: SCREEN + 0x624b0 + k * 0x12a8 (flags +0x1288, type +0x128c), each with one native
-- child, in context slot 2.
local CTX = 0x2a000000
fake.patch(0x347ce90, le64(CTX))
fake.heap(CTX, string.rep('\0', 0x2c600))
for j = 0, 12 do write_mem(CTX + j * 0x3698, '\1') end
write_mem(CTX + 0x2c5bc, le32(0xffffffff))
local function rd32(a) local v = ffi.new('uint32_t[1]'); ffi.copy(v, read_mem(a, 4), 4); return tonumber(v[0]) end
local function rd64(a) local v = ffi.new('uint64_t[1]'); ffi.copy(v, read_mem(a, 8), 8); return tonumber(v[0]) end
local function top() local t = rd32(CTX + 0x2c5bc); return t >= 2147483648 and t - 4294967296 or t end
fake.rd32, fake.rd64, fake.top = rd32, rd64, top
local unpair = ffi.new('union { float f[2]; uint64_t u; }')
local function pair_of(v) unpair.u = v; return {tonumber(unpair.f[0]), tonumber(unpair.f[1])} end
function fake.slot_widget(k) return SCREEN + 0x624b0 + k * 0x12a8 end
function fake.setup_slots()
    for k = 0, 3 do
        local w = fake.slot_widget(k)
        write_mem(w, le32(0x00100000))
        write_mem(w + 0xf8, le64(CTX + 2 * 0x3698))
        local child = SCREEN + 0x100000 + k * 0x400
        write_mem(child, le32(0x00300000)); write_mem(child + 0xe8, le64(0)); write_mem(child + 0xf0, le64(w))
        write_mem(w + 0xe0, le64(child))
    end
    write_mem(SCREEN + 8, le32(1))                        -- the screen's state: taking panel input
    write_mem(SCREEN + 0x595f0 + 0xd978, '\1')            -- the grid active
    write_mem(SCREEN + 0x595f0 + 0xd968, le32(0xffffffff)) -- nothing hovered
    write_mem(INPUT + 0xe1ad4, '\1')                      -- mouse mode
end
function fake.children(w)
    local out, node = {}, rd64(w + 0xe0)
    while node ~= 0 and #out < 64 do out[#out + 1] = node; node = rd64(node + 0xe8) end
    return out
end
function fake.confirm(on) write_mem(INPUT + 0x328 + 10 * 0x20, on and '\1' or '\0') end
fake.widgets, fake.opacity, fake.colour, fake.material, fake.rotation, fake.layer, fake.size = {}, {}, {}, {}, {}, {}, {}
fake.hit_asked = {}
fake.position, fake.anchor, fake.pivot, fake.destroyed, fake.pushes = {}, {}, {}, {}, 0
fake.natives[0x143eab0] = function(w)                    -- picture_init
    w = tonumber(w)
    local t = top()
    local slot = t >= 0 and read_mem(CTX + 0x2c5b8 + t, 1):byte() or 0
    write_mem(w, le32(0x00340000))
    write_mem(w + 0xe0, le64(0) .. le64(0) .. le64(0) .. le64(CTX + slot * 0x3698))
    fake.widgets[#fake.widgets + 1] = w
end
fake.natives[0x144f800] = function(w, id, x) fake.material[tonumber(w)] = bit.tohex(id) end
fake.natives[0x1447160] = function(w, v) fake.size[tonumber(w)] = pair_of(v) end
fake.natives[0x14476a0] = function(w, v) fake.position[tonumber(w)] = pair_of(v) end
fake.natives[0x144f160] = function(w, v) fake.anchor[tonumber(w)] = pair_of(v) end
fake.natives[0x144f0d0] = function(w, v) fake.pivot[tonumber(w)] = pair_of(v) end
fake.natives[0x1448690] = function(w, c) fake.colour[tonumber(w)] = {tonumber(c[0]), tonumber(c[1]), tonumber(c[2])} end
fake.natives[0x1448ad0] = function(w, v) fake.opacity[tonumber(w)] = tonumber(v) end
fake.natives[0x14491f0] = function(w, v) fake.layer[tonumber(w)] = tonumber(v) end
fake.natives[0x1448ef0] = function(w, v) fake.rotation[tonumber(w)] = tonumber(v) end
fake.natives[0x144c5c0] = function(parent, child)        -- attach: first in the parent's children
    parent, child = tonumber(parent), tonumber(child)
    write_mem(child + 0xe8, le64(rd64(parent + 0xe0)))
    write_mem(parent + 0xe0, le64(child))
    write_mem(child + 0xf0, le64(parent))
end
fake.natives[0x144dd70] = function(w)                    -- destroy
    w = tonumber(w)
    fake.destroyed[#fake.destroyed + 1] = w
    write_mem(w, le32(0))
end
fake.natives[0x12ef4b0] = function(base, slot)           -- ui_context_push
    fake.pushes = fake.pushes + 1
    local t = top() + 1
    write_mem(CTX + 0x2c5b8 + t, string.char(tonumber(slot)))
    write_mem(CTX + 0x2c5bc, le32(t % 4294967296))
end
fake.natives[0x12ef4d0] = function()                     -- ui_context_pop
    write_mem(CTX + 0x2c5bc, le32((top() - 1) % 4294967296))
end
fake.natives[0x178f970] = function(cursor, w, x)         -- the hit test: the cursor over a piece of slot hover_slot
    fake.hit_cursor = tonumber(cursor)
    fake.hit_asked[tonumber(w)] = true
    if fake.body_slot and tonumber(w) == fake.slot_widget(fake.body_slot) then return 1 end  -- the cursor on a slot
    local parent = rd64(tonumber(w) + 0xf0)
    if fake.hover_equip and parent == fake.equip_slot(fake.hover_equip) then return 1 end   -- a Leave Out button
    if fake.hover_parent and parent == fake.hover_parent then return 1 end                  -- a pin, the reroll button
    return (fake.hover_slot and parent == fake.slot_widget(fake.hover_slot)) and 1 or 0
end
local function rd16(a) local v = ffi.new('uint16_t[1]'); ffi.copy(v, read_mem(a, 2), 2); return tonumber(v[0]) end
fake.rd16 = rd16
fake.fades, fake.redraws = {}, {}
fake.natives[0x1450dd0] = function(w, out, seconds, alpha, delay)  -- widget_fade (here: at its end at once)
    w = tonumber(w)
    fake.fades[#fake.fades + 1] = string.format('%x %d %.2f %.2f %.2f', w, tonumber(out), tonumber(seconds),
                                                tonumber(alpha), tonumber(delay))
    fake.opacity[w] = tonumber(out) ~= 0 and 0 or tonumber(alpha)
    return tonumber(delay) + tonumber(seconds)
end
fake.natives[0x18932f0] = function(slot)                   -- the slot redraw
    slot = tonumber(slot)
    fake.redraws[slot] = (fake.redraws[slot] or 0) + 1
end
fake.natives[0x18936d0] = function(slot, on)               -- set-hover: on a change the sound (turning on), bit 0, redraw
    slot, on = tonumber(slot), tonumber(on)
    local flags = rd16(slot + 0x1288)
    if bit.band(flags, 1) ~= on then
        if on ~= 0 then fake.sounds[#fake.sounds + 1] = '0xdd84ae45' end
        write_mem(slot + 0x1288, ffi.string(ffi.new('uint16_t[1]', on ~= 0 and bit.bor(flags, 1) or bit.band(flags, 0xfffe)), 2))
        fake.natives[0x18932f0](slot)
    end
end
fake.natives[0x144d200] = function(w)                      -- mark dirty: header bit 2 up the parent chain
    w = tonumber(w)
    while w ~= 0 do
        local h = rd32(w)
        if bit.band(h, 4) ~= 0 then return end
        write_mem(w, le32(bit.bor(h, 4)))
        w = rd64(w + 0xf0)
    end
end
-- A Helldiver in a mission (weapons left behind): the game state, the local player's network id -> entity -> avatar
-- index (2) -> selection controller, the inventory row (index 1: primary 501, secondary 502, support 503, the
-- grenade count 4), the wielder's hand 0, the health manager. The game's functions: the selection request (applied at
-- once unless fake.switch_frames is set: the holster animation), the may-switch test (fake.can), the death test
-- (fake.dead), the count event, the inventory and selection messages, the entity lookup (fake.alive), destroy.
local GAME, OWNER, AVATARS, INV, WIELDER, HEALTH = 0x30000000, 0x31000000, 0x32000000, 0x33000000, 0x34000000, 0x35000000
local ENTITY, UNIT = 0x1234, 0x55
local CTRL = AVATARS + 0x53dcd0 + 2 * 0x1238
local ROWS, COUNTS = INV + 0x10000, INV + 0x20000
local ROW = ROWS + 1 * 0x30
local function map_block(key, value)                      -- 16 entries, multiplier 1, empty key 0xffffffff
    local t = {}
    for i = 0, 15 do t[#t + 1] = (i == key % 16) and (le32(key) .. le32(value)) or (le32(0xffffffff) .. le32(0)) end
    return table.concat(t)
end
local function map_header(data) return le64(data) .. le32(16) .. le32(0xffffffff) .. le32(1) end
fake.requests, fake.events, fake.messages, fake.destroyed_entities = {}, {}, {}, {}
fake.can, fake.dead, fake.alive = true, false, {[501] = true, [502] = true, [503] = true, [601] = true}
function fake.setup_helldiver(state)
    fake.patch(0x3326340, le64(GAME)); fake.heap(GAME + 0xac21c, le32(state or 4))
    write_mem(PLAYERS + 0x88, le32(1)); write_mem(PLAYERS + 0x3a8, le32(UNIT))
    fake.patch(0x346bf98, le64(OWNER))
    fake.heap(OWNER + 0xf22ec8, map_header(OWNER + 0x100000)); fake.heap(OWNER + 0x100000, map_block(UNIT, 3))
    fake.heap(OWNER + 0x1e65e4 * 8, string.rep('\0', 3 * 24) .. le32(ENTITY) .. string.rep('\0', 20))
    fake.patch(0x3326d20, le64(AVATARS))
    fake.heap(AVATARS + 0xf8, map_header(AVATARS + 0x100000)); fake.heap(AVATARS + 0x100000, map_block(ENTITY, 2))
    fake.heap(CTRL, le32(ENTITY) .. le32(1) .. le32(0) .. le32(1) .. le32(0) .. string.rep('\0', 12))
    fake.patch(0x3326738, le64(INV))
    fake.heap(INV, string.rep('\0', 0x28) .. map_header(INV + 0x30000) .. string.rep('\0', 4) .. le64(INV + 0x40000) .. string.rep('\0', 8) .. le64(ROWS)
                   .. le64(COUNTS) .. string.rep('\0', 0x20))
    fake.heap(INV + 0x30000, map_block(ENTITY, 1))
    fake.heap(INV + 0x40000, le64(0) .. le64(INV + 0x50000)); fake.heap(INV + 0x50000, le64(0) .. le32(ENTITY) .. le32(0) .. le32(0x77) .. string.rep('\0', 12))
    fake.heap(ROWS, string.rep('\0', 0x30) .. le32(501) .. le32(502) .. le32(503) .. le32(0) .. le32(0) .. le32(0)
                    .. le32(0) .. le32(1) .. le32(0) .. le32(0) .. le64(0xabcdef) .. string.rep('\0', 0x30))
    fake.heap(COUNTS, le64(0) .. le32(4) .. le32(0) .. le64(0))
    fake.patch(0x3326420, le64(WIELDER))
    fake.heap(WIELDER + 0x30, map_header(WIELDER + 0x100000) .. string.rep('\0', 4) .. le64(0) .. string.rep('\0', 0x10)
                              .. le64(WIELDER + 0x200000))
    fake.heap(WIELDER + 0x100000, map_block(ENTITY, 0)); fake.heap(WIELDER + 0x200000, le32(501) .. string.rep('\0', 0x200))
    fake.patch(0x3326688, le64(HEALTH)); fake.heap(HEALTH, string.rep('\0', 0x10))
end
function fake.row() return {rd32(ROW), rd32(ROW + 4), rd32(ROW + 8), rd32(ROW + 0x1c)} end
function fake.count() return rd32(COUNTS + 8) end
function fake.hand() return rd32(WIELDER + 0x200000) end
function fake.set_row(at, v) write_mem(ROW + at, le32(v)) end
function fake.set_count(v) write_mem(COUNTS + 8, le32(v)) end
function fake.set_state(v) write_mem(GAME + 0xac21c, le32(v)) end
function fake.set_entity(e) write_mem(OWNER + 0x1e65e4 * 8 + 3 * 24, le32(e)) end
function fake.select(slot)                                  -- the game's own apply: selection and hand 0
    write_mem(ROW + 0x1c, le32(slot))
    write_mem(WIELDER + 0x200000, le32(slot >= 1 and slot <= 3 and rd32(ROW + (slot - 1) * 4) or 0))
end
-- A reinforce: a new Helldiver (entity e) in the same avatar and row slots, with a fresh row (weapons a, b, c).
function fake.reinforce(e, a, b, c)
    fake.set_entity(e)
    write_mem(AVATARS + 0x100000, map_block(e, 2)); write_mem(INV + 0x30000, map_block(e, 1))
    write_mem(WIELDER + 0x100000, map_block(e, 0))
    write_mem(CTRL, le32(e) .. le32(1) .. le32(0) .. le32(1))
    write_mem(INV + 0x50000 + 8, le32(e))
    write_mem(ROW, le32(a) .. le32(b) .. le32(c) .. string.rep('\0', 16) .. le32(1))
    write_mem(WIELDER + 0x200000, le32(a)); write_mem(COUNTS + 8, le32(4))
    fake.alive[a], fake.alive[b], fake.alive[c] = true, true, true
end
fake.natives[0xa93e90] = function(ctrl, slot)              -- the selection request
    ctrl, slot = tonumber(ffi.cast('uint64_t', ctrl)), tonumber(slot)
    fake.requests[#fake.requests + 1] = slot
    if ctrl ~= CTRL then error('request on another controller') end
    write_mem(CTRL + 4, le32(slot))
    if slot >= 1 and slot <= 3 and rd32(ROW + (slot - 1) * 4) == 0 then return end  -- an empty slot: refused
    if fake.switch_frames then fake.pending = {slot = slot, frames = fake.switch_frames}
    elseif fake.hand_frames then
        write_mem(ROW + 0x1c, le32(slot))
        fake.pending = {slot = slot, frames = fake.hand_frames}
    else fake.select(slot) end
end
fake.natives[0xa92bc0] = function(ctrl)
    if tonumber(ffi.cast('uint64_t', ctrl)) ~= CTRL then error('may-switch on another controller') end
    return fake.can and 1 or 0
end
fake.natives[0x927050] = function(health, entity) return fake.dead and 1 or 0 end
fake.natives[0xfd97e0] = function(goid, event, at)
    fake.events[#fake.events + 1] = string.format('%x %x %d', tonumber(goid), tonumber(event), rd32(tonumber(at)))
end
fake.natives[0xbe3f40] = function(target, avatar, p, s, sup, bp, melee, throwable)
    fake.messages[#fake.messages + 1] = string.format('inventory %d %x %d %d %d %d %d %x', tonumber(target), tonumber(avatar),
        tonumber(p), tonumber(s), tonumber(sup), tonumber(bp), tonumber(melee), tonumber(throwable))
end
fake.natives[0xbeb660] = function(target, avatar, slot)
    fake.messages[#fake.messages + 1] = string.format('selection %d %x %d', tonumber(target), tonumber(avatar), tonumber(slot))
end
fake.natives[0xfd9d40] = function(entity) return fake.alive[tonumber(entity)] and 0x5000 or 0 end
fake.releases = {}
fake.natives[0x785d10] = function(_, avatar, entity, send)  -- the hand release: the hand holding entity, or -1
    entity = tonumber(entity)
    fake.releases[#fake.releases + 1] = string.format('%x %d %d', tonumber(avatar), entity, tonumber(send))
    if rd32(WIELDER + 0x200000) ~= entity then return 0xffffffff end
    write_mem(WIELDER + 0x200000, le32(0))
    return 0
end
fake.natives[0xfdc310] = function(owner, entity)
    fake.destroyed_entities[#fake.destroyed_entities + 1] = tonumber(entity); fake.alive[tonumber(entity)] = nil
end
-- The game's frame for the switch animation: a pending selection applies after its frames.
function fake.game_frame()
    if fake.pending then
        fake.pending.frames = fake.pending.frames - 1
        if fake.pending.frames <= 0 then fake.select(fake.pending.slot); fake.pending = nil end
    end
end
-- The game's hover pass for slot k (0x1893550 in mouse mode): skipped while the slot's header has bit 2 (then the
-- tree update clears it), else the hit test to set-hover.
function fake.game_hover(k)
    local w = fake.slot_widget(k)
    local h = rd32(w)
    if bit.band(h, 4) ~= 0 then write_mem(w, le32(bit.band(h, 0xfffffffb))); return 'skipped' end
    local on = (fake.body_slot == k or fake.hover_slot == k) and 1 or 0
    fake.natives[0x18936d0](w, on)
    return on
end
fake.natives[0x585b80] = function(action)                -- action_index: the confirm (high dword 10) is index 10
    fake.action = action
    return 10
end
-- The Leave Out buttons. The equipment view (SCREEN + 0x66f70; hovered +0x8310, active +0x831c), shown in the panel's
-- mode 1 (SCREEN + 0x6f290; transition byte +0x6f294); its weapon slots (view + 0x4118 / 0x5670 / 0x6bc8; flags u16
-- +0x1548, frame colour +0xbf8), each with one native child, in context slot 2. The slot redraw (0x1897300) draws
-- the frame white when the hover bit is set, else grey. Labels: init (0x143afa0), text (0x143bf90 / 0x143c950), font
-- (0x11f79b0, size 0x143c0b0), the layout (0x144e1a0: 9 units a character, 18 high), the child refresh (0x144c2c0).
local VIEW = SCREEN + 0x66f70
local EQUIP = {0x4118, 0x5670, 0x6bc8}
function fake.equip_slot(k) return VIEW + EQUIP[k] end
function fake.setup_equipment()
    for k = 1, 3 do
        local w = fake.equip_slot(k)
        write_mem(w, le32(0x00100000))
        write_mem(w + 0xf8, le64(CTX + 2 * 0x3698))
        local child = SCREEN + 0x110000 + k * 0x400
        write_mem(child, le32(0x00300000)); write_mem(child + 0xe8, le64(0)); write_mem(child + 0xf0, le64(w))
        write_mem(w + 0xe0, le64(child))
    end
    write_mem(SCREEN + 8, le32(1))
    write_mem(VIEW + 0x831c, '\1')
    write_mem(VIEW + 0x8310, le32(0xffffffff))              -- nothing hovered
    write_mem(INPUT + 0xe1ad4, '\1')
end
function fake.set_mode(m) write_mem(SCREEN + 0x6f290, le32(m)) end
function fake.set_transition(v) write_mem(SCREEN + 0x6f294, string.char(v)) end
function fake.frame_white(k) local c = ffi.new('float[1]'); ffi.copy(c, read_mem(fake.equip_slot(k) + 0xbf8, 4), 4); return tonumber(c[0]) == 1 end
fake.equip_redraws, fake.labels = {}, {}
fake.natives[0x1897300] = function(slot)
    slot = tonumber(slot)
    local flags = rd16(slot + 0x1548)
    fake.equip_redraws[#fake.equip_redraws + 1] = string.format('%x %d', slot, flags)
    local v = bit.band(flags, 1) ~= 0 and 1 or 0.4
    write_mem(slot + 0xbf8, f32(v) .. f32(v) .. f32(v))
end
-- The game's hover pass for equipment slot k (0x18980B0 in mouse mode): bit 0 from the hit test, on a change the
-- hover sound (turning on) and the redraw.
function fake.game_equip_hover(k, on)
    local w = fake.equip_slot(k)
    local flags = rd16(w + 0x1548)
    if bit.band(flags, 1) ~= (on and 1 or 0) then
        if on then fake.sounds[#fake.sounds + 1] = '0x56fa2864' end
        write_mem(w + 0x1548, ffi.string(ffi.new('uint16_t[1]', on and bit.bor(flags, 1) or bit.band(flags, 0xfffe)), 2))
        fake.natives[0x1897300](w)
    end
    write_mem(VIEW + 0x8310, le32(on and (k + 2) or 0xffffffff))
end
fake.natives[0x143afa0] = function(w)                    -- label_init
    w = tonumber(w)
    local t = top()
    local slot = t >= 0 and read_mem(CTX + 0x2c5b8 + t, 1):byte() or 0
    write_mem(w, le32(0x001c0000))
    write_mem(w + 0xe0, le64(0) .. le64(0) .. le64(0) .. le64(CTX + slot * 0x3698))
    fake.labels[w] = {}
    fake.widgets[#fake.widgets + 1] = w
end
fake.natives[0x143bf90] = function(w, id) fake.labels[tonumber(w)].id = bit.tohex(id) end
fake.natives[0x143c950] = function(w, key, s)
    local l = fake.labels[tonumber(w)]
    l.key, l.text = bit.tohex(key), ffi.string(s)
end
fake.natives[0x11f79b0] = function(w, font, variant, style, scale, force)
    fake.labels[tonumber(w)].font = string.format('%d %d %d %.1f %d', tonumber(font), tonumber(variant), tonumber(style),
                                                  tonumber(scale), tonumber(force))
end
fake.natives[0x143c0b0] = function(w, size) fake.labels[tonumber(w)].size = tonumber(size); write_mem(tonumber(w) + 0x27c, f32(size)) end
fake.natives[0x144e1a0] = function(w) write_mem(tonumber(w) + 0x0c, f32(#fake.labels[tonumber(w)].text * 9) .. f32(18)) end
fake.natives[0x144c2c0] = function(parent) fake.refreshed = (fake.refreshed or 0) + 1 end
-- Pinned stratagems and Randomize Lineup. The owned check (0x136fc20(offers, type)): fake.owned (default: the types
-- with an info). The slot setter (0x189d050(panel, slot, item id)): item 0x1000 + type, the widget's type set and
-- logged. The list's marker (0x18d1440(list, offer, byte)) and the details panel (0x18d7210(grid)).
fake.owned, fake.set_slots, fake.marks, fake.previews = nil, {}, {}, 0
fake.natives[0x136fc20] = function(offers, t)
    t = tonumber(t)
    fake.owned_asked = (fake.owned_asked or 0) + 1
    if fake.owned then return fake.owned[t] and 1 or 0 end
    return NAMES[t] and 1 or 0
end
fake.natives[0x189d050] = function(panel, slot, item)
    slot, item = tonumber(slot), tonumber(item)
    fake.set_slots[#fake.set_slots + 1] = string.format('%d %d', slot, item - 0x1000)
    write_mem(fake.slot_widget(slot) + 0x128c, le32(item - 0x1000))
end
fake.natives[0x18d1440] = function(list, offer, byte)
    offer, byte = tonumber(offer), tonumber(byte)
    fake.marks[#fake.marks + 1] = string.format('%x %d', offer, byte)
    fake.pin_marked = offer
    local n = rd32(SCREEN + 0xd2f20 + 0x92984)
    for i = 0, n - 1 do
        if rd32(SCREEN + 0xd2f20 + 0x92990 + i * 4) == offer then write_mem(SCREEN + 0xd2f20 + 0x92dc2 + i, string.char(byte)) end
    end
end
fake.natives[0x18d7210] = function(grid) fake.previews = fake.previews + 1 end
-- More stratagems: an info (hud_type +0xb8, info_flags +0x104) and an offer (the offers table's stratagem range grows;
-- the record's ban byte at offers + 0x1d99 + index * 0xb8).
local next_offer = 15
function fake.add_stratagem(t, name, hud, flags, banned)
    local info = INFO + t * 0x200
    NAMES[t] = name
    fake.patch(0x37cb600 + t * 8, le64(info))
    fake.heap(info, le32(t) .. le32(0x1000 + t) .. string.rep('\0', 8) .. le64(info + 0x110)
                    .. string.rep('\0', 0x110 - 0x18) .. name .. string.rep('\0', 64))
    write_mem(info + 0xb8, le32(hud)); write_mem(info + 0x104, le32(flags))
    local index = next_offer
    next_offer = next_offer + 1
    write_mem(OFFERS + 0xd1d48 + index * 4, le32(index))
    write_mem(OFFERS + 0xb9ce4 + index * 0x18, le32(index) .. le32(0xb000 + t) .. le32(0x1000 + t))
    write_mem(OFFERS + 0xd1d10, le32(next_offer))
    write_mem(OFFERS + 0x1d99 + index * 0xb8, string.char(banned and 1 or 0))
end
function fake.set_hud(t, hud) write_mem(INFO + t * 0x200 + 0xb8, le32(hud)) end
-- The stratagem list's groups, rows and cells: groups = the first position of each group; each group's rows of up
-- to 4. The layout (0x18d2b60) rebinds every page from the ids (page p shows row first + p): a page's cell count
-- (+0xb9b4) and each cell's offer (+0x2b5c); the page cache (+0x92718) is recorded. Cells are widgets in context
-- slot 2 with no children. The list grid's state words (SCREEN + 0xd2850 + 0x178c88 / +0x178c8c) and the pad flag
-- (input + 0xe1ad5).
fake.heap(SCREEN + 0x24b000, string.rep('\0', 0x1000))
function fake.cell(p, c) return LIST + 0xc10 + p * 0xaed0 + c * 0x2b68 end
function fake.ids()
    local n = rd32(LIST + 0x92984)
    local out = {}
    for i = 0, n - 1 do out[#out + 1] = rd32(LIST + 0x92990 + i * 4) - 0xb000 end
    return table.concat(out, ',')
end
function fake.bytes(at)
    local n = rd32(LIST + 0x92984)
    local s = read_mem(LIST + at, n)
    local out = {}
    for i = 1, #s do out[i] = tostring(s:byte(i)) end
    return table.concat(out, ',')
end
function fake.bind()
    local first = rd32(LIST + 0x928d8)
    local used = 0
    for p = 0, 11 do
        local row = fake.rows[first + p + 1]
        write_mem(LIST + 0xb9b4 + p * 0xaed0, le32(row and row[2] or 0))
        for c = 0, 3 do
            local offer = (row and c < row[2]) and rd32(LIST + 0x92990 + (row[1] + c) * 4) or 0
            write_mem(fake.cell(p, c) + 0x2b5c, le32(offer))
        end
        if row then used = p + 1 end
    end
    write_mem(LIST + 0x91f0c, le32(used))
end
local plain_layout = fake.natives[0x18d2b60]
fake.natives[0x18d2b60] = function(list)
    plain_layout(list)
    fake.cache_cleared = read_mem(LIST + 0x92718, 48) == string.rep('\255', 48)
    if fake.rows then fake.bind() end
end
function fake.set_pin_list(types, groups, sel, byte2)
    fake.set_list(types, sel)
    local b2 = ''
    for i = 1, #types do b2 = b2 .. string.char(byte2 and byte2[i] or 0) end
    write_mem(LIST + 0x92ec2, b2)
    write_mem(LIST + 0x92748, le32(#groups))
    local starts, rows = '', {}
    for g, first in ipairs(groups) do
        starts = starts .. le32(first)
        local last = groups[g + 1] or #types
        for r = first, last - 1, 4 do rows[#rows + 1] = {r, math.min(4, last - r)} end
    end
    write_mem(LIST + 0x927d0, starts)
    write_mem(LIST + 0x92718, string.rep('\0', 48))
    write_mem(LIST + 0x928d8, le32(0))
    write_mem(LIST + 0x928dc, le32(0xffffffff))
    write_mem(LIST + 0x92988, le32(0))
    fake.rows = rows
    fake.bind()
end
function fake.setup_cells()
    for p = 0, 11 do
        for c = 0, 3 do
            local w = fake.cell(p, c)
            write_mem(w, le32(0x00100000)); write_mem(w + 0xe0, le64(0)); write_mem(w + 0xf8, le64(CTX + 2 * 0x3698))
        end
    end
end
function fake.hover_cell(p, c)
    write_mem(LIST + 0x928dc, le32(p or 0xffffffff))
    if p then write_mem(LIST + 0xb9bc + p * 0xaed0, le32(c)) end
end
function fake.set_focus_offer(offer) write_mem(LIST + 0x92988, le32(offer)) end
function fake.set_grid_focus(k) write_mem(SCREEN + 0x595f0 + 0xd96c, le32(k)) end
function fake.set_mouse(on) write_mem(INPUT + 0xe1ad4, on and '\1' or '\0') end
function fake.set_pad(on) write_mem(INPUT + 0xe1ad5, on and '\1' or '\0'); write_mem(INPUT + 0xe1ad4, on and '\0' or '\1') end
-- The booster widget (slot grid + 0x8af8), in context slot 2.
function fake.booster() return SCREEN + 0x595f0 + 0x8af8 end
function fake.setup_booster()
    local w = fake.booster()
    write_mem(w, le32(0x00100000)); write_mem(w + 0xe0, le64(0)); write_mem(w + 0xf8, le64(CTX + 2 * 0x3698))
end
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


def retarget(sig, field, target):
    """Edits pointing every occurrence of a rip/call field of sig at target (an rva)."""
    rva, _, fields = SIG_ROWS[sig]
    _, starts, ends = fields[field]
    return [(rva + at, ((target - (rva + end)) % 2 ** 32).to_bytes(4, 'little')) for at, end in zip(starts, ends)]


def build(*edits):
    """A prepare function for new_game: the image with these (rva, bytes) edits."""
    def prepare(lua):
        f = lua.globals().fake
        for rva, data in edits:
            f.patch(rva, data)
    return prepare


def static(version):
    main_script = SOURCE[SOURCE.index('\nif rawget(_G,'):]
    for pattern in (r'//', r'\bgoto\b', r'&(?!&)', r'~(?!=)', r'<<', r'>>', r'math\.type', r'string\.pack'):
        check(not re.search(pattern, main_script.replace('-->', '')), f'no Lua 5.3+ construct {pattern!r}')
    check(SOURCE.startswith('-- HD2-Addon: mods/alomare/flexible_loadouts\n'), 'declaration line first')
    # A recon build may carry its test aids (the recon keys); a release (a whole-number version) none.
    leftovers = r'f10|snapshot|save_raw|DuplicateStratagems|StratagemsUnleashed' + (
        r'|recon|test key' if re.fullmatch(r'\d+', version) else '')
    check(not re.search(leftovers, main_script.replace(version, ''), re.I), 'no research leftovers or old names')
    in_script = re.findall(r"name = '(\w+)', rva = (0x[0-9a-f]+),(?: optional = true,)? text = '([^']+)'", main_script)
    wanted = [(n, v[0], v[1]) for n, v in SIG_ROWS.items()]
    check([(n, int(r, 16), t) for n, r, t in in_script] == wanted,
          'the entry carries the signatures research/signatures.py builds (%d)' % len(in_script))
    check(not sigspec.check(MOD / 'flexible_loadouts.lua', sigspec.build(signatures.SPECS)),
          'the script carries the current signature block and engine (tools/sigscan.lua)')
    check(not re.search(r'-- (?:BEGIN|END) PLUS|-- PLUS$|-- STANDARD', MAIN, re.M), 'one edition: no edition markers')
    # Nothing of the former Plus edition (copies, the vehicle rule lifted), in code or comments. (Vehicles, the
    # game's marker and its kind bits are now read by Randomize Lineup and the pins.)
    leftovers = sorted(set(re.findall(r"PLUS|Plus|[Cc]opies|vehicle rule|native\.\w*select"
                                      r"|'select'|LIST\.|more than once", main_script)))
    check(not leftovers, 'no Plus parts in the script: %r' % leftovers)
    check('if not (EXTRA.ready or EXTRA.advance or EXTRA.clear or EXTRA.weapons) then' in main_script,
          'with no feature available the mod reports NOT AVAILABLE')
    # The Windows functions under the mod's own names (another mod's declarations of the bare names, made first in
    # this harness with other types, would otherwise take over every call).
    check(not re.search(r"\b(GetCurrentProcess|GetModuleHandleA|ReadProcessMemory|WriteProcessMemory)\(", MAIN)
          and len(re.findall(r'__asm__\("', MAIN)) >= 4, "Windows functions under the mod's own names (flo_...)")

def extras(image, verdict):
    """The features both editions have. verdict: how the edition's OK status starts."""
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
    log = lambda: text(logs / 'FlexibleLoadouts.log')
    check(f.timer() == 0x3fe00000 and list(f.sounds.values()) == ['0x4d777731'] and 'Ready with 2 empty slot(s)' in log(),
          'refused ready: the timer starts at 1.75 s with the ready sound: 0x%x %r' % (f.timer(), list(f.sounds.values())))
    poses = lambda: list(f.poses.values())
    check(poses() == ['0x4242 0x97e150a4 0 0'], 'refused ready: the ready pose sent for the panel\'s unit: %r' % poses())
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
    check(poses()[1:] == ['0x4242 0x5d1d1963 0 0'], 'cancelled: the ready pose stopped: %r' % poses())
    f.set_flash(2, 0); f.frame_step(1)
    lua.execute('fake.write(%d, fake.le32(8))' % (0x23000000 + 0x3ac + 0x20))  # the other player is ready
    f.set_flash(3, 1); f.frame_step(1)
    check(f.timer() == 0x3fe00000 and list(f.sounds.values())[-1] == '0x7947920',
          'the last player to ready: the last ready sound: %r' % list(f.sounds.values()))
    f.set_flash(3, 0); f.set_timer(0xbf800000); f.set_list_open(True); f.frame_step(1)
    f.set_flash(3, 1); f.frame_step(2)
    check(f.timer() == 0xbf800000 and len(poses()) == 3, 'a flash while the list is open: nothing')
    f.set_list_open(False); f.set_flash(3, 0); f.frame_step(1)
    lua.execute("fake.write(%d, '\\0')" % (0x21000000 + 0x53a78 + 0x1ee0c))  # not the local panel
    f.set_flash(3, 1); f.frame_step(1)
    check(f.timer() == 0xbf800000, 'not the local panel: nothing')
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check('Ready with empty slots: on' in status and 'Ready press during a flash: on' in status
          and 'List kept open after a replacement: on' in status, 'status: the list extras on: %r' % status.splitlines()[-4:])

    # 15b. A Ready press while a flash still shows (the handler refused without flashing again): told by the game's
    #      press check, it toggles too, so readying and cancelling don't wait for the flash to end.
    lua.execute("fake.write(%d, '\\1')" % (0x21000000 + 0x53a78 + 0x1ee0c))  # the local panel again
    f.set_flash(3, 0); f.set_timer(0xbf800000); f.frame_step(2)
    f.set_flash(2, 1); f.set_flash(3, 1); f.frame_step(1)                   # refused: ready
    check(f.timer() == 0x3fe00000, 'refused with a flash starting: readying')
    f.frame_step(5)
    check(f.timer() == 0x3fe00000 and f.press_args == '0x28b0 0x29000000',
          'a flash showing, no press: nothing (the check asked on the READY prompt with the input object): %r' % f.press_args)
    n = len(f.sounds)
    f.ready_pressed = True; f.frame_step(1); f.ready_pressed = False         # pressed again during the flash
    check(f.timer() == 0xbf800000 and len(f.sounds) == n and 'Ready cancelled (2 empty slot(s))' in log()
          and poses()[-1] == '0x4242 0x5d1d1963 0 0', 'a press while the flash still shows: cancelled at once, pose stopped')
    f.frame_step(3)
    f.ready_pressed = True; f.frame_step(1); f.ready_pressed = False         # and again: ready
    check(f.timer() == 0x3fe00000 and list(f.sounds.values())[-1] == '0x7947920' and len(f.sounds) == n + 1
          and poses()[-1] == '0x4242 0x97e150a4 0 0',
          'pressed again during the flash: readying (the other player is ready: the last ready sound), pose sent')
    k = len(poses())
    f.frame_step(2)
    f.set_timer(0xbf800000); f.ready_pressed = True; f.frame_step(1); f.ready_pressed = False
    check(f.timer() == 0xbf800000, 'the timer went idle this frame (the handler toggled itself): no second toggle')
    f.frame_step(2)
    f.set_flash(2, 0); f.set_flash(3, 0); f.frame_step(1)
    f.ready_pressed = True; f.frame_step(1); f.ready_pressed = False
    check(f.timer() == 0xbf800000, 'a press with no flash showing (the handler accepted it): nothing')
    f.set_flash(2, 1); f.set_list_open(True); f.frame_step(1)
    f.ready_pressed = True; f.frame_step(1); f.ready_pressed = False
    check(f.timer() == 0xbf800000 and len(poses()) == k, 'a press while the list is open: nothing (no pose either)')
    f.set_list_open(False); f.set_unit(0xffffffff); f.frame_step(1)
    f.ready_pressed = True; f.frame_step(1); f.ready_pressed = False
    check(f.timer() == 0x3fe00000 and len(poses()) == k, 'no unit (-1): readying, no pose sent')

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
    check('Replaced slot 2: list opened on slot 3' in text(logs / 'FlexibleLoadouts.log'), 'logged')

    # 17. The Action key (Mod Bindings Menu, its old id kept): a press empties the hovered
    #     (with the mouse; an X counts) else the focused slot the Clear Stratagems way, with the remove sound; holding
    #     it does nothing more; with the list open, while ready or off the screen nothing.
    def clear_game(prepare=''):
        lua, logs = new_game(image, "ModBindingsMenu = {api = 1, version = 3, register_binding = function(id, label, slot, o) "
                                    "fake.bound = id .. '|' .. label() .. '|' .. o.category() .. '|' .. tostring(o.backend); return true end, "
                                    "is_down = function(id) return fake.clear_down == true end}")
        f = lua.globals().fake
        f.frame_step(1)
        f.setup_panel(lua.table(lua.table(77, False)))
        f.setup_slots()
        f.set_slot(0, 5); f.set_slot(1, 9); f.set_slot(2, 12); f.set_slot(3, 0)
        f.set_block(0, lua.table(5, 9, 12))
        lua.execute(prepare)
        f.open_screen(0)
        f.frame_step(12)
        return lua, logs, f

    def press(f, frames=1):
        f.clear_down = True; f.frame_step(frames); f.clear_down = False; f.frame_step(1)

    types = lambda f: [f.slot_type(k) for k in range(4)]
    log = lambda logs: text(logs / 'FlexibleLoadouts.log')
    lua, logs, f = clear_game('fake.write(SCREEN + 0x595f0 + 0xd96c, fake.le32(1))')   # slot 2 focused
    check(f.bound == 'alomare.flexible_stratagems.clear|Action|Flexible Loadouts|nil',
          'the key (its old id), no backend asked for: %r' % f.bound)
    press(f)
    check(types(f) == [5, 0, 12, 0] and f.block_types(0) == '5,12' and f.saved == '0x10'
          and list(f.sounds.values())[-1] == '0x96c8c848' and 'slot 2 emptied (key)' in log(logs),
          'a press, nothing hovered: the focused slot emptied, written and saved: %r' % types(f))
    lua.execute('fake.hover_slot = 2')
    f.frame_step(2)
    press(f)
    lua.execute('fake.hover_slot = nil')
    check(types(f) == [5, 0, 0, 0] and 'slot 3 emptied (key)' in log(logs), "with the mouse on slot 3's X: that slot")
    press(f)
    check(types(f) == [5, 0, 0, 0] and 'that stratagem slot is empty' in log(logs), 'the focused slot empty: nothing')
    lua, logs, f = clear_game("fake.write(0x29000000 + 0xe1ad4, '\\0'); fake.write(SCREEN + 0x595f0 + 0xd96c, fake.le32(2))")
    lua.execute('fake.write(SCREEN + 0x595f0 + 0xd968, fake.le32(0))')   # a hovered slot left: not used with a controller
    press(f)
    check(types(f) == [5, 9, 0, 0] and 'Key: mode 0, controller, group 0' in log(logs),
          'with a controller: the focused slot (the hovered one ignored)')
    lua, logs, f = clear_game()
    press(f, 60)
    check(types(f) == [0, 9, 12, 0] and 'Clear Stratagems:' not in log(logs),
          'held a second: only the focused slot at the press: %r' % types(f))
    lua, logs, f = clear_game()
    f.set_category(10)
    press(f, 60)
    check(types(f) == [5, 9, 12, 0] and not f.closed and 'Key: nothing (the list is not on the stratagems' in log(logs),
          'with the list open (not built on the stratagems), pressed or held: nothing')
    lua, logs, f = clear_game()
    f.set_timer(0x3fe00000)
    press(f, 60)
    check(types(f) == [5, 9, 12, 0] and not f.saved and 'Key: nothing (ready' in log(logs), 'not while ready')
    lua, logs, f = clear_game()
    f.close_screen(); f.frame_step(12)
    press(f, 40); f.frame_step(12)
    check(f.slot_type(0) == 5 and not f.saved, 'outside the loadout screen: nothing')

    # 18. Without the ready code only that extra is off; the picker and the other extra still work.
    lua, logs = new_game(image, build(broken('ready_slots')))
    f = lua.globals().fake
    f.frame_step(40)
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check(status.startswith(verdict) and 'Ready with empty slots: NOT AVAILABLE (code "ready_slots" not found)' in status
          and 'List kept open after a replacement: on' in status,
          'ready code missing: only that extra is off: %r' % status.splitlines()[-2:])
    lua, logs = new_game(image, build(broken('ready_press')))
    f = lua.globals().fake
    f.frame_step(40)
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check('Ready with empty slots: on' in status and 'Ready press during a flash: NOT AVAILABLE (code "ready_press" not found)'
          in status, 'press check missing: only the press during a flash is off: %r' % status.splitlines()[-5:])
    lua, logs = new_game(image, build((SIG_ROWS['ready_entry'][0] + SIG_ROWS['ready_entry'][2]['press_call'][1][0],
                                       (0x10).to_bytes(4, 'little'))))
    f = lua.globals().fake
    f.frame_step(40)
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check('Ready press during a flash: NOT AVAILABLE (the ready handler does not call the press check found)' in status,
          'the handler calling another press check: off: %r' % status.splitlines()[-5:])
    lua, logs = new_game(image, build(broken('emote_send')))
    f = lua.globals().fake
    f.frame_step(40)
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check('Ready press during a flash: on' in status
          and 'Ready pose with empty slots: NOT AVAILABLE (code "emote_send" not found)' in status,
          'emote sender missing: only the ready pose is off: %r' % status.splitlines()[-5:])
    lua, logs = new_game(image, build((SIG_ROWS['ready_emote'][0] + SIG_ROWS['ready_emote'][2]['emote'][1][0],
                                       (0x10).to_bytes(4, 'little'))))
    f = lua.globals().fake
    f.frame_step(40)
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check('Ready with empty slots: on' in status
          and 'Ready pose with empty slots: NOT AVAILABLE (code "ready_emote"' in status,
          'the toggle calling another emote sender: the pose is off: %r' % status.splitlines()[-5:])
    lua, logs = new_game(image, build((SIG_ROWS['equip_tail'][0] + SIG_ROWS['equip_tail'][2]['focus_call'][1][0],
                                       (0x10).to_bytes(4, 'little'))))
    f = lua.globals().fake
    f.frame_step(40)
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check('List kept open after a replacement: NOT AVAILABLE (the equip handler does not focus with the setter found)'
          in status, 'the equip handler calling another focus setter: that extra is off: %r' % status.splitlines()[-1:])


def core(image, version):
    """The core: the game's own loadout rules stay (no second copy, one vehicle of a kind)."""
    # S1. This build: OK, nothing asked of Mod Options Menu; idle outside the loadout screen.
    lua, logs = new_game(image, 'fake.install_menu()')
    f = lua.globals().fake
    f.frame_step(1)
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check(status.startswith('OK - active in the Hellpod loadout') and 'Flexible Loadouts %s\n' % version in status
          and "Game code found at this game version's addresses" in status and 'opies' not in status
          and 'Plus' not in status, 'status OK on this build: %r' % status.splitlines()[:3])
    check(f.base_updates == 1, 'update chained')
    rate = reads_per_frame(f, 120)
    check(rate <= 1 and not f.game_writes, 'outside the loadout screen: %.2f reads per frame, no writes' % rate)
    f.frame_step(30)
    check(not len(f.options), 'Mod Options Menu installed: nothing registered (the toggles are on the loadout)')
    check(lua.eval('FlexibleLoadouts.edition') is None and lua.eval('FlexibleLoadouts._test.settings') is None,
          'no edition name, no settings')

    # S2. The stratagem list open on a loadout with vehicles: the loadout's stratagems stay refused and the vehicles'
    #     kind bits stay, before and after a pick; nothing is written and no game function is called but the
    #     owned check (Randomize Lineup's count, read-only).
    lua, logs = new_game(image)
    f = lua.globals().fake
    f.frame_step(1)
    f.set_flags(12, 0x00200021)
    f.set_flags(9, 0x80100000)
    f.set_block(0, lua.table(5, 9, 12, 3))
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(0, 0, 0, 1, 0, 0))
    f.set_category(10)
    f.open_screen(0)
    f.frame_step(10)
    rate = reads_per_frame(f, 20)
    # List open: the screen (3), the list-open byte, the loadout block and the scroll; the clear buttons: the four slot
    # headers every 10 frames until the slots are alive; the pins (no mouse mode here: a controller): the list-open
    # byte, category, count, ids, first row, the input (2), the screen and list gates (7) and the focused stratagem,
    # and the cells every 10 frames.
    check(rate <= 22 and f.list_selectable() == '0,0,0,1,0,0' and f.flags(12) == 0x00200021 and f.flags(9) == 0x80100000,
          'list open: %.1f reads per frame, the loadout stays refused, the kind bits stay' % rate)
    f.set_block(0, lua.table(5, 20, 12, 3))
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(0, 1, 0, 0, 0, 0))
    f.frame_step(5)
    f.set_list(lua.table(), lua.table())
    f.set_category(3)
    f.frame_step(5)
    f.close_screen()
    f.frame_step(12)
    check(f.list_selectable() == '' and f.flags(12) == 0x00200021 and not f.game_writes and set(f.calls.values()) <= {'0x136fc20'},
          'after a pick, the list closed and the screen left: nothing written or called')

    # S3. Errors: five stop the mod.
    lua, logs = new_game(image)
    f = lua.globals().fake
    f.frame_step(1)
    f.open_screen(0)
    f.frame_step(10)
    f.fail_at = 0x21000000 + 0x273990   # the list-open byte
    f.frame_step(20)
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check(status.startswith('STOPPED - repeated errors') and 'boom' in text(logs / 'FlexibleLoadouts.log')
          and not f.game_writes, 'errors stop the mod after five: %r' % status.splitlines()[:1])
    before = f.base_updates
    f.frame_step(3)
    check(f.base_updates == before + 3, 'update still chained after stopping')

    # S4. Another build where code moved: the screen query is elsewhere and the screen slot is +0xb8 instead of +0xb0.
    #     The mod finds it by search and follows the new slot (a refused ready there is toggled).
    def moved_build(lua):
        f = lua.globals().fake
        rva, garbage = broken('screen')
        f.patch(rva, garbage)
        f.patch(FREE + 0x200, moved(image, 'screen', FREE + 0x200, {'slot': 0xb8}))
        lua.execute("fake.heap(STACK, string.rep('\\0', 0xb8) .. fake.le64(SCREEN) .. string.rep('\\0', 0x400 - 0xc0))")
    lua, logs = new_game(image, moved_build)
    f = lua.globals().fake
    frames = 0
    while not text(logs / 'FlexibleLoadouts_STATUS.log') and frames < 60:
        f.frame_step(1)
        frames += 1
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check(status.startswith('OK - active') and 'Game code found by search (1 moved: screen)' in status,
          'moved code found by search in %d frames: %r' % (frames, status.splitlines()[2:3]))
    f.setup_panel(lua.table(lua.table(77, False)))
    f.set_block(0, lua.table(5, 9))
    f.open_screen(0)
    f.frame_step(12)
    f.set_flash(2, 1)
    f.frame_step(1)
    check(f.timer() == 0x3fe00000, 'the loadout is served through the moved screen slot (a refused ready is toggled)')

    # S5. Builds the mod can't trust: nothing runs, the status says why.
    cases = (
        (build(broken('offers_count')), 'code "offers_count" not found'),
        (build(broken('category'), (FREE, moved(image, 'category', FREE)), (FREE + 0x100, moved(image, 'category', FREE + 0x100))),
         'code "category" found 2 times'),
        (build(broken('refresh_a'), (FREE, moved(image, 'refresh_a', FREE))), 'refresh_a outside the refresh'),
        (build((SIG_ROWS['refresh_a'][0] + SIG_ROWS['refresh_a'][2]['list_count'][1][1], (0x92988).to_bytes(4, 'little'))),
         'code "refresh_a" field "list_count" occurrences disagree'),
        # None of the features' code: nothing to do.
        (build(broken('ready_slots'), broken('open_list'), broken('set_slot'), broken('inv_rpc')),
         'code "ready_slots" not found'),
    )
    for prepare, why in cases:
        lua, logs = new_game(image, prepare)
        f = lua.globals().fake
        f.setup_panel(lua.table(lua.table(77, False)))
        f.set_block(0, lua.table(5, 9))
        f.open_screen(0)
        f.frame_step(40)
        f.set_flash(2, 1)
        f.frame_step(2)
        status = text(logs / 'FlexibleLoadouts_STATUS.log')
        check(status.startswith('NOT AVAILABLE - this game version is not supported (%s)' % why) and not f.game_writes
              and not len(f.calls) and f.timer() == 0xbf800000, 'another build (%s): nothing written or called: %r'
              % (why, status.splitlines()[:1]))

    # S6. Without the list opener only the list kept open is off; without both list-open signatures, Clear
    #     Stratagems is off too, so nothing is left (and nothing runs, without errors).
    lua, logs = new_game(image, build(broken('open_list')))
    f = lua.globals().fake
    f.frame_step(40)
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check(status.startswith('OK - active') and 'Ready with empty slots: on' in status
          and 'List kept open after a replacement: NOT AVAILABLE (code "open_list" not found)' in status
          and 'Action key: on' in status, 'the list opener missing: only the list kept open is off')
    f.setup_panel(lua.table(lua.table(77, False)))
    f.open_screen(0)
    f.frame_step(12)
    f.set_flash(2, 1)
    f.frame_step(1)
    check(f.timer() == 0x3fe00000, 'and a refused ready is still toggled')
    lua, logs = new_game(image, build(broken('ready_call'), broken('open_list')))
    f = lua.globals().fake
    f.frame_step(40)
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check(status.startswith('OK - active') and 'Action key: NOT AVAILABLE' in status
          and 'Ready with empty slots: NOT AVAILABLE (code "ready_call" not found)' in status
          and 'Clear buttons: NOT AVAILABLE' in status and 'destroys the kept weapons): on' in status,
          'no list-open flag: every loadout feature off, the weapon options on: %r' % status.splitlines()[:1])
    lua, logs = new_game(image, build(broken('ready_call'), broken('open_list'), broken('inv_rpc')))
    f = lua.globals().fake
    f.frame_step(40)
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check(status.startswith('NOT AVAILABLE - this game version is not supported (code "ready_call" not found)'),
          'no list-open flag and no weapon code: every feature off: %r' % status.splitlines()[:1])
    f.open_screen(0)
    f.frame_step(30)
    check(lua.eval('FlexibleLoadouts.errors') == 0 and not f.game_writes, 'and nothing runs, without errors')



def clear_buttons(image):
    """The clear buttons: a red X on each filled local slot, of the game's own widgets."""
    def screen_game(prepare=''):
        lua, logs = new_game(image, prepare)
        f = lua.globals().fake
        f.frame_step(1)
        f.setup_panel(lua.table(lua.table(77, False)))
        f.setup_slots()
        f.set_slot(0, 5); f.set_slot(1, 9); f.set_slot(2, 0); f.set_slot(3, 12)
        f.set_block(0, lua.table(5, 9, 12))
        return lua, logs, f

    def slots(lua):
        return lua.eval('FlexibleLoadouts._test.buttons.slots')

    def piece(lua, k, name):
        b = slots(lua)[k]
        return int(b.pieces[name]) if b is not None and b.pieces[name] is not None else None

    log = lambda logs: text(logs / 'FlexibleLoadouts.log')

    # C1. This build: the buttons are on.
    lua, logs, f = screen_game()
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check('Clear buttons: on' in status, 'status: the clear buttons on')

    # C2. The screen opens (local index set): one button per slot, each piece of the game's picture kind made in the
    #     slot's GUI context (the push and pop balanced), attached under the slot (first in its children), centred
    #     13 units in from the slot's top-right corner, upright; a plate of the game's fill under the game's cross.
    f.open_screen(0)
    f.frame_step(12)
    made = [k for k in range(4) if slots(lua)[k] is not None]
    check(made == [0, 1, 2, 3] and f.top() == -1 and f.pushes == 4, 'four buttons made, the context stack balanced: %r' % made)
    w1 = f.slot_widget(1)
    names = ('plate', 'mark')
    pieces = [piece(lua, 1, n) for n in names]
    check(all(p and f.rd64(p + 0xf0) == w1 and p in list(f.children(w1).values()) for p in pieces)
          and f.rd64(pieces[0] + 0xf8) == 0x2a000000 + 2 * 0x3698 and piece(lua, 1, 'bar_a') is None,
          "slot 2's pieces: under the slot, in its context, no bars")
    check(all(tuple(f.anchor[p].values()) == (1, 1) and tuple(f.pivot[p].values()) == (0.5, 0.5)
              and tuple(f.position[p].values()) == (-13, -13) and f.rotation[p] is None for p in pieces)
          and tuple(f.size[pieces[0]].values()) == (20, 20) and tuple(f.size[pieces[1]].values()) == (20, 20)
          and f.layer[pieces[0]] == 17 and f.layer[pieces[1]] == 18, 'placed at the corner, upright, the cross above')
    check(f.material[pieces[1]] == '4acbc968ba925d47' and f.material[pieces[0]] == 'e819a58401ff619f'
          and f.can_get == 'material content/ui/shared/misc/check_no_no_curve', "the cross is the game's check_no_no_curve")

    # C3. Shown on filled slots only: the game's red cross on a dark plate; hidden while the list is open, while
    #     readying, with the pad (not mouse mode), during the input delay and for another group. Each change of shown
    #     starts the game's own fade once per piece (in 0.2 s to its alpha, out 0.1 s); nothing per frame after.
    def opacity(k, name):
        p = piece(lua, k, name)
        return f.opacity[p] if p else None
    def fade(k, name, out, seconds, alpha):
        return '%x %d %.2f %.2f 0.00' % (piece(lua, k, name), out, seconds, alpha)
    check([opacity(k, 'mark') for k in range(4)] == [1, 1, 0, 1] and [opacity(k, 'plate') for k in range(4)]
          == [0.85, 0.85, 0, 0.85], 'shown on the filled slots, the cross on a plate: %r' % [opacity(k, 'mark') for k in range(4)])
    fades = list(f.fades.values())
    check(fade(0, 'plate', 0, 0.2, 0.85) in fades and fade(0, 'mark', 0, 0.2, 1) in fades and len(fades) == 6,
          "faded in with the game's fade (0.2 s): %r" % fades)
    check(tuple(round(c, 3) for c in f.colour[piece(lua, 0, 'mark')].values()) == (0.694, 0.078, 0)
          and tuple(round(c, 2) for c in f.colour[piece(lua, 0, 'plate')].values()) == (0.07, 0.07, 0.07),
          'tinted red, the plate dark')
    n = len(f.fades)
    f.frame_step(5)
    check(len(f.fades) == n, 'no fade started while nothing changes')
    f.set_list_open(True); f.frame_step(1)
    fades = list(f.fades.values())[n:]
    check(fade(0, 'plate', 1, 0.1, 0.85) in fades and fade(0, 'mark', 1, 0.1, 1) in fades and len(fades) == 6
          and opacity(0, 'mark') == 0, 'the list open: faded out (0.1 s): %r' % fades)
    f.set_list_open(False); f.frame_step(1)
    for setup, undo, what in (('fake.set_list_open(true)', 'fake.set_list_open(false)', 'the list open'),
                              ('fake.set_timer(0x3fe00000)', 'fake.set_timer(0xbf800000)', 'readying'),
                              ("fake.write(0x29000000 + 0xe1ad4, '\\0')", "fake.write(0x29000000 + 0xe1ad4, '\\1')", 'pad mode'),
                              ('fake.write(SCREEN + 0x27399c, fake.le32(0x40400000))',
                               'fake.write(SCREEN + 0x27399c, fake.le32(0))', 'the input delay'),
                              ('fake.write(SCREEN + 0x2739c8, fake.le32(1))', 'fake.write(SCREEN + 0x2739c8, fake.le32(0))',
                               'another group')):
        lua.execute(setup)
        f.frame_step(1)
        # (with a controller the focused slot's X stays in sight, for the Clear Stratagem key: slot 1 is focused)
        seen = [opacity(k, 'mark') for k in range(4)]
        hidden = seen == ([1, 0, 0, 0] if what == 'pad mode' else [0, 0, 0, 0])
        lua.execute(undo)
        f.frame_step(1)
        check(hidden and opacity(0, 'mark') == 1, '%s: hidden (but the focused one with a controller), then shown '
              'again: %r' % (what, seen))
    lua.execute("fake.write(0x29000000 + 0xe1ad4, '\\0'); fake.write(SCREEN + 0x595f0 + 0xd96c, fake.le32(3))")
    lua.execute('fake.hover_slot = 3; fake.write(SCREEN + 0x595f0 + 0xd968, fake.le32(3))')   # (the game's hover)
    f.frame_step(1)
    check([opacity(k, 'mark') for k in range(4)] == [0, 0, 0, 1] and f.rd32(0x21000000 + 0x595f0 + 0xd968) == 3,
          'with a controller: the focused slot 4 marked, its X not hovered (no block written)')
    lua.execute("fake.hover_slot = nil; fake.write(0x29000000 + 0xe1ad4, '\\1'); "
                "fake.write(SCREEN + 0x595f0 + 0xd96c, fake.le32(0))")
    f.frame_step(1)

    # C4. Hovering slot 2's X: the grid's hovered slot is written as none each frame, the X turns light red; no press,
    #     nothing emptied. Leaving it: no more writes.
    lua.execute('fake.hover_slot = 1')
    f.frame_step(1)
    hovered = f.rd32(0x21000000 + 0x595f0 + 0xd968)
    check(hovered == 0xffffffff and f.hit_cursor == 0x20000000 + 0x5f0 and f.slot_type(1) == 9
          and f.hit_asked[piece(lua, 1, 'plate')] and not f.hit_asked[piece(lua, 1, 'mark')]
          and tuple(round(c, 2) for c in f.colour[piece(lua, 1, 'mark')].values()) == (1, 0.36, 0.28)
          and tuple(round(c, 2) for c in f.colour[piece(lua, 1, 'plate')].values()) == (0.16, 0.16, 0.16),
          'X hovered: the hovered slot written as none (the cursor widget asked about the plate), the X lighter, '
          'nothing emptied')
    lua.execute('fake.write(SCREEN + 0x595f0 + 0xd968, fake.le32(1))')  # the game's hover update
    lua.execute('fake.hover_slot = nil')
    f.frame_step(2)
    check(f.rd32(0x21000000 + 0x595f0 + 0xd968) == 1 and 'X left' in log(logs), 'X left: the game\'s hover left alone')

    # C5. A click on the first hovered frame stays the game's (nothing emptied); a click on a hovered, blocked X
    #     empties that slot the Clear Stratagems way, with the remove sound; the next frame logs no list opening.
    sounds = len(f.sounds)
    lua.execute('fake.hover_slot = 3')
    f.confirm(True); f.frame_step(1); f.confirm(False)
    check(f.slot_type(3) == 12 and len(f.sounds) == sounds, 'a click on the first hovered frame: the game\'s (nothing emptied)')
    f.frame_step(1)
    f.confirm(True); f.frame_step(1); f.confirm(False)
    check(f.slot_type(3) == 0 and f.block_types(0) == '5,9' and f.slots_written == '0x53a78 -1' and f.saved == '0x10'
          and list(f.sounds.values())[-1] == '0x96c8c848' and 'slot 4 emptied (X clicked)' in log(logs),
          'a click on a blocked X: slot 4 emptied, written and saved, the remove sound (ui_generic_back)')
    n = len(f.fades)
    f.frame_step(2)
    check('no list after the click' in log(logs) and opacity(3, 'mark') == 0 and opacity(3, 'plate') == 0
          and len(f.fades) == n, "no list; the emptied slot's X hidden at once (no fade)")
    lua.execute('fake.hover_slot = nil')

    # C6. The recon build's test keys are gone: F7 and F8 change nothing.
    before = (opacity(0, 'mark'), opacity(0, 'plate'), len(f.sounds))
    f.press('f7'); f.press('f8'); f.frame_step(1)
    check((opacity(0, 'mark'), opacity(0, 'plate'), len(f.sounds)) == before and 'test key' not in log(logs),
          'F7 and F8: nothing')

    # C7. The game tears a piece down (header 0): found by the next full check (every 10 frames); this visit's other
    #     pieces are destroyed (no X twice on the slot) and the button made again. The game re-makes a slot (its
    #     children reset, ours no longer listed): our pieces are destroyed and the button made again.
    old = [piece(lua, 0, n) for n in names]
    lua.execute('fake.write(%d, fake.le32(0))' % old[0])
    f.frame_step(12)
    destroyed = sorted(int(v) for v in f.destroyed.values())
    check(piece(lua, 0, 'plate') not in old and destroyed == sorted(old[1:]),
          'a piece torn down: the other pieces destroyed, the button made again')
    n = len(f.destroyed)
    olds = [piece(lua, 2, name) for name in names]
    lua.execute('fake.write(%d, fake.le64(0))' % (f.slot_widget(2) + 0xe0))
    f.frame_step(12)
    destroyed = sorted(int(v) for v in list(f.destroyed.values())[n:])
    check(destroyed == sorted(olds) and piece(lua, 2, 'plate') not in olds, 'an orphan of this visit: destroyed, made again')

    # C8. Leaving and coming back to the same screen: buttons still in place are kept (none made); an orphan from the
    #     earlier visit is only forgotten (its context may be gone) and made again.
    made = int(lua.eval('FlexibleLoadouts._test.buttons.made'))
    f.close_screen(); f.frame_step(12)
    f.open_screen(0); f.frame_step(12)
    check(int(lua.eval('FlexibleLoadouts._test.buttons.made')) == made, 'the same screen again: the buttons kept')
    n = len(f.destroyed)
    f.close_screen(); f.frame_step(12)
    lua.execute('fake.write(%d, fake.le64(0))' % (f.slot_widget(1) + 0xe0))
    f.open_screen(0); f.frame_step(12)
    check(len(f.destroyed) == n and int(lua.eval('FlexibleLoadouts._test.buttons.made')) == made + 1
          and 'forgotten (an earlier visit)' in log(logs), 'an orphan from an earlier visit: forgotten, remade')

    # C9. Without the game's cross loaded: the bars on a plate.
    lua, logs, f = screen_game('fake.mark_loaded = false')
    f.open_screen(0)
    f.frame_step(22)
    w0 = f.slot_widget(0)
    bars = [piece(lua, 0, n) for n in ('bar_a', 'bar_b')]
    check(piece(lua, 0, 'mark') is None and opacity(0, 'plate') == 0.85 and opacity(0, 'bar_a') == 1
          and opacity(0, 'bar_b') == 1 and opacity(2, 'plate') == 0 and f.rotation[bars[0]] == 45
          and f.rotation[bars[1]] == -45 and all(f.material[p] == 'e819a58401ff619f' for p in bars)
          and all(p in list(f.children(w0).values()) for p in bars), 'the cross not loaded: bars (+-45) on a plate')

    # C10. Code the buttons can't trust: off, the other features on, no widget made.
    kinds = (
        (build(broken('widget_rotation_set')), 'code "widget_rotation_set" not found'),
        (build((SIG_ROWS['gui_fill_build'][0] + SIG_ROWS['gui_fill_build'][2]['call_attach'][1][0],
                (0x10).to_bytes(4, 'little'))), 'widget_attach at 144c5c0, but the game calls'),
        (build(broken('set_slot')), 'needs the Clear Stratagems code'),
    )
    for prepare, why in kinds:
        lua, logs = new_game(image, prepare)
        f = lua.globals().fake
        f.frame_step(40)
        f.setup_panel(lua.table(lua.table(77, False)))
        f.setup_slots()
        f.set_slot(0, 5)
        f.open_screen(0)
        f.frame_step(5)
        status = text(logs / 'FlexibleLoadouts_STATUS.log')
        check(status.startswith('OK - active') and 'Clear buttons: NOT AVAILABLE (%s'
              % why in status and not len(f.widgets) and 'Ready with empty slots: on' in status,
              'buttons off (%s), nothing made, the rest on: %r' % (why, status.splitlines()[-1:]))

    # C11. The slot under a hovered X looks unhovered. The cursor on slot 2's body: the game hovers it (its sound).
    #      Onto the X: the mod calls the game's set-hover(off) (no sound) and marks the slot dirty every frame, so the
    #      game's hover pass skips it (no sound again). Back onto the body: hovered again silently. Onto the X and off
    #      the slot: left unhovered, nothing written.
    lua, logs, f = screen_game()
    f.open_screen(0); f.frame_step(12)
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check('Clear buttons, the slot unhovered under its X: on' in status and 'Clear buttons, fades: on' in status,
          'status: the highlight and the fades on')
    w1 = f.slot_widget(1)
    lua.execute('fake.body_slot = 1')
    f.game_hover(1)
    sounds = len(f.sounds)
    check(f.rd16(w1 + 0x1288) & 1 == 1 and list(f.sounds.values())[-1] == '0xdd84ae45', 'the body: hovered by the game')
    redraws = f.redraws[w1] or 0
    lua.execute('fake.hover_slot = 1')
    f.frame_step(1)
    passes = []
    for _ in range(3):
        passes.append(f.game_hover(1))
        f.frame_step(1)
    check(f.rd16(w1 + 0x1288) & 1 == 0 and (f.redraws[w1] or 0) == redraws + 1 and passes == ['skipped'] * 3
          and len(f.sounds) == sounds and 'slot 2 unhovered under its X' in log(logs),
          'onto the X: unhovered once (redrawn), the hover pass skipped each frame, no sound: %r' % passes)
    # (each frame: the game's hover pass, then the mod's update)
    lua.execute('fake.hover_slot = nil')
    skipped = f.game_hover(1)
    f.frame_step(1)
    check(skipped == 'skipped' and f.rd16(w1 + 0x1288) & 1 == 1 and (f.redraws[w1] or 0) == redraws + 2
          and len(f.sounds) == sounds and f.game_hover(1) == 1 and len(f.sounds) == sounds
          and 'slot 2 hovered again (the X left)' in log(logs),
          'back onto the body: hovered again silently (redrawn), the game agrees without a sound')
    lua.execute('fake.hover_slot = 1')
    f.frame_step(1)
    f.game_hover(1)
    f.frame_step(1)
    lua.execute('fake.hover_slot = nil; fake.body_slot = nil')
    f.game_hover(1)
    f.frame_step(1)
    check(f.rd16(w1 + 0x1288) & 1 == 0 and 'slot 2 left unhovered (the cursor left it)' in log(logs)
          and f.game_hover(1) == 0 and len(f.sounds) == sounds, 'onto the X, then off the slot: left unhovered')

    # C12. Without the dirty mark the slot is left as the game draws it; without the fade code the X shows and hides
    #      at once; a fade whose tail calls another opacity setter is not used. The buttons stay on.
    for prepare, line, what in (
            (build(broken('widget_mark_dirty')),
             'the slot unhovered under its X: NOT AVAILABLE (code "widget_mark_dirty" not found)', 'no dirty mark'),
            (build((SIG_ROWS['widget_mark_dirty'][0] + SIG_ROWS['widget_mark_dirty'][2]['dirty_parent'][1][0],
                    (0xe8).to_bytes(4, 'little'))),
             'the slot unhovered under its X: NOT AVAILABLE ("dirty_parent" differs from "widget_parent")',
             'a dirty mark on another field'),
            (build(broken('widget_fade')), 'fades: NOT AVAILABLE (code "widget_fade" not found)', 'no fade'),
            # (the tail calls the setter twice: both calls retargeted to one other function)
            (build(*[(SIG_ROWS['widget_fade_tail'][0] + at, ((0x1448ad0 + 0x40 - (SIG_ROWS['widget_fade_tail'][0] + at + 4))
                                                           % 2 ** 32).to_bytes(4, 'little'))
                     for at in SIG_ROWS['widget_fade_tail'][2]['fade_opacity_set'][1]]),
             'fades: NOT AVAILABLE (the fade calls another opacity setter)', 'the fade calling another setter')):
        lua, logs, f = screen_game(prepare)
        f.frame_step(40)
        f.open_screen(0); f.frame_step(12)
        status = text(logs / 'FlexibleLoadouts_STATUS.log')
        w1 = f.slot_widget(1)
        lua.execute('fake.body_slot = 1; fake.hover_slot = 1')
        f.game_hover(1)
        f.frame_step(2)
        unhover = f.rd16(w1 + 0x1288) & 1 == 0
        ok = 'Clear buttons: on' in status and 'Clear buttons, ' + line in status
        if what in ('no dirty mark', 'a dirty mark on another field'):
            ok = ok and not unhover and len(f.fades) == 6
        else:
            ok = ok and unhover and not len(f.fades) and opacity(0, 'mark') == 1 and opacity(0, 'plate') == 0.85
        check(ok, '%s: that extra off, the buttons on: %r' % (what, [l for l in status.splitlines() if 'Clear' in l]))

def weapons_left(image):
    """Weapons left behind: the three Leave Out toggles (kept in FlexibleLoadouts.settings), applied to the local
    Helldiver in a mission."""
    PRIMARY, SECONDARY, GRENADES = 1, 2, 3
    KEYS = {PRIMARY: 'leave_primary', SECONDARY: 'leave_secondary', GRENADES: 'leave_grenades'}

    def mission(prepare='', state=4, options=(), before=''):
        lua, logs = new_game(image, prepare)
        f = lua.globals().fake
        lua.execute('fake.install_menu()')
        if options:   # the toggles as an earlier session left them (read at the start)
            (logs / 'FlexibleLoadouts.settings').write_text(
                ''.join('%s\t%d\n' % (KEYS[k], k in options) for k in KEYS), encoding='utf-8')
        f.setup_helldiver(state)
        lua.execute(before)
        f.frame_step(2)
        return lua, logs, f

    def set_leave(lua, k, on):
        lua.eval('FlexibleLoadouts._test.set_leave')(k, on)

    log = lambda logs: text(logs / 'FlexibleLoadouts.log')
    row = lambda f: list(f.row().values())
    msgs = lambda f: list(f.messages.values())

    # W1. This build: on; no settings yet: all kept, nothing registered in Mod Options Menu, nothing read or written in
    #     a mission.
    lua, logs, f = mission()
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check('Weapons left behind (recon build, test key F8 destroys the kept weapons): on' in status
          and 'Mod Options' not in status, 'status: weapons left behind on')
    check(not len(f.options) and 'Leave Out: no settings yet (primary kept, secondary kept, grenades kept)' in log(logs),
          'no settings yet: all kept, no Mod Options Menu option')
    rate = reads_per_frame(f, 120)
    check(rate <= 1 and not f.game_writes and row(f) == [501, 502, 503, 1] and not len(f.requests),
          'all kept: nothing written or asked in a mission, %.2f reads per frame (the loadout screen poll)' % rate)

    # W2. Primary left out (a toggle changed: saved at once), the primary in hand: the game's selection asked for the
    #     secondary; once it is in hand the primary slot is emptied (the weapon kept), then teammates get the game's
    #     inventory message (the primary empty) and the selection. Then settled: a check every 10 frames.
    set_leave(lua, PRIMARY, True)
    check(text(logs / 'FlexibleLoadouts.settings') == 'leave_primary\t1\nleave_secondary\t0\nleave_grenades\t0\npinned\t\n'
          and not (logs / 'FlexibleLoadouts.settings.tmp').exists()
          and not (logs / 'FlexibleLoadouts.settings.bak').exists()
          and 'Leave Out: primary left out (primary left out, secondary kept, grenades kept)' in log(logs),
          'a toggle changed: the settings written at once (no temp or backup left)')
    f.frame_step(1)
    check(list(f.requests.values()) == [2] and row(f) == [501, 502, 503, 2], 'primary left out: the secondary asked for')
    f.frame_step(1)
    check(row(f) == [0, 502, 503, 2] and msgs(f) == ['inventory -2 1234 0 502 503 0 0 abcdef', 'selection -2 1234 2']
          and 'primary left behind (501' in log(logs) and f.count() == 4,
          'then the primary slot emptied, teammates sent the row and the selection: %r' % msgs(f))
    reads = f.reads
    f.frame_step(20)
    check((f.reads - reads) / 20 <= 4 and len(f.messages) == 2 and len(f.requests) == 1,
          'settled: %.1f reads per frame, nothing sent again' % ((f.reads - reads) / 20))

    # W3. The game selects the empty slot itself (a ledge, an objective): the secondary asked for again.
    f.select(1)
    f.frame_step(11)
    check(list(f.requests.values())[-1] == 2 and row(f)[3] == 2, 'the empty primary selected by the game: back to the secondary')

    # W4. A primary picked up from the ground (a new entity in the slot): the player's to keep.
    f.set_row(0, 601)
    f.frame_step(11)
    check(row(f)[0] == 601 and 'a primary picked up (601): kept' in log(logs), 'a picked-up primary: kept')

    # W5. The settings last: a new session reads them (the primary left out from the start); kept again: saved.
    lua, logs, f = mission(options=(PRIMARY,))
    f.frame_step(2)
    check(row(f) == [0, 502, 503, 2] and 'Leave Out: primary left out, secondary kept, grenades kept' in log(logs),
          'the settings of an earlier session: the primary left out from the start')
    set_leave(lua, PRIMARY, False)
    check(text(logs / 'FlexibleLoadouts.settings') == 'leave_primary\t0\nleave_secondary\t0\nleave_grenades\t0\npinned\t\n'
          and not (logs / 'FlexibleLoadouts.settings.bak').exists(), 'kept again: the file replaced')
    lua, logs, f = mission(before="local b = io.open(CowboyBingusModLoader.log_directory .. '/FlexibleLoadouts.settings.bak', "
                                  "'wb'); b:write('leave_grenades\\t1\\n'); b:close()")
    check('Leave Out: primary kept, secondary kept, grenades left out' in log(logs),
          'only the backup there (a save cut short): read from it')

    # W6. Both weapons left behind: the support weapon in hand, both slots emptied.
    lua, logs, f = mission(options=(PRIMARY, SECONDARY))
    f.frame_step(12)
    check(row(f) == [0, 0, 503, 3] and msgs(f)[-2:] == ['inventory -2 1234 0 0 503 0 0 abcdef', 'selection -2 1234 3'],
          'both left behind: the support weapon in hand: %r %r' % (row(f), msgs(f)))
    lua, logs, f = mission(options=(PRIMARY, SECONDARY), before='fake.set_row(8, 0)')
    f.frame_step(12)
    check(row(f) == [0, 0, 0, 0] and list(f.requests.values())[0] == 0, 'no support weapon either: unarmed')

    # W7. Grenades left out: the count at 0 with the game's count event, again after a refill.
    lua, logs, f = mission(options=(GRENADES,))
    f.frame_step(1)
    check(f.count() == 0 and list(f.events.values()) == ['77 d92082f9 0'] and row(f) == [501, 502, 503, 1]
          and not len(f.messages), 'grenades: the count 0, the event posted, the weapons alone')
    f.set_count(2)
    f.frame_step(11)
    check(f.count() == 0 and len(f.events) == 2, 'a refill: back to 0')
    lua, logs, f = mission(options=(GRENADES,), before='fake.set_count(3); fake.set_row(0x1c, 4)')
    check(f.count() == 3 and list(f.requests.values())[-1] == 1, 'a grenade in hand: put back first (the primary asked)')

    # W8. The holster animation and the may-switch test: nothing emptied while the primary is still in hand, nothing
    #     asked or sent while switching is not allowed (the pod, a seat, ragdoll).
    lua, logs, f = mission('fake.switch_frames = 5', options=(PRIMARY,))
    f.frame_step(1)
    check(row(f)[0] == 501 and f.hand() == 501, 'switching: the primary kept while in hand')
    f.frame_step(5)
    check(row(f)[0] == 0 and f.hand() == 502, 'then emptied once the secondary is in hand')
    lua, logs, f = mission('fake.hand_frames = 4', options=(PRIMARY,))
    check(row(f) == [501, 502, 503, 2] and f.hand() == 501, 'the selection changed, the primary still in hand: kept')
    f.frame_step(4)
    check(row(f)[0] == 0 and f.hand() == 502, 'emptied once it is out of hand')
    lua, logs, f = mission('fake.can = false', options=(PRIMARY,))
    f.frame_step(12)
    check(not len(f.requests) and row(f)[0] == 501 and not len(f.messages), 'switching not allowed: nothing asked')
    f.can = True
    f.frame_step(3)
    check(row(f)[0] == 0 and len(f.messages) == 2, 'allowed again: done')

    # W9. A reinforce (a new Helldiver): handled again; the last one's kept weapon logged.
    f.reinforce(0x1236, 701, 702, 703)
    f.frame_step(13)
    check(row(f) == [0, 702, 703, 2] and 'Weapons: Helldiver 4662' in log(logs)
          and "that Helldiver's kept primary (501) still exists" in log(logs)
          and msgs(f)[-2:] == ['inventory -2 1236 0 702 703 0 0 abcdef', 'selection -2 1236 2'],
          'a reinforce: the new primary left behind: %r' % row(f))

    # W10. Dead, out of the mission, or a controller naming another entity: nothing asked, written or sent.
    for prepare, state, what in (('fake.dead = true', 4, 'dead'), ('', 3, 'on the ship'),
                                 ('', 4, 'another controller')):
        lua, logs, f = mission(prepare, state, options=(PRIMARY, GRENADES),
                               before='fake.write(0x32000000 + 0x53dcd0 + 2 * 0x1238, fake.le32(0x999))'
                               if what == 'another controller' else '')
        f.frame_step(12)
        check(row(f) == [501, 502, 503, 1] and f.count() == 4 and not len(f.requests) and not len(f.messages)
              and not f.game_writes, '%s: nothing done' % what)

    # W11. The recon build's test key F8: the kept weapon destroyed with the game's own destroy.
    lua, logs, f = mission(options=(PRIMARY,))
    f.frame_step(1)
    f.press('f8')
    check(list(f.destroyed_entities.values()) == [501] and row(f)[0] == 0, 'F8: the kept primary destroyed')

    # W12. Code the weapon options can't trust: off (no settings read), the rest on.
    tr_rva, _, tr_fields = SIG_ROWS['throw_return']
    hr_rva, _, hr_fields = SIG_ROWS['hand_release']
    for prepare, why in ((build(broken('inv_rpc')), 'code "inv_rpc" not found'),
                         (build(broken('throw_return')), 'code "throw_return" not found'),
                         (build((hr_rva + hr_fields['hr_hands'][1][0], b'\x06')), 'wielder hand layout'),
                         (build(*retarget('throw_return', 'tr_request', 0xa93430)), '"sr_request" differs from "tr_request"'),
                         (build((tr_rva + tr_fields['tr_last_weapon'][1][0], (0x53dcd0 + 0x80).to_bytes(4, 'little'))),
                          'selection controller layout'),
                         (build(*retarget('can_switch', 'cs_avatars', 0x3326738)),
                          '"la_avatars" differs from "cs_avatars"')):
        lua, logs = new_game(image, prepare)
        f = lua.globals().fake
        f.frame_step(40)
        status = text(logs / 'FlexibleLoadouts_STATUS.log')
        # (The settings are still read: they hold the pins too.)
        check(status.startswith('OK - active') and 'test key F8 destroys the kept weapons): NOT AVAILABLE (%s' % why in status
              and 'Clear buttons: on' in status
              and 'Leave Out buttons: NOT AVAILABLE (needs the weapon code' in status,
              'weapons off (%s), no settings read, the rest on: %r' % (why, status.splitlines()[-1:]))

    # W13. The way back after a throw (the controller's previous slot after a stratagem, its last weapon slot after the
    #      last grenade): one naming an empty weapon slot becomes the slot the mod switches to; one naming a weapon
    #      still there, or a grenade, stays. Only grenades left out: left alone.
    prev = lambda f: (f.rd32(0x32000000 + 0x53dcd0 + 2 * 0x1238 + 8), f.rd32(0x32000000 + 0x53dcd0 + 2 * 0x1238 + 12))
    set_prev = lambda lua, a, b: lua.execute('fake.write(%d, fake.le32(%d) .. fake.le32(%d))'
                                             % (0x32000000 + 0x53dcd0 + 2 * 0x1238 + 8, a, b))
    lua, logs, f = mission(options=(PRIMARY, SECONDARY), before='fake.set_row(8, 0)')
    f.frame_step(12)
    check(row(f) == [0, 0, 0, 0] and prev(f) == (0, 0)
          and "the controller's last weapon slot was the primary, empty: now unarmed" in log(logs),
          'unarmed: the last weapon slot (the primary, emptied) now unarmed: %r' % (prev(f),))
    set_prev(lua, 1, 2)                       # a stratagem asked for from the primary, then the secondary
    f.frame_step(11)
    check(prev(f) == (0, 0) and "the controller's previous slot was the primary, empty: now unarmed" in log(logs),
          'both named again: unarmed in both: %r' % (prev(f),))
    set_prev(lua, 4, 0)                       # a stratagem from a grenade in hand
    f.frame_step(11)
    check(prev(f) == (4, 0), 'a grenade named as the previous slot: kept (its count decides): %r' % (prev(f),))
    lua, logs, f = mission(options=(PRIMARY,))
    f.frame_step(12)
    set_prev(lua, 1, 1)
    f.frame_step(11)
    check(prev(f) == (2, 2), 'the primary left out: the empty primary named becomes the secondary: %r' % (prev(f),))
    set_prev(lua, 3, 2)
    f.frame_step(11)
    check(prev(f) == (3, 2), 'the support weapon and the secondary (still there): kept')
    lua, logs, f = mission(options=(PRIMARY, SECONDARY))
    f.frame_step(12)
    set_prev(lua, 2, 1)
    f.frame_step(11)
    check(prev(f) == (3, 3), 'both left out with a support weapon: the support weapon: %r' % (prev(f),))
    lua, logs, f = mission(options=(GRENADES,), before='fake.set_row(8, 0)')
    f.frame_step(2)
    set_prev(lua, 3, 3)
    f.frame_step(11)
    check(prev(f) == (3, 3), 'only grenades left out: left alone (the game handles a missing support weapon)')

    # W14. A weapon dropped with nothing to switch to (the game's drop: the slot emptied, unarmed selected, the
    #      weapon still in hand): released with the game's hand release after a few frames, then the fallback asked
    #      for when it is a weapon. Never while the row holds it, while dead entities or only grenades are left out.
    def drop_support(lua):
        lua.execute('fake.set_row(8, 0); fake.set_row(0x1c, 0)')
    releases = lambda f: list(f.releases.values())
    lua, logs, f = mission(options=(PRIMARY, SECONDARY))
    f.frame_step(12)
    check(row(f) == [0, 0, 503, 3] and f.hand() == 503 and not releases(f), 'the support weapon in hand: nothing released')
    asked = len(f.requests)
    drop_support(lua)
    f.frame_step(3)
    check(f.hand() == 503 and not releases(f), 'dropped: not released at once')
    f.frame_step(15)                          # seen at the next check (10 frames), then 5 frames in hand
    check(releases(f) == ['1234 503 0'] and f.hand() == 0 and len(f.requests) == asked
          and 'Weapons: 503 in hand, not in the row (selection 0): released (hand 0; now 0)' in log(logs),
          'then released (no send, as the drop does), nothing else asked: %r' % releases(f))
    f.frame_step(20)
    check(len(releases(f)) == 1, 'released once')
    lua, logs, f = mission(options=(PRIMARY,))
    f.frame_step(12)
    f.select(3)
    drop_support(lua)
    f.frame_step(20)
    check(releases(f) == ['1234 503 0'] and list(f.requests.values())[-1] == 2 and f.hand() == 502 and row(f)[3] == 2,
          'the secondary kept: released, then the secondary asked for: %r %r' % (releases(f), row(f)))
    lua, logs, f = mission(options=(PRIMARY, SECONDARY))
    f.frame_step(12)
    lua.execute('fake.alive[503] = nil')
    drop_support(lua)
    f.frame_step(20)
    check(not releases(f) and f.hand() == 503, 'an entity that no longer exists: left alone')
    lua, logs, f = mission(options=(GRENADES,))
    f.frame_step(2)
    f.select(3)
    drop_support(lua)
    f.frame_step(20)
    check(not releases(f), 'only grenades left out: left alone (the game switches to the primary)')

    # W15. The recon build's state trace: one line per change of the selection, the controller's slots, the hand,
    #      what is held and the switch test.
    lua, logs, f = mission(options=(PRIMARY,))
    f.frame_step(30)
    lines = [l for l in log(logs).splitlines() if 'Weapons: state ' in l]
    check(len(lines) >= 2 and 'selection 1, requested 1, previous 0, last weapon 1, hand 501, held 0, carried 0, '
          'switch allowed' in lines[0] and len(set(l.split('] ', 1)[1] for l in lines)) == len(lines),
          'the state trace: logged on change only: %r' % lines[:3])


def leave_out_buttons(image):
    """The Leave Out buttons: REMOVE and a check box on the local panel's weapon and grenade slots (the equipment view)."""
    def screen_game(prepare=''):
        lua, logs = new_game(image, prepare)
        f = lua.globals().fake
        f.frame_step(1)
        f.setup_panel(lua.table(lua.table(77, False)))
        f.setup_slots()
        f.setup_equipment()
        f.set_slot(0, 5)
        f.set_block(0, lua.table(5))
        return lua, logs, f

    def toggle(lua, k):
        return lua.eval('FlexibleLoadouts._test.toggles.slots')[k]

    def piece(lua, k, name):
        t = toggle(lua, k)
        return int(t.pieces[name]) if t is not None else None

    log = lambda logs: text(logs / 'FlexibleLoadouts.log')
    leave = lambda lua: [bool(lua.eval('FlexibleLoadouts._test.leave')[k]) for k in (1, 2, 3)]

    # L1. This build: on. The stratagems shown (mode 0): no button made; the X's shown.
    lua, logs, f = screen_game()
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check('Leave Out buttons: on' in status, 'status: the Leave Out buttons on')
    f.open_screen(0)
    f.frame_step(12)
    check(all(toggle(lua, k) is None for k in (1, 2, 3)) and lua.eval('FlexibleLoadouts._test.buttons.slots')[0] is not None,
          'the stratagems shown: no Leave Out button, the X made')

    # L2. The equipment view (mode 1) while it changes (transition byte set): nothing made, the X's hidden. Settled:
    #     a button per weapon slot, in the slot's GUI context (the stack balanced), under the slot: a plate of the
    #     game's fill, the game's cross, the REMOVE label made as the game makes its titles (the #COUNT text with the
    #     mod's upper-cased string, font 4, size 14.4), the plate fitted to the label's measured width, centred on the
    #     slot's top edge, the box and the label placed on it.
    f.set_mode(1); f.set_transition(1)
    f.frame_step(12)
    x_mark = int(lua.eval('FlexibleLoadouts._test.buttons.slots')[0].pieces.mark)
    check(all(toggle(lua, k) is None for k in (1, 2, 3)) and f.opacity[x_mark] == 0,
          'the view changing: no button made; the X hidden (grid mode)')
    f.set_transition(0)
    f.frame_step(12)
    check(all(toggle(lua, k) is not None for k in (1, 2, 3)) and f.top() == -1, 'three buttons made, the stack balanced')
    w1 = f.equip_slot(1)
    plate, box, label = (piece(lua, 1, n) for n in ('plate', 'box', 'label'))
    children = list(f.children(w1).values())
    check(all(p in children and f.rd64(p + 0xf0) == w1 and f.rd64(p + 0xf8) == 0x2a000000 + 2 * 0x3698
              for p in (plate, box, label)), "the primary's pieces: under the slot, in its context")
    lab = f.labels[label]
    rounded = lambda v: tuple(round(c, 2) for c in v.values())
    check(lab.id == 'c67c7faf' and lab.key == 'ab2a7b35' and lab.text == 'REMOVE' and lab.font == '4 0 0 1.0 0'
          and round(lab.size, 2) == 14.4 and tuple(f.pivot[label].values()) == (1, 0.5) and f.refreshed,
          'the label: the #COUNT text "REMOVE", font 4 size 14.4, right-aligned: %r' % dict(lab))
    check(f.material[plate] == 'e819a58401ff619f' and f.material[box] == '4acbc968ba925d47'
          and rounded(f.size[plate]) == (81, 19.8) and all(rounded(f.anchor[p]) == (0.5, 1) for p in (plate, box, label))
          and rounded(f.pivot[plate]) == (0.5, 1) and rounded(f.position[plate]) == (0, -3.6)
          and rounded(f.size[box]) == (16.2, 16.2) and rounded(f.position[box]) == (30.6, -13.5)
          and rounded(f.position[label]) == (19.8, -13.5)
          and f.layer[plate] == 17 and f.layer[box] == 18 and f.layer[label] == 18,
          'the plate fitted to the label (6.3 + 54 + 2.7 + 16.2 + 1.8 = 81 x 19.8) on the top centre, the box at its '
          'right end, the label left of it: %r %r %r' % (rounded(f.size[plate]), rounded(f.position[box]),
                                                        rounded(f.position[label])))

    # L3. Shown (the game's fade in), unchecked: the cross grey, the label grey; the X's stay hidden.
    check(f.opacity[plate] == 0.85 and f.opacity[box] == 1 and f.opacity[label] == 1
          and tuple(round(c, 2) for c in f.colour[box].values()) == (0.55, 0.55, 0.55)
          and tuple(round(c, 3) for c in f.colour[label].values()) == (0.694, 0.694, 0.694),
          'shown: the cross grey, the label grey')

    # L4. The cursor on the primary's body (the game hovers it, white), then onto its button: the view's hovered slot
    #     written as none, the hover sound of the game's check boxes, the label white, the slot redrawn unhovered (the
    #     hover bit cleared for the redraw, then set back: no sound from the slot). The game keeps the bit set; a white
    #     redraw of its own is undone again.
    f.game_equip_hover(1, True)
    check(f.frame_white(1), 'the body: white')
    lua.execute('fake.hover_equip = 1')
    sounds = len(f.sounds)
    f.game_equip_hover(1, True)
    f.frame_step(1)
    redraws = list(f.equip_redraws.values())
    check(f.rd32(0x21000000 + 0x66f70 + 0x8310) == 0xffffffff and list(f.sounds.values())[sounds:] == ['0x65e34ad8']
          and not f.frame_white(1) and f.rd16(w1 + 0x1548) & 1 == 1 and redraws[-1] == '%x 0' % w1
          and tuple(f.colour[label].values()) == (1, 1, 1), 'onto the button: unhovered by the redraw, the label white')
    f.natives[0x1897300](w1)    # the game redraws it white (a focus change)
    f.game_equip_hover(1, True)
    f.frame_step(1)
    check(not f.frame_white(1), 'a white redraw of the game: undone again')

    # L5. A click on the first hovered frame stays the game's; on a blocked button it toggles: the primary left out
    #     (saved), the game's check in the X's red, the toggle sound; no list.
    lua.execute('fake.hover_equip = nil')
    f.game_equip_hover(1, True)
    f.frame_step(1)
    check(f.frame_white(1) and 'Leave Out buttons: left' in log(logs), 'off the button onto the body: white again')
    lua.execute('fake.hover_equip = 2')
    f.game_equip_hover(2, True)
    f.confirm(True); f.frame_step(1); f.confirm(False)
    check(leave(lua) == [False, False, False], "a click on the first hovered frame: the game's (nothing toggled)")
    f.game_equip_hover(2, True)
    f.frame_step(1)
    sounds = len(f.sounds)
    f.game_equip_hover(2, True)
    f.confirm(True); f.frame_step(1); f.confirm(False)
    box2 = piece(lua, 2, 'box')
    check(leave(lua) == [False, True, False] and list(f.sounds.values())[sounds:] == ['0x468c8e58']
          and text(logs / 'FlexibleLoadouts.settings') == 'leave_primary\t0\nleave_secondary\t1\nleave_grenades\t0\npinned\t\n',
          'a click on a blocked button: the secondary left out (saved), the toggle sound')
    f.game_equip_hover(2, True)
    f.frame_step(1)
    check('no list after the click' in log(logs) and f.opened is None and f.material[box2] == '57a71f86fac394aa'
          and tuple(round(c, 3) for c in f.colour[box2].values()) == (0.694, 0.078, 0),
          'no list after the click; the next frame the check, red')
    f.game_equip_hover(2, True)
    f.confirm(True); f.frame_step(1); f.confirm(False)
    f.game_equip_hover(2, True)
    f.frame_step(1)
    check(leave(lua) == [False, False, False] and f.material[box2] == '4acbc968ba925d47',
          'clicked again: kept, the cross back')
    f.game_equip_hover(2, True)
    f.confirm(True); f.frame_step(1); f.confirm(False)
    lua.execute('fake.hover_equip = nil')
    f.game_equip_hover(2, False)
    f.frame_step(1)

    # L6. No click taken (a controller, readying): the unchecked buttons hidden, the checked one (the secondary) still
    #     in sight; the stratagems shown again: all hidden.
    for setup, undo, what in (("fake.write(0x29000000 + 0xe1ad4, '\\0')", "fake.write(0x29000000 + 0xe1ad4, '\\1')",
                               'a controller'),
                              ('fake.set_timer(0x3fe00000)', 'fake.set_timer(0xbf800000)', 'readying')):
        lua.execute(setup)
        f.frame_step(1)
        seen = [f.opacity[piece(lua, k, 'box')] for k in (1, 2, 3)]
        lua.execute(undo)
        f.frame_step(1)
        check(seen == [0, 1, 0] and f.opacity[piece(lua, 1, 'box')] == 1, '%s: only the checked button in sight: %r'
              % (what, seen))
    lua.execute("fake.write(0x29000000 + 0xe1ad4, '\\0'); fake.write(0x21000000 + 0x66f70 + 0x8314, fake.le32(3))")
    f.frame_step(1)
    seen = [f.opacity[piece(lua, k, 'box')] for k in (1, 2, 3)]
    lua.execute("fake.write(0x29000000 + 0xe1ad4, '\\1'); fake.write(0x21000000 + 0x66f70 + 0x8314, fake.le32(0))")
    f.frame_step(1)
    check(seen == [1, 1, 0], 'a controller on the primary: its button marked too (with the checked one): %r' % seen)
    f.set_mode(0)
    f.frame_step(1)
    check([f.opacity[piece(lua, k, 'box')] for k in (1, 2, 3)] == [0, 0, 0] and f.opacity[x_mark] == 1,
          'the stratagems shown again: the buttons hidden, the X back')

    # L7. A piece torn down: the button made again (the other pieces destroyed); the screen left and back: kept.
    f.set_mode(1)
    f.frame_step(2)
    old = [piece(lua, 3, n) for n in ('plate', 'box', 'label')]
    lua.execute('fake.write(%d, fake.le32(0))' % old[2])
    f.frame_step(12)
    check(piece(lua, 3, 'label') not in old and sorted(int(v) for v in f.destroyed.values())[-2:] == sorted(old[:2]),
          'a label torn down: the button destroyed and made again')
    made = int(lua.eval('FlexibleLoadouts._test.toggles.made'))
    f.close_screen(); f.frame_step(12)
    f.open_screen(0); f.frame_step(12)
    check(int(lua.eval('FlexibleLoadouts._test.toggles.made')) == made, 'the same screen again: the buttons kept')

    # L8. Without the game's check loaded: a square of the fill (grey, red when checked).
    lua, logs, f = screen_game('fake.mark_loaded = false')
    f.open_screen(0); f.set_mode(1); f.frame_step(12)
    b = piece(lua, 1, 'box')
    check(f.material[b] == 'e819a58401ff619f' and tuple(round(v, 2) for v in f.size[b].values()) == (9.72, 9.72)
          and tuple(round(c, 2) for c in f.colour[b].values()) == (0.55, 0.55, 0.55),
          'the marks not loaded: a grey square box')

    # L9. The Action key in the equipment view: the hovered (mouse) else focused weapon
    #     slot's toggle flips, with the toggle sound; on an armour slot nothing; held, flipped once.
    stub = ("ModBindingsMenu = {api = 1, version = 3, register_binding = function() return true end, "
            "is_down = function(id) return fake.clear_down == true end}")
    lua, logs, f = screen_game(stub)
    f.open_screen(0); f.set_mode(1); f.frame_step(12)

    def press(frames=1):
        f.clear_down = True; f.frame_step(frames); f.clear_down = False; f.frame_step(1)
    lua.execute('fake.write(0x21000000 + 0x66f70 + 0x8314, fake.le32(4))')   # the secondary focused
    press()
    check(leave(lua) == [False, True, False] and list(f.sounds.values())[-1] == '0x468c8e58',
          'a press, nothing hovered: the focused secondary left out')
    lua.execute('fake.hover_equip = 1')
    f.game_equip_hover(1, True); f.frame_step(1)
    f.game_equip_hover(1, True)
    press()
    check(leave(lua) == [True, True, False], 'with the mouse on the primary: the primary')
    lua.execute('fake.hover_equip = nil; fake.write(0x21000000 + 0x66f70 + 0x8314, fake.le32(0))')
    f.game_equip_hover(1, False); f.frame_step(1)
    press()
    check(leave(lua) == [True, True, False] and 'Key: nothing to do there' in log(logs), 'an armour slot: nothing')
    lua.execute('fake.write(0x21000000 + 0x66f70 + 0x8314, fake.le32(5))')
    press(40)
    check(leave(lua) == [True, True, True] and f.slot_type(0) == 5, 'held on the grenades: flipped once, the stratagems '
          'left alone')

    # L10. Code the buttons can't trust: off, the X's and the weapon options on, no button made.
    for prepare, why in ((build(broken('label_init')), 'code "label_init" not found'),
                         (build(broken('view_click')), 'code "view_click" not found'),
                         (build(*retarget('view_hover', 'view_slot_redraw', 0x18932f0)),
                          'the view hover calls another slot redraw'),
                         (build(*retarget('label_title', 'call_font_set', 0x143c0b0)),
                          'the title build calls font_set at')):
        lua, logs, f = screen_game(prepare)
        f.frame_step(40)
        f.open_screen(0); f.set_mode(1); f.frame_step(12)
        status = text(logs / 'FlexibleLoadouts_STATUS.log')
        check('Leave Out buttons: NOT AVAILABLE (%s' % why in status and 'Clear buttons: on' in status
              and 'destroys the kept weapons): on' in status and toggle(lua, 1) is None,
              'buttons off (%s), the rest on: %r' % (why, [l for l in status.splitlines() if 'Leave' in l]))


BINDING_MENU = ("ModBindingsMenu = {api = 1, version = 3, register_binding = function(id, label, slot, o) "
                "fake.bound = id .. '|' .. label() .. '|' .. o.category() .. '|' .. tostring(o.backend); return true end, "
                "is_down = function(id) return fake.clear_down == true end}")


def pins(image):
    """Pinned stratagems: a pin on the hovered or focused stratagem of the list; pinned ones first in their group."""
    def list_game(prepare=BINDING_MENU, settings=None):
        def setup(lua):
            lua.execute(prepare)
            if settings is not None:
                lua.execute("local f = io.open(CowboyBingusModLoader.log_directory .. '/FlexibleLoadouts.settings', 'wb'); "
                            "f:write(%r); f:close()" % settings)
            f = lua.globals().fake
            f.add_stratagem(31, 'ORBITAL. LASER', 0, 0)
            f.add_stratagem(40, 'SENTRY. GATLING', 3, 0)
            f.add_stratagem(41, 'MINES. ANTI-PERSONNEL', 3, 0)
        lua, logs = new_game(image, setup)
        f = lua.globals().fake
        f.frame_step(1)
        f.setup_panel(lua.table(lua.table(77, False)))
        f.setup_slots()
        f.setup_cells()
        f.set_slot(0, 5); f.set_slot(1, 0); f.set_slot(2, 0); f.set_slot(3, 0)
        f.set_block(0, lua.table(5))
        f.open_screen(0)
        f.frame_step(12)
        return lua, logs, f

    # The list: red 5, 9, 31 (5 equipped), blue 12, 20, green 40, 41; rows of the groups: (5 9 31) (12 20) (40 41).
    def open_list(f, lua):
        f.set_category(10)
        f.set_pin_list(lua.table(5, 9, 31, 12, 20, 40, 41), lua.table(0, 3, 5), lua.table(0, 1, 1, 1, 1, 1, 1),
                       lua.table(0, 0, 0, 0, 1, 0, 0))

    def pin(lua, p, c, name='plate'):
        r = lua.eval('FlexibleLoadouts._test.pins.cells')[lua.globals().fake.cell(p, c)]
        return int(r.pieces[name]) if r is not None else None

    log = lambda logs: text(logs / 'FlexibleLoadouts.log')
    settings = lambda logs: text(logs / 'FlexibleLoadouts.settings')

    # P1. This build: on; no settings: nothing pinned.
    lua, logs, f = list_game()
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check('Pinned stratagems: on' in status and 'Randomize Lineup: on' in status,
          'status: the pins and the randomizer on: %r' % [l for l in status.split('\n') if 'Pinned' in l or 'Randomize' in l])

    # P2. The list opens with nothing pinned: logged with its groups, nothing written, no pin made (nothing hovered).
    f.game_writes, f.laid_out = 0, 0
    open_list(f, lua)
    f.frame_step(3)
    check(f.ids() == '5,9,31,12,20,40,41' and not f.game_writes and f.laid_out == 0 and pin(lua, 1, 1) is None
          and 'Pins: list of 7 in 3 group(s) (0-2, 3-4, 5-6); 0 pinned' in log(logs),
          'list open, nothing pinned: left as built, nothing written: %r %r %r' % (f.ids(), f.game_writes, f.laid_out))

    # P3. A stratagem hovered (row 2, its 2nd cell: 20): a pin made in the cell's context, at its top-right corner like
    #     the X, the game's waypoint in grey on the dark plate.
    f.hover_cell(1, 1)
    f.frame_step(1)
    plate, mark = pin(lua, 1, 1), pin(lua, 1, 1, 'mark')
    cell = f.cell(1, 1)
    check(plate and f.rd64(plate + 0xf0) == cell and f.rd64(mark + 0xf8) == 0x2a000000 + 2 * 0x3698
          and tuple(f.anchor[plate].values()) == (1, 1) and tuple(f.position[plate].values()) == (-13, -13)
          and f.material[mark] == 'ea6c3908c95dd015' and f.opacity[plate] == 0.85 and abs(f.colour[mark][1] - 0.55) < 1e-6
          and 'content/ui/mission/hud/map/waypoint is loaded' in log(logs),
          'hovered: a grey pin on its cell (the game waypoint): %r' % [plate and f.rd64(plate + 0xf0) == cell, mark and f.rd64(mark + 0xf8), plate and tuple(f.anchor[plate].values()), plate and tuple(f.position[plate].values()), mark and f.material[mark], plate and f.opacity[plate], mark and f.colour[mark] and tuple(f.colour[mark].values())])
    check(pin(lua, 0, 0) is None, 'not hovered, not pinned: no pin')

    # P4. The pin hovered: its cell's selectable byte 0 each frame (the game refuses a click there); a click on the
    #     first hovered frame does nothing; on a blocked pin it pins 20: saved, the toggle sound, 20 first of the blue
    #     group (its bytes with it), the page cache cleared, the game's layout, the byte put back by the marker.
    f.hover_parent = cell
    f.confirm(True); f.frame_step(1); f.confirm(False)
    check(f.bytes(0x92dc2) == '0,1,1,1,0,1,1' and f.ids() == '5,9,31,12,20,40,41' and 'pinned\t' not in settings(logs),
          'the pin hovered: its cell takes no click (byte 0); the first frame: nothing pinned')
    sounds, laid = len(f.sounds), f.laid_out
    f.confirm(True); f.frame_step(1); f.confirm(False)
    check(f.ids() == '5,9,31,20,12,40,41' and f.bytes(0x92dc2) == '0,1,1,1,1,1,1' and f.bytes(0x92ec2) == '0,0,0,1,0,0,0'
          and settings(logs).endswith('pinned\t%d\n' % (0x1000 + 20)) and list(f.sounds.values())[sounds:] == ['0x468c8e58']
          and f.laid_out == laid + 1 and f.cache_cleared and f.pin_marked == 0xb000 + 20
          and 'Pins: list reordered (pinned' in log(logs),
          'clicked: 20 pinned and first of its group, saved: %r %r %r' % (f.ids(), f.bytes(0x92dc2), settings(logs)))
    f.hover_parent = None
    f.frame_step(11)
    check(pin(lua, 1, 0) and abs(f.colour[pin(lua, 1, 0, 'mark')][2] - 0.914) < 1e-6 and f.opacity[pin(lua, 1, 0)] == 0.85,
          'the pinned one (now in the 1st cell of its row): its pin in sight, yellow')

    # P5. The focus kept on its stratagem: the focused one before a reorder is focused again (the game's setter), and
    #     the details panel told.
    f.set_focus_offer(0xb000 + 12)
    previews = f.previews
    f.hover_cell(1, 0); f.hover_parent = f.cell(1, 0)
    f.frame_step(1)
    f.confirm(True); f.frame_step(1); f.confirm(False)
    check(f.ids() == '5,9,31,12,20,40,41' and f.list_focused == 0xb000 + 12 and f.previews == previews + 1
          and settings(logs).endswith('pinned\t\n'),
          'unpinned: back to the game order, the focus on its stratagem: %r' % f.ids())
    f.hover_parent = None; f.hover_cell(None)

    # P6. The Action key with the list open: the hovered stratagem pinned (31, first of the reds); the list closed
    #     and opened again (built in the game's order): reordered on its first frame.
    def press(f):
        f.clear_down = True; f.frame_step(1); f.clear_down = False; f.frame_step(1)
    f.hover_cell(0, 2)
    f.frame_step(1)
    press(f)
    check(f.ids() == '31,5,9,12,20,40,41' and settings(logs).endswith('pinned\t%d\n' % (0x1000 + 31)),
          'the key on a hovered stratagem: pinned: %r' % f.ids())
    f.hover_cell(None)
    f.set_category(3); f.frame_step(2)
    open_list(f, lua)
    f.frame_step(1)
    check(f.ids() == '31,5,9,12,20,40,41', 'opened again: the pin first on its first frame: %r' % f.ids())

    # P7. With a controller: the focused stratagem shows its pin (no hover, no click); the key toggles it.
    f.set_pad(True)
    f.set_focus_offer(0xb000 + 41)
    f.frame_step(11)
    check(pin(lua, 2, 1) and f.opacity[pin(lua, 2, 1)] == 0.85, 'a controller: the focused stratagem shows its pin')
    press(f)
    check(f.ids() == '31,5,9,12,20,41,40', 'the key on the focused stratagem: pinned: %r' % f.ids())
    f.set_pad(False)

    # P8. The pins last: a new session reads them; the list is reordered on its first frame.
    lua, logs, f = list_game(settings='leave_primary\t0\nleave_secondary\t0\nleave_grenades\t0\npinned\t%d,%d\n'
                                      % (0x1000 + 41, 0x1000 + 9))
    open_list(f, lua)
    f.frame_step(1)
    check(f.ids() == '9,5,31,12,20,41,40' and '2 pinned stratagem(s)' in log(logs),
          'the pins of an earlier session: applied: %r' % f.ids())


def randomize(image):
    """Randomize Lineup: a reroll button by the booster; four slots filled one at a time with a lineup."""
    RED, GREEN, BACKPACK, WEAPON, FED, EXPENDABLE, VEHICLE = (5, 9, 31), (40, 41), (20,), (12,), (50,), (51,), (52,)

    def roll_game(owned=None, extra=''):
        def setup(lua):
            lua.execute(BINDING_MENU)
            f = lua.globals().fake
            f.set_hud(12, 2); f.set_flags(12, 0x1)                 # a support weapon
            f.set_hud(20, 2); f.set_flags(20, 0x8)                 # a backpack
            f.set_hud(3, 1)                                        # mission
            f.add_stratagem(31, 'ORBITAL. LASER', 0, 0)
            f.add_stratagem(40, 'SENTRY. GATLING', 3, 0)
            f.add_stratagem(41, 'MINES. ANTI-PERSONNEL', 3, 0)
            f.add_stratagem(50, 'SUPPORT. RECOILLESS', 2, 0x9)
            f.add_stratagem(51, 'SUPPORT. EAT', 2, 0x10001)
            f.add_stratagem(52, 'VEHICLES. FRV', 2, 0x200020)
            f.add_stratagem(53, 'VEHICLES. TANK', 2, 0x400020)
            f.add_stratagem(54, 'ORBITAL. BANNED', 0, 0, True)
            f.add_stratagem(55, 'ORBITAL. NOT OWNED', 0, 0)
            if owned:
                f.owned = lua.table_from({t: True for t in owned})
            else:
                f.owned = lua.table_from({t: True for t in (3, 5, 9, 12, 20, 31, 40, 41, 50, 51, 52, 53, 54)})
            lua.execute(extra)
        lua, logs = new_game(image, setup)
        f = lua.globals().fake
        f.frame_step(1)
        f.setup_panel(lua.table(lua.table(77, False)))
        f.setup_slots()
        f.setup_booster()
        f.set_slot(0, 5); f.set_slot(1, 12); f.set_slot(2, 20); f.set_slot(3, 40)
        f.set_block(0, lua.table(5, 12, 20, 40))
        f.open_screen(0)
        f.frame_step(12)
        return lua, logs, f

    def button(lua, name='plate'):
        b = lua.eval('FlexibleLoadouts._test.dice.button')
        return int(b.pieces[name]) if b is not None else None

    log = lambda logs: text(logs / 'FlexibleLoadouts.log')
    rolled = lambda f: [tuple(int(x) for x in s.split()) for s in f.set_slots.values()]

    def valid(picks):
        """The lineup the four picks make, or None."""
        light, heavy = EXPENDABLE + WEAPON, EXPENDABLE + FED
        lineups = {1: (RED, light, BACKPACK, GREEN), 2: (RED, RED, heavy, GREEN), 3: (VEHICLE, RED, GREEN, GREEN)}
        types = [t for _, t in picks]
        if len(set(types)) != 4 or [k for k, _ in picks] != [0, 1, 2, 3]:
            return None
        for n, pools in lineups.items():
            if all(t in pool for t, pool in zip(types, pools)):
                return n
        return None

    # R1. The owned stratagems by class (the tank, the banned and the unowned one left out); the button made under
    #     the booster widget, at the bottom of its left edge, the game's refresh arrows on the dark plate, shown.
    lua, logs, f = roll_game()
    plate, mark = button(lua), button(lua, 'mark')
    booster = f.booster()
    check('Randomize Lineup: owned red 3, green 2, backpack 1, weapon 1, fed 1, expendable 1, vehicle 1; '
          'lineups 1-3: 12, 12, 3 ways' in log(logs), 'the owned stratagems by class, each lineup\'s ways')
    check(plate and f.rd64(plate + 0xf0) == booster and tuple(f.anchor[plate].values()) == (0, 0)
          and tuple(f.position[plate].values()) == (0, 10) and tuple(f.size[plate].values()) == (20, 20)
          and f.material[mark] == 'b279857f186a3b76' and f.opacity[plate] == 0.85,
          'the reroll button under the booster, shown')

    # R2. Hovered: the slots' hovered index written as none (a click there is the mod's), lighter; a click on the first
    #     hovered frame does nothing; on a blocked button the roll: slot 1 at once with its colour's pick sound, then
    #     one slot about every 0.22 s; a valid lineup of four different stratagems, each saved.
    f.hover_parent = booster
    f.confirm(True); f.frame_step(1); f.confirm(False)
    check(f.rd32(0x21000000 + 0x595f0 + 0xd968) == 0xffffffff and len(f.set_slots) == 0 and f.colour[mark][1] == 1,
          'hovered: the slots blocked, nothing rolled on the first frame')
    sounds = len(f.sounds)
    f.confirm(True); f.frame_step(1); f.confirm(False)
    first = rolled(f)
    f.frame_step(10)
    check(len(first) == 1 and len(rolled(f)) == 1 and list(f.sounds.values())[sounds] in ('0x1a077fd1', '0x2d36b8b8', '0x7200dc32'),
          'clicked: the first slot at once, with a pick sound: %r' % first)
    f.frame_step(40)
    picks = rolled(f)
    check(valid(picks) and [f.slot_type(k) for k in range(4)] == [t for _, t in picks] and f.saved == '0x10'
          and 'Randomize Lineup: done' in log(logs),
          'four slots one at a time, a valid lineup (%s): %r' % (valid(picks), picks))
    f.hover_parent = None

    # R3. Many rolls: every lineup drawn, always valid, never the loadout already there, no repeat ever in the slots.
    seen, bad = set(), []
    for _ in range(30):
        f.set_slots = lua.table()
        before = [f.slot_type(k) for k in range(4)]
        lua.eval('FlexibleLoadouts._test.dice').start(0x21000000, 0, 'test')
        for _ in range(60):
            f.frame_step(1)
            types = [f.slot_type(k) for k in range(4) if f.slot_type(k)]
            if len(types) != len(set(types)):
                bad.append(types)
        n = valid(rolled(f))
        seen.add(n)
        if not n or [t for _, t in rolled(f)] == before:
            bad.append(rolled(f))
    check(seen == {1, 2, 3} and not bad, 'thirty rolls: all three lineups, all valid, no repeats: %r %r' % (seen, bad[:3]))

    # R4. The Action key on the booster slot (a controller: its focus) rolls; the list opening stops a roll.
    f.set_slots = lua.table()
    f.set_mouse(False)
    f.set_grid_focus(4)
    f.clear_down = True; f.frame_step(1); f.clear_down = False
    f.frame_step(15)
    f.set_category(10)
    f.frame_step(30)
    check(len(f.set_slots) == 2 and 'Randomize Lineup: stopped after 2 slot(s) (the list opened)' in log(logs),
          'the key on the booster rolls; the list opening stops it: %r' % rolled(f))
    f.set_category(0)
    f.set_mouse(True)

    # R5. A slot disabled by the mission is left as it is.
    lua, logs, f = roll_game()
    f.set_slot(3, 0, 4)
    lua.eval('FlexibleLoadouts._test.dice').start(0x21000000, 0, 'test')
    f.frame_step(60)
    check([k for k, _ in rolled(f)] == [0, 1, 2] and f.slot_type(3) == 0, 'a disabled slot: left alone: %r' % rolled(f))

    # R6. Owning too little (one lineup at most one way): no button.
    lua, logs, f = roll_game(owned=(5, 9, 40, 41))
    check(button(lua) is None and 'lineups 1-3: 0, 0, 0 ways' in log(logs), 'too few stratagems: no button')
    lua, logs, f = roll_game(owned=(5, 40, 12, 20))
    check(button(lua) is None and 'lineups 1-3: 1, 0, 0 ways' in log(logs), 'one way only: no button')

    # R7. Code the randomizer can't trust (the owned loop's end not the stratagem table's): off, the rest on.
    rva, _, fields = SIG_ROWS['ready_owned']
    lua, logs = new_game(image, build((rva + fields['owned_end'][1][0], (0x97).to_bytes(4, 'little'))))
    lua.globals().fake.frame_step(2)
    status = text(logs / 'FlexibleLoadouts_STATUS.log')
    check('Randomize Lineup: NOT AVAILABLE' in status and 'Pinned stratagems: on' in status and 'Clear buttons: on' in status,
          'the owned loop disagreeing: the randomizer off alone')


def main():
    image = DUMP.read_bytes()
    for name, rva, text_, fields, _optional in sigspec.build(signatures.SPECS):
        SIG_ROWS[name] = (rva, text_, fields)
    version = re.search(r"local M = \{version = '([^']+)'", MAIN).group(1)
    static(version)
    core(image, version)
    extras(image, 'OK - active')
    clear_buttons(image)
    weapons_left(image)
    leave_out_buttons(image)
    pins(image)
    randomize(image)

    passed = sum(results)
    print(f'{passed}/{len(results)} passed')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
