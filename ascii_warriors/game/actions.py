"""Player verbs.

Every function returns the energy cost of the action, or ``0`` when nothing
happened and no time should pass.
"""

from __future__ import annotations

from typing import Optional

from ..data.calendar import TICKS_PER_HOUR
from ..engine.fov import line_of_fire
from ..engine.scheduler import ACTION_COST
from ..world import tiles as tile_data
from . import combat, crafting
from .item import Item

FREE = 0
NORMAL = ACTION_COST
SLOW = ACTION_COST * 2


def move_or_attack(game, dx: int, dy: int) -> int:
    """Walk one step, or attack whatever is in the way."""
    p = game.player
    nx, ny, nz = p.x + dx, p.y + dy, p.z
    if not game.local.in_bounds(nx, ny, nz):
        game.log.warn("You have reached the edge of the area. Travel to move on.")
        return FREE

    target = game.creature_at(nx, ny, nz)
    if target is not None:
        if p.is_hostile_to(target) or target.is_hostile_to(p):
            combat.melee_attack(p, target, rng=game.rng, log=game.log)
            if target.body.dead:
                game.kill_creature(target)
            p.needs.exert(8)
            return NORMAL
        game.log.info("%s is in your way." % target.display_name())
        return FREE

    tile = tile_data.get(game.local.tile(nx, ny, nz))
    if tile.has("DOOR") and not tile.has("OPEN"):
        game.local.set_tile(nx, ny, nz, "door_open")
        game.log.info("You open the door.")
        return NORMAL

    if not game.is_passable(nx, ny, nz, p):
        # Try stepping up onto a ramp or ledge.
        if game.is_passable(nx, ny, nz + 1, p) and tile_data.get(
            game.local.tile(p.x, p.y, p.z)
        ).has("RAMP"):
            game.move_creature(p, nx, ny, nz + 1)
            return NORMAL
        if tile.has("WALL"):
            game.log.info("There is %s in the way." % tile.name)
        elif tile.has("WATER"):
            game.log.warn("The water is too deep to wade.")
        else:
            game.log.info("You cannot go that way.")
        return FREE

    # Step down where there is nothing to stand on.
    while nz > game.local.zmin and not game.local.has_floor(nx, ny, nz):
        nz -= 1

    game.move_creature(p, nx, ny, nz)
    pile = game.items_at(nx, ny, nz)
    if pile:
        if len(pile) == 1:
            game.log.info("You see %s here." % pile[0].name(article=True))
        else:
            game.log.info("You see %d items here." % len(pile))
    site_tile = tile_data.get(game.local.tile(nx, ny, nz))
    if site_tile.has("WATER"):
        p.add_exp("swimming", 8)
    p.needs.exert(2)
    return NORMAL


def move_z(game, dz: int) -> int:
    """Climb a staircase or ramp."""
    p = game.player
    here = tile_data.get(game.local.tile(p.x, p.y, p.z))
    if dz > 0:
        if not here.has("STAIR_UP"):
            game.log.info("There is no way up here.")
            return FREE
        if not game.is_passable(p.x, p.y, p.z + 1, p):
            game.log.info("The way up is blocked.")
            return FREE
        game.move_creature(p, p.x, p.y, p.z + 1)
        game.log.info("You climb up.")
    else:
        if not here.has("STAIR_DOWN"):
            game.log.info("There is no way down here.")
            return FREE
        if not game.is_passable(p.x, p.y, p.z - 1, p):
            game.log.info("The way down is blocked.")
            return FREE
        game.move_creature(p, p.x, p.y, p.z - 1)
        game.log.info("You climb down.")
    p.add_exp("climbing", 10)
    p.needs.exert(6)
    return NORMAL


def wait(game, ticks: int = NORMAL) -> int:
    """Stand still for one action."""
    return max(1, ticks)


def rest(game, ticks: int) -> int:
    """Rest without sleeping, healing slowly."""
    p = game.player
    p.body.rest_heal(ticks, p.attributes.factor("recuperation"))
    p.needs.fatigue = max(0, p.needs.fatigue - ticks // 2)
    game.log.info("You rest a while.")
    return max(1, ticks)


def sleep(game, hours: int = 8) -> int:
    """Sleep, healing and clearing fatigue."""
    p = game.player
    hostiles = [
        c for c in game.visible_creatures() if c.is_hostile_to(p)
    ]
    if hostiles:
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
    game.quests.on_pickup(game, target)
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
        game.quests.on_pickup(game, it)
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
    combat.melee_attack(p, target, target_part=part, rng=game.rng, log=game.log)
    if target.body.dead:
        game.kill_creature(target)
    p.needs.exert(10)
    return NORMAL


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
        wanted = weapon.defn.weapon.ranged if weapon.defn.weapon else None
        ammo_id = "stone_ammo" if wanted == "stone" else wanted
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
    combat.ranged_attack(p, target, weapon, ammo, rng=game.rng, log=game.log)
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
    else:
        game.log.info("You find nothing of interest.")
    return NORMAL


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


def craft_recipe(game, recipe) -> int:
    """Make something."""
    ok, msg = crafting.craft(game.player, recipe, game)
    game.log.good(msg) if ok else game.log.warn(msg)
    return SLOW if ok else FREE


def travel_start(game) -> int:
    """Check whether world-map travel is allowed right now."""
    if not game.can_travel():
        game.log.warn("You cannot travel with enemies so close.")
        return FREE
    return FREE
