"""Player verbs.

Every function returns the energy cost of the action, or ``0`` when nothing
happened and no time should pass.
"""

from __future__ import annotations

from typing import Optional

from ..data import items as item_data
from ..data.calendar import TICKS_PER_HOUR
from ..engine.fov import line_of_fire
from ..engine.scheduler import ACTION_COST
from ..world import tiles as tile_data
from . import combat, crafting, medical, swimming
from .item import Item

FREE = 0
NORMAL = ACTION_COST
SLOW = ACTION_COST * 2


def read_book(game, item) -> int:
    """Read a book or a slab through, and take what is in it.

    Reading is not free. A deep book with a poor reader is most of a day in a
    place where nothing is trying to kill you, which is exactly what makes a
    library somewhere safe worth having.
    """
    from . import books

    p = game.player
    book = books.of(item)
    if book is None:
        game.log.info("There is nothing written on it.")
        return FREE
    if not books.can_read(p):
        game.log.warn("You cannot make out the letters.")
        return FREE
    if game.hostiles_in_sight():
        game.log.warn("Not with company.")
        return FREE

    turns = books.read_turns(p, book)
    for line in books.read(game, p, book):
        game.log.info(line)
    p.needs.fatigue += turns // 20
    return turns


def perform(game, form) -> int:
    """Perform a form to whoever is standing there.

    The audience is whoever can see you, which means performing in an empty
    field is practice and performing in a tavern is a living. A tavern crowd
    that liked it throws coins, and that is the only income in the game that
    does not involve killing something or selling what it was carrying.
    """
    from ..world import artforms
    from . import performance

    p = game.player
    audience = [c for c in game.visible_creatures()
                if not c.is_hostile_to(p) and p.distance_to(c) <= HEARING]
    result = performance.perform(game, game.rng, p, form, audience)
    for line in performance.describe(result):
        game.log.good(line) if result.good else game.log.info(line)

    if not result.audience:
        game.log.info("Nobody was listening.")
        return performance.PERFORM_TURNS
    _applaud(game, result)
    return performance.PERFORM_TURNS


#: How far a performance carries. Further than a conversation, not as far as
#: a scream.
HEARING = 8


def _applaud(game, result) -> None:
    """The audience's answer: coins, renown, or somewhere else to be."""
    from . import performance, renown

    p = game.player
    in_tavern = (game.local is not None
                 and game.local.tile(p.x, p.y, p.z) == "tavern")
    if result.band >= 4:
        thrown = sum(_throw(game, c, result.band, in_tavern)
                     for c in result.audience)
        result.coins = thrown
        if thrown:
            _pay(game, thrown)
            game.log.good("Coins land at your feet. You gather %d." % thrown)
        from . import standing as standing_mod

        standing_mod.did(game, "performance", seen_by=result.audience)
        gained = renown.add(game, result.band - 3)
        if gained and result.band >= performance.LEGENDARY_AT:
            game.log.good("They will talk about that for years.")
    elif result.band == 0:
        game.log.warn("Somebody tells you to sit down.")


def _throw(game, listener, band: int, in_tavern: bool) -> int:
    """What one listener parts with. Most people part with nothing."""
    odds = 0.20 + 0.14 * (band - 4)
    if in_tavern:
        odds += 0.25
    if not game.rng.chance(min(0.9, odds)):
        return 0
    purse = listener.inventory.coins() if listener.inventory else 0
    return max(1, min(purse, game.rng.randint(1, 3 + band * 2)))


def _pay(game, coins: int) -> None:
    """Put thrown coins in the player's purse."""
    from ..data import items as item_data
    from .item import Item

    stack = game.player.inventory.by_def("coin")
    if stack:
        stack[0].count += coins
        return
    item = Item(item_data.get("coin"), "copper")
    item.count = coins
    game.player.inventory.add(item)


def set_fire(game) -> int:
    """Put the torch you are carrying to whatever is next to you.

    The torch has been burning since v1 and the tile table has had FLAMMABLE
    on the tree, the sapling and the shrub for just as long. This is the line
    that joins them.
    """
    from ..engine.geometry import DIRS8
    from ..world import fire as fire_mod

    p = game.player
    # A lit torch, or the tool that exists to start one. `flint_and_steel`
    # has been tradeable and lootable since the item table was written and
    # had never once been asked for.
    if not fire_mod.carrying_flame(p) and not p.inventory.by_def("flint_and_steel"):
        game.log.info("You have nothing to strike a light with.")
        return FREE
    for dx, dy in ((0, 0),) + tuple(DIRS8):
        cell = (p.x + dx, p.y + dy, p.z)
        if fire_mod.fuel_at(game.local, cell) <= 0:
            continue
        extra = fire_mod.item_fuel(game.items_at(*cell))
        if game.fire.ignite(game.local, cell, extra=extra):
            game.log.warn("It catches, and begins to burn.")
            return NORMAL
    game.log.info("There is nothing here that will take a flame.")
    return FREE


def disarm_trap(game) -> int:
    """Take apart a trap you have found, next to you or under you."""
    from ..engine.geometry import DIRS8
    from . import traps as traps_mod

    p = game.player
    for dx, dy in ((0, 0),) + tuple(DIRS8):
        cell = (p.x + dx, p.y + dy, p.z)
        trap = traps_mod.at(game, cell)
        if trap is None or not trap.found or not trap.armed:
            continue
        ok, said = traps_mod.disarm(game, cell)
        game.log.good(said) if ok else game.log.warn(said)
        return SLOW
    game.log.info("There is no trap here you know of.")
    return FREE


def ride_or_dismount(game) -> int:
    """Get on whatever is next to you, or get off what you are on."""
    from . import mounts

    p = game.player
    if mounts.mounted(game):
        _ok, said = mounts.dismount(game)
        game.log.info(said)
        return NORMAL
    animal = _adjacent_animal(game, mounts.is_mount)
    if animal is None:
        game.log.info("There is nothing here to ride.")
        return FREE
    ok, said = mounts.ride(game, animal)
    game.log.good(said) if ok else game.log.warn(said)
    return NORMAL if ok else FREE


def tame_animal(game) -> int:
    """Try to win over an animal standing next to you.

    It takes a real turn whether or not it works, because an animal that shies
    away from you has still taken your afternoon.
    """
    from . import mounts

    animal = _adjacent_animal(game, mounts.is_trainable)
    if animal is None:
        game.log.info("There is no animal here to tame.")
        return FREE
    ok, said = mounts.tame(game, animal, game.rng)
    game.log.good(said) if ok else game.log.info(said)
    game.player.needs.exert(20)
    return SLOW


def _adjacent_animal(game, pred):
    """The nearest animal beside the player that passes *pred*."""
    from ..engine.geometry import DIRS8

    p = game.player
    for dx, dy in DIRS8:
        c = game.creature_at(p.x + dx, p.y + dy, p.z)
        if c is not None and c.alive and pred(c):
            return c
    return None


def raise_dead(game) -> int:
    """Use the secret, if you have it and there is anything to use it on.

    All of this is v3.5's machinery. It was written to take any creature and
    any world, so the only thing a player who has read the slab needs is a key
    to press.
    """
    from . import night

    p = game.player
    if not night.is_necromancer(p):
        game.log.info("You do not know how.")
        return FREE
    corpses = night.corpses_near(game, p.x, p.y, p.z)
    if not corpses:
        game.log.info("There is nothing here to raise.")
        return FREE
    item, cell = corpses[0]
    risen = night.raise_corpse(game, p, item, cell)
    if risen is None:
        game.log.info("Something is standing on it.")
        return FREE
    game.log.warn("%s gets up." % risen.name)
    p.add_exp("knowledge", 60)
    return NORMAL


def toggle_sneak(game) -> int:
    """Start or stop moving quietly.

    Free: deciding to be careful is not an action, it is a posture. What it
    costs you is speed, light and the ability to run, all of which the rest of
    the game charges for on its own.
    """
    from . import stealth

    p = game.player
    on = stealth.set_sneaking(p, not stealth.is_sneaking(p))
    if on:
        game.log.info("You move quietly.")
        if stealth._carrying_light(p):
            game.log.warn("Your light gives you away. Douse it with ~.")
    else:
        game.log.info("You stop sneaking.")
    return FREE


def _step_on_the_graph(game, creature, nx: int, ny: int):
    """Where a step onto ``(nx, ny)`` lands, if the walker's graph has it.

    `LocalMap.neighbours` is the rule for what a walker can do -- level
    ground, up a ramp it is standing on, down onto a ramp on the level below,
    and either way along a staircase -- and its edges are deliberately
    symmetric so that A* cannot route anybody somewhere they cannot get back
    from. Every creature in the game is moved by it.

    This used to reimplement the up half of that rule and nothing else, which
    made the player the only thing on the map that could not walk downhill.
    Measured over eight adventurer lifetimes: 764 free steps attempted, 360
    refused, and 184 of those 360 were steps any wolf standing on that tile
    could have taken. Asking the graph is not the same as copying it.
    """
    if game.local is None:
        return None
    here = (creature.x, creature.y, creature.z)
    for cell in game.local.neighbours(*here):
        if (cell[0], cell[1]) != (nx, ny) or cell[2] == here[2]:
            continue
        if game.creature_at(*cell) is not None:
            continue
        if not game.is_passable(cell[0], cell[1], cell[2], creature):
            continue
        return cell
    return None


def move_or_attack(game, dx: int, dy: int) -> int:
    """Walk one step, or attack whatever is in the way."""
    from . import webs

    p = game.player
    if webs.caught(game, p):
        # Struggling is the move. You do not get to also walk out of it.
        _free, said = webs.struggle(game, p, game.rng)
        if said:
            game.log.warn(said)
        return NORMAL
    was = (p.x, p.y, p.z)
    nx, ny, nz = p.x + dx, p.y + dy, p.z
    if not game.local.in_bounds(nx, ny, nz):
        game.log.warn("You have reached the edge of the area. Travel to move on.")
        return FREE

    target = game.creature_at(nx, ny, nz)
    if target is not None:
        if p.is_hostile_to(target) or target.is_hostile_to(p):
            result = combat.melee_attack(p, target, rng=game.rng,
                                         log=game.log, world=game)
            if target.body.dead:
                game.kill_creature(target)
            p.needs.exert(8)
            return result.cost
        game.log.info("%s is in your way." % target.display_name())
        return FREE

    tile = tile_data.get(game.local.tile(nx, ny, nz))
    if tile.has("DOOR") and not tile.has("OPEN"):
        game.local.set_tile(nx, ny, nz, "door_open")
        game.log.info("You open the door.")
        return NORMAL

    if not game.is_passable(nx, ny, nz, p):
        step = _step_on_the_graph(game, p, nx, ny)
        if step is None:
            if tile.has("WALL"):
                game.log.info("There is %s in the way." % tile.name)
            elif tile.has("WATER"):
                game.log.warn("You are in no state to swim that.")
            else:
                game.log.info("You cannot go that way.")
            return FREE
        # Fall through on the cell the graph gave, so a step down a slope
        # goes over the same traps, items and water as a step along one.
        nx, ny, nz = step

    from . import traps as traps_mod

    # Stepping into thin air used to slide the player quietly down to the
    # first solid thing, however far that was. `move_creature` settles it now,
    # and charges for the drop.
    game.move_creature(p, nx, ny, nz)
    nx, ny, nz = p.x, p.y, p.z
    if p.body.dead:
        return NORMAL
    if traps_mod.cross(game, p, (nx, ny, nz)):
        return NORMAL
    traps_mod.step_on(game, p, (nx, ny, nz))
    traps_mod.look_around(game, searching=False)
    pile = game.items_at(nx, ny, nz)
    if pile:
        if len(pile) == 1:
            game.log.info("You see %s here." % pile[0].name(article=True))
        else:
            game.log.info("You see %d items here." % len(pile))
    site_tile = tile_data.get(game.local.tile(nx, ny, nz))
    if site_tile.has("WATER"):
        p.add_exp("swimming", 8)
    depth = swimming.depth_of(game.local.tile(nx, ny, nz))
    if swimming.is_swimming(depth):
        p.needs.exert(swimming.SWIM_EXERTION)
        if not swimming.is_swimming(
                swimming.depth_of(game.local.tile(*was))):
            game.log.warn("You wade off the bottom and start swimming.")
        return int(ACTION_COST / swimming.SWIM_SPEED)
    if swimming.is_swimming(swimming.depth_of(game.local.tile(*was))):
        game.log.good("You pull yourself out of the water.")
    p.needs.exert(2)
    return NORMAL


def move_z(game, dz: int) -> int:
    """Climb a staircase, by the same rule everything else on the map uses.

    The vertical twin of `_step_on_the_graph`, and it had the same defect:
    this re-derived its own idea of a climbable tile -- STAIR_UP under your
    feet to go up, STAIR_DOWN to go down -- while `LocalMap.neighbours`,
    which every creature in the game is moved by, also offers *the foot of
    a staircase coming down from above* and *the head of one going up from
    below*. Those edges are deliberately symmetric so A* cannot strand
    anybody; the player was the one walker refused them.

    Measured over three adventurer lifetimes in v4.15: `move_z` called 19
    times, standing on a plain STAIR_UP/STAIR_DOWN tile *none* of them, and
    refused 19 times. The player's climb command had never once worked in
    any run the project has ever made -- while every wolf and goblin walked
    those same edges, and the player reached other levels only sideways, by
    ramp. Asking the graph is not the same as copying it.
    """
    p = game.player
    step = 1 if dz > 0 else -1
    target = (p.x, p.y, p.z + step)
    if game.local is None or target not in set(
            game.local.neighbours(p.x, p.y, p.z)):
        game.log.info("There is no way up here." if step > 0
                      else "There is no way down here.")
        return FREE
    if not game.is_passable(target[0], target[1], target[2], p):
        game.log.info("The way up is blocked." if step > 0
                      else "The way down is blocked.")
        return FREE
    game.move_creature(p, *target)
    game.log.info("You climb up." if step > 0 else "You climb down.")
    p.add_exp("climbing", 10)
    p.needs.exert(6)
    return NORMAL


def wait(game, ticks: int = NORMAL) -> int:
    """Stand still for one action."""
    return max(1, ticks)


def rest(game, ticks: int) -> int:
    """Rest without sleeping, healing slowly."""
    p = game.player
    if game.hostiles_in_sight():
        game.log.warn("You cannot rest with enemies nearby.")
        return FREE
    p.body.rest_heal(ticks, p.attributes.factor("recuperation"))
    p.needs.fatigue = max(0, p.needs.fatigue - ticks // 2)
    game.log.info("You rest a while.")
    return max(1, ticks)


def sleep(game, hours: int = 8) -> int:
    """Sleep, healing and clearing fatigue."""
    p = game.player
    if game.hostiles_in_sight():
        game.log.warn("You cannot sleep with enemies nearby.")
        return FREE
    ticks = hours * TICKS_PER_HOUR
    p.needs.sleep(ticks)
    p.body.rest_heal(ticks, p.attributes.factor("recuperation"))
    game.log.good("You sleep for %d hours." % hours)
    return ticks


def pick_up(game, item: Optional[Item] = None) -> int:
    """Take something off the ground."""
    p = game.player
    pile = game.items_at(p.x, p.y, p.z)
    if not pile:
        game.log.info("There is nothing here to pick up.")
        return FREE
    target = item or pile[0]
    if not game.take_item(target, p.x, p.y, p.z):
        return FREE
    p.inventory.add(target)
    game.log.info("You pick up %s." % target.name(article=True))
    game.player_took(target)
    return NORMAL


def pick_up_all(game) -> int:
    """Take everything on this cell."""
    p = game.player
    pile = list(game.items_at(p.x, p.y, p.z))
    if not pile:
        game.log.info("There is nothing here to pick up.")
        return FREE
    for it in pile:
        game.take_item(it, p.x, p.y, p.z)
        p.inventory.add(it)
        game.player_took(it)
    game.log.info("You pick up %d items." % len(pile))
    return NORMAL


def drop(game, item: Item) -> int:
    """Put something down."""
    p = game.player
    p.inventory.unequip_item(item)
    removed = p.inventory.remove(item, item.count)
    if removed is None:
        return FREE
    if removed in p.inventory.items:
        p.inventory.items.remove(removed)
    game.drop_item(removed, p.x, p.y, p.z)
    game.player_gave_up(removed)
    game.log.info("You drop %s." % removed.name(article=True))
    return NORMAL


def equip(game, item: Item) -> int:
    """Wear or wield something."""
    ok, msg = game.player.inventory.equip(item)
    game.log.info(msg) if ok else game.log.warn(msg)
    return NORMAL if ok else FREE


def unequip(game, slot: str) -> int:
    """Take something off."""
    item = game.player.inventory.unequip(slot)
    if item is None:
        return FREE
    game.log.info("You remove %s." % item.name(article=True))
    return NORMAL


def eat(game, item: Item) -> int:
    """Eat food."""
    p = game.player
    if not item.is_edible:
        game.log.warn("You cannot eat that.")
        return FREE
    msg = p.needs.eat(item)
    game.log.info(msg)
    item.count -= 1
    if item.count <= 0 and item in p.inventory.items:
        p.inventory.items.remove(item)
        p.inventory.unequip_item(item)
    return NORMAL


def water_source_near(game) -> bool:
    """True if the player is standing on or beside drinkable water."""
    p = game.player
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            t = tile_data.get(game.local.tile(p.x + dx, p.y + dy, p.z))
            if t.has("WATER_SOURCE"):
                return True
            if t.has("WATER") and not t.has("DEEP"):
                return True
    return False


def refill_waterskins(game) -> int:
    """Top up every carried waterskin. Returns how many rations were added."""
    p = game.player
    skins = len(p.inventory.by_def("waterskin"))
    if skins <= 0:
        return 0
    capacity = skins * 4
    have = p.inventory.count_of("water_drink")
    if have >= capacity:
        return 0
    added = capacity - have
    p.inventory.add(Item("water_drink", "water", count=added))
    return added


def drink(game, item: Optional[Item] = None) -> int:
    """Drink, from an item or from water underfoot."""
    p = game.player
    if item is None:
        if water_source_near(game):
            p.needs.thirst = 0
            game.log.info("You drink your fill.")
            added = refill_waterskins(game)
            if added:
                game.log.info("You fill your waterskin.")
            return NORMAL
        water = p.inventory.by_def("water_drink")
        if water:
            item = water[0]
        else:
            # Anything else in the pack, before giving up. The fallback
            # reached exactly one item id, so an adventurer carrying four
            # skins of dwarven ale and no water was told there was nothing
            # to drink -- while `Needs.drink` takes any drink there is and
            # the loot tables hand out wine, rum, beer and mead.
            item = next((i for i in p.inventory.items if i.is_drink), None)
            if item is None:
                game.log.warn("There is nothing to drink here.")
                return FREE
    if not item.is_drink:
        game.log.warn("You cannot drink that.")
        return FREE
    msg = p.needs.drink(item)
    game.log.info(msg)
    item.count -= 1
    if item.count <= 0 and item in p.inventory.items:
        p.inventory.items.remove(item)
        p.inventory.unequip_item(item)
    return NORMAL


def open_close(game, dx: int, dy: int) -> int:
    """Open or close an adjacent door."""
    p = game.player
    x, y, z = p.x + dx, p.y + dy, p.z
    tid = game.local.tile(x, y, z)
    t = tile_data.get(tid)
    if not t.has("DOOR"):
        game.log.info("There is no door there.")
        return FREE
    if t.has("OPEN"):
        if game.creature_at(x, y, z) is not None:
            game.log.warn("Something is standing in the doorway.")
            return FREE
        game.local.set_tile(x, y, z, "door_closed")
        game.log.info("You close the door.")
    else:
        game.local.set_tile(x, y, z, "door_open")
        game.log.info("You open the door.")
    return NORMAL


def climb(game, dx: int, dy: int) -> int:
    """Climb an adjacent wall or tree."""
    p = game.player
    x, y, z = p.x + dx, p.y + dy, p.z
    t = tile_data.get(game.local.tile(x, y, z))
    if not t.climb:
        game.log.info("There is nothing to climb there.")
        return FREE
    if not game.is_passable(x, y, z + 1, p):
        game.log.info("You cannot get a purchase.")
        return FREE
    difficulty = 8 - p.skills.level("climbing") // 2
    if game.rng.randint(1, 20) + int(p.attributes.factor("agility") * 4) < difficulty:
        game.log.warn("You slip and fall back.")
        p.add_exp("climbing", 10)
        return NORMAL
    game.move_creature(p, x, y, z + 1)
    game.log.info("You climb up.")
    p.add_exp("climbing", 25)
    p.needs.exert(15)
    return SLOW


def attack_dir(game, dx: int, dy: int, *, part: Optional[str] = None) -> int:
    """Attack whatever is in a direction, optionally aiming at a body part."""
    p = game.player
    target = game.creature_at(p.x + dx, p.y + dy, p.z)
    if target is None:
        game.log.info("There is nothing there to attack.")
        return FREE
    result = combat.melee_attack(p, target, target_part=part, rng=game.rng,
                                 log=game.log, world=game)
    if target.body.dead:
        game.kill_creature(target)
    p.needs.exert(10)
    return result.cost


def wrestle(game, dx: int, dy: int, move: str) -> int:
    """Grapple an adjacent creature."""
    p = game.player
    target = game.creature_at(p.x + dx, p.y + dy, p.z)
    if target is None:
        game.log.info("There is nothing there to grab.")
        return FREE
    combat.wrestle(p, target, move, rng=game.rng, log=game.log)
    if target.body.dead:
        game.kill_creature(target)
    p.needs.exert(15)
    return NORMAL


def fire(game, tx: int, ty: int) -> int:
    """Shoot a ranged weapon at a spot."""
    p = game.player
    weapon = p.inventory.weapon()
    if weapon is None or not weapon.is_ranged:
        game.log.warn("You have no ranged weapon readied.")
        return FREE
    ammo = p.inventory.ammo()
    if ammo is None:
        ammo_id = item_data.ammo_for(weapon.defn)
        matches = p.inventory.by_def(ammo_id) if ammo_id else []
        ammo = matches[0] if matches else None
    if ammo is None:
        game.log.warn("You have no ammunition.")
        return FREE
    z = p.z
    path = line_of_fire(
        p.x, p.y, tx, ty, lambda x, y: game.local.blocks_sight(x, y, z)
    )
    target = None
    for x, y in path:
        c = game.creature_at(x, y, z)
        if c is not None and c is not p:
            target = c
            break
    if target is None:
        game.log.info("Your shot flies wide and is lost.")
        ammo.count -= 1
        if ammo.count <= 0 and ammo in p.inventory.items:
            p.inventory.items.remove(ammo)
            p.inventory.unequip_item(ammo)
        return NORMAL
    combat.ranged_attack(p, target, weapon, ammo, rng=game.rng,
                         log=game.log, ground=game)
    if target.body.dead:
        game.kill_creature(target)
    return NORMAL


def throw(game, item: Item, tx: int, ty: int) -> int:
    """Throw an item at a spot."""
    p = game.player
    z = p.z
    path = line_of_fire(
        p.x, p.y, tx, ty, lambda x, y: game.local.blocks_sight(x, y, z)
    )
    p.inventory.unequip_item(item)
    thrown = item.split(1) if item.count > 1 else item
    if thrown is item and item in p.inventory.items:
        p.inventory.items.remove(item)

    target = None
    landing = (p.x, p.y, z)
    for x, y in path:
        landing = (x, y, z)
        c = game.creature_at(x, y, z)
        if c is not None and c is not p:
            target = c
            break
    if target is not None:
        combat.throw_item(p, target, thrown, rng=game.rng, log=game.log)
        if target.body.dead:
            game.kill_creature(target)
    else:
        game.log.info("You throw %s." % thrown.name(article=True))
    game.drop_item(thrown, landing[0], landing[1], landing[2])
    p.needs.exert(8)
    return NORMAL


def talk(game, other) -> int:
    """Open a conversation. The UI drives the actual dialogue."""
    if other is None:
        game.log.info("There is no one there.")
        return FREE
    if not other.defn.has("CAN_SPEAK"):
        game.log.info("The %s cannot speak." % other.short_name())
        return FREE
    if other.body.dead:
        game.log.info("The dead have nothing to say.")
        return FREE
    return NORMAL


def search(game) -> int:
    """Look carefully around for hidden things."""
    p = game.player
    p.add_exp("observer", 20)
    found = []
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            x, y, z = p.x + dx, p.y + dy, p.z
            if not game.local.in_bounds(x, y, z):
                continue
            t = tile_data.get(game.local.tile(x, y, z))
            if t.has("ORE") or t.has("GEM"):
                found.append(t.name)
    if found:
        game.log.good("You notice %s nearby." % ", ".join(sorted(set(found))))
    from . import traps as traps_mod

    trail = read_tracks(game)
    spotted = traps_mod.look_around(game, searching=True)
    for _cell, trap in spotted:
        game.log.warn("You spot a %s." % trap.name)
    if not found and not trail and not spotted:
        game.log.info("You find nothing of interest.")
    return NORMAL


def read_tracks(game) -> bool:
    """Look at the ground. True if anything had walked on it.

    Folded into `search` rather than given a key of its own, because looking
    hard at the ground is what searching already was and a second key for it
    would be two verbs for one action.
    """
    from . import tracks as tracks_mod

    p = game.player
    if not tracks_mod.can_track(p):
        return False
    found = tracks_mod.nearby(game)
    if not found:
        return False
    p.add_exp("tracker", 25)
    cell, track = found[0]
    for line in tracks_mod.read(game, p, cell, track):
        game.log.good(line)
    rest = len(found) - 1
    if rest and p.skills.level("tracker") >= tracks_mod.SPECIES_AT:
        game.log.info("The trail runs on -- %d more prints nearby." % rest)
    return True


def butcher(game, corpse: Item) -> int:
    """Butcher a corpse into meat, bone and hide."""
    p = game.player
    if corpse not in p.inventory.items:
        pile = game.items_at(p.x, p.y, p.z)
        if corpse in pile:
            game.take_item(corpse, p.x, p.y, p.z)
            p.inventory.add(corpse)
        else:
            return FREE
    out = crafting.butcher_corpse(p, corpse, game)
    if not out:
        game.log.warn("There is nothing to butcher.")
        return FREE
    game.log.good("You butcher the corpse: %s." % ", ".join(
        i.name() for i in out
    ))
    return SLOW


def build_fire(game) -> int:
    """Light a campfire."""
    p = game.player
    here = tile_data.get(game.local.tile(p.x, p.y, p.z))
    if here.has("FIRE"):
        game.log.info("There is already a fire here.")
        return FREE
    if not here.walk or here.has("WATER"):
        game.log.warn("You cannot build a fire here.")
        return FREE
    from ..world import fire as fire_mod

    if not fire_mod.carrying_flame(p) and not p.inventory.by_def("flint_and_steel"):
        game.log.warn("You have nothing to strike a light with.")
        return FREE
    fuel = p.inventory.by_def("log") or p.inventory.by_def("torch")
    if not fuel:
        game.log.warn("You have no fuel.")
        return FREE
    it = fuel[0]
    it.count -= 1
    if it.count <= 0 and it in p.inventory.items:
        p.inventory.items.remove(it)
        p.inventory.unequip_item(it)
    game.local.set_tile(p.x, p.y, p.z, "campfire")
    game.log.good("You build a campfire.")
    p.needs.add_thought("sat by a warm fire", -4)
    return SLOW


def sharpen(game, item: Optional[Item] = None) -> int:
    """Work a whetstone over a blade.

    The `sharpen_weapon` recipe has been in the crafting table since it was
    written, taking a whetstone and handing back a whetstone, because until
    weapons could go blunt there was nothing for it to do.
    """
    from . import wear as wear_mod

    p = game.player
    weapon = item if item is not None else p.inventory.weapon()
    msg = wear_mod.sharpen(p, weapon, game.rng)
    if msg.startswith("You put"):
        game.log.good(msg)
        return SLOW
    game.log.info(msg)
    return FREE


def write_book(game, item: Optional[Item] = None, kind: str = "") -> int:
    """Fill a blank book with what you know.

    `writing` has been in the skill table since it was written and the scholar
    profession starts with four of it. Every book in the world arrived already
    written; nobody could add one.
    """
    from . import books

    p = game.player
    if not books.can_write(p):
        game.log.warn("You do not know how to set words down.")
        return FREE
    if item is None:
        item = next((i for i in p.inventory.items if books.writable(i)), None)
    if item is None:
        game.log.warn("You have no blank book to write in.")
        return FREE
    if game.hostiles_in_sight():
        game.log.warn("Not with company.")
        return FREE
    subjects = books.subjects_for(p)
    if not subjects:
        game.log.warn("You know nothing well enough to fill a book.")
        return FREE
    kind = kind or subjects[0][0]
    turns = books.write_turns(p, kind)
    book, said = books.write(game.world, game.rng, p, item, kind)
    if book is None:
        game.log.warn(said)
        return FREE
    game.log.good(said)
    p.needs.fatigue += turns // 30
    return turns


def gather_here(game) -> int:
    """Pick what is growing under or beside you.

    The fortress has had herbalism wired end to end since it had farms; an
    adventurer standing on the same shrub could do nothing at all.
    """
    from . import foraging

    items, said = foraging.gather(game, game.player, game.rng)
    game.log.good(said) if items else game.log.info(said)
    game.player.needs.exert(6)
    return foraging.GATHER_TURNS if items or "search" in said else FREE


#: Ticks a prayer takes. Long enough to be a decision on a dangerous map.
PRAY_TURNS = 300


def pray_here(game) -> int:
    """Stop at an altar and be quiet for a moment.

    Every temple in the game was furnished with one of these and there was
    nothing to say to it. What it does for an adventurer is what a night's
    sleep does: it settles you.
    """
    from ..world import religion as religion_mod

    p = game.player
    if game.local is None or game.local.tile(p.x, p.y, p.z) != "altar":
        game.log.info("There is no altar here.")
        return FREE
    game.log.good(religion_mod.prayer_line(game.world, p))
    p.needs.prayer = 0
    p.needs.add_thought("prayed at an altar", -6)
    return PRAY_TURNS


def fish_here(game) -> int:
    """Spend a while at the water's edge.

    `fishing` is a skill, a fortress labor and the hunter's trade, `fish_food`
    is stocked, cooked and eaten, carp and pike swim in the bestiary -- and
    until now nobody in either mode had ever caught one.
    """
    from . import foraging

    if game.hostiles_in_sight():
        game.log.warn("Not with company.")
        return FREE
    items, said = foraging.fish(game, game.player, game.rng)
    if not items and ("no fishing rod" in said or "no water" in said):
        game.log.warn(said)
        return FREE
    game.log.good(said) if items else game.log.info(said)
    return foraging.FISH_TURNS


def craft_recipe(game, recipe) -> int:
    """Make something."""
    ok, msg = crafting.craft(game.player, recipe, game)
    game.log.good(msg) if ok else game.log.warn(msg)
    return SLOW if ok else FREE


def light_source(game, item: Optional[Item] = None) -> int:
    """Light or put out a torch or lantern."""
    p = game.player
    if item is None:
        lit = [i for i in p.inventory.items if i.is_light and i.flags.get("lit")]
        if lit:
            item = lit[0]
        else:
            usable = [
                i for i in p.inventory.items if i.is_light and i.charges > 0
            ]
            if not usable:
                game.log.warn("You have nothing to light.")
                return FREE
            item = usable[0]
    if not item.is_light:
        game.log.warn("That will not burn.")
        return FREE
    if item.flags.get("lit"):
        item.flags["lit"] = False
        game.log.info("You put out %s." % item.name(article=True))
        game.update_fov()
        return NORMAL
    if item.charges <= 0:
        game.log.warn("%s is spent." % item.name(article=True).capitalize())
        return FREE
    item.flags["lit"] = True
    game.log.good("You light %s. The dark pulls back." % item.name(article=True))
    game.update_fov()
    return NORMAL


def treat_wound(game, patient, part_id: str, treatment: str) -> int:
    """Apply first aid to yourself or a companion."""
    frags = medical.treat(game.player, patient, part_id, treatment, rng=game.rng)
    for f in frags:
        game.log.add([f], "info")
    game.player.needs.exert(10)
    return SLOW


def diagnose(game, patient) -> int:
    """Look over somebody's injuries."""
    for f in medical.diagnose(game.player, patient):
        game.log.add([f], "info")
    return NORMAL


def travel_start(game) -> int:
    """Check whether world-map travel is allowed right now."""
    if not game.can_travel():
        game.log.warn("You cannot travel with enemies so close.")
        return FREE
    return FREE
