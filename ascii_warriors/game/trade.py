"""Buying, selling and haggling.

Prices move with your Appraiser and Negotiator skills and with how greedy the
merchant is. Sell to a merchant who wants what you are selling and you do
better; try to sell a goblin's rusted dagger to a dwarven smith and you will not.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from ..data import items as item_data
from ..engine.rng import RNG
from .item import Item, make_item

#: Merchants pay this fraction of an item's worth before skill adjustments.
BASE_SELL_RATE = 0.35
#: And charge this multiple of it when selling to you.
BASE_BUY_RATE = 1.35

#: What each kind of trader stocks.
STOCK_TABLES: Dict[str, Tuple[str, ...]] = {
    "merchant": (
        "dagger", "short_sword", "sword", "axe", "mace", "spear", "bow",
        "crossbow", "arrow", "bolt", "leather_armor", "cap", "helm",
        "mail_shirt", "high_boots", "shield", "buckler", "cloak", "tunic",
        "trousers", "shoes", "backpack", "waterskin", "rope", "torch",
        "lantern", "bandage", "splint", "whetstone", "flint_and_steel",
        "lockpick", "meat", "bread", "cheese", "plump_helmet", "dwarven_ale",
        "wine", "book",
    ),
    "tavern_keeper": (
        "dwarven_ale", "wine", "beer", "rum", "mead", "bread", "cheese",
        "meat", "prepared_meal", "plump_helmet", "torch",
    ),
    "smith": (
        "dagger", "short_sword", "sword", "long_sword", "axe", "battle_axe",
        "mace", "warhammer", "spear", "pick", "helm", "mail_shirt",
        "breastplate", "greaves", "gauntlets", "shield", "whetstone",
    ),
    "priest": ("bandage", "splint", "book", "bread"),
}

#: What each kind of trader is willing to buy, by item category.
BUYS: Dict[str, Tuple[str, ...]] = {
    "merchant": ("weapon", "armor", "clothing", "shield", "ammo", "tool",
                 "gem", "book", "food", "drink", "container", "misc",
                 "remains"),
    "tavern_keeper": ("food", "drink", "remains", "gem"),
    "smith": ("weapon", "armor", "shield", "ammo", "gem", "misc"),
    "priest": ("gem", "book"),
}


def trader_kind(npc) -> str:
    """Which stock table an NPC trades from, or ``""`` if they do not trade."""
    role = npc.ai.role if npc.ai else ""
    if role in STOCK_TABLES:
        return role
    if npc.profession in STOCK_TABLES:
        return npc.profession
    if npc.def_id == "merchant" or role == "merchant":
        return "merchant"
    return ""


def is_trader(npc) -> bool:
    """True if this NPC will trade with you at all."""
    return bool(trader_kind(npc)) and not npc.body.dead and npc.faction != "hostile"


def stock_merchant(npc, rng: RNG, *, tier: int = 2) -> None:
    """Fill a trader's inventory the first time you talk to them."""
    if npc.speech.get("stocked"):
        return
    npc.speech["stocked"] = True
    kind = trader_kind(npc) or "merchant"
    table = STOCK_TABLES.get(kind, STOCK_TABLES["merchant"])
    count = rng.randint(6, 14)
    for _ in range(count):
        def_id = rng.choice(table)
        defn = item_data.get(def_id)
        n = rng.randint(2, 10) if defn.stack else 1
        npc.inventory.add(make_item(rng, def_id, tier=tier, count=n))
    npc.inventory.add(Item("coin", "silver", count=rng.randint(60, 400)))


def _haggle_factor(customer, merchant) -> float:
    """How far the customer's skills move a price in their favour, 0 to 0.45."""
    appraisal = customer.skills.level("appraisal")
    negotiation = customer.skills.level("negotiation")
    social = customer.attributes.factor("social_awareness")
    bonus = (appraisal * 0.012 + negotiation * 0.018) * social
    return max(0.0, min(0.45, bonus))


def price_to_buy(item: Item, merchant, customer, game=None) -> int:
    """What the merchant charges the customer for one unit of *item*.

    *game* is optional because two of the four callers are prices quoted
    without a world to hand; with it, what the merchant's people think of you
    moves the number, though never as far as the Appraiser skill does.
    """
    unit = max(1, item.value // max(1, item.count))
    greed = merchant.personality.greed_factor() if merchant is not None else 1.0
    price = unit * BASE_BUY_RATE * (0.75 + 0.5 * greed)
    price *= 1.0 - _haggle_factor(customer, merchant)
    price *= _standing_factor(game, merchant)
    return max(1, int(round(price)))


def price_to_sell(item: Item, merchant, customer, game=None) -> int:
    """What the merchant pays the customer for one unit of *item*."""
    if merchant is not None and not wants(merchant, item):
        return 0
    unit = max(1, item.value // max(1, item.count))
    greed = merchant.personality.greed_factor() if merchant is not None else 1.0
    price = unit * BASE_SELL_RATE * (1.25 - 0.4 * greed)
    price *= 1.0 + _haggle_factor(customer, merchant)
    price /= _standing_factor(game, merchant)
    return max(1, int(round(price)))


def wants(merchant, item: Item) -> bool:
    """True if this merchant will buy that kind of item."""
    kind = trader_kind(merchant) or "merchant"
    if item.def_id == "coin":
        return False
    return item.category in BUYS.get(kind, BUYS["merchant"])


def for_sale(merchant) -> List[Item]:
    """Everything the merchant is offering."""
    return [
        i for i in merchant.inventory.items
        if i.def_id != "coin" and not merchant.inventory.is_equipped(i)
    ]


def sellable(customer, merchant) -> List[Item]:
    """Everything the customer is carrying that this merchant would buy."""
    return [
        i for i in customer.inventory.items
        if wants(merchant, i) and not customer.inventory.is_equipped(i)
    ]


def buy(game, merchant, item: Item, count: int = 1) -> Tuple[bool, str]:
    """Customer buys *count* units from the merchant."""
    customer = game.player
    count = max(1, min(count, item.count))
    unit = price_to_buy(item, merchant, customer, game)
    total = unit * count
    if customer.inventory.coins() < total:
        return (False, "You cannot afford that. It costs %d." % total)

    customer.inventory.spend_coins(total)
    merchant.inventory.add(Item("coin", "silver", count=total))

    if count >= item.count:
        merchant.inventory.items.remove(item)
        bought = item
    else:
        bought = item.split(count)
    customer.inventory.add(bought)

    customer.add_exp("negotiation", 20)
    customer.add_exp("appraisal", 10)
    game.quests.on_pickup(game, bought)
    return (True, "You buy %s for %d coins." % (bought.name(), total))


def sell(game, merchant, item: Item, count: int = 1) -> Tuple[bool, str]:
    """Customer sells *count* units to the merchant."""
    customer = game.player
    if not wants(merchant, item):
        return (False, "%s has no interest in that." % merchant.display_name())
    count = max(1, min(count, item.count))
    unit = price_to_sell(item, merchant, customer, game)
    total = unit * count
    if merchant.inventory.coins() < total:
        return (False, "%s cannot afford that." % merchant.display_name())

    merchant.inventory.spend_coins(total)
    customer.inventory.add(Item("coin", "silver", count=total))

    customer.inventory.unequip_item(item)
    if count >= item.count:
        customer.inventory.items.remove(item)
        sold = item
    else:
        sold = item.split(count)
    merchant.inventory.add(sold)

    customer.add_exp("negotiation", 20)
    customer.add_exp("appraisal", 15)
    return (True, "You sell %s for %d coins." % (sold.name(), total))


#: What a night in a tavern costs.
ROOM_PRICE = 12


def rent_room(game, keeper) -> Tuple[bool, str]:
    """Pay a tavern keeper for a safe night's sleep."""
    from ..data.calendar import TICKS_PER_HOUR

    customer = game.player
    price = max(4, int(ROOM_PRICE * keeper.personality.greed_factor()))
    if customer.inventory.coins() < price:
        return (False, "A room costs %d coins. You do not have it." % price)
    customer.inventory.spend_coins(price)
    keeper.inventory.add(Item("coin", "silver", count=price))

    ticks = 8 * TICKS_PER_HOUR
    customer.needs.sleep(ticks)
    customer.body.rest_heal(ticks, customer.attributes.factor("recuperation"))
    customer.needs.add_thought("slept in a proper bed", -8)
    game._tick_world(ticks)
    return (True, "You pay %d coins and sleep soundly until morning." % price)


def _standing_factor(game, merchant) -> float:
    """What the merchant's people's opinion of you does to their prices."""
    if game is None or merchant is None:
        return 1.0
    from . import standing

    return standing.price_factor(game, merchant)
