"""Build templates for Claude Companion.

Every template is a list of entity specs in *local* tile coordinates, the
same shape the mod's place/check/fit commands take: {"n", "x", "y", "d", ...}.
x grows east and y grows south, as in the game. An entity's x/y is its centre,
so a 1x1 entity on tile (3, 4) sits at (3.5, 4.5) and a 2x2 one covering tiles
3-4 sits at (4.0, ...).

The mod moves a template into the world with an anchor {x, y, rot, mirror}:
mirror across the local y axis, rotate clockwise by `rot` quarter turns, then
add (x, y). `transform` below does the same thing so plans can be previewed.

Directions use Factorio 2.x numbering: north 0, east 4, south 8, west 12.
Geometry was checked against the real 2.1.25 binary:
  - an inserter's direction points at the side it picks up from
  - a mining drill's direction is the side it drops onto
  - a north-facing boiler takes water on the two ends of its back (south)
    row and puts steam out of the middle of its front (north) row
  - a steam engine takes steam at both ends of its long axis
  - an offshore pump outputs on the side opposite the way it faces
"""

N, E, S, W = 0, 4, 8, 12


def ent(name, x, y, d=N, recipe=None, kind=None):
    spec = {"n": name, "x": x, "y": y, "d": d}
    if recipe:
        spec["r"] = recipe
    if kind:
        spec["t"] = kind
    return spec


def transform(spec, anchor):
    """Where a local spec lands in the world. Mirrors control.lua's transform."""
    x, y, d = spec["x"], spec["y"], spec.get("d", 0)
    if anchor.get("mirror"):
        x, d = -x, (16 - d) % 16
    k = anchor.get("rot", 0) % 4
    for _ in range(k):
        x, y = -y, x
    out = dict(spec)
    out.update(x=anchor.get("x", 0) + x, y=anchor.get("y", 0) + y, d=(d + 4 * k) % 16)
    return out


def rot_for(vector):
    """The rotation that turns local north (0, -1) into `vector`."""
    return {(0, -1): 0, (1, 0): 1, (0, 1): 2, (-1, 0): 3}[(round(vector[0]), round(vector[1]))]


# ---------------------------------------------------------------------------
# power

def steam_power(boilers=1, engines=2, pipes=1, fuel_belt=False, poles=True):
    """Offshore pump, a line of boilers, and `engines` steam engines per boiler.

    Local frame: the pump's output tile is (0, 0) and the layout grows north
    from it (the pump itself sits on tile (0, 1), facing the water to the
    south). Boilers chain north along column 0-1 with their steam outputs
    facing east; engines run east from each boiler. With fuel_belt, a belt on
    column -2 and burner inserters on column -1 feed coal to every boiler.
    """
    out = [ent("offshore-pump", 0.5, 1.5, S)]
    for k in range(pipes):
        out.append(ent("pipe", 0.5, 0.5 - k))
    centres = [-0.5 - pipes - 3 * i for i in range(boilers)]
    for i, cy in enumerate(centres):
        out.append(ent("boiler", 1.0, cy, E))
        for j in range(engines):
            out.append(ent("steam-engine", 4.5 + 5 * j, cy, E))
        if poles and i % 2 == 0:
            out.append(ent("small-electric-pole", 2.5 + 5 * engines, cy))
        if fuel_belt:
            out.append(ent("burner-inserter", -0.5, cy, W))
    if fuel_belt:
        top, bottom = int(centres[-1] - 1.5), int(centres[0] + 1.5)
        for ty in range(top, bottom):
            out.append(ent("transport-belt", -1.5, ty + 0.5, N))
    return out


def steam_dual(units=1, inserter="inserter", pole="small-electric-pole", lead=3, feed="west"):
    """See _steam_dual for the plant itself.

    `lead` moves the whole plant `lead` tiles north of the pump, to clear a
    ragged shoreline and leave a lane for the coal belt. With lead >= 3 the
    water crosses that lane in a pipe-to-ground pair, so row -1 is free from
    edge to edge. A coal stub runs along row -1 from the plant's west edge
    (feed="west"; a belt arriving at local (-12, -1) flowing east) or east
    edge (feed="east"; arriving at (16, -1) flowing west), then turns north
    into the middle belt. feed=None leaves the lane empty.

    Electric inserters need power before they move coal, so put a few coal
    into each boiler by hand the first time.
    """
    out = []
    for spec in _steam_dual(units, inserter, pole):
        if spec["n"] != "offshore-pump":
            spec["y"] -= lead
        out.append(spec)
    if lead >= 3:
        out.append(ent("pipe-to-ground", 0.5, 0.5, S))  # pump side
        out.append(ent("pipe-to-ground", 0.5, 1.5 - lead, N))  # plant side
    else:
        for i in range(lead):
            out.append(ent("pipe", 0.5, 0.5 - i))
    if feed and lead >= 3:
        xs = range(-11, 2) if feed == "west" else range(3, 16)
        d = E if feed == "west" else W
        for tx in xs:
            out.append(ent("transport-belt", tx + 0.5, -0.5, d))
        for ty in range(1 - lead, 0):  # x 2 from row -1 up to the plant
            out.append(ent("transport-belt", 2.5, ty + 0.5, N))
    return out


def _steam_dual(units, inserter, pole):
    """Chris's dual-sided steam plant: a coal belt up the middle feeding a
    column of boilers on each side, two engines per boiler.

    Same frame as steam_power: the pump sits on tile (0, 1) facing the water
    to the south and outputs onto (0, 0); the plant grows north. One unit is
    4 tiles tall and holds 2 boilers and 4 engines (3.6 MW). In 2.x one
    water makes 10 steam, so a pump could feed 200 boilers; the real limit
    is the coal belt down the middle, about 33 boilers (16 units) per yellow belt.

    Columns (x): engines -11..-2, west boiler -1..0 (water on its back column
    x 0), inserter 1, coal belt 2 flowing north, inserter 3, east boiler 4..5
    (water on x 4), engines 6..15. Row 0 carries the water across the belt in
    a pipe-to-ground pair. Each unit's boilers fill rows -4k-3..-4k-1; the gap row
    above holds the water pipes between boilers and the poles. Coal goes onto
    the belt at its south end, tile (2, 0).
    """
    out = [
        ent("offshore-pump", 0.5, 1.5, S),
        ent("pipe", 0.5, 0.5),
        ent("pipe-to-ground", 1.5, 0.5, W),
        ent("pipe-to-ground", 3.5, 0.5, E),
        ent("pipe", 4.5, 0.5),
    ]
    for k in range(units):
        y = -1.5 - 4 * k  # middle row of this unit's boilers
        out.append(ent("boiler", 0.0, y, W))
        out.append(ent("boiler", 5.0, y, E))
        out.append(ent(inserter, 1.5, y, E))
        out.append(ent(inserter, 3.5, y, W))
        for cx in (-3.5, -8.5, 8.5, 13.5):
            out.append(ent("steam-engine", cx, y, E))
        gap = -3.5 - 4 * k
        if k < units - 1:
            out.append(ent("pipe", 0.5, gap))
            out.append(ent("pipe", 4.5, gap))
        for px in (-5.5, 1.5, 3.5, 10.5):
            out.append(ent(pole, px, gap))
    for ty in range(-4 * units + 1, 1):
        out.append(ent("transport-belt", 2.5, ty + 0.5, N))
    return out


# ---------------------------------------------------------------------------
# mining

def drill_strip(segments=2, tail=0, drill="electric-mining-drill", belt="transport-belt",
                pole="small-electric-pole"):
    """Two columns of electric drills facing a shared belt that flows north.

    Seven tiles wide (drill, belt, drill) and 7*segments+1 long. Each segment
    is a one-tile gap row holding a pole, then two drills per side; one pole
    powers the four drills around it and the poles are 7 apart, inside the
    small pole's wire reach. The belt carries on `tail` tiles past the north
    end. Local tile (0, 0) is the north-west corner.
    """
    out = []
    length = 7 * segments + 1
    for ty in range(-tail, length):
        out.append(ent(belt, 3.5, ty + 0.5, N))
    for s in range(segments + 1):
        out.append(ent(pole, 2.5, 7 * s + 0.5))
        if s == segments:
            break
        for cy in (7 * s + 2.5, 7 * s + 5.5):
            out.append(ent(drill, 1.5, cy, E))
            out.append(ent(drill, 5.5, cy, W))
    return out


def drill_row(pairs=4, belt="transport-belt", drill="electric-mining-drill", pole="small-electric-pole"):
    """Chris's mining layout: drills side by side with no gaps, facing a shared
    belt that flows north, and one free column behind each drill row for poles.

    Columns west to east: poles (x 0), drills (1..3), belt (4), drills (5..7),
    poles (8). Nine tiles wide, 3*pairs long. Drills come in pairs along each
    side; a small pole behind each pair (every 6 tiles) touches both drills,
    and the poles are 6 apart, inside wire reach. No gap rows, so more drills
    per tile of ore than drill_strip. Local tile (0, 0) is the north-west corner.
    """
    out = []
    length = 3 * pairs
    for ty in range(length):
        out.append(ent(belt, 4.5, ty + 0.5, N))
    for k in range(pairs):
        cy = 3 * k + 1.5
        out.append(ent(drill, 2.5, cy, E))
        out.append(ent(drill, 6.5, cy, W))
        if k % 2 == 0:
            py = 3 * k + 3.0  # between this drill and the next one
            out.append(ent(pole, 0.5, py - 0.5 if py < length else length - 0.5))
            out.append(ent(pole, 8.5, py - 0.5 if py < length else length - 0.5))
    return out


def burner_smelt(count=4, rows=1):
    """Burner drills dropping straight into stone furnaces: no belts, no power.

    Row one is drills on tiles y 0-1 facing south into furnaces on y 2-3. A
    second row mirrors it: furnaces on y 4-5 fed by drills on y 6-7 facing
    north. Columns are two tiles wide. Both drills and furnaces need coal by
    hand.
    """
    out = []
    for k in range(count):
        cx = 2 * k + 1.0
        out.append(ent("burner-mining-drill", cx, 1.0, S))
        out.append(ent("stone-furnace", cx, 3.0))
        if rows > 1:
            out.append(ent("stone-furnace", cx, 5.0))
            out.append(ent("burner-mining-drill", cx, 7.0, N))
    return out


def burner_coal(count=4, chest="wooden-chest"):
    """Burner drills on coal, each dropping into its own chest to the south."""
    out = []
    for k in range(count):
        cx = 2 * k + 1.0
        out.append(ent("burner-mining-drill", cx, 1.0, S))
        out.append(ent(chest, cx + 0.5, 2.5))
    return out


# A burner drill drops just east of its centre whichever way it is mirrored,
# so a mirrored copy would miss its chest. (Checked by selftest.py.)
burner_coal.mirrorable = False


def coal_loop(count=1):
    """Self-fuelling burner drills on coal: pinwheels of four drills.

    Each drill faces the next one clockwise, so its coal drops into that
    drill's fuel slot. A burner drill drops at centre + (-0.5, -1.3) rotated
    by its facing: NW faces east onto NE, NE south onto SE, SE west onto SW,
    SW north onto NW. Each pinwheel is 4x4. Pinwheels sit side by side going
    east. Once every fuel slot is full the drills stop, so take coal out of them.
    Prime one drill by hand.
    """
    out = []
    for k in range(count):
        ox = 4 * k
        out.append(ent("burner-mining-drill", ox + 1.0, 1.0, E))
        out.append(ent("burner-mining-drill", ox + 3.0, 1.0, S))
        out.append(ent("burner-mining-drill", ox + 3.0, 3.0, W))
        out.append(ent("burner-mining-drill", ox + 1.0, 3.0, N))
    return out


# The drop offset is chiral, so a mirrored pinwheel drops onto bare ground.
coal_loop.mirrorable = False


# Chris's coal block (built in game 2026-11-24): 16 burner drills, 8x8, in a
# single serpentine loop so each drill fuels the next. Rows go north to south
# and columns west to east; arrows give the side each drill drops onto.
_COAL_SNAKE = [
    (E, E, E, S),
    (N, S, W, S),
    (N, S, N, S),
    (N, W, N, W),
]


def coal_snake():
    """Chris's 16-drill self-fuelling coal block: one closed loop through all
    16 burner drills (path: across the top, down the east column, then
    snaking back west and up the west column). Prime one drill and the coal
    goes round. Pull coal out of any of them; the 16 fuel slots hold up to 800."""
    out = []
    for j, row in enumerate(_COAL_SNAKE):
        for i, d in enumerate(row):
            out.append(ent("burner-mining-drill", 1.0 + 2 * i, 1.0 + 2 * j, d))
    return out


coal_snake.mirrorable = False


# ---------------------------------------------------------------------------
# smelting

def smelter_column(rows=8, furnace="stone-furnace", inserter="inserter", belt="transport-belt",
                   pole="small-electric-pole", sides=2):
    """Furnaces either side of a shared output belt.

    Columns west to east: input belt (flows south), inserter, furnace (2),
    inserter, OUTPUT belt (flows north), inserter, furnace (2), inserter,
    input belt (flows south). Eleven tiles wide, 2*rows long. Put ore on one
    lane of each input belt and coal on the other. Both input belts start at
    the north end and the output leaves from the north end too. With sides=1
    only the west half is built (six tiles wide).
    """
    out = []
    length = 2 * rows
    columns = [(0.5, S), (5.5, N)] + ([(10.5, S)] if sides > 1 else [])
    for x, d in columns:
        for ty in range(length):
            out.append(ent(belt, x, ty + 0.5, d))
    for i in range(rows):
        top = 2 * i + 0.5
        out.append(ent(furnace, 3.0, 2 * i + 1.0))
        out.append(ent(inserter, 1.5, top, W))   # takes ore and coal from the west belt
        out.append(ent(inserter, 4.5, top, W))   # takes plates out of the furnace
        if sides > 1:
            out.append(ent(furnace, 8.0, 2 * i + 1.0))
            out.append(ent(inserter, 6.5, top, E))
            out.append(ent(inserter, 9.5, top, E))
        if i % 2 == 0:
            for x in ((1.5, 4.5, 6.5, 9.5) if sides > 1 else (1.5, 4.5)):
                out.append(ent(pole, x, 2 * i + 1.5))
    return out


# ---------------------------------------------------------------------------
# plumbing

def belt_path(points, belt="transport-belt"):
    """A belt through axis-aligned waypoints given as tile coordinates.

    Each tile takes the direction of the segment leaving it; the last tile
    keeps the direction of the last segment.
    """
    out, last_d = [], N
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if x1 != x2 and y1 != y2:
            raise ValueError(f"belt segment {x1},{y1} -> {x2},{y2} is not straight")
        dx, dy = (x2 > x1) - (x2 < x1), (y2 > y1) - (y2 < y1)
        last_d = {(0, -1): N, (1, 0): E, (0, 1): S, (-1, 0): W}[(dx, dy)]
        x, y = x1, y1
        while (x, y) != (x2, y2):
            out.append(ent(belt, x + 0.5, y + 0.5, last_d))
            x, y = x + dx, y + dy
    x, y = points[-1]
    out.append(ent(belt, x + 0.5, y + 0.5, last_d))
    return out


def pole_line(start, end, spacing=7, pole="small-electric-pole"):
    """Poles every `spacing` tiles along a straight line of tiles."""
    (x1, y1), (x2, y2) = start, end
    length = max(abs(x2 - x1), abs(y2 - y1))
    steps = max(1, -(-length // spacing))
    out = []
    for i in range(steps + 1):
        t = i / steps
        out.append(ent(pole, round(x1 + (x2 - x1) * t) + 0.5, round(y1 + (y2 - y1) * t) + 0.5))
    return out


LAYOUTS = {
    "steam_power": steam_power,
    "drill_strip": drill_strip,
    "burner_smelt": burner_smelt,
    "burner_coal": burner_coal,
    "coal_loop": coal_loop,
    "coal_snake": coal_snake,
    "drill_row": drill_row,
    "steam_dual": steam_dual,
    "smelter_column": smelter_column,
}
