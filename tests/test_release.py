"""Offline test of the Stratagems Unleashed release under LuaJIT, with the real game.dll dump as process memory.

The dump (_research/game_25480438.dll, offsets == RVAs) is mapped at a fake base, so the code signatures are
matched against the game's own code; the globals they lead to (screen stack, loadout screen, stratagem list, offers
table, stratagem table) and the two native functions (the list's marker and select) are simulated. "Other builds"
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
SOURCE = (MOD / 'stratagems_unleashed.lua').read_text(encoding='utf-8')
DUMP = MOD.parent / '_research' / 'game_25480438.dll'
sys.path.insert(0, str(MOD / 'research'))
sys.path.insert(0, str(MOD.parent / 'tools'))
import signatures  # noqa: E402
import sigspec  # noqa: E402

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
update = function(dt) fake.base_updates = (fake.base_updates or 0) + 1 end

-- Globals.
fake.patch(0x347ce38, le64(STACK))
fake.patch(0x347ce50, le64(SYS))
fake.patch(0x3326468, le64(PLAYERS))
fake.patch(0x347cef0, le64(SELF))
fake.patch(0x3326348, le64(CLK))
fake.heap(STACK, le32(0) .. string.rep('\0', 172) .. le64(SCREEN) .. string.rep('\0', 0x400 - 184))
fake.heap(SCREEN, string.rep('\0', 0x166000))
fake.heap(SCREEN + 0x72868, le64(0))
fake.heap(PLAYERS + 0x80, le32(0) .. le32(1))
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
function fake.set_synced(players)  -- {{peer, {{type, uses, cd_end}...}}...}
    write_mem(SYS + 0x2d200, le32(#players))
    for i, p in ipairs(players) do
        local base = SYS + (i - 1) * 0x1690
        write_mem(base, le64(p[1]))
        local s = ''
        for _, e in ipairs(p[2]) do s = s .. entry(e[1], e[2], e[3]) end
        write_mem(base + 0x38 + 0x188, s .. string.rep('\0', 0x600 - #s))
        write_mem(base + 0x38 + 0x788, le32(#p[2]))
    end
end
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
function fake.set_category(c) write_mem(SCREEN + 0x2818, le32(c)) end
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
    for _ = 1, n or 1 do fake.frame = fake.frame + 1; update(0.016) end
end
function fake.press(key) fake.down[key] = true; fake.frame_step(1); fake.down[key] = false end
'''

results = []


def check(cond, what):
    results.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + what)


def new_game(image, prepare=''):
    logdir = tempfile.mkdtemp(prefix='su_rel_')
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
    body = SOURCE.split('\n', 1)[1]
    for pattern in (r'//', r'\bgoto\b', r'&(?!&)', r'~(?!=)', r'<<', r'>>', r'math\.type', r'string\.pack'):
        check(not re.search(pattern, body.replace('-->', '')), f'no Lua 5.3+ construct {pattern!r}')
    check(SOURCE.startswith('-- HD2-Addon: mods/alomare/stratagems_unleashed\n'), 'declaration line first')
    check(not re.search(r'f10|snapshot|save_raw|recon|DuplicateStratagems', SOURCE, re.I), 'no research leftovers')
    image = DUMP.read_bytes()
    for name, rva, text_, fields in sigspec.build(signatures.SPECS):
        SIG_ROWS[name] = (rva, text_, fields)
    in_script = re.findall(r"name = '(\w+)', rva = (0x[0-9a-f]+), text = '([^']+)'", SOURCE)
    check([(n, int(r, 16), t) for n, r, t in in_script] == [(n, v[0], v[1]) for n, v in SIG_ROWS.items()],
          'the script carries the signatures research/signatures.py builds (%d)' % len(in_script))

    # 1. This build: OK status; idle outside the loadout screen (a check every 10 frames).
    lua, logs = new_game(image)
    f = lua.globals().fake
    f.frame_step(1)
    status = text(logs / 'StratagemsUnleashed_STATUS.log')
    version = re.search(r"local M = \{version = '([^']+)'", SOURCE).group(1)
    check(status.startswith('OK - duplicate stratagems and vehicles can be picked') and 'Stratagems Unleashed %s' % version in status
          and "Game code found at this game version's addresses" in status, 'status OK on this build: %r' % status)
    check(f.base_updates == 1, 'update chained')
    rate = reads_per_frame(f, 100)
    check(rate <= 0.2 and not f.game_writes, 'outside the loadout screen: %.2f reads per frame, no writes' % rate)

    # 2. Loadout screen, another category: a few reads per frame, nothing written.
    f.set_flags(12, 0x00200021)
    f.set_flags(9, 0x80100000)
    f.set_flags(20, 0x0000000a)
    f.set_block(0, lua.table(5, 9, 12, 3))
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(1, 1, 1, 1, 1, 1))
    f.set_category(3)
    f.open_screen(0)
    f.frame_step(10)
    rate = reads_per_frame(f, 20)
    check(rate <= 3 and not f.game_writes and f.flags(12) == 0x00200021, 'other category: %.1f reads per frame, nothing written' % rate)

    # 3. The stratagem list opens: vehicle bits cleared; steady state costs one list read.
    f.set_category(10)
    f.frame_step(1)
    check(f.flags(12) == 0x21 and f.flags(9) == 0x80000000 and f.flags(20) == 0xa,
          'list open: only the vehicle bits cleared: %x %x %x' % (f.flags(12), f.flags(9), f.flags(20)))
    writes = f.game_writes
    rate = reads_per_frame(f, 20)
    check(rate <= 4 and f.game_writes == writes, 'list open, nothing refused: %.1f reads per frame, no writes' % rate)

    # 4. The game's refresh refuses the loadout's stratagems (and one item for another reason): the loadout's are
    #    marked back through the game's marker, the other stays refused and costs nothing more afterwards.
    f.set_selected(0xb009)  # a controller's focus on a loadout stratagem, no pick
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(0, 0, 0, 1, 0, 0))
    f.frame_step(1)
    check(f.list_selectable() == '1,1,1,1,1,0' and f.marked == 4, 'loadout stratagems marked selectable: %s' % f.list_selectable())
    rate = reads_per_frame(f, 20)
    check(rate <= 4 and f.marked == 4, 'an unrelated refused item: %.1f reads per frame, not marked again' % rate)
    check(not f.selects and f.selected() == 0xb009, 'no pick yet: the selection (focus) is left alone')

    # 5. A pick (Railcannon again): the refresh refuses the loadout's stratagems again; the selection left on the
    #    Railcannon is cleared once, so its next pick plays the sound.
    f.set_selected(0xb005)
    f.set_block(0, lua.table(5, 5, 12, 3))
    f.set_list(lua.table(5, 9, 12, 20, 3, 77), lua.table(0, 1, 0, 1, 0, 0))
    f.frame_step(1)
    check(f.selects == 1 and f.selected() == 0 and f.list_selectable() == '1,1,1,1,1,0',
          'after a pick: selection cleared, loadout marked again')
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

    # 7. Errors: the vehicle bits are restored; five errors stop the mod.
    lua, logs = new_game(image, "fake.natives[0x18d1440] = function() error('boom') end")
    f = lua.globals().fake
    f.frame_step(1)
    f.set_flags(12, 0x00200021)
    f.set_block(0, lua.table(5, 9))
    f.set_list(lua.table(5, 9), lua.table(0, 0))
    f.set_category(10)
    f.open_screen(0)
    f.frame_step(20)
    status = text(logs / 'StratagemsUnleashed_STATUS.log')
    check(f.flags(12) == 0x00200021 and status.startswith('STOPPED - repeated errors') and 'boom' in text(logs / 'StratagemsUnleashed.log'),
          'errors restore the vehicle bits and stop the mod after five: %r' % status.splitlines()[:1])
    before = f.base_updates
    f.frame_step(3)
    check(f.base_updates == before + 3, 'update still chained after stopping')

    # 8. Another build where code moved: the marker, select and the screen query are elsewhere (the refresh calls the
    #    moved marker), and the screen slot is +0xb8 instead of +0xb0. The mod finds them by search, follows the new
    #    slot, and calls the natives at their new addresses.
    # select starts 16 bytes into the second search chunk: inside the first chunk's overlap too, counted once.
    new = {'marker': FREE, 'select': 0x1000 + 0x400000 + 0x10, 'screen': FREE + 0x200}

    def moved_build(lua):
        f = lua.globals().fake
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
    while not text(logs / 'StratagemsUnleashed_STATUS.log') and frames < 60:
        f.frame_step(1)
        frames += 1
    elapsed = time.perf_counter() - started
    status = text(logs / 'StratagemsUnleashed_STATUS.log')
    print('INFO search of game.dll: %d frames, %.2f s in this LuaJIT (%.0f ms per frame)' % (frames, elapsed, elapsed * 1000 / frames))
    check(status.startswith('OK - duplicate stratagems') and 'Game code found by search (3 moved: screen, marker, select)' in status,
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

    # 9. Builds the mod can't trust: nothing runs, the status says why.
    def build(*edits):
        def prepare(lua):
            f = lua.globals().fake
            for rva, data in edits:
                f.patch(rva, data)
        return prepare
    marker_rva = SIG_ROWS['marker'][0]
    kind_mech = SIG_ROWS['kind_mech']
    flags_at = kind_mech[0] + kind_mech[2]['flags'][1][0]
    cases = (
        (build(broken('marker')), 'code "marker" not found'),
        (build(broken('select'), (FREE, moved(image, 'select', FREE)), (FREE + 0x100, moved(image, 'select', FREE + 0x100))),
         'code "select" found 2 times'),
        (build((flags_at, (0x108).to_bytes(4, 'little'))), '"flags" differs between signatures'),
        (build(broken('marker'), (FREE, moved(image, 'marker', FREE))), 'the refresh does not call the marker'),
        (build((SIG_ROWS['refresh_a'][0] + SIG_ROWS['refresh_a'][2]['list_count'][1][1], (0x92988).to_bytes(4, 'little'))),
         '"list_count" in code "refresh_a" is inconsistent'),
    )
    for prepare, why in cases:
        lua, logs = new_game(image, prepare)
        f = lua.globals().fake
        f.set_block(0, lua.table(5, 9))
        f.set_list(lua.table(5, 9), lua.table(0, 0))
        f.set_category(10)
        f.open_screen(0)
        f.frame_step(40)
        status = text(logs / 'StratagemsUnleashed_STATUS.log')
        check(status.startswith('NOT AVAILABLE - this game version is not supported (%s)' % why) and not f.game_writes
              and not len(f.calls) and f.list_selectable() == '0,0', 'another build (%s): nothing written or called: %r'
              % (why, status.splitlines()[:1]))
    del marker_rva

    passed = sum(results)
    print(f'{passed}/{len(results)} passed')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
