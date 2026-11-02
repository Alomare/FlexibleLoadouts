# Flexible Loadouts: how it works in the game's code

Flexible Loadouts changes the Hellpod loadout screen of Helldivers 2: ready up with empty stratagem slots, the stratagem list kept open after a replacement, a red X on each filled stratagem slot that empties it, a key that empties or toggles the hovered or focused slot, Leave Out toggles on the primary, secondary and grenade slots that send the local Helldiver into the mission without them, pinned stratagems that come first in their group of the stratagem list, and a button that fills the four slots with a random lineup. Everything is done through the game's own data and functions, read and called from Lua under Bingus Shared Loader; no game code is patched (game.dll is Themida-packed).

Addresses are game.dll RVAs for build 25480438. Function names in Ghidra sessions are `FUN_<address>` with the module at 0x7ffcea020000 (RVA = address - 0x7ffcea020000). The mod does not use these addresses directly: every address and structure offset it uses is read from the game's code through the signatures listed at the end, so it survives updates that move code without changing it.

Unless marked otherwise, a finding below was confirmed in game. "(from the code)" marks a reading of the decompiled code that the mod relies on without a dedicated live check; "(not yet confirmed in game)" marks parts of the current code that have not been tested live yet.

## The Hellpod loadout screen

- Screen stack global `[0x347ce38]`; the loadout screen is the stack entry of type 11, its object at `[stack] + 0xb0` (about 2.5 MB). The stratagem list lives inside this object, so the stack's top stays 11 while the list is open.
- Screen head: local player index `+0x27d0` (0xffffffff when the screen opens, set about 140 frames later), menu category `+0x2818` (10 = stratagems), the slot being edited `+0x281c`, list open byte `+0x273990`, intro timer `+0x273988`.
- **Pending loadout blocks**: one per player at `screen + 0x10 + i * 0x9f0`. A block has the synced loadout layout (below): weapons at `+0`, `+0x60`, `+0xc0` (blocks of 0x60), stratagem entries at `+0x188` (48 bytes each), count `+0x788`. Entry uses: 0xffffffff unlimited; flag byte (+9) 0 for picks, 1 for mission entries.
- Each pick lands in the local block and, 10-15 frames later, in the local synced list: the picker syncs on every equip. Nothing polls the block: a value written into it does not change the slots on screen and is not sent until the screen exits.
- Exit (`0x1467790`, from on_exit `0x1467b90`): `0xb4eec0(block)` expands the block in place by mission type (mission stratagems, event stratagems); `0x1751350(block)` saves it; `0x13620a0(_, peer, block, 1)` sends it to the peers (host, then everyone).
- **Player panels**: `screen + 0x53a78`, 0x1ee18 bytes apart; panel 0 is the local one. Panel fields: entity `+0x1edf8`, unit `+0x1edfc`, local flag `+0x1ee0c`, a busy byte `+0x1ee0e`, ready timer `+0x1ee14` (float, -1.0 when idle), READY prompt `+0x28b0`.
- **Stratagem slot grid**: `panel + 0x5b78` (= `screen + 0x595f0`): hovered slot `+0xd968`, focused slot `+0xd96c`, active byte `+0xd978`. Focus setter `0x1895770(grid, slot)`. Mouse click `0x18950b0`: with the grid active and confirm pressed this frame in mouse mode, a hovered slot (`+0xd968 < 5`) gets the click sound 0xa31d0645, the focus and the stratagem list.
- **Stratagem slot widgets**: `panel + 0x5b78 + 0x8ec0 + k * 0x12a8` (k = 0..3): flags u16 at `+0x1288` (bit 0 hovered, bit 2 disabled: no hover, can't be clicked; a mission modifier sets it), type at `+0x128c` (0 = empty). `0x1893600(widget, type)` sets one (type 0 hides the icon). The pick path: `0x189d050(panel, slot, item)` (item -> type, then the widget setter), then `0x189d120(panel, -1)`, which writes the slots into the loadout block through `0x18966a0(grid, [panel + 0x1edf0])` (clears the entries, then appends the non-empty slots) and sends the change (rpc_sync_stratagem_changes); the equip handler then refreshes the list and saves the block (`0x1751350`).
- Slot hover test `0x1893550(slot)`: a disabled slot is unhovered; a slot whose widget header has bit 2 (pending widget changes) skips the test that frame; otherwise the game's hit test goes to set-hover `0x18936d0(slot, on)` (on a change: bit 0, the hover sound 0xdd84ae45 when turning on, the redraw `0x18932f0`). The white hover frame (frame `+0x798`, 3 units) is only redrawn on state changes.
- **Grid mode** `screen + 0x6f290`: 0 shows the stratagem grid, 1 the equipment view (the panel's second prompt switches it). A transition byte right after it (`screen + 0x6f294`) is set for about 0.1 s after a switch, while the new view is still invisible but its hover and click already run.
- **Equip handler** `0x146e0a0(screen, input)`: maps the item to a stratagem type, applies the vehicle kind rule (below), sets the slot, refreshes the list's markers (`0x18d1890(list, block)`) and saves. It has no duplicate check. Its tail (`0x146e5f6`) looks for the first enabled empty slot (types at `screen + 0x6373c`, not in grid mode 1): with one it focuses it and sets the edited slot, keeping the list open; else it plays 0x97753411 and closes the list (`0x146f3b0`). The list opener `0x146e9d0(screen)` opens the list for the focused slot.
- **Input gates** before the panels get input: the screen input `0x146d370` does nothing while the launch byte `+0x2808` is set, the input delay `+0x27399c` (float) runs, the bytes `+0x27fc` / `+0x273998` / `+0x27f9` are set, or the states `+0x27398c` (0 or 7) / `+0xd1f94` (0 or 3) differ; it hands input to the panels (`0x146d9b0`) with the list closed while the screen's state (`+8`) is 1. `0x146d9b0` gives a click to the active group's panel (`+0x2739c8`) only when its busy byte is clear, it is the local panel and its ready timer is idle; then by grid mode to the slot grid (`0x18950b0`) or the equipment view (`0x1898400`).
- The Noesis `ui.MenuLoadout` page (`xaml/0x4eba493cb089b0cf.xaml`, placeholder art) is not the live picker; the picker is native widgets.

## The stratagem list and the one-of-each rule

- List `screen + 0xd2f20` (its grid `screen + 0xd2850`): offer count `+0x92984` (up to 256), offer ids `+0x92990` (u32), **selectable bytes `+0x92dc2`**, selected offer `+0x9298c`, scroll `+0x92960` (float, clamped to [0, `+0x8c0`] by the list update `0x18cf820`). Cells: pages of 0xaed0, cells of 0x2b68, flag word at cell `+0x2b5a` (bit 2 = the equipped look).
- The refresh `0x18d1890(list, block)` sets every selectable byte to 1, then calls the marker `0x18d1440(list, offer, 0)` for each stratagem in the block (byte 0 and the equipped look). Item id (StratagemInfo `+4`) maps to an offer id through the offers table `[0x347cef8]`: entries at `+0xb9ce4` (24 bytes: offer `@4`, item `@8`), count `+0x1ce0`, the stratagem range's indices at `+0xd1d48` from `+0xd1d0c` to `+0xd1d10`.
- **The refusal**: the press handler `0x18cf930` asks `0x18d2690(list, page, index)` for the selectable byte and returns 6 (refused) on 0. This is the only place the game refuses a stratagem already in the loadout: the equip handler, the loadout sync and the mission code all accept a list with repeats (a duplicate sent the normal way works in a mission, each copy with its own cooldown). The list's drawing also reads the selectable byte, and the refresh rewrites it: a byte written directly is re-greyed by the game; the marker with byte 1 (`0x18d1440(list, offer, 1)`) ungreys and redraws the cell the game's way.
- The vehicle kind rule: the equip handler allows one stratagem per kind, from StratagemInfo flags `+0x104`: **0x100000 mech, 0x200000 FRV, 0x400000 tank** (9 stratagems carry them on this build). Picking a second of a kind is redirected to the slot already holding that kind.
- Selection: select `0x18d10d0(list, offer)` sets `+0x9298c` and a 0x80 highlight bit on the cell; the mouse press plays the equip sound `0x18d0210(list, offer)` only when the pressed offer differs from the selected one (the controller path always plays it).
- The opener rebuilds the list (`0x18d8710(list grid, item of the focused slot, block)`), which resets the scroll and focuses the slot's current item (or the first selectable cell when the slot is empty). `0x18d1280(list, offer)` focuses a cell without scrolling; `0x18d2b60(list)` lays the list out.

## Ready with empty slots

- The screen calls the local panel's ready handler `0x189c250(panel, input)` while the list is closed. The handler runs only when the READY prompt fires, asked of the prompt's press check `0x1891850(prompt, input)`.
- The handler counts the four slot widgets: filled = type != 0; disabled = empty with flag bit 2; owned = stratagem types 1..0x95 passing `0x136fc20(offers, type)`. Required = min(owned, 4 - disabled). While filled < required it flashes each empty enabled slot whose flash byte (`widget + 0x18`) is 0 (an animation, the byte set to 1; the widget update `0x18932c0` clears it when the animation ends), plays 0xf50f0501 and returns 5. It refuses the same way while any slot still flashes, also without starting a new flash. The string "You need to select four stratagems to be able to ready up" (0xb23162b7) is unused.
- Otherwise it toggles: it first calls the emote sender `0xbf2e20(unused, unit = [panel + 0x1edfc], event, 0.0, 0.0)` with 0x97e150a4 when readying or 0x5d1d1963 when cancelling (RPC 0xf24760a9 to all peers through the send core `0xbde430(rpc, -1, args, 4)`: this is the ready pose every peer sees), then for an idle timer starts it at 1.75 s with sound 0x7947920 (every other player already ready) or 0x4d777731; the panel update `0x189b920` counts it down and sets bit 3 of the local player's flags (players `[0x3326468]`, flags `+0x3ac + i * 0x20`; bit 3 or 11 counts as ready). Cancelling puts the timer back to -1.0, clears bit 3 and plays 0xf50f0501. The UI sound function is `0x1327f50(unused, id)`.
- **The game's UI update runs before the Lua update in a frame**, so a mod can't see a press before the game handles it. The mod watches the local panel's flash bytes while the list is closed: a 0 -> 1 change is the handler refusing a ready press, and the mod then runs the handler's toggle itself (emote, timer, sound, or the cancel). While a flash still shows, the mod asks the game's own press check whether READY fired this frame; pressed, a slot flashing and the timer's idle state unchanged since the last frame (the handler's own toggle always flips it) means refused, and the mod toggles.
- The press check `0x1891850(prompt, input)` only reads: nothing when the prompt's state `+0x2f84` is 1 (1 swaps the prompt for another widget, 2 hides both); else its action `+0x2f88` pressed this frame, or confirm while hovered (`+0x2f90`, mouse mode) or focused (`+0x2f91`, otherwise). ReadyUp is input action settings id 0x35, menu input 0x24.
- Input: the UI input object is `[0x347cf18]` (the UI frame `0x1437860` passes it to the stack dispatcher `0x14ac950`, which for screen type 11 calls `0x146d370`). An action's press byte is at `input + 0x328 + index * 0x20`, the index given by the action mapper `0x585b80(action)` (high dword + low dword * 0x61 for a low dword up to 12); confirm is the action 0xa00000000. Mouse mode is the byte `input + 0xe1ad4`; the last device being a pad is `input + 0xe1ad5`.

## The list kept open

After a replacement in a full loadout (slots 1 to 3) the equip handler closes the list. The mod remembers the edited slot and the loadout while the list is open; when the list closes after a pick that kept four stratagems, it focuses the next slot (`0x1895770`) and calls the list opener, as the handler does while slots are empty. Since the opener resets the scroll, the mod then focuses the stratagem just picked (the edited slot's type -> item -> offer, `0x18d1280`), writes the scroll back and lays the list out.

## The clear buttons

A red X in the top-right corner of each filled stratagem slot of the local panel, made of the game's own widgets.

- **Widgets in the mod's memory.** Each piece is a picture of the game's widget kind in 0x160 bytes the mod allocates (zeroed, 16-byte aligned, never freed: the game may keep pointers to a widget). A widget is made inside the GUI context of its parent: `widget_init` (`0x1446840`) stores the context `base + stack[top] * 0x3698` (contexts `[0x347ce90]`, stack top `+0x2c5bc`, stack `+0x2c5b8`) at `+0xf8`, so the mod pushes the slot's context (`[slot + 0xf8]`) with `0x12ef4b0(base, slot)` and pops it with `0x12ef4d0()`. Attached under the slot widget with `0x144c5c0(parent, child)`, the pieces are placed by the game's widget tree every frame (resolution, UI scale, the screen's intro). Child list: first child `+0xe0`, next sibling `+0xe8`, parent `+0xf0`.
- **Placement and look**: anchor (1, 1), pivot (0.5, 0.5), position (-13, -13), 20 x 20, layers 17-18; the game's red cross `content/ui/shared/misc/check_no_no_curve` (0x4acbc968ba925d47; the game tints it (0.694, 0.078, 0) at 0x147f7bd) on a dark plate of the game's solid fill `content/ui/shared/material/gui_fill` (0xe819a58401ff619f). The cross is loaded on this screen; the mod checks `Application.can_get('material', name)` before using it and falls back to two fill bars rotated +-45 degrees (`0x1448ef0`).
- **Shown** only when the game would take a click on the slot: all the input gates above, the grid active, mouse mode, the slot filled and not disabled. Hidden while the list is open, while readying and during the screen's intro; with a controller only the focused slot shows its X, as a marker that takes no click.
- **Hover and click.** Hover is the game's own hit test `0x178f970(cursor widget = [0x347ce38] + 0x5f0, piece, 0)`. While an X is hovered the mod writes the grid's hovered slot (`grid + 0xd968`) as -1 every frame: the game's click reads it before the mod writes it again, so a click on the X opens no list. A click counts for the mod when confirm fires on an X that was hovered (so blocked) the frame before; the slot is then emptied the pick's way (widget setter with type 0, `0x189d120(panel, -1)`, save). A slot emptied in the middle stays empty (later stratagems don't shift), the emptied loadout holds in the mission, and teammates see it.
- **Lifecycle**: the mod checks every few frames that each piece is alive and still in the slot's child list. A button lost while the screen is open (a piece torn down, the slot re-made) has its live pieces destroyed (`0x144dd70`) and is made again; one from an earlier visit is only forgotten. Setters run on change only, never on a piece whose header reads 0.
- **Fades**: the game's fade helper `0x1450dd0(w, out, seconds, alpha, delay)` (219 call sites) fades from the current opacity (`+0x44`) with a smoothstep tween run by the game on its frame time (its tail calls the opacity setter `0x1448ad0` and the tween `0x1448870`). The X fades in over 0.2 s and out over 0.1 s, the game's own show and hide timings. While a piece fades the game skips its parent slot's hover test (the tween marks the parent chain dirty), so the slot can't be hovered or clicked for the fade's length.
- **The slot's highlight under its X**: the slot keeps its white hover frame while the cursor is on the X (the X is inside the slot). The mod calls set-hover(slot, 0) (the game's unhovered look, no sound) and every frame the dirty mark `0x144d200(slot)` (header bit 2 on the widget and up its parent chain), which makes the game skip the slot's hover test; back on the slot body it sets the hover bit and calls the redraw, hovered again without the hover sound.

## The Action key

A Mod Bindings Menu binding named Action (id `alomare.flexible_stratagems.clear`, kept from the mod's old name because the id keys players' saved bindings), for the mouse and controllers. In the stratagem view a press empties the hovered slot in mouse mode (the X's hover counts: the game's hovered index is -1 then), else the focused one (`grid + 0xd96c`), the X's way; on the booster slot (index 4, or the reroll button) it randomizes the lineup. In the equipment view it flips the Leave Out toggle of the hovered (`view + 0x8310`) or focused (`view + 0x8314`) weapon slot; an armour or empty slot does nothing. With the stratagem list open it pins or unpins the hovered stratagem in mouse mode, else the focused one. It does nothing while the input gates fail (other than mouse mode): ready, another active group. With a controller the focused slot shows its X or its Leave Out button, and the focused stratagem its pin, as a marker (no hover, no click).

## Leave Out toggles

A REMOVE button with a check box at the top centre of the local panel's primary, secondary and grenade slots. It takes clicks only when all the input gates pass, in mode 1 with the view active and the transition byte clear; a checked one also stays in sight (no hover, no click) while the equipment view shows without taking input (ready, a controller).

- **The equipment view** (`screen + 0x66f70`, panel input `0x1898400`) holds six slots of class `0x1896fb0` (130 x 96 units) at `view + 0x110 + k * 0x1558`: armour first, the primary k = 3 (`view + 0x4118`), the secondary k = 4 (`+0x5670`), the throwable k = 5 (`+0x6bc8`); the record setter `0x18991a0(view, block, active)` gives each its item (`0x18975d0`) from block `+0`, `+0x60`, `+0xc0`. A slot's flags u16 are at `+0x1548` (bit 0 hovered, bit 1 focused, bit 2 disabled), its frame at `+0xbb0` (colour at frame `+0x48`). Hovered index `view + 0x8310` (set to -1 then hit-tested every frame by the view update `0x18980b0`, with no header bit-2 skip; hover sound 0x56fa2864 on enter; redraw `0x1897300`), focused `+0x8314`, active `+0x831c`. The click opens the list while the view is active, confirm fired, mouse mode, hovered != -1. A weapon pick only sets the slot's item: no slot is re-made.
- **The button**: a plate of the game's fill (19.8 units high, anchored at the slot's top centre, its width fitted to the label), a label and a 16.2 x 16.2 box at the plate's right end: `check_no_no_curve` tinted grey or `check_yes_no_curve` (0x57a71f86fac394aa) tinted the clear X's red (0.694, 0.078, 0). The game itself tints that check yellow (1, 0.914, 0) in its HUD's stratagem rows (`0x1865900`). Hover sound 0x65e34ad8 and toggle sound 0x468c8e58, the game's check box rows.
- **A text label from scratch**, made as the game makes the slot grid's "MISSION STRATAGEMS" title (`0x189433d`): `label_init` `0x143afa0` on 0x2b8 bytes (widget type 7) inside the parent's context (the font setter reads the context), `set_label(w, 0xc67c7faf)` (the #COUNT template, a pure tag) and `set_string_arg(w, 0xab2a7b35, char *)` `0x143c950` with the mod's text (the label keeps the pointer: keep the buffer alive), `font_set(w, 4, 0, 0, 1.0, 0)` `0x11f79b0`, font size `0x143c0b0`, layer, opacity, attach, then the parent's child refresh `0x144c2c0`. After the context pop, `widget_measure` `0x144e1a0` lays the label out and `+0x0c` holds its width and line height. There is no alignment setter: right alignment comes from pivot (1, 0.5). The game does not upper-case label text; the mod does.
- **Hover and click** as with the X (the view's hovered index written as -1 while a button is hovered). The view hit-tests its slots every frame and set-hover off would replay the hover sound, so the slot is only redrawn unhovered: the mod clears the hover bit for one call of the game's redraw `0x1897300` and sets it back.
- The choices are kept in `FlexibleLoadouts.settings` in the loader's log folder (one `key<TAB>value` line each, written through a `.tmp` file with the old one kept as `.bak`): `0|1` for each toggle, and `pinned` with the pinned stratagems' item ids.

## Pinned stratagems

A pin on the hovered (mouse) or focused (controller) stratagem of the list, and on every pinned one; a click on it or the Action key pins or unpins. Pinned stratagems come first in their group. Not yet confirmed in game.

- **How the list is built** (from the code): only when it opens, by the rebuild `0x18d8710(list grid, item of the slot, block)` (its only caller is the opener `0x146e9d0`); the refresh after an equip (`0x18d1890`) only rewrites the selectable bytes and the equipped look by offer id. The rebuild takes the owned stratagems (types 1 to 0x95 passing `0x136fc20(offers, type)`) and sorts them with qsort (comparator `0x18d86e0`): StratagemInfo `+0xb8` (hud_type: offensive, supply, defensive, ...), then `+0x188` (an unnamed enum), then the type. Each is added with `0x18d43a0(list, offer, hud_type, selectable, byte2)`; a new hud_type starts a new group and row. Groups: count `list + 0x92748`, first positions `+0x927d0[g]`; a group's header text comes from its first offer's hud_type, so any member gives the same header.
- **Arrays by list position** (count `+0x92984`, up to 256): offer ids `+0x92990`, selectable bytes `+0x92dc2`, a second byte `+0x92ec2` (dims the cell; the controller confirm refuses it; probably "locked"). Kind 3 (stratagems) does not use the per-position records at `+0x92ff8`.
- **Pages are row widgets, reused**: 12 pages at `list + 0xb00 + p * 0xaed0`, 4 cells each (`list + 0xc10 + p * 0xaed0 + c * 0x2b68`, 80 x 80 units; offer id at cell `+0x2b5c`; a page's cell count at `+0xb9b4`); page p shows row `first + p` (first visible row `+0x928d8`, pages in use `+0x91f0c`). A page-to-row cache (`+0x92718`, one u32 a page) lets the layout `0x18d2b60` skip pages whose row did not change. The cells are real widgets made once (`0x18c9970` through widget_init, so `+0xf8` holds their GUI context); scrolling and rebuilds only rebind them, so a child picture must follow its cell's current offer.
- **Reordering**: right after each build the mod moves the pinned offers to the front of their group (ids, selectable and second bytes together, inside the group only, so rows, headers, row heights and the scroll range stay valid), writes the page cache to -1 and calls the layout, which rebinds every visible cell from the arrays (icon, equipped look, dim, the selected highlight by id, the focus bits by position). The focused offer (`+0x92988`) is read first and focused again with `0x18d1280(list, offer)`, then the details panel is told with `0x18d7210(list grid)`, as the game does after a focus change. Cells and ids must agree: the mouse pick reads the offer from the cell but the equip reads the ids.
- **Hover and click**: the hover pass `0x18d0690` sets the hovered page `+0x928dc` and its column (`+0xb9bc` of the page) and plays a hover sound on every change (so writing -1 there, the X's way, would play it every frame). The mouse press `0x18cf930` reads the hovered cell's selectable byte and refuses (no sound, no focus change, no pick) on 0. So while a pin is hovered the mod writes that byte 0 each frame, and puts it back with the game's marker `0x18d1440(list, offer, byte)` when the pin is left. Mouse mode for the list is `[0x347cf18] + 0xe1ad4` set and `+0xe1ad5` (pad) clear; the list grid's state words (`list grid + 0x178c88`, `+0x178c8c`, the details panel) are 0 while it is browsed normally.
- The pin is the game's map waypoint (`content/ui/mission/hud/map/waypoint`, 0xea6c3908c95dd015) on the X's plate, used only when `Application.can_get` says it is loaded.

## Randomize Lineup

A small button (the game's `content/ui/shared/misc/refresh_icon`, 0xb279857f186a3b76, on the X's plate) at the bottom of the seam between the 4th stratagem slot and the booster, and the Action key on the booster slot, fill the four slots one at a time with a lineup. Not yet confirmed in game.

- **Classes from the game's data**: StratagemInfo `+0xb8` hud_type gives the colour (0 red, 2 blue, 3 green; 1 and 4 the yellow mission ones): the game's colour table `0x331b610` indexed by it is read by the slot setter `0x1893600`, and its pick sounds by colour (`0x18d0210`: 0x1a077fd1 red, 0x7200dc32 blue, 0x2d36b8b8 green) switch on it. Neither the category (`+0x3c`) nor the beacon colour gives the colour. Blue splits by info_flags `+0x104` (typelib bit names): support weapon 0x1, backpack 0x8, vehicle 0x20 (with the kind bits 0x100000 mech, 0x200000 FRV, 0x400000 tank), expendable 0x10000. A support weapon with the backpack bit comes with its own backpack.
- **Owned and available**: the owned check `0x136fc20(offers, type)` (enabled and selectable info, an offers entry for the item in state 2 or 4) is what the list and the ready handler use; the list is exactly the owned types. An offer whose record byte `[0x347cef8] + 0x1d99 + record * 0xb8` is set (an online override: a temporary ban) still shows but the press refuses it, so the mod leaves those out. A slot the mission takes away carries flag bit 2.
- **Writing a slot**: `0x189d050(panel, slot, item id)` turns the item into a type and sets the slot widget; while the grid is active it also sends the slot to teammates (RPC 0x1c826120, whose handler updates that slot and plays 0xb345f657). Then `0x189d120(panel, -1)` and the save, as for a clear. A later slot holding the same stratagem (or a vehicle, when a vehicle goes in) is emptied first, so the loadout never holds a repeat or two vehicles.
- **The booster slot** is the slot grid's index 4 (hovered `grid + 0xd968`, focused `+0xd96c`) and its own widget at `grid + 0x8af8` (80 x 80, flags `+0x3c0`), anchored at the grid's right; it touches the 4th slot's widget (the plates are 10 units apart). The button is a child of the booster widget at its bottom-left corner (anchor (0, 0), y up), straddling the seam, so it hides and shows with the stratagem grid; while it is hovered the slots' hovered index is written -1 as for the X.

## Weapons left behind

The loadout itself can't hold "none" for a weapon (dead ends below), so the mod acts in the mission on the local Helldiver only, the way OnlyTanks' Holster empties a slot. Leaving the primary out works solo in game: the Helldiver comes out of the pod with the secondary in hand, and switching, resupplies, ledges and objectives keep the primary away. Leaving both weapons or the grenades out, reinforcing, and what teammates see are not yet confirmed in game.

- **The local avatar**: game state `[[0x3326340] + 0xac21c] == 4` in a mission; players `[0x3326468]`, local player `+0x88`, network id `+0x3a8` -> entity through `0xfd9ba0` (the entity owner `[0x346bf98]`) -> avatar index (avatar manager `[0x3326d20]`, its entity map) -> selection controller (`avatars + 0x53dcd0 + index * 0x1238`; its entity must be the local one). This is the game's own local-avatar check `0xa40070`.
- **The mission inventory** `[0x3326738]`: an entity -> row map (`+0x28`, capacity `+0x30`), rows at `+0x50`, 48 bytes each: `+0` primary, `+4` secondary, `+8` support, `+0xc` backpack, `+0x10` held, `+0x14` carried, `+0x18` melee, `+0x1c` selection (0 = unarmed), `+0x28` throwable; owner descriptors at `+0x40` (entity `+8`, network id `+0x10`); grenade counts at `[inv + 0x58] + index * 8`. The wielder `[0x3326420]`: hand 0 holds the weapon in hand. The death test `0x927050(health manager, entity)` (health manager `[0x3326688]`, life state `+0x19c` of 2 or more).
- **Putting a weapon away**: the game's own selection request `0xa93e90(controller, slot)` for the first weapon kept (the other one, else the support weapon, else 0 = unarmed, which takes the game's holster path), only while `0xa92bc0(controller)` allows a switch and nothing is held or carried. Once the weapon is out of hand its slot is written 0 and the entity kept. The game refuses a switch to an empty slot and resupplies skip one.
- **After a throw** (`0xa97a40`): after a stratagem the game requests the controller's previous slot (`controller + 8`), after a grenade another grenade while the count holds one, else the last weapon slot (`controller + 0xc`); closing the stratagem menu without a throw (`0xa8fb50`) also requests the previous slot. The request `0xa93e90` copies the slot requested before into the previous slot only when it is 1-4 (into the last weapon slot when 1-3), so from unarmed (0) both keep naming the weapon left behind. A request for an empty slot is refused (the requested slot reset to the current selection), and the Helldiver stays in the throw pose holding nothing; the stratagem menu (`0xa8f570`) requests slot 5 only when the selection isn't 5 already, so it no longer opens either (seen in game). The mod therefore writes its own fallback (the other weapon, the support weapon, or 0 = unarmed, a valid request: the game's holster path) into either field when it names an empty weapon slot.
- **A dropped weapon with nothing to switch to**: the drop (`0xa95f30` -> `0x9af090` -> `0x9ae6e0`) drops the support weapon (`0x9a8840`), empties its slot and, when it was selected, writes the selection 0 directly; then, for the selected slot, it requests the controller's previous slot (unless it is that slot, 0 or 5), else the primary. With the weapons left behind that request is refused, nothing wields over the hand, and the dropped weapon stays wielded (seen in game: it fires from the ground). The mod releases a weapon that stays in hand for a few frames while the row no longer holds it with the game's own hand release `0x785d10(_, avatar, entity, 0)` (the drop's own call, send 0), then asks for the fallback when it is a weapon (not yet confirmed in game).
- **Teammates** (not yet confirmed in game): each machine runs the weapon code on its own copy of the row, and the state handlers force slot 1, so after each change the mod sends the game's own inventory message (`0xbe3f40`, RPC 0x42729286, an empty slot as 0x7fff, as the game sends an empty support slot at every spawn) and selection message (`0xbeb660`, RPC 0xa4617570) to every other peer (target -2).
- **Grenades** (not yet confirmed in game): the count written 0 and the game's count event `0xfd97e0(owner network id, 0xd92082f9, &count)` posted so the HUD follows; again after each refill.
- The entity -> descriptor lookup `0xfd9d40(entity)` returns NULL once an entity is gone; the inventory's destroy-all `0x9ae530` destroys through `0xfdc310(entities, entity)` (host-authoritative: a client's request goes to the host).

## Other game data

Findings about the stratagem systems that the current code does not use but that may help others.

- **StratagemInfo** (400 bytes; the typelib has no member names, so offsets come from aligning it with the older community JSON by type shape): `+0x0` type, `+0x4` item id, `+0x10` debug_name (char *), `+0x3c` category, `+0x50` uses, `+0x64` extra_travel_time, `+0x68` cooldown_duration_success (f32), `+0x70` origin_type, `+0x94` cooldown_type (0 Individual, else shared), `+0xb8` hud_type, `+0xbc` cost, `+0xc4` depends_on, `+0xc8` additional_stratagem, `+0xcc` max_in_loadout (u32), `+0x104` info_flags (support weapon 0x1, backpack 0x8, vehicle 0x20, expendable 0x10000, the vehicle kinds 0x100000 mech, 0x200000 FRV, 0x400000 tank), `+0x188` the list's second sort key. The stratagem table is a pointer array at `0x37cb600` indexed by type (a default info at `0x37cb470` for type 0); types run 1 to 0x95.
- `max_in_loadout` is 0 for every stratagem except Eagle Rearm and Carpet Bombing Run (1); it is not the one-of-each rule. It caps the `additional_stratagem` entries the mission start adds (that is why several Eagles add one Eagle Rearm).
- **The synced loadout** `[0x347ce50]` (also the player history system): player count `+0x2d200`, players at `i * 0x1690`: peer id `+0` (u64), primary `+0x38`, sidearm `+0x98`, throwable `+0xf8` (0x60 each), stratagem entries `+0x1c0` (48 bytes, up to 32), count `+0x7c0`. Entry: type `+0`, uses left `+4`, flag byte `+9`, cooldown start `+0x10`, end `+0x18`, base `+0x20`, times in microseconds on the scene clock `[0x3326348] + 0x18`. Every peer keeps every player's list. The local peer id is `[0x347cef0] + 0xb398` (the host's `+0xb3a8`).
- Writers: `rpc_sync_stratagems` (`0x670530`, `0xb87a70`) and `rpc_sync_stratagem_changes` (`0xb9b040`, `0x135c810`) carry a count and up to 16 types per peer; the builder `0x11e82d0` copies them as sent. The mission start `0x6ae1f0` prepends the mission type's stratagems (table `0x213f550`, up to 6 per mission type), then appends each entry's `additional_stratagem`; uses come from `0x879550(profile, peer, type)`.
- Using a stratagem (`0xb9a6d0(peer, entry index, ...)`, `0x135c2c0`) starts the cooldown of that entry index: start = now, end = duration * 1e6 + base. The Eagle family (type 0x31 Eagle Rearm, or `additional_stratagem` 0x31) shares the rearm timer, and a stratagem with a shared cooldown type has end, start and base copied to every entry of its type in every player's list. A client writing its own list's cooldown fields holds: the host's syncs only raise them.
- The per-player profile record (`[0x33264f8] + 0xa7c + i * 0x40`, saved by `0x87b7b0`) is cosmetic (body type, helmet, cape, armour, booster `+0xa8c`, victory pose, player card, title); the stratagem picks live in the ship inventory.

## Dead ends and gotchas

- **No "none" weapon in the loadout** (from the code): a saved 0 becomes the default weapon when `0x17514c0` rebuilds the block (Liberator 0xaa035309, Peacemaker 0xa7977f98, G-12 0xbe376ea8); an unknown id null-dereferences the weapon-change request `0x13656f0`, which the Hellpod reset `0x1470740` sends for all three weapons; and the loadout sender `0x13620a0` skips zero weapons (`test ebx, ebx; je` at 0x13622a8), so receivers would get the later weapons shifted into the earlier slots.
- **No "none" cape** (from the code): unknown ids become the default cape and -1 leaves the avatar undressed on every peer; the game's local hide `0x832b90(_, avatar entity, visible)` affects only the player's own view.
- Clicking the slot grid can't be blocked by setting a slot's disabled bit (the player could no longer click it), and zeroing a flash byte early skips the widget's end-of-flash call (`0x18932f0`). A one-frame disabled bit during the Ready press does not work either: the game handles the press before the Lua update.
- Engine and loader gotchas met here: the main chunk of a Lua script can hold at most 200 locals (LuaJIT), so large mods need `do` blocks; all Bingus Shared Loader addons share one LuaJIT state and so one FFI namespace, where a C function keeps its first declaration, so the mod declares Windows functions under its own names (`flo_ReadProcessMemory __asm__("ReadProcessMemory")`, and so on).
- Renames: a mod keeps its guid so mod managers update it in place, but HD2 Arsenal keeps the Name of a player's first import, and a Mod Bindings Menu binding id keys players' saved bindings, so it must not change.
- Ghidra labels the item -> type mapping `0x11f2490` as 0x1212490; the RVA here is the right one.

## Signatures

`research/signatures.py` defines 88 code signatures (6 required, 82 optional), built against a game.dll dump and checked to match exactly once, and writes them into `flexible_loadouts.lua` together with the shared signature engine. Each is tried at this build's address first, else game.dll's executable sections are searched a few MB per frame. Values (globals, offsets, call targets, constants) are read from the matched instructions; repeated values must agree within and across signatures, and calls must reach the functions found on their own. A failed required signature turns the mod off; a failed optional one turns off only the feature that needs it. Each feature's signatures carry field names of their own and are cross-checked against the core's, so a disagreement turns off that feature alone.

| Signature | RVA | Gives |
|---|---|---|
| `screen` | 0x1082ef0 | the screen stack global, the loadout screen slot, the local index |
| `category` | 0x146e0bc | the menu category offset |
| `refresh_call` | 0x146e677 | the list, block base and stride, the refresh |
| `refresh_a` | 0x18d194f | list count, selectable bytes, block count and entries, the stratagem table |
| `refresh_b` | 0x18d19c5 | the offers table, its stratagem range and entries, the marker |
| `offers_count` | 0x146e1cf | the offers table's count |
| `ready_call` | 0x146d9fb | list open, panels, the ready handler |
| `ready_slots` | 0x189c3b8 | slot flags, flash byte, slot stride, UI sound |
| `ready_toggle` | 0x189c4d0 | players, flags, ready timer and times, ready sounds |
| `ready_emote` | 0x189c552 | the panel's unit, the two pose events, the emote call |
| `emote_send` | 0xbf2e20 | the pose RPC, the send core |
| `ready_entry` | 0x189c25a | the READY prompt offset, the press check call |
| `ready_press` | 0x1891850 | the UI input global |
| `equip_tail` | 0x146e5f6 | slots written, list and grid refresh, save, slot search, close, focus, edited slot, the last stratagem type |
| `open_list` | 0x146e9d0 | the list opener |
| `set_slot` | 0x189d050 | slot widget base and stride, the widget setter |
| `list_update` | 0x18cf84f | the list's scroll and its limit, the layout |
| `list_focus` | 0x18d1280 | the list's offer ids, focus without scrolling |
| `focus` | 0x1895770 | the grid's focused slot |
| `slot_hover` | 0x1893550 | cursor widget, hit test, slot flags, redraw, set-hover |
| `widget_mark_dirty` | 0x144d200 | the dirty mark (parent link) |
| `widget_fade`, `widget_fade_tail` | 0x1450dd0, 0x1450f47 | the fade helper, opacity field, tween slots, opacity setter, tween |
| `grid_click` | 0x18952fe | grid active, action mapper, press bytes, hovered slot, input, mouse mode, focus |
| `screen_gates` | 0x146d443 | the screen's input gates |
| `grid_gates` | 0x146da3c | active group, panel stride, panel gates, grid mode, grid and view inputs |
| `view_hover` | 0x18980fd | the equipment view's hover: pad mode, hovered index, slot stride, redraw |
| `view_click` | 0x1898631 | the view's click: active, hovered, focused |
| `view_slots` | 0x18991b4 | the weapon slots in the view |
| `view_slot_redraw` | 0x1897300 | the view slot's flags, plate, frame |
| `view_transition` | 0x18999f0 | the transition byte and the mode |
| `label_title` | 0x189433d | the game's title label build: label and widget calls, font, size, layer, colour |
| `label_init` | 0x143afa0 | the label's type and fields |
| `label_text_call` | 0x190a7a2 | set_label, the #COUNT key, set_string_arg |
| `font_set` | 0x11f79b0 | the font records and materials |
| `widget_measure` | 0x144e1a0 | label layout |
| `gui_fill_build` | 0x11f5236 | the game building a gui_fill picture: seven widget calls |
| `picture_init`, `widget_material_set`, `widget_size_set`, `widget_position_set`, `widget_anchor_set`, `widget_pivot_set`, `widget_color_set`, `widget_opacity_set`, `widget_layer_set`, `widget_rotation_set`, `widget_attach`, `widget_destroy` | 0x143eab0, 0x144f800, 0x1447160, 0x14476a0, 0x144f160, 0x144f0d0, 0x1448690, 0x1448ad0, 0x14491f0, 0x1448ef0, 0x144c5c0, 0x144dd70 | the widget functions by their first instructions |
| `widget_init` | 0x1446840 | the GUI context stack, the widget's context and parent fields |
| `ui_context` | 0x12ef4b0 | context push (pop 0x20 further) |
| `widget_children` | 0x144c5c0 | first child, next sibling, parent |
| `local_avatar` | 0xa40076 | players, local player, network id, unit lookup, avatar manager and map |
| `unit_lookup` | 0xfd9ba0 | network id -> entity |
| `inv_selection` | 0x9a84a0 | the inventory global, its map, rows and selection |
| `throw_count` | 0x9adc79 | grenade counts, the count event, owner descriptors |
| `select_request` | 0xa96209 | selection controllers, the selection request |
| `throw_return` | 0xa98006 | the controller's previous and last weapon slots |
| `can_switch` | 0xa92bc0 | "may switch weapons now" |
| `is_dead` | 0x927050 | the death test |
| `health` | 0x4a441a | the health manager global |
| `game_state` | 0x9aa9ec | the game state and its mission value |
| `wielder` | 0x785d28 | the wielder's map and hands |
| `hand_release` | 0x785d10 | the wielder's hand release |
| `inv_rpc` | 0xbe3f40 | the inventory message |
| `sel_rpc` | 0xbeb660 | the selection message |
| `entity_lookup` | 0xfd9d40 | entity -> descriptor |
| `weapon_destroy` | 0x9ae5c2 | the entity destroy (a test aid; no feature uses it) |
| `list_add` | 0x18d4410 | the list's group count and first positions, ids, selectable and second bytes |
| `list_pages` | 0x18d2fb3 | pages in use, page base and stride, the page cache |
| `list_cells` | 0x18d0700 | cells: first cell, stride, a page's cell count and hovered column |
| `list_mode` | 0x18cf99d | the list's mouse and pad bytes |
| `list_press` | 0x18cf9ff | the hovered page, the first visible row |
| `list_bind` | 0x18cafb0 | a cell's offer |
| `list_focused` | 0x18d1400 | the focused offer |
| `list_grid_hover` | 0x18d58a0 | the details panel state, the hover pass |
| `list_grid_input` | 0x18d5af2 | the list grid's state, the press |
| `list_preview` | 0x18d5e62 | focus and the details panel after a pick |
| `pick_ban` | 0x18d8b92 | the offer record's ban byte and stride |
| `pick_record` | 0x18d8bf1 | StratagemInfo hud_type |
| `hud_colour` | 0x189363f | hud_type, the colour table |
| `kind_frv`, `kind_mech`, `kind_tank` | 0x146e306, 0x146e411, 0x146e4f8 | info_flags and the vehicle kind bits |
| `ready_owned` | 0x189c345 | the owned check and the type loop's end |
| `booster_focus` | 0x1895785 | the booster widget |
| `booster_redraw` | 0x1893bf0 | the booster's flags |
| `pick_sound` | 0x18d0311 | the pick sound of each colour |

## Prior art and credits

- [Holster](https://github.com/OnlyTanks/HD2-Holster) by OnlyTanks showed that a Helldiver can be made unarmed mid-mission with the game's own inventory switch, and that teammates see it; its local-avatar chain and its use of the game's inventory switch informed the weapons left behind. It has no license, so only these facts are used; no code of theirs is used.
- [HD2-Transmog](https://github.com/tyrypyrking/HD2-Transmog) by tyrypyrking: its map of the loadout screen's card graph located the player panels. Facts only; no code of theirs is used.
- [HD2Runtime by SkyeShade](https://github.com/SkyeShade/HD2Runtime): the health manager global (`[0x3326688]`, in its record getter `0x4a4410`); its stratagem list confirmed the owned check and the classes Randomize Lineup reads.
- The native widget technique (the game's own widgets, the gui_fill material, the widget function set) follows HD2 HUD+, through the author's Helmet Passives Reborn; the local-avatar check and the owner's unit map follow the author's Ragdoll on Command.
- Built on [Bingus Shared Loader](https://github.com/CowboyBingus/BingusSharedLoader) and [Mod Bindings Menu](https://github.com/CowboyBingus/ModBindingsMenu) by CowboyBingus, whose `bingus_text.lua` provides the translations.

## Research tools

- `research/signatures.py`: the signature spec; builds and checks every signature against a game.dll dump and writes the signature and engine blocks into the script (`--check` only verifies).
- `tests/test_release.py`: the offline tests: the built entry under LuaJIT against a game.dll dump (not included), with the loadout screen, stratagem list (groups, pages and cells), ready panel, widgets, mission inventory and Mod Bindings Menu simulated.
