-- Claude Companion: lets Claude read the map and lay down ghosts over a local
-- UDP bridge, and passes chat to Claude through a file in script-output.
--
-- Protocol: the bridge sends one JSON object per packet to the port given to
-- --enable-lua-udp: {"id": 7, "cmd": "map", "args": {...}}. The reply goes back
-- to the packet's source port as {"id": 7, "ok": true, "result": ...}. Replies
-- larger than one packet are split into "CHUNK <id> <i> <n>\n<piece>" packets.

local CHAT_FILE = "claude-companion/chat.jsonl"
local MAX_PACKET = 60000
local CLAUDE_COLOR = { r = 1.0, g = 0.85, b = 0.6 }

local D = defines.direction
local DIRECTIONS = {
	north = D.north, northeast = D.northeast, east = D.east, southeast = D.southeast,
	south = D.south, southwest = D.southwest, west = D.west, northwest = D.northwest,
}

-- Things a ghost may be placed over; they get marked for deconstruction.
local CLEARABLE = { tree = true, ["simple-entity"] = true, ["item-entity"] = true, fish = true }
-- Things that never block a ghost.
local PASSABLE = { character = true, resource = true, ["highlight-box"] = true, ["flying-text"] = true,
	corpse = true, ["character-corpse"] = true, ["deconstructible-tile-proxy"] = true, ["tile-ghost"] = true,
	smoke = true, ["smoke-with-trigger"] = true, ["entity-ghost"] = false }

---------------------------------------------------------------------------
-- small helpers

local function peer()
	-- Single player: the only instance. Multiplayer: the server, which is the
	-- machine the bridge runs on.
	if game.is_multiplayer() then return 0 end
	return nil
end

local function pos_of(p, default)
	if p == nil then return default end
	if p.x ~= nil then return { x = p.x, y = p.y } end
	return { x = p[1], y = p[2] }
end

local function dir_of(d)
	if d == nil then return D.north end
	if type(d) == "number" then return d % 16 end
	local v = DIRECTIONS[d]
	if v == nil then error("unknown direction '" .. tostring(d) .. "'") end
	return v
end

local function surface_of(args)
	if args.surface then
		local s = game.get_surface(args.surface)
		if not s then error("unknown surface '" .. tostring(args.surface) .. "'") end
		return s
	end
	local p = game.connected_players[1]
	if p then return p.surface end
	return game.surfaces.nauvis
end

local function force_of(args)
	if args.force then
		local f = game.forces[args.force]
		if not f then error("unknown force '" .. tostring(args.force) .. "'") end
		return f
	end
	local p = game.connected_players[1]
	if p then return p.force end
	return game.forces.player
end

local function player_of(args)
	if args.player then
		local p = game.get_player(args.player)
		if not p then error("unknown player '" .. tostring(args.player) .. "'") end
		return p
	end
	return game.connected_players[1] or game.players[1]
end

-- An area from {area = {{x1, y1}, {x2, y2}}} or {center = {x, y}, radius = r}.
-- Without either, centred on the first player.
local function area_of(args, default_radius, max_radius)
	if args.area then
		local a, b = pos_of(args.area[1]), pos_of(args.area[2])
		return { { math.min(a.x, b.x), math.min(a.y, b.y) }, { math.max(a.x, b.x), math.max(a.y, b.y) } }
	end
	local c = pos_of(args.center)
	if not c then
		local p = player_of(args)
		c = p and p.position or { x = 0, y = 0 }
	end
	local r = math.min(args.radius or default_radius, max_radius)
	return { { math.floor(c.x - r), math.floor(c.y - r) }, { math.floor(c.x + r) + 1, math.floor(c.y + r) + 1 } }
end

-- defines.entity_status by number, so statuses can be reported by name
local STATUS_NAME = {}
for name, id in pairs(defines.entity_status) do STATUS_NAME[id] = name end

local function status_name(e)
	local ok, st = pcall(function() return e.status end)
	if not (ok and st) then return nil end
	return STATUS_NAME[st] or tostring(st)
end

local function deepcopy(t)
	if type(t) ~= "table" then return t end
	local out = {}
	for k, v in pairs(t) do out[k] = deepcopy(v) end
	return out
end

local function round(v, places)
	local m = 10 ^ (places or 2)
	return math.floor(v * m + 0.5) / m
end

local function say(text)
	game.print("[Claude] " .. text, { color = CLAUDE_COLOR, sound = defines.print_sound.never })
end

---------------------------------------------------------------------------
-- placement: templates, transforms and collision checks

-- A spec is {n|name, x, y | position, d|direction, r|recipe, t|type}.
local function normalise(spec)
	return {
		name = spec.n or spec.name,
		position = spec.position and pos_of(spec.position) or { x = spec.x, y = spec.y },
		direction = dir_of(spec.d or spec.direction),
		recipe = spec.r or spec.recipe,
		type = spec.t or spec.type,
	}
end

-- Templates are authored in local tile coordinates; an anchor moves them into
-- the world. Mirror first (across the local y axis), then rotate clockwise
-- by quarter turns, then translate.
local function transform(spec, anchor)
	local x, y, d = spec.position.x, spec.position.y, spec.direction
	if anchor.mirror then
		x = -x
		d = (16 - d) % 16
	end
	local k = (anchor.rot or 0) % 4
	for _ = 1, k do x, y = -y, x end
	return {
		name = spec.name,
		position = { x = (anchor.x or 0) + x, y = (anchor.y or 0) + y },
		direction = (d + 4 * k) % 16,
		recipe = spec.recipe,
		type = spec.type,
	}
end

local function expand(args)
	local list = args.entities or args.template
	if not list then error("no entities given") end
	local anchor = args.anchor or {}
	local out = {}
	for i, raw in ipairs(list) do
		out[i] = transform(normalise(raw), anchor)
	end
	return out
end

-- The prototype's collision box turned to `dir` and moved to `pos`.
local function rotated_box(proto, pos, dir)
	local cb = proto.collision_box
	local x1, y1, x2, y2 = cb.left_top.x, cb.left_top.y, cb.right_bottom.x, cb.right_bottom.y
	local q = math.floor(dir / 4) % 4
	if q == 1 then
		x1, y1, x2, y2 = -y2, x1, -y1, x2
	elseif q == 2 then
		x1, y1, x2, y2 = -x2, -y2, -x1, -y1
	elseif q == 3 then
		x1, y1, x2, y2 = y1, -x2, y2, -x1
	end
	return { { pos.x + x1, pos.y + y1 }, { pos.x + x2, pos.y + y2 } }
end

local function same_spot(e, spec)
	return math.abs(e.position.x - spec.position.x) < 0.01 and math.abs(e.position.y - spec.position.y) < 0.01
end

-- Machines that can't be rotated (assemblers without fluid boxes, poles,
-- chests) are stored facing north whatever a rotated template says, so only
-- compare facing for things that actually rotate.
local FACING_FREE = {
	["electric-pole"] = true, container = true, ["logistic-container"] = true, lamp = true, lab = true,
	furnace = true, roboport = true, radar = true, ["constant-combinator"] = false,
}
local function same_facing(e, spec)
	if e.direction == spec.direction then return true end
	local proto = prototypes.entity[spec.name]
	if FACING_FREE[proto.type] then return true end
	if proto.type == "assembling-machine" then
		-- facing only matters for an assembler with fluid connections
		local ok, boxes = pcall(function() return proto.fluidbox_prototypes end)
		return ok and (boxes == nil or #boxes == 0)
	end
	local ok, rotatable = pcall(function() return proto.supports_direction end)
	return ok and rotatable == false
end

-- Decides whether `spec` can go down. Returns status, detail, obstacles:
--   "ok"      can be placed; obstacles = trees/rocks to clear first
--   "exists"  the same entity or ghost is already there
--   "blocked" detail says by what
local function assess(surface, force, spec)
	local proto = prototypes.entity[spec.name]
	if not proto then return "blocked", "unknown entity '" .. tostring(spec.name) .. "'" end

	local box = rotated_box(proto, spec.position, spec.direction)
	local found = surface.find_entities_filtered { area = box }
	local obstacles = {}
	for _, e in pairs(found) do
		if e.type == "entity-ghost" then
			if e.ghost_name == spec.name and same_spot(e, spec) and same_facing(e, spec) then
				return "exists", "ghost"
			end
			return "blocked", "ghost of " .. e.ghost_name .. " at " .. round(e.position.x) .. "," .. round(e.position.y)
		elseif e.name == spec.name and same_spot(e, spec) and same_facing(e, spec) then
			return "exists", "built"
		elseif CLEARABLE[e.type] then
			obstacles[#obstacles + 1] = e
		elseif not PASSABLE[e.type] then
			return "blocked", e.name .. " at " .. round(e.position.x) .. "," .. round(e.position.y)
		end
	end

	local check = {
		name = spec.name, position = spec.position, direction = spec.direction, force = force,
		build_check_type = defines.build_check_type.manual_ghost, forced = #obstacles > 0,
	}
	if not surface.can_place_entity(check) then
		return "blocked", "terrain (water, cliff, missing resource or out of map)"
	end
	return "ok", nil, obstacles
end

local function add_bom(bom, name)
	local items = prototypes.entity[name].items_to_place_this
	if items and items[1] then
		local item = items[1]
		bom[item.name] = (bom[item.name] or 0) + (item.count or 1)
	end
end

local function cheats_allowed()
	return settings.global["claude-companion-allow-cheats"].value
end

---------------------------------------------------------------------------
-- map reading

local water_tiles
local function water_names()
	if not water_tiles then
		water_tiles = {}
		for name, proto in pairs(prototypes.tile) do
			if proto.collision_mask.layers["water_tile"] then water_tiles[#water_tiles + 1] = name end
		end
	end
	return water_tiles
end

local RESOURCE_CHAR = {
	["iron-ore"] = "i", ["copper-ore"] = "c", coal = "k", stone = "s", ["uranium-ore"] = "u", ["crude-oil"] = "o",
}

local TYPE_CHAR = {
	["transport-belt"] = "belt", ["underground-belt"] = "U", splitter = "S", inserter = "N",
	["mining-drill"] = "D", furnace = "F", ["assembling-machine"] = "A", ["electric-pole"] = "+",
	pipe = "-", ["pipe-to-ground"] = "-", boiler = "B", generator = "G", lab = "L", container = "C",
	["logistic-container"] = "C", ["offshore-pump"] = "P", ["ammo-turret"] = "Y", ["electric-turret"] = "Y",
	wall = "W", gate = "W", roboport = "R", radar = "Q", ["storage-tank"] = "O", pump = "-",
	["rocket-silo"] = "Z", beacon = "M", ["solar-panel"] = "=", accumulator = "a", reactor = "X",
	tree = "T", ["simple-entity"] = "r", cliff = "X", character = "@", ["entity-ghost"] = ":",
	["unit-spawner"] = "E", turret = "E", unit = "e",
}

local BELT_CHAR = { [D.north] = "^", [D.east] = ">", [D.south] = "v", [D.west] = "<" }

local function entity_char(e)
	if e.force and e.force.name == "enemy" then
		return (e.type == "unit") and "e" or "E"
	end
	local c = TYPE_CHAR[e.type]
	if c == "belt" then return BELT_CHAR[e.direction] or "=" end
	return c or "#"
end

---------------------------------------------------------------------------
-- commands

local handlers = {}

function handlers.ping()
	return {
		tick = game.tick,
		version = script.active_mods["ClaudeCompanion"],
		players = #game.connected_players,
		multiplayer = game.is_multiplayer(),
		cheats = cheats_allowed(),
	}
end

function handlers.say(args)
	say(tostring(args.text or ""))
	return {}
end

function handlers.state(args)
	local players = {}
	for _, p in pairs(game.connected_players) do
		local c = p.character
		players[#players + 1] = {
			index = p.index, name = p.name, surface = p.surface.name,
			position = { x = round(p.position.x, 1), y = round(p.position.y, 1) },
			has_character = c ~= nil,
			driving = p.driving,
		}
	end
	local force = force_of(args)
	local research = force.current_research
	local queue = {}
	for _, t in pairs(force.research_queue or {}) do queue[#queue + 1] = t.name end
	return {
		tick = game.tick,
		daytime = round(surface_of(args).daytime, 2),
		players = players,
		research = research and { name = research.name, progress = round(force.research_progress, 3) } or nil,
		research_queue = queue,
		evolution = round(game.forces.enemy.get_evolution_factor(surface_of(args)), 3),
	}
end

-- A character grid of an area. One character per tile; see `legend`.
function handlers.map(args)
	local surface = surface_of(args)
	local area = area_of(args, 40, 120)
	local x0, y0 = area[1][1], area[1][2]
	local w, h = area[2][1] - x0, area[2][2] - y0

	local grid = {}
	for row = 1, h do
		local line = {}
		for col = 1, w do line[col] = "." end
		grid[row] = line
	end
	local function put(x, y, c)
		local col, row = math.floor(x) - x0 + 1, math.floor(y) - y0 + 1
		if row >= 1 and row <= h and col >= 1 and col <= w then grid[row][col] = c end
	end

	for _, t in pairs(surface.find_tiles_filtered { area = area, name = water_names() }) do
		put(t.position.x, t.position.y, "~")
	end
	for _, r in pairs(surface.find_entities_filtered { area = area, type = "resource" }) do
		put(r.position.x, r.position.y, RESOURCE_CHAR[r.name] or "*")
	end
	-- Natural things first so buildings and ghosts draw over them.
	local layers = {
		surface.find_entities_filtered { area = area, type = { "tree", "simple-entity", "cliff" } },
		surface.find_entities_filtered { area = area, type = { "tree", "simple-entity", "cliff", "resource", "character", "entity-ghost", "fish" }, invert = true },
		surface.find_entities_filtered { area = area, type = "entity-ghost" },
		surface.find_entities_filtered { area = area, type = "character" },
	}
	for li, list in ipairs(layers) do
		for _, e in pairs(list) do
			local c = entity_char(e)
			if li == 4 or e.type == "tree" or e.type == "simple-entity" then
				put(e.position.x, e.position.y, c)
			else
				local b = e.bounding_box
				for y = math.floor(b.left_top.y + 0.05), math.ceil(b.right_bottom.y - 0.05) - 1 do
					for x = math.floor(b.left_top.x + 0.05), math.ceil(b.right_bottom.x - 0.05) - 1 do
						put(x, y, c)
					end
				end
			end
		end
	end

	local rows = {}
	for row = 1, h do rows[row] = table.concat(grid[row]) end
	return {
		origin = { x = x0, y = y0 }, width = w, height = h, rows = rows,
		legend = ". land  ~ water  i iron  c copper  k coal  s stone  u uranium  o oil  T tree  r rock  X cliff/reactor  @ player  " ..
			": ghost  ^>v< belt  U underground  S splitter  N inserter  D drill  F furnace  A assembler  + pole  - pipe  " ..
			"B boiler  G steam engine  L lab  C chest  P offshore pump  Y turret  W wall  R roboport  Q radar  O tank  E enemy base  e biter  # other",
	}
end

-- Entities in an area, with exact positions and settings.
function handlers.scan(args)
	local surface = surface_of(args)
	local area = area_of(args, 20, 150)
	local filter = { area = area, type = { "resource", "tree", "simple-entity", "cliff", "fish" }, invert = true }
	if args.names then filter = { area = area, name = args.names } end
	local out, nature = {}, { tree = 0, rock = 0, cliff = 0 }
	local limit = args.limit or 1500
	for _, e in pairs(surface.find_entities_filtered(filter)) do
		if #out >= limit then break end
		local row = { n = e.name, x = e.position.x, y = e.position.y, d = e.direction }
		if e.type == "entity-ghost" then
			row.n = e.ghost_name
			row.ghost = true
		end
		if e.force and e.force.name ~= "player" then row.f = e.force.name end
		local ok, recipe = pcall(function() return e.get_recipe() end)
		if ok and recipe then row.r = recipe.name end
		if e.type == "underground-belt" or (e.type == "entity-ghost" and e.ghost_type == "underground-belt") then
			row.t = e.belt_to_ground_type
		end
		if e.type == "mining-drill" and e.status then
			row.s = status_name(e)
		end
		out[#out + 1] = row
	end
	nature.tree = surface.count_entities_filtered { area = area, type = "tree" }
	nature.rock = surface.count_entities_filtered { area = area, type = "simple-entity" }
	nature.cliff = surface.count_entities_filtered { area = area, type = "cliff" }
	return { area = area, entities = out, truncated = #out >= limit, nature = nature }
end

-- Statuses that mean "fine", so area_status lists only what needs a look.
local OK_STATUS = { working = true, normal = true, charging = true, discharging = true, fully_charged = true,
	networks_connected = true }

-- {area} or {center, radius}: how our buildings there are doing. `counts` is
-- status by entity name; `not_working` lists the ones that aren't fine.
function handlers.area_status(args)
	local surface, force = surface_of(args), force_of(args)
	local area = area_of(args, 32, 200)
	local counts, bad, limit = {}, {}, args.limit or 200
	for _, e in pairs(surface.find_entities_filtered { area = area, force = force }) do
		local st = e.type ~= "entity-ghost" and e.type ~= "character" and status_name(e)
		if st then
			counts[e.name] = counts[e.name] or {}
			counts[e.name][st] = (counts[e.name][st] or 0) + 1
			if not OK_STATUS[st] and #bad < limit then
				bad[#bad + 1] = { n = e.name, x = e.position.x, y = e.position.y, s = st }
			end
		end
	end
	return { area = area, counts = counts, not_working = bad }
end

-- Ore patches near a point, as connected groups.
function handlers.resources(args)
	local surface = surface_of(args)
	local area = area_of(args, 150, 400)
	local center = { x = (area[1][1] + area[2][1]) / 2, y = (area[1][2] + area[2][2]) / 2 }
	local by_name = {}
	for _, r in pairs(surface.find_entities_filtered { area = area, type = "resource" }) do
		local list = by_name[r.name]
		if not list then
			list = {}
			by_name[r.name] = list
		end
		local x, y = math.floor(r.position.x), math.floor(r.position.y)
		list[x .. "," .. y] = { x = x, y = y, amount = r.amount }
	end

	local patches = {}
	for name, cells in pairs(by_name) do
		local reach = (name == "crude-oil") and 10 or 2
		local seen = {}
		for key, cell in pairs(cells) do
			if not seen[key] then
				local p = { name = name, tiles = 0, amount = 0, x1 = cell.x, y1 = cell.y, x2 = cell.x, y2 = cell.y, sx = 0, sy = 0 }
				local stack = { cell }
				seen[key] = true
				while #stack > 0 do
					local c = table.remove(stack)
					p.tiles = p.tiles + 1
					p.amount = p.amount + c.amount
					p.sx, p.sy = p.sx + c.x, p.sy + c.y
					if c.x < p.x1 then p.x1 = c.x end
					if c.y < p.y1 then p.y1 = c.y end
					if c.x > p.x2 then p.x2 = c.x end
					if c.y > p.y2 then p.y2 = c.y end
					for dx = -reach, reach do
						for dy = -reach, reach do
							local k = (c.x + dx) .. "," .. (c.y + dy)
							local n = cells[k]
							if n and not seen[k] then
								seen[k] = true
								stack[#stack + 1] = n
							end
						end
					end
				end
				p.cx, p.cy = round(p.sx / p.tiles, 1), round(p.sy / p.tiles, 1)
				p.sx, p.sy = nil, nil
				p.x2, p.y2 = p.x2 + 1, p.y2 + 1 -- bounding box in tile edges
				p.distance = round(math.sqrt((p.cx - center.x) ^ 2 + (p.cy - center.y) ^ 2), 0)
				patches[#patches + 1] = p
			end
		end
	end
	table.sort(patches, function(a, b) return a.distance < b.distance end)
	local out = {}
	for i = 1, math.min(#patches, args.limit or 30) do out[i] = patches[i] end
	return { center = center, patches = out }
end

-- Places an offshore pump could go, nearest first. `output` is the tile the
-- first pipe or boiler port must sit on.
function handlers.offshore_spots(args)
	local surface = surface_of(args)
	local force = force_of(args)
	local area = area_of(args, 80, 250)
	local c = { x = (area[1][1] + area[2][1]) / 2, y = (area[1][2] + area[2][2]) / 2 }
	local water = surface.find_tiles_filtered { area = area, name = water_names() }
	local is_water = {}
	for _, t in pairs(water) do is_water[t.position.x .. "," .. t.position.y] = true end
	local shore = {}
	for _, t in pairs(water) do
		local x, y = t.position.x, t.position.y
		if not (is_water[(x + 1) .. "," .. y] and is_water[(x - 1) .. "," .. y] and is_water[x .. "," .. (y + 1)] and is_water[x .. "," .. (y - 1)]) then
			shore[#shore + 1] = { x = x, y = y, d = (x - c.x) ^ 2 + (y - c.y) ^ 2 }
		end
	end
	table.sort(shore, function(a, b) return a.d < b.d end)

	-- unit vector each facing points along; the output is on the opposite side
	local facing = { [D.north] = { 0, -1 }, [D.east] = { 1, 0 }, [D.south] = { 0, 1 }, [D.west] = { -1, 0 } }
	local spots, tried, limit = {}, {}, args.limit or 8
	local spacing = args.spacing or 6
	for _, s in ipairs(shore) do
		if #spots >= limit then break end
		for dx = -1, 1 do
			for dy = -1, 1 do
				for dir, v in pairs(facing) do
					local pos = { x = s.x + dx + 0.5, y = s.y + dy + 0.5 }
					local key = pos.x .. "," .. pos.y .. "," .. dir
					if not tried[key] then
						tried[key] = true
						local far = true
						for _, o in ipairs(spots) do
							if math.abs(o.position.x - pos.x) + math.abs(o.position.y - pos.y) < spacing then far = false end
						end
						if far and #spots < limit and surface.can_place_entity { name = "offshore-pump", position = pos, direction = dir, force = force, build_check_type = defines.build_check_type.manual_ghost } then
							spots[#spots + 1] = {
								position = pos, direction = dir,
								output = { x = pos.x - v[1], y = pos.y - v[2] },
								outward = { x = -v[1], y = -v[2] },
							}
						end
					end
				end
			end
		end
	end
	return { spots = spots }
end

-- Dry run: what would happen if these entities were placed.
function handlers.check(args)
	local surface, force = surface_of(args), force_of(args)
	local specs = expand(args)
	local blocked, exists, clear, bom = {}, 0, 0, {}
	for i, spec in ipairs(specs) do
		local status, detail, obstacles = assess(surface, force, spec)
		if status == "blocked" then
			blocked[#blocked + 1] = { i = i, n = spec.name, x = spec.position.x, y = spec.position.y, why = detail }
		elseif status == "exists" then
			exists = exists + 1
		else
			clear = clear + #obstacles
			add_bom(bom, spec.name)
		end
	end
	return { total = #specs, blocked = blocked, exists = exists, to_clear = clear, bom = bom }
end

-- Tries a template at each anchor in turn and reports the first that fits.
function handlers.fit(args)
	local surface, force = surface_of(args), force_of(args)
	local template = {}
	for i, raw in ipairs(args.template) do template[i] = normalise(raw) end
	local best
	for ai, anchor in ipairs(args.anchors) do
		local bad, clear, first = 0, 0, nil
		for _, base in ipairs(template) do
			local status, detail, obstacles = assess(surface, force, transform(base, anchor))
			if status == "blocked" then
				bad = bad + 1
				first = first or (base.name .. ": " .. detail)
				if best and bad >= best.blocked then break end
			elseif status == "ok" then
				clear = clear + #obstacles
			end
		end
		if bad == 0 and clear <= (args.max_clear or math.huge) then
			return { fits = true, index = ai, anchor = anchor, to_clear = clear }
		end
		if not best or bad < best.blocked then
			best = { index = ai, anchor = anchor, blocked = bad, first = first }
		end
	end
	return { fits = false, best = best }
end

-- Places ghosts (or, with cheats on and instant = true, real entities).
-- Trees and rocks in the way are marked for deconstruction. Placement is
-- all-or-nothing unless partial = true.
function handlers.place(args)
	local surface, force = surface_of(args), force_of(args)
	local specs = expand(args)
	local instant = args.instant and true or false
	if instant and not cheats_allowed() then error("instant placement needs the 'Allow Claude to use cheats' map setting") end

	local plan, blocked, exists = {}, {}, 0
	for i, spec in ipairs(specs) do
		local status, detail, obstacles = assess(surface, force, spec)
		if status == "blocked" then
			blocked[#blocked + 1] = { i = i, n = spec.name, x = spec.position.x, y = spec.position.y, why = detail }
		elseif status == "exists" then
			exists = exists + 1
		else
			plan[#plan + 1] = { spec = spec, obstacles = obstacles }
		end
	end
	if #blocked > 0 and not args.partial then
		return { placed = 0, blocked = blocked, exists = exists, note = "nothing placed; pass partial=true to place the rest" }
	end

	local placed, cleared, bom, failed = 0, 0, {}, {}
	local tags = args.tag and { claude = args.tag } or nil
	for _, item in ipairs(plan) do
		local spec = item.spec
		for _, o in ipairs(item.obstacles) do
			if o.valid then
				if instant then o.destroy() else o.order_deconstruction(force) end
				cleared = cleared + 1
			end
		end
		local e
		if instant then
			e = surface.create_entity { name = spec.name, position = spec.position, direction = spec.direction, force = force,
				type = spec.type, recipe = spec.recipe, raise_built = true }
		else
			e = surface.create_entity { name = "entity-ghost", inner_name = spec.name, position = spec.position,
				direction = spec.direction, force = force, type = spec.type, tags = tags, raise_built = true }
			if e and spec.recipe then e.set_recipe(spec.recipe) end
		end
		if e then
			placed = placed + 1
			add_bom(bom, spec.name)
		else
			failed[#failed + 1] = { n = spec.name, x = spec.position.x, y = spec.position.y }
		end
	end
	return { placed = placed, exists = exists, cleared = cleared, blocked = blocked, failed = failed, bom = bom }
end

-- {tile = "landfill", area = box} or {tile, positions = {{x, y}, ...}}: lays
-- tile ghosts (landfill, stone path, concrete) for robots or Claude's
-- character to build. Tiles that can't take the ghost are skipped.
function handlers.tiles(args)
	local surface, force = surface_of(args), force_of(args)
	local proto = prototypes.tile[args.tile or ""]
	if not proto then error("no tile named " .. tostring(args.tile)) end
	local spots = {}
	if args.positions then
		for _, raw in ipairs(args.positions) do spots[#spots + 1] = pos_of(raw) end
	else
		local area = area_of(args, 2, 50)
		for x = math.floor(area[1][1]), math.ceil(area[2][1]) - 1 do
			for y = math.floor(area[1][2]), math.ceil(area[2][2]) - 1 do spots[#spots + 1] = { x = x, y = y } end
		end
	end
	local placed, skipped = 0, 0
	for _, pos in ipairs(spots) do
		local at = { x = math.floor(pos.x) + 0.5, y = math.floor(pos.y) + 0.5 }
		local ok, g = pcall(surface.create_entity, { name = "tile-ghost", inner_name = proto.name, position = at,
			force = force, raise_built = true })
		if ok and g then placed = placed + 1 else skipped = skipped + 1 end
	end
	local bom, items = {}, proto.items_to_place_this
	if items and items[1] and placed > 0 then bom[items[1].name] = placed * (items[1].count or 1) end
	return { placed = placed, skipped = skipped, bom = bom }
end

-- Removes ghosts in an area (all of them, or only those placed under `tag`).
function handlers.remove_ghosts(args)
	local surface, force = surface_of(args), force_of(args)
	local area = area_of(args, 10, 300)
	local n = 0
	for _, g in pairs(surface.find_entities_filtered { area = area, type = "entity-ghost", force = force }) do
		local keep = args.tag and not (g.tags and g.tags.claude == args.tag)
		if not keep then
			g.destroy()
			n = n + 1
		end
	end
	return { removed = n }
end

-- Marks entities for deconstruction: trees and rocks by default, or the
-- player's own buildings when `names` lists them.
function handlers.deconstruct(args)
	local surface, force = surface_of(args), force_of(args)
	local area = area_of(args, 10, 200)
	local list
	if args.names then
		list = surface.find_entities_filtered { area = area, name = args.names, force = force }
	else
		list = surface.find_entities_filtered { area = area, type = { "tree", "simple-entity" } }
	end
	local n = 0
	for _, e in pairs(list) do
		if e.order_deconstruction(force) then n = n + 1 end
	end
	return { marked = n }
end

-- Marks only the trees and rocks that overlap a ghost's footprint in the area,
-- so planned builds get cleared without felling the rest of the forest.
function handlers.clear_under_ghosts(args)
	local surface, force = surface_of(args), force_of(args)
	local area = area_of(args, 50, 1000)
	local seen, n = {}, 0
	for _, g in pairs(surface.find_entities_filtered { area = area, type = "entity-ghost", force = force }) do
		for _, e in pairs(surface.find_entities_filtered { area = g.bounding_box, type = { "tree", "simple-entity" } }) do
			if not seen[e.unit_number or e] and not e.to_be_deconstructed() then
				seen[e.unit_number or e] = true
				if e.order_deconstruction(force) then n = n + 1 end
			end
		end
	end
	return { marked = n }
end

-- Cancels deconstruction orders in an area (trees and rocks by default).
function handlers.cancel_deconstruct(args)
	local surface, force = surface_of(args), force_of(args)
	local area = area_of(args, 10, 1000)
	local filter = { area = area }
	if args.names then filter.name = args.names else filter.type = { "tree", "simple-entity" } end
	local n = 0
	for _, e in pairs(surface.find_entities_filtered(filter)) do
		if e.to_be_deconstructed() then
			e.cancel_deconstruction(force)
			n = n + 1
		end
	end
	return { cancelled = n }
end

-- Outstanding ghosts, the items they need, and what the player is short of.
function handlers.ghosts(args)
	local surface, force = surface_of(args), force_of(args)
	local filter = { type = "entity-ghost", force = force }
	if args.area or args.center then filter.area = area_of(args, 50, 1000) end
	local need, count = {}, 0
	for _, g in pairs(surface.find_entities_filtered(filter)) do
		count = count + 1
		local items = g.ghost_prototype.items_to_place_this
		if items and items[1] then need[items[1].name] = (need[items[1].name] or 0) + (items[1].count or 1) end
	end
	local have, short = {}, {}
	local p = player_of(args)
	local inv = p and p.get_main_inventory()
	if inv then
		for name in pairs(need) do have[name] = inv.get_item_count(name) end
	end
	for name, n in pairs(need) do
		if (have[name] or 0) < n then short[name] = n - (have[name] or 0) end
	end
	return { ghosts = count, need = need, have = have, short = short }
end

-- Blueprint strings are too big for one UDP packet, so they arrive in parts:
-- bp_part {id, i, n, data} for i = 1..n, then bp_build {id, position, direction}.
-- The game's own build_blueprint does the placing, so recipes, filters,
-- splitter priorities, chest limits and circuit wires all survive. Trees and
-- rocks in the way are marked for deconstruction (build_mode.forced).
-- Uploads are kept in memory only: a save/load drops any half-sent string.
local uploads = {}

function handlers.bp_part(args)
	local u = uploads[args.id]
	if not u or args.i == 1 then
		u = { n = args.n, parts = {} }
		uploads[args.id] = u
	end
	u.parts[args.i] = args.data
	local have = 0
	for _ in pairs(u.parts) do have = have + 1 end
	return { have = have, of = u.n }
end

function handlers.bp_build(args)
	local u = uploads[args.id]
	if not u then error("no upload with id " .. tostring(args.id)) end
	for i = 1, u.n do
		if not u.parts[i] then error("upload " .. args.id .. " is missing part " .. i .. " of " .. u.n) end
	end
	local text = table.concat(u.parts)
	local surface, force = surface_of(args), force_of(args)
	local inv = game.create_inventory(1)
	local ok, result = pcall(function()
		local stack = inv[1]
		stack.set_stack { name = "blueprint" }
		local rc = stack.import_stack(text)
		if rc == 1 then error("the game could not import that string") end
		if not stack.is_blueprint then error("that string is not a single blueprint (a book?)") end
		local ghosts = stack.build_blueprint {
			surface = surface, force = force, position = pos_of(args.position),
			direction = dir_of(args.direction or 0), build_mode = defines.build_mode.forced,
			by_player = player_of(args), raise_built = true,
		}
		local by_name = {}
		for _, g in pairs(ghosts) do
			local name = g.valid and (g.type == "entity-ghost" and g.ghost_name or g.name) or "?"
			by_name[name] = (by_name[name] or 0) + 1
		end
		return { placed = #ghosts, by_name = by_name, import_warnings = (rc == -1) }
	end)
	inv.destroy()
	uploads[args.id] = nil
	if not ok then error(result) end
	if result.placed > 0 then say("Pasted a blueprint: " .. result.placed .. " ghosts.") end
	return result
end

-- Queues hand-crafting on the player's character, exactly as if they had
-- clicked the recipe: real ingredients and real crafting time, intermediates
-- included. {recipe = name, count = items wanted} and/or {ghosts = true} to
-- craft whatever the outstanding ghosts are short of. Counts are in items,
-- not crafts. Whatever gets queued is announced in chat, so the player is
-- never surprised by their own queue.
function handlers.craft(args)
	local p = player_of(args)
	if not (p and p.character) then error("no character to craft with") end
	local wanted = {}
	if args.recipe then wanted[args.recipe] = args.count or 1 end
	if args.ghosts then
		for name, n in pairs(handlers.ghosts({ player = args.player }).short) do
			wanted[name] = (wanted[name] or 0) + n
		end
	end
	local queued, skipped, parts = {}, {}, {}
	for name, n in pairs(wanted) do
		local r = p.force.recipes[name]
		if not r then
			skipped[name] = "no recipe with that name"
		elseif not r.enabled then
			skipped[name] = "not researched"
		else
			local prod = r.products[1]
			local per = (prod and (prod.amount or prod.amount_max)) or 1
			local crafts = math.min(math.ceil(n / per), p.get_craftable_count(name))
			if crafts < 1 then
				skipped[name] = "missing ingredients"
			else
				local ok, got = pcall(p.begin_crafting, { recipe = name, count = crafts, silent = true })
				if ok and got and got > 0 then
					queued[name] = got * per
					parts[#parts + 1] = (got * per) .. " " .. name
				else
					skipped[name] = ok and "could not queue" or tostring(got)
				end
			end
		end
	end
	if #parts > 0 then say("Queued in your crafting: " .. table.concat(parts, ", ")) end
	return { queued = queued, skipped = skipped }
end

function handlers.inventory(args)
	local p = player_of(args)
	if not p then error("no player") end
	local out = { main = {}, robots = nil }
	local inv = p.get_main_inventory()
	if inv then
		for _, s in pairs(inv.get_contents()) do out.main[s.name] = (out.main[s.name] or 0) + s.count end
	end
	local c = p.character
	local net = c and c.logistic_cell and c.logistic_cell.logistic_network
	if net then
		out.robots = { construction_available = net.available_construction_robots, construction_total = net.all_construction_robots }
	end
	return out
end

-- Item production. `last_10m` is the amount over the last ten minutes.
function handlers.production(args)
	local surface, force = surface_of(args), force_of(args)
	local stats = force.get_item_production_statistics(surface)
	local names = args.items
	if not names then
		names = {}
		for name in pairs(stats.input_counts) do names[#names + 1] = name end
	end
	local out = {}
	for _, name in ipairs(names) do
		out[name] = {
			made_total = stats.get_input_count(name),
			used_total = stats.get_output_count(name),
			made_last_10m = round(stats.get_flow_count { name = name, category = "input", precision_index = defines.flow_precision_index.ten_minutes, count = true }, 1),
			used_last_10m = round(stats.get_flow_count { name = name, category = "output", precision_index = defines.flow_precision_index.ten_minutes, count = true }, 1),
		}
	end
	return out
end

function handlers.research(args)
	local force = force_of(args)
	if args.add then
		local ok = force.add_research(args.add)
		return { queued = ok }
	end
	local available = {}
	for name, tech in pairs(force.technologies) do
		if tech.enabled and not tech.researched then
			local ready = true
			for _, pre in pairs(tech.prerequisites) do
				if not pre.researched then ready = false break end
			end
			if ready then available[#available + 1] = name end
		end
	end
	table.sort(available)
	return { available = available }
end

-- Highlights an area in game so the player can see what Claude is planning.
function handlers.mark(args)
	local surface = surface_of(args)
	local area = area_of(args, 5, 500)
	local color = args.color or { r = 0.85, g = 0.55, b = 0.40, a = 0.8 }
	storage.marks = storage.marks or {}
	local ttl = args.seconds and math.floor(args.seconds * 60) or nil
	local rect = rendering.draw_rectangle { surface = surface, left_top = area[1], right_bottom = area[2], color = color,
		width = 3, filled = false, time_to_live = ttl, draw_on_ground = true }
	storage.marks[#storage.marks + 1] = rect
	if args.text then
		local label = rendering.draw_text { surface = surface, target = { area[1][1], area[1][2] - 1 }, text = "Claude: " .. args.text,
			color = color, scale = 1.5, time_to_live = ttl }
		storage.marks[#storage.marks + 1] = label
	end
	return { marks = #storage.marks }
end

function handlers.clear_marks()
	local n = 0
	for _, obj in pairs(storage.marks or {}) do
		if obj.valid then
			obj.destroy()
			n = n + 1
		end
	end
	storage.marks = {}
	return { cleared = n }
end

-- Runs Lua sent by Claude. Only with the cheats setting on.
function handlers.lua(args)
	if not cheats_allowed() then error("running Lua needs the 'Allow Claude to use cheats' map setting") end
	local chunk, err = load(args.code, "=claude", "t", setmetatable({}, { __index = _ENV }))
	if not chunk then error(err) end
	local result = chunk()
	return { value = serpent.block(result, { comment = false, nocode = true }) }
end

---------------------------------------------------------------------------
-- transport

local function reply(port, message)
	local data = helpers.table_to_json(message)
	if #data <= MAX_PACKET then
		helpers.send_udp(port, data, peer())
		return
	end
	local n = math.ceil(#data / MAX_PACKET)
	for i = 1, n do
		local piece = string.sub(data, (i - 1) * MAX_PACKET + 1, i * MAX_PACKET)
		helpers.send_udp(port, "CHUNK " .. tostring(message.id) .. " " .. i .. " " .. n .. "\n" .. piece, peer())
	end
end

local function handle(payload)
	local ok, request = pcall(helpers.json_to_table, payload)
	if not ok or type(request) ~= "table" then
		return { ok = false, error = "could not parse request as JSON" }
	end
	local id = request.id
	local fn = handlers[request.cmd]
	if not fn then return { id = id, ok = false, error = "unknown command '" .. tostring(request.cmd) .. "'" } end
	local ran, result = pcall(fn, request.args or {})
	if not ran then return { id = id, ok = false, error = tostring(result) } end
	return { id = id, ok = true, result = result }
end

script.on_event(defines.events.on_udp_packet_received, function(event)
	reply(event.source_port, handle(event.payload))
end)

-- Exposed for tests and for /c use: remote.call("claude_companion", "run", "map", {radius = 10})
remote.add_interface("claude_companion", {
	run = function(cmd, args)
		local fn = handlers[cmd]
		if not fn then error("unknown command '" .. tostring(cmd) .. "'") end
		return fn(args or {})
	end,
})

---------------------------------------------------------------------------
-- chat to Claude

local function to_claude(record)
	record.tick = game.tick
	helpers.write_file(CHAT_FILE, helpers.table_to_json(record) .. "\n", true, peer())
end

local announced = false

script.on_event(defines.events.on_tick, function()
	if not announced then
		announced = true
		to_claude { kind = "session", players = #game.connected_players }
	end
	helpers.recv_udp(peer())
end)

script.on_event(defines.events.on_console_chat, function(event)
	if not event.player_index then return end
	local mode = settings.global["claude-companion-chat-mode"].value
	if mode == "command" then return end
	if mode == "mentions" and not string.find(string.lower(event.message), "claude", 1, true) then return end
	local p = game.get_player(event.player_index)
	to_claude { kind = "chat", player = p and p.name, message = event.message }
end)

commands.add_command("claude", { "command-help.claude" }, function(cmd)
	if not cmd.parameter or cmd.parameter == "" then return end
	local p = cmd.player_index and game.get_player(cmd.player_index)
	to_claude { kind = "chat", player = p and p.name, message = cmd.parameter, direct = true }
	if p then p.print("[You -> Claude] " .. cmd.parameter, { color = { r = 0.7, g = 0.7, b = 0.7 } }) end
end)

-- The one entity (built or ghost) whose position is within half a tile of `position`.
local function entity_at(args, filter)
	local surface, force = surface_of(args), force_of(args)
	local pos = pos_of(args.position)
	local f = { area = { { pos.x - 0.45, pos.y - 0.45 }, { pos.x + 0.45, pos.y + 0.45 } }, force = force }
	for k, v in pairs(filter or {}) do f[k] = v end
	local found = surface.find_entities_filtered(f)
	if #found == 0 then error("nothing there at " .. pos.x .. "," .. pos.y) end
	return found[1]
end

-- {position, recipe}: changes a crafting machine's recipe (built or ghost).
-- Items already inside a built machine go back to the player when possible.
function handlers.set_recipe(args)
	local e = entity_at(args)
	local returned = e.set_recipe(args.recipe)
	local back = 0
	if returned and e.type ~= "entity-ghost" then
		local p = player_of(args)
		for k, stack in pairs(returned) do
			local name, n, q
			if type(stack) == "number" then name, n = k, stack else name, n, q = stack.name, stack.count or 0, stack.quality end
			if p and n > 0 then back = back + p.insert { name = name, count = n, quality = q } end
		end
	end
	return { name = e.type == "entity-ghost" and e.ghost_name or e.name, recipe = args.recipe, returned_to_player = back }
end

-- {position, to}: marks a built entity for upgrade to `to` (e.g. an
-- assembler 1 to an assembler 2). Robots swap it like the upgrade planner does,
-- keeping the recipe; the new item must be in the network or your inventory.
function handlers.upgrade(args)
	local e = entity_at(args)
	local ok = e.order_upgrade { target = args.to, force = force_of(args), player = player_of(args) }
	return { entity = e.name, to = args.to, ordered = ok }
end

-- {position, slots}: limits a chest to that many slots (the red X bar);
-- slots = nil removes the limit. Built chests only.
function handlers.chest_limit(args)
	local e = entity_at(args, { type = { "container", "logistic-container" } })
	local inv = e.get_inventory(defines.inventory.chest)
	inv.set_bar(args.slots and (args.slots + 1) or nil)
	return { chest = e.name, slots = args.slots or #inv }
end

-- {positions = {{x, y}, ...}, tree = "tree-05", item = "tree-sapling"}: plants
-- trees from the player's own saplings, one item per tree (bots cannot build
-- trees from ghosts). Spots that are blocked are skipped.
function handlers.plant(args)
	local p = player_of(args)
	local inv = p and p.get_main_inventory()
	if not inv then error("no player inventory") end
	local surface = surface_of(args)
	local tree, item = args.tree or "tree-05", args.item or "tree-sapling"
	local planted, blocked = 0, 0
	for _, raw in ipairs(args.positions or {}) do
		if inv.get_item_count(item) < 1 then break end
		local pos = pos_of(raw)
		if surface.can_place_entity { name = tree, position = pos } then
			surface.create_entity { name = tree, position = pos }
			inv.remove { name = item, count = 1 }
			planted = planted + 1
		else
			blocked = blocked + 1
		end
	end
	if planted > 0 then say("Planted " .. planted .. " trees from your saplings.") end
	return { planted = planted, blocked = blocked, saplings_left = inv.get_item_count(item) }
end

---------------------------------------------------------------------------
-- power and telemetry

-- One entry per electric network that has a generator: watts produced and
-- consumed (averaged over the last minute) by entity name, generator
-- capacity, and boilers out of fuel. Watts = per-tick joules * 60.
-- Generator max output in joules per tick. 2.x made many prototype stats
-- quality methods, and reading a missing key raises, so try both forms.
local function max_power(proto)
	local ok, v = pcall(function() return proto.get_max_power_output() end)
	if ok and v then return v end
	ok, v = pcall(function() return proto.max_power_output end)
	return (ok and v) or 0
end

function handlers.power(args)
	local surface, force = surface_of(args), force_of(args)
	local nets = {}
	for _, g in pairs(surface.find_entities_filtered { type = { "generator", "solar-panel", "burner-generator" }, force = force }) do
		local id = g.electric_network_id
		if id then
			local n = nets[id]
			if not n then
				n = { id = id, generators = {}, capacity_w = 0 }
				nets[id] = n
			end
			n.generators[g.name] = (n.generators[g.name] or 0) + 1
			n.capacity_w = n.capacity_w + max_power(g.prototype) * 60
		end
	end
	-- network statistics live on poles only (2.x), so find one per network
	for _, pole in pairs(surface.find_entities_filtered { type = "electric-pole", force = force }) do
		local n = nets[pole.electric_network_id]
		if n and not n.any then n.any = pole end
	end
	local out = {}
	for id, n in pairs(nets) do
		if not n.any then goto continue end
		local stats = n.any.electric_network_statistics
		local function flows(category)
			local t, total = {}, 0
			local counts = category == "input" and stats.input_counts or stats.output_counts
			for name in pairs(counts) do
				local w = stats.get_flow_count { name = name, category = category,
					precision_index = defines.flow_precision_index.one_minute, count = false } * 60
				if w > 0 then
					t[name] = round(w)
					total = total + w
				end
			end
			return t, total
		end
		-- Electric network statistics count consumption as "input" and
		-- generation as "output" (checked live in 2.1.25), the reverse of items.
		local made, made_total = flows("output")
		local used, used_total = flows("input")
		out[#out + 1] = {
			network = id, generators = n.generators, capacity_w = round(n.capacity_w),
			produced_w = round(made_total), consumed_w = round(used_total),
			load = n.capacity_w > 0 and round(made_total / n.capacity_w, 3) or nil,
			by_producer = made, by_consumer = used,
		}
		::continue::
	end
	local no_fuel = 0
	for _, b in pairs(surface.find_entities_filtered { type = "boiler", force = force }) do
		if b.status == defines.entity_status.no_fuel then no_fuel = no_fuel + 1 end
	end
	return { networks = out, boilers_out_of_fuel = no_fuel }
end

-- Telemetry: once a game minute, append power and key production rates to
-- script-output/claude-companion/telemetry.jsonl, so trends can be studied
-- later even while nobody is connected over UDP.
local TELEMETRY_FILE = "claude-companion/telemetry.jsonl"
local TELEMETRY_ITEMS = { "iron-plate", "copper-plate", "steel-plate", "stone-brick", "coal", "stone",
	"iron-gear-wheel", "electronic-circuit", "automation-science-pack", "logistic-science-pack" }

script.on_nth_tick(3600, function()
	local ok, rec = pcall(function()
		local surface = game.surfaces.nauvis
		local force = game.forces.player
		local p = handlers.power({})
		local stats = force.get_item_production_statistics(surface)
		local items = {}
		for _, name in ipairs(TELEMETRY_ITEMS) do
			local m = stats.get_flow_count { name = name, category = "input",
				precision_index = defines.flow_precision_index.one_minute, count = true }
			if m > 0 then items[name] = round(m, 1) end
		end
		local nets = {}
		for _, n in ipairs(p.networks) do
			nets[#nets + 1] = { capacity_w = n.capacity_w, produced_w = n.produced_w, consumed_w = n.consumed_w, load = n.load }
		end
		return { tick = game.tick, power = nets, boilers_out_of_fuel = p.boilers_out_of_fuel, per_min = items,
			ghosts = surface.count_entities_filtered { type = "entity-ghost", force = force } }
	end)
	if ok then helpers.write_file(TELEMETRY_FILE, helpers.table_to_json(rec) .. "\n", true, peer()) end
end)

---------------------------------------------------------------------------
-- task board: a checklist panel Claude fills over the bridge
--
-- storage.tasks = { list = {task...}, guide = {[player_index] = {id, line, tag}} }
-- task = { id, text, gps = {x, y}?, done = bool, when = condition? }
-- condition (ticks itself off when true, checked every 2 seconds):
--   {research = name}                       technology researched
--   {item = name, count = n}                in the player's main inventory
--   {built = name, count = n, area = box}   that many built (not ghosts) in the box
--   {no_ghosts = box}                       every ghost in the box is built
--   {made = name, count = n}                produced in total (production stats)

local function task_state()
	storage.tasks = storage.tasks or { list = {}, guide = {} }
	storage.tasks.guide = storage.tasks.guide or {}
	return storage.tasks
end

local function find_task(id)
	for _, t in ipairs(task_state().list) do
		if t.id == id then return t end
	end
end

local function render_board(p)
	if p.gui.left.claude_tasks then p.gui.left.claude_tasks.destroy() end
	local st = task_state()
	if #st.list == 0 then return end
	local frame = p.gui.left.add { type = "frame", name = "claude_tasks", direction = "vertical", caption = "Claude's board" }
	local guiding = st.guide[p.index] and st.guide[p.index].id
	for _, t in ipairs(st.list) do
		local row = frame.add { type = "flow", direction = "horizontal" }
		row.style.vertical_align = "center"
		row.add { type = "checkbox", state = t.done and true or false, tags = { claude_task = t.id, action = "check" } }
		local caption = t.done and ("[color=0.55,0.55,0.55]" .. t.text .. "[/color]") or t.text
		local label = row.add { type = "label", caption = caption }
		label.style.single_line = false
		label.style.maximal_width = 330
		if t.gps and not t.done then
			local b = row.add { type = "button", caption = (guiding == t.id) and "x" or "->",
				tooltip = (guiding == t.id) and "Stop pointing" or "Point me there",
				tags = { claude_task = t.id, action = "guide" } }
			b.style.width = 34
			b.style.height = 24
			b.style.padding = 0
		end
	end
end

local function render_all()
	for _, p in pairs(game.connected_players) do render_board(p) end
end

local function stop_guide(p)
	local st = task_state()
	local g = st.guide[p.index]
	if not g then return end
	if g.line and g.line.valid then g.line.destroy() end
	if g.tag and g.tag.valid then g.tag.destroy() end
	st.guide[p.index] = nil
end

local function start_guide(p, t)
	stop_guide(p)
	if not (t.gps and p.character) then return end
	local pos = { x = t.gps[1] or t.gps.x, y = t.gps[2] or t.gps.y }
	local g = { id = t.id, pos = pos }
	local ok, line = pcall(rendering.draw_line, {
		surface = p.surface, from = p.character, to = pos, color = { r = 1, g = 0.85, b = 0.6, a = 0.7 },
		width = 2, dash_length = 1, gap_length = 0.75, players = { p },
	})
	if ok then g.line = line end
	local ok2, tag = pcall(p.force.add_chart_tag, p.surface, { position = pos, text = "Claude: " .. t.text })
	if ok2 then g.tag = tag end
	task_state().guide[p.index] = g
end

local function complete(t, by)
	if t.done then return end
	t.done = true
	say("Done: " .. t.text)
	to_claude { kind = "task", id = t.id, text = t.text, done = true, by = by }
	for _, p in pairs(game.connected_players) do
		local g = task_state().guide[p.index]
		if g and g.id == t.id then stop_guide(p) end
	end
	render_all()
end

local function condition_met(when, p)
	if not when then return false end
	if when.research then
		local tech = p.force.technologies[when.research]
		return tech and tech.researched
	elseif when.item then
		local inv = p.get_main_inventory()
		return inv and inv.get_item_count(when.item) >= (when.count or 1)
	elseif when.built then
		return p.surface.count_entities_filtered { area = when.area, name = when.built, force = p.force } >= (when.count or 1)
	elseif when.no_ghosts then
		return p.surface.count_entities_filtered { area = when.no_ghosts, type = "entity-ghost", force = p.force } == 0
	elseif when.made then
		return p.force.get_item_production_statistics(p.surface).get_input_count(when.made) >= (when.count or 1)
	end
	return false
end

function handlers.tasks_set(args)
	local st = task_state()
	local old = {}
	for _, t in ipairs(st.list) do old[t.id] = t end
	st.list = {}
	for i, t in ipairs(args.tasks or {}) do
		local id = t.id or tostring(i)
		st.list[#st.list + 1] = { id = id, text = t.text or id, gps = t.gps, when = t.when,
			done = t.done or (old[id] and old[id].done) or false }
	end
	render_all()
	return { tasks = #st.list }
end

function handlers.tasks_done(args)
	local t = find_task(args.id)
	if not t then error("no task " .. tostring(args.id)) end
	complete(t, "claude")
	return { done = t.id }
end

function handlers.tasks_get()
	return { tasks = task_state().list }
end

script.on_nth_tick(120, function()
	local st = storage.tasks
	if not st or #st.list == 0 then return end
	local p = game.connected_players[1]
	if not p then return end
	for _, t in ipairs(st.list) do
		if not t.done and t.when then
			local ok, met = pcall(condition_met, t.when, p)
			if ok and met then complete(t, "game") end
		end
	end
	-- arrived: stop pointing once within 6 tiles
	for _, q in pairs(game.connected_players) do
		local g = st.guide[q.index]
		if g and q.character then
			local dx, dy = q.position.x - g.pos.x, q.position.y - g.pos.y
			if dx * dx + dy * dy < 36 then
				stop_guide(q)
				render_board(q)
			end
		end
	end
end)

script.on_event(defines.events.on_gui_click, function(event)
	local tags = event.element and event.element.valid and event.element.tags
	if not (tags and tags.claude_task and tags.action == "guide") then return end
	local p = game.get_player(event.player_index)
	local t = find_task(tags.claude_task)
	if not (p and t) then return end
	local g = task_state().guide[p.index]
	if g and g.id == t.id then stop_guide(p) else start_guide(p, t) end
	render_board(p)
end)

script.on_event(defines.events.on_gui_checked_state_changed, function(event)
	local tags = event.element and event.element.valid and event.element.tags
	if not (tags and tags.claude_task and tags.action == "check") then return end
	local t = find_task(tags.claude_task)
	if not t then return end
	if event.element.state then
		complete(t, "player")
	else
		t.done = false
		to_claude { kind = "task", id = t.id, text = t.text, done = false, by = "player" }
		render_all()
	end
end)

script.on_event(defines.events.on_player_joined_game, function(event)
	local p = game.get_player(event.player_index)
	if p then render_board(p) end
end)

script.on_event(defines.events.on_research_finished, function(event)
	if not event.by_script then to_claude { kind = "research", name = event.research.name } end
	local queue = event.research.force.research_queue
	if not queue or #queue == 0 then to_claude { kind = "alert", what = "research_queue_empty" } end
end)

---------------------------------------------------------------------------
-- Claude's own character: a player-less character driven by a job queue.
--
-- It plays by the same rules as a player: it walks (game pathfinding), only
-- builds, refuels or crafts with items it carries, and must be within reach.
-- Jobs (agent_jobs {jobs = {...}, replace = bool}):
--   {type = "walk", to = {x, y}}
--   {type = "take", from = {x, y}, item = name, count = n?}   from a chest/machine
--   {type = "put", to = {x, y}, item = name, count = n?}
--   {type = "build", area = box}        revive every ghost in the box it has items for
--   {type = "refuel", area = box, fuel = "coal", per = 5}   top up burners
--   {type = "craft", recipe = name, count = n}
--   {type = "say", text = "..."}
--   {type = "take_belt", area = box, item = name, count = n?}   off belts
--   {type = "mine", kind = "resource"|"tree"|"rock"|"entity", name?, at?, radius?, count?}
--   {type = "deconstruct", area = box}  mine everything marked for deconstruction
--   {type = "pickup", at?, radius?}     items lying on the ground
--   {type = "rotate", at = {x, y}, direction = n?}
--   {type = "wait", ticks = n} or {type = "wait", craft = true}
--   {type = "collect", area = box, item = name?, count = n?}   from building outputs
--   {type = "repeat", every_ticks = n, jobs = {...}, times = k?}
-- craft takes wait = true; refuel takes target = n and shares a short supply.
-- put also feeds a belt; build also lays tile ghosts (landfill) and clears
-- trees and rocks marked for deconstruction under a ghost.
-- Every finished or failed job is reported to Claude through the chat file.

local AGENT_REACH = 8
local AGENT_COLOR = { r = 1.0, g = 0.85, b = 0.6 }

local function agent_state()
	storage.agent = storage.agent or { jobs = {} }
	return storage.agent
end

local function agent_char()
	local a = agent_state()
	if a.char and a.char.valid then return a.char end
	return nil
end

local function agent_report(kind, job, extra)
	local rec = { kind = "agent", event = kind, job = job and job.type or nil }
	for k, v in pairs(extra or {}) do rec[k] = v end
	to_claude(rec)
end

local function dist(a, b)
	local dx, dy = a.x - b.x, a.y - b.y
	return math.sqrt(dx * dx + dy * dy)
end

-- atan2 sector order: east, southeast, south, ... (y grows south)
local DIR8 = {
	defines.direction.east, defines.direction.southeast, defines.direction.south, defines.direction.southwest,
	defines.direction.west, defines.direction.northwest, defines.direction.north, defines.direction.northeast,
}

local unstick -- defined below, used by goto_step

local function stop_walking(c)
	c.walking_state = { walking = false, direction = defines.direction.north }
end

-- Moves the character toward `goal`. Returns true once within `within`.
local function goto_step(a, c, goal, within)
	if dist(c.position, goal) <= within then
		stop_walking(c)
		a.path, a.path_req, a.path_goal = nil, nil, nil
		return true
	end
	local same_goal = a.path_goal and a.path_goal.x == goal.x and a.path_goal.y == goal.y
	if not same_goal then a.path, a.path_req, a.path_goal, a.path_fail = nil, nil, goal, nil end
	if not a.path then
		if not a.path_req then
			local proto = prototypes.entity["character"]
			-- Plan with a padded box: the character only walks in 8 directions, so
			-- a path threaded through a tight gap (between tree trunks, say) can't
			-- be followed and it walks into the trunk. Padding keeps clearance.
			-- Fall back to the true box after a failure, for genuinely tight spots.
			local box = (a.path_fail or 0) == 0 and { { -0.45, -0.45 }, { 0.45, 0.45 } } or proto.collision_box
			a.path_req = c.surface.request_path {
				bounding_box = box, collision_mask = proto.collision_mask,
				start = c.position, goal = goal, force = c.force, radius = math.max(within - 0.5, 0.5),
				entity_to_ignore = c, pathfind_flags = { cache = false, prefer_straight_paths = true },
			}
		end
		stop_walking(c)
		return false
	end
	local wp = a.path[a.wp]
	if not wp then
		a.path = nil -- ran out of waypoints short of the goal: path again
		return false
	end
	local p = c.position
	local dx, dy = wp.position.x - p.x, wp.position.y - p.y
	if dx * dx + dy * dy < 0.09 then
		a.wp = a.wp + 1
		return false
	end
	local i = math.floor((math.atan2(dy, dx) / (2 * math.pi)) * 8 + 0.5) % 8
	c.walking_state = { walking = true, direction = DIR8[i + 1] }
	-- stuck check: no progress for 2 seconds -> re-path; still stuck after
	-- that -> step to the nearest clear spot (it is usually wedged on a trunk)
	a.stuck = a.stuck or { pos = p, tick = game.tick, tries = 0 }
	if dist(a.stuck.pos, p) > 0.5 then
		a.stuck = { pos = p, tick = game.tick, tries = 0 }
	elseif game.tick - a.stuck.tick > 120 then
		local tries = (a.stuck.tries or 0) + 1
		if tries >= 2 then unstick(c) end
		a.path, a.path_req = nil, nil
		a.stuck = { pos = c.position, tick = game.tick, tries = tries }
	end
	return false
end

-- Moves the character to the nearest spot with clear space around it (at
-- most a few tiles). Used when the pathfinder rejects its start position,
-- e.g. wedged in the gap between an assembler and an inserter.
unstick = function(c)
	local here = c.position
	for _, r in ipairs({ 1.5, 3, 5 }) do
		local p = c.surface.find_non_colliding_position("character", { here.x + 0.01, here.y + 0.01 }, r, 0.5, true)
		if p and (math.abs(p.x - here.x) > 0.3 or math.abs(p.y - here.y) > 0.3) then
			c.teleport(p)
			return p
		end
	end
end

script.on_event(defines.events.on_script_path_request_finished, function(event)
	local a = storage.agent
	if not (a and a.path_req == event.id) then return end
	a.path_req = nil
	if event.path then
		a.path, a.wp = event.path, 1
	else
		a.path_fail = (a.path_fail or 0) + 1
		if event.try_again_later then return end
		-- first failure: the start spot is often the problem, so step clear and retry
		if a.path_fail == 1 then
			local c = agent_char()
			if c then unstick(c) end
			return
		end
		if a.path_fail >= 3 then
			local job = a.jobs[1]
			a.path_goal, a.path_fail = nil, nil
			if job and job.todo and a.target_bi then
				-- build/refuel: give up on this one target, keep the job
				job.todo[a.target_bi] = nil
				job.unreachable = (job.unreachable or 0) + 1
			else
				table.remove(a.jobs, 1)
				agent_report("failed", job, { reason = "no path" })
			end
		end
	end
end)

local function entity_at_pos(c, pos)
	local found = c.surface.find_entities_filtered { position = pos_of(pos), radius = 0.6, force = c.force }
	for _, e in pairs(found) do
		if e ~= c and e.type ~= "entity-ghost" then return e end
	end
end

local function item_inventories(e)
	-- Every inventory the entity has, output first so a take drains products
	-- before ingredients. Walks the indices instead of naming inventories:
	-- the defines were renamed in 2.x (furnace_result -> crafter_output, ...).
	local out, seen = {}, {}
	local ok, first = pcall(e.get_output_inventory)
	if ok and first then
		out[1] = first
		seen[first.index] = true
	end
	for id = 1, e.get_max_inventory_index() do
		local got, inv = pcall(e.get_inventory, id)
		if got and inv and not seen[id] then
			out[#out + 1] = inv
			seen[id] = true
		end
	end
	return out
end

-- A character with no player behind it is invisible to the game's own
-- bookkeeping: what it crafts, mines and builds reaches neither the
-- production statistics nor the technologies unlocked by a trigger ("craft a
-- lab"). So the mod does that bookkeeping for it.

-- The prototype name inside an ItemIDFilter / EntityIDFilter, however it reads.
local function id_name(f)
	if f == nil or type(f) == "string" then return f end
	local ok, n = pcall(function() return f.name end)
	if not ok or n == nil then return nil end
	if type(n) == "string" then return n end
	local ok2, n2 = pcall(function() return n.name end)
	return ok2 and n2 or nil
end

-- Researches every technology whose trigger this satisfies. `kind` is
-- "craft-item", "mine-entity" or "build-entity"; `name` the item or entity.
local function fire_triggers(c, kind, name)
	local force, fired = c.force, {}
	local stats = force.get_item_production_statistics(c.surface)
	for _, tech in pairs(force.technologies) do
		local trig = tech.enabled and not tech.researched and tech.prototype.research_trigger
		if trig and trig.type == kind and id_name(kind == "craft-item" and trig.item or trig.entity) == name then
			local ready = kind ~= "craft-item" or stats.get_input_count(name) >= (trig.count or 1)
			for _, pre in pairs(tech.prerequisites) do
				if not pre.researched then ready = false end
			end
			if ready then
				tech.researched = true
				fired[#fired + 1] = tech.name
				to_claude { kind = "research", name = tech.name, trigger = kind, by = "agent" }
			end
		end
	end
	return fired
end

-- Records `n` of an item as produced by our force.
local function credit_item(c, name, n)
	if n ~= 0 then c.force.get_item_production_statistics(c.surface).on_flow(name, n) end
end

local function product_amount(p)
	local n = p.amount or ((p.amount_min or 1) + (p.amount_max or 1)) / 2
	return n * (p.probability or 1)
end

-- Credits the crafts the character finished since the last look, by watching
-- its crafting queue shrink. Intermediates are credited too, as for a player.
local function credit_crafting(a, c)
	local snap = a.craft_snap
	local size = c.crafting_queue_size
	if not snap and size == 0 then return end
	local now = {}
	if size > 0 then
		for _, q in pairs(c.crafting_queue) do now[q.recipe] = (now[q.recipe] or 0) + q.count end
	end
	for recipe, n in pairs(snap or {}) do
		local done = n - (now[recipe] or 0)
		local r = done > 0 and c.force.recipes[recipe]
		if r then
			-- products only: the game already counts the ingredients as used
			for _, prod in pairs(r.products) do
				if prod.type == "item" then
					credit_item(c, prod.name, product_amount(prod) * done)
					fire_triggers(c, "craft-item", prod.name)
				end
			end
		end
	end
	a.craft_snap = next(now) and now or nil
end

local BELT_TYPES = { ["transport-belt"] = true, ["underground-belt"] = true, ["splitter"] = true }

-- Hand-mining progress per tick, at the character's real speed.
local function mining_speed(c)
	local function num(f, d) local ok, v = pcall(f); return (ok and type(v) == "number") and v or d end
	return num(function() return c.prototype.mining_speed end, 0.5)
		* (1 + num(function() return c.force.manual_mining_speed_modifier end, 0)
			+ num(function() return c.character_mining_speed_modifier end, 0)) / 60
end

-- One tick of mining entity `t` (not a resource) by hand, with progress kept
-- on the job. Returns "busy", "mined", or "full" (no room for the result).
local function mine_entity_step(c, inv, job, t)
	if job.mining ~= t then job.mining, job.progress = t, 0 end
	job.progress = (job.progress or 0) + mining_speed(c)
	if job.progress < (t.prototype.mineable_properties.mining_time or 1) then return "busy" end
	job.mining, job.progress = nil, 0
	local done = t.mine { inventory = inv, force = false, raise_destroyed = true, ignore_minable = false }
	return done and "mined" or "full"
end

local function hand_reach(c)
	local ok, r = pcall(function() return c.reach_distance end)
	return math.min((ok and r) or 10, AGENT_REACH)
end

-- One step of the current job. Returns "done", "failed" (with extra info) or nil.
local function job_step(a, c, job)
	local inv = c.get_main_inventory()
	if job.type == "walk" then
		return goto_step(a, c, pos_of(job.to), job.within or 1.5) and "done" or nil

	elseif job.type == "say" then
		say(job.text or "")
		return "done"

	elseif job.type == "craft" then
		if job.queued then -- wait = true: stay until the crafting is finished
			if c.crafting_queue_size > 0 then return nil end
			return "done", { queued = job.queued, crafted = true }
		end
		local can = c.get_craftable_count(job.recipe)
		if can < 1 then return "failed", { reason = "missing ingredients for " .. tostring(job.recipe) } end
		local ok, n = pcall(c.begin_crafting, { recipe = job.recipe, count = math.min(job.count or 1, can), silent = true })
		if ok and n and n > 0 then
			if job.wait then
				job.queued = n
				return nil
			end
			return "done", { queued = n }
		end
		return "failed", { reason = "cannot craft " .. tostring(job.recipe) }

	elseif job.type == "take" or job.type == "put" then
		local target = pos_of(job.type == "take" and job.from or job.to)
		if not goto_step(a, c, target, AGENT_REACH) then return nil end
		local e = entity_at_pos(c, target)
		if not e then return "failed", { reason = "nothing at target" } end
		local moved = 0
		if job.type == "take" then
			for _, src in pairs(item_inventories(e)) do
				local here = src.get_item_count(job.item)
				local want = job.count and (job.count - moved) or here
				if want > 0 and here > 0 then
					local got = src.remove { name = job.item, count = math.min(want, here) }
					local put = got > 0 and inv.insert { name = job.item, count = got } or 0
					if put < got then src.insert { name = job.item, count = got - put } end
					moved = moved + put
				end
			end
		elseif BELT_TYPES[e.type] then
			-- onto a belt: one item per lane as room comes free, like dropping by hand
			job.moved = job.moved or 0
			job.want = job.want or math.min(job.count or inv.get_item_count(job.item), inv.get_item_count(job.item))
			for li = 1, e.get_max_transport_line_index() do
				local line = e.get_transport_line(li)
				if job.moved < job.want and line.can_insert_at_back()
					and line.insert_at_back { name = job.item, count = 1 } then
					inv.remove { name = job.item, count = 1 }
					job.moved, job.idle = job.moved + 1, 0
				end
			end
			if job.moved >= job.want then return "done", { item = job.item, moved = job.moved } end
			job.idle = (job.idle or 0) + 1
			if job.idle > 300 then return "done", { item = job.item, moved = job.moved, reason = "belt is full" } end
			return nil
		else
			local have = inv.get_item_count(job.item)
			local n = math.min(job.count or have, have)
			if n > 0 then
				local ins = e.insert { name = job.item, count = n }
				if ins > 0 then inv.remove { name = job.item, count = ins } end
				moved = ins
			end
		end
		return "done", { item = job.item, moved = moved }

	elseif job.type == "take_belt" then
		-- pick items straight off belts in an area (e.g. plates backed up on a spine)
		local area = job.area
		local cx, cy = (area[1][1] + area[2][1]) / 2, (area[1][2] + area[2][2]) / 2
		if not goto_step(a, c, { x = cx, y = cy }, AGENT_REACH) then return nil end
		local want, got = job.count or 100, 0
		for _, belt in pairs(c.surface.find_entities_filtered { area = area, type = { "transport-belt", "underground-belt", "splitter" } }) do
			for li = 1, belt.get_max_transport_line_index() do
				if got >= want then break end
				local line = belt.get_transport_line(li)
				local n = line.remove_item { name = job.item, count = want - got }
				if n > 0 then
					local put = inv.insert { name = job.item, count = n }
					if put < n then line.insert_at_back({ name = job.item, count = n - put }) end
					got = got + put
				end
			end
			if got >= want then break end
		end
		return "done", { item = job.item, moved = got }

	elseif job.type == "build" or job.type == "refuel" then
		if not job.todo then
			job.todo, job.made, job.skipped = {}, 0, {}
			if job.type == "build" then
				for _, g in pairs(c.surface.find_entities_filtered { area = job.area, type = { "entity-ghost", "tile-ghost" }, force = c.force }) do
					job.todo[#job.todo + 1] = g
				end
			else
				for _, e in pairs(c.surface.find_entities_filtered { area = job.area, force = c.force }) do
					if e.type ~= "character" and e.burner then job.todo[#job.todo + 1] = e end
				end
				-- How much each burner gets. With enough fuel, each is topped up to
				-- `target`; with too little, all are levelled up to the same amount
				-- instead of the first few taking everything.
				local fuel, target = job.fuel or "coal", job.target or job.per or 5
				local have, short = {}, 0
				for i, e in pairs(job.todo) do
					local finv = e.get_fuel_inventory()
					have[i] = finv and finv.get_item_count(fuel) or target
					short = short + math.max(0, target - have[i])
				end
				local budget, level = inv.get_item_count(fuel), target
				if budget < short then
					level, job.shared = 0, true
					for l = 1, target do
						local cost = 0
						for _, h in pairs(have) do cost = cost + math.max(0, l - h) end
						if cost > budget then break end
						level = l
					end
				end
				job.give, job.burners, job.used = {}, #job.todo, 0
				local left = budget
				for i, h in pairs(have) do
					job.give[i] = math.max(0, level - h)
					left = left - job.give[i]
				end
				if job.shared then -- the remainder, one each
					for i, h in pairs(have) do
						if left > 0 and h + job.give[i] < target then
							job.give[i], left = job.give[i] + 1, left - 1
						end
					end
				end
			end
		end
		-- keep the current target until it's handled; otherwise the nearest valid one
		local best, bi
		if a.target_bi and job.todo[a.target_bi] and job.todo[a.target_bi].valid then
			bi, best = a.target_bi, 0
		end
		for i, t in pairs(bi and {} or job.todo) do
			if t.valid then
				local d = dist(c.position, t.position)
				if not best or d < best then best, bi = d, i end
			else
				job.todo[i] = nil
			end
		end
		if not bi then
			a.target_bi = nil
			return "done", { made = job.made, missing = job.skipped, unreachable = job.unreachable, blocked = job.blocked,
				burners = job.burners, fuel_used = job.used, shared = job.shared }
		end
		a.target_bi = bi
		local t = job.todo[bi]
		if job.type == "build" then
			local items = t.ghost_prototype.items_to_place_this
			local need = items and items[1]
			local count = need and (need.count or 1) or 1
			if not need or inv.get_item_count(need.name) < count then
				if need then job.skipped[need.name] = (job.skipped[need.name] or 0) + count end
				job.todo[bi] = nil
				return nil
			end
			if not goto_step(a, c, t.position, AGENT_REACH) then return nil end
			-- revive returns nil when something is in the way
			local built_name = t.ghost_name
			if t.revive { raise_revive = true } then
				inv.remove { name = need.name, count = count }
				job.made = job.made + 1
				fire_triggers(c, "build-entity", built_name)
			else
				-- clear what is marked for deconstruction under it (trees, rocks,
				-- our own buildings) by hand, then try again
				local box = t.bounding_box
				for _, o in pairs(c.surface.find_entities_filtered { area = box, to_be_deconstructed = true }) do
					local mp = o.valid and o ~= c and o.prototype.mineable_properties
					if mp and mp.minable then
						if mine_entity_step(c, inv, job, o) == "full" then
							return "done", { made = job.made, missing = job.skipped, reason = "inventory full" }
						end
						return nil
					end
				end
				job.blocked = (job.blocked or 0) + 1
			end
			job.todo[bi] = nil
		else
			local fuel = job.fuel or "coal"
			local finv = t.get_fuel_inventory()
			local short = finv and job.give[bi] or 0
			if short <= 0 then
				job.todo[bi] = nil
				return nil
			end
			if inv.get_item_count(fuel) < 1 then
				return "done", { made = job.made, burners = job.burners, fuel_used = job.used, reason = "out of " .. fuel }
			end
			if not goto_step(a, c, t.position, AGENT_REACH) then return nil end
			local n = finv.insert { name = fuel, count = math.min(short, inv.get_item_count(fuel)) }
			if n > 0 then
				inv.remove { name = fuel, count = n }
				job.made, job.used = job.made + 1, job.used + n
			end
			job.todo[bi] = nil
		end
		return nil
	elseif job.type == "mine" then
		-- Hand mining at the character's real speed and reach. Targets, nearest
		-- first, within `radius` of `at` (default: around the character):
		--   kind = "resource" (default; `name` = "iron-ore", "coal", ...),
		--   "tree", "rock", or "entity" (pick up our own buildings, `name` required).
		-- Stops after `count` items of the main product, or when nothing is left.
		local kind = job.kind or "resource"
		-- an unnamed "entity" job would pick up every building of ours in range
		if kind == "entity" and not job.name then
			return "failed", { reason = "mine kind=entity needs a name" }
		end
		local center = pos_of(job.at) or c.position
		job.got = job.got or 0
		if job.count and job.got >= job.count then return "done", { got = job.got } end
		local t = job.target
		if not (t and t.valid) then
			job.target, job.progress = nil, 0
			local filter = { position = center, radius = job.radius or 24 }
			if kind == "resource" then filter.type = "resource"; filter.name = job.name
			elseif kind == "tree" then filter.type = "tree"
			elseif kind == "rock" then filter.type = "simple-entity"
			else filter.force = c.force; filter.name = job.name end
			local best, bd
			for _, e in pairs(c.surface.find_entities_filtered(filter)) do
				local mp = e.prototype.mineable_properties
				local ok = mp and mp.minable and e ~= c and e.type ~= "character" and e.type ~= "entity-ghost"
				-- a player can't hand-mine oil, or ore that needs a fluid (uranium)
				if ok and kind == "resource" and (e.prototype.infinite_resource or mp.required_fluid) then
					ok = false
					job.skipped_fluid = job.skipped_fluid or (mp.required_fluid and true) or nil
				end
				if ok then
					local d = dist(c.position, e.position)
					if not bd or d < bd then best, bd = e, d end
				end
			end
			if not best then
				if job.skipped_fluid and job.got == 0 then
					return "failed", { reason = "cannot hand-mine " .. tostring(job.name or "this ore") .. ": it needs a fluid" }
				end
				return "done", { got = job.got, reason = "nothing left to mine" }
			end
			job.target, t = best, best
		end
		local ok_reach, reach = pcall(function() return c.resource_reach_distance end)
		reach = (ok_reach and reach) or 2.7
		if kind ~= "resource" then
			local ok_r, r = pcall(function() return c.reach_distance end)
			reach = math.min((ok_r and r) or 10, AGENT_REACH)
		end
		if not goto_step(a, c, t.position, reach - 0.3) then return nil end
		local mp = t.prototype.mineable_properties
		job.progress = (job.progress or 0) + mining_speed(c)
		if job.progress < (mp.mining_time or 1) then return nil end
		job.progress = 0
		-- the item we count: the named one, else the first product
		local main = job.item or (mp.products and mp.products[1] and mp.products[1].name)
		local before = main and inv.get_item_count(main) or 0
		if kind == "resource" then
			for _, p in pairs(mp.products or {}) do
				if p.type == "item" and (not p.probability or math.random() < p.probability) then
					local n = p.amount or math.random(p.amount_min or 1, p.amount_max or 1)
					if n > 0 then
						if not inv.can_insert { name = p.name, count = n } then
							return "done", { got = job.got, reason = "inventory full" }
						end
						inv.insert { name = p.name, count = n }
						credit_item(c, p.name, n)
					end
				end
			end
			fire_triggers(c, "mine-entity", t.name)
			if t.amount <= 1 then t.deplete() else t.amount = t.amount - 1 end
			job.got = job.got + (main and (inv.get_item_count(main) - before) or 1)
		else
			local mined_name = t.name
			local done = t.mine { inventory = inv, force = false, raise_destroyed = true, ignore_minable = false }
			if not done then return "done", { got = job.got, reason = "inventory full" } end
			job.target = nil
			local gained = main and (inv.get_item_count(main) - before) or 1
			job.got = job.got + gained
			-- wood and stone count as produced; picking a building back up doesn't
			if kind ~= "entity" then
				if main then credit_item(c, main, gained) end
				fire_triggers(c, "mine-entity", mined_name)
			end
		end
		if job.count and job.got >= job.count then return "done", { got = job.got } end
		return nil

	elseif job.type == "pickup" then
		-- items lying on the ground within `radius` of `at`
		local center = pos_of(job.at) or c.position
		local items = c.surface.find_entities_filtered { position = center, radius = job.radius or 10, type = "item-entity" }
		local best, bd
		for _, e in pairs(items) do
			local d = dist(c.position, e.position)
			if not bd or d < bd then best, bd = e, d end
		end
		if not best then return "done", { got = job.got or 0 } end
		if not goto_step(a, c, best.position, 1.2) then return nil end
		local st = best.stack
		local n = inv.insert(st)
		if n <= 0 then return "done", { got = job.got or 0, reason = "inventory full" } end
		if n >= st.count then best.destroy() else st.count = st.count - n end
		job.got = (job.got or 0) + n
		return nil

	elseif job.type == "collect" then
		-- take `item` (or everything) from the output of every building in `area`
		if not job.todo then
			job.todo, job.moved, job.from = {}, 0, 0
			for _, e in pairs(c.surface.find_entities_filtered { area = job.area, force = c.force }) do
				local chest = e.type == "container" or e.type == "logistic-container"
				if e ~= c and e.type ~= "character" and e.type ~= "entity-ghost" and (job.chests or not chest) then
					local ok, out = pcall(e.get_output_inventory)
					if ok and out and not out.is_empty() and (not job.item or out.get_item_count(job.item) > 0) then
						job.todo[#job.todo + 1] = e
					end
				end
			end
		end
		local result = { item = job.item, moved = job.moved, from = job.from }
		if job.count and job.moved >= job.count then return "done", result end
		local t, bi, bd
		for i, e in pairs(job.todo) do
			if e.valid then
				local d = dist(c.position, e.position)
				if not bd or d < bd then t, bi, bd = e, i, d end
			else
				job.todo[i] = nil
			end
		end
		if not t then return "done", result end
		if not goto_step(a, c, t.position, AGENT_REACH) then return nil end
		local out, took = t.get_output_inventory(), 0
		for _, st in pairs(out.get_contents()) do
			if not job.item or st.name == job.item then
				local want = job.count and math.min(st.count, job.count - job.moved - took) or st.count
				if want > 0 then
					local stack = { name = st.name, count = want, quality = st.quality }
					local put = inv.insert(stack)
					if put > 0 then
						stack.count = put
						out.remove(stack)
						took = took + put
					end
					if put < want then
						job.moved, job.from = job.moved + took, job.from + 1
						return "done", { item = job.item, moved = job.moved, from = job.from, reason = "inventory full" }
					end
				end
			end
		end
		job.moved = job.moved + took
		if took > 0 then job.from = job.from + 1 end
		job.todo[bi] = nil
		return nil

	elseif job.type == "repeat" then
		-- {every_ticks = n, jobs = {...}, times = k?}: runs the jobs now and again
		-- every n ticks until agent_stop. Registers the schedule and moves on, so
		-- other jobs still run in between.
		local every = tonumber(job.every_ticks)
		if not every or every < 60 then return "failed", { reason = "repeat needs every_ticks of 60 or more" } end
		if type(job.jobs) ~= "table" or #job.jobs == 0 then return "failed", { reason = "repeat needs jobs" } end
		for _, j in ipairs(job.jobs) do
			if j.type == "repeat" then return "failed", { reason = "a repeat can't hold another repeat" } end
		end
		a.repeats = a.repeats or {}
		a.repeat_id = (a.repeat_id or 0) + 1
		a.repeats[#a.repeats + 1] = { id = a.repeat_id, every = every, jobs = job.jobs, times = job.times,
			runs = 0, next_tick = game.tick }
		return "done", { id = a.repeat_id, every_ticks = every }

	elseif job.type == "deconstruct" then
		-- mine by hand everything marked for deconstruction in `area`, nearest first
		job.got = job.got or 0
		local t = job.target
		if not (t and t.valid) then
			job.target = nil
			local best, bd
			for _, e in pairs(c.surface.find_entities_filtered { area = job.area, to_be_deconstructed = true }) do
				local mp = e ~= c and e.prototype.mineable_properties
				if mp and mp.minable and e.type ~= "deconstructible-tile-proxy" then
					local d = dist(c.position, e.position)
					if not bd or d < bd then best, bd = e, d end
				end
			end
			if not best then return "done", { got = job.got } end
			job.target, t = best, best
		end
		if not goto_step(a, c, t.position, hand_reach(c) - 0.3) then return nil end
		local r = mine_entity_step(c, inv, job, t)
		if r == "full" then return "done", { got = job.got, reason = "inventory full" } end
		if r == "mined" then job.got, job.target = job.got + 1, nil end
		return nil

	elseif job.type == "rotate" then
		-- turn a building: to `direction` (0 north, 4 east, 8 south, 12 west), or one step if not given
		local target = pos_of(job.at)
		if not goto_step(a, c, target, hand_reach(c) - 0.3) then return nil end
		local e = entity_at_pos(c, target)
		if not e then return "failed", { reason = "nothing at target" } end
		if not e.supports_direction then return "failed", { reason = e.name .. " cannot be rotated" } end
		if job.direction then e.direction = job.direction else e.rotate() end
		return "done", { name = e.name, direction = e.direction }

	elseif job.type == "wait" then
		-- `ticks` to wait, or `craft = true` to wait until the crafting queue is empty
		job.until_tick = job.until_tick or (game.tick + (job.ticks or 0))
		if job.craft and c.crafting_queue_size > 0 then return nil end
		if game.tick < job.until_tick then return nil end
		return "done"

	end
	return "failed", { reason = "unknown job type " .. tostring(job.type) }
end

-- A job that finished but did nothing is a warning, not a plain "done":
-- a take that moved 0 looks just like one that worked otherwise.
local function add_warning(job, extra)
	local t, why = job.type, nil
	if t == "take" or t == "take_belt" or t == "collect" then
		if (extra.moved or 0) == 0 then why = "nothing to take there" end
	elseif t == "put" then
		if (extra.moved or 0) == 0 then why = "nothing was put" end
	elseif t == "mine" or t == "deconstruct" or t == "pickup" then
		if (extra.got or 0) == 0 then why = "nothing found" end
	elseif t == "build" then
		if (extra.made or 0) == 0 then
			why = (extra.missing and next(extra.missing) and "missing items") or (extra.blocked and "blocked")
				or (extra.unreachable and "unreachable") or "no matching ghosts"
		end
	elseif t == "refuel" then
		if (extra.made or 0) == 0 then
			if extra.burners == 0 then why = "no burners in area"
			elseif extra.reason then why = extra.reason
			else extra.reason = "nothing needed fuel" end
		end
	end
	if why then
		extra.warn = true
		extra.reason = extra.reason or why
	end
end

-- Queues the jobs of every repeat that is due and not still running.
local function run_repeats(a)
	for _, r in pairs(a.repeats or {}) do
		if not r.pending and game.tick >= r.next_tick then
			for k, j in ipairs(r.jobs) do
				local copy = deepcopy(j)
				copy.quiet, copy.repeat_id, copy.repeat_last = true, r.id, k == #r.jobs or nil
				a.jobs[#a.jobs + 1] = copy
			end
			r.pending, r.runs, r.next_tick = true, r.runs + 1, game.tick + r.every
		end
	end
end

local function repeat_round_done(a, id)
	for i, r in pairs(a.repeats or {}) do
		if r.id == id then
			r.pending = nil
			if r.times and r.runs >= r.times then table.remove(a.repeats, i) end
			return
		end
	end
end

script.on_nth_tick(1, function()
	local a = storage.agent
	if not (a and a.char) then return end
	local c = agent_char()
	if not c then return end
	-- crafting carries on after the craft job is done, so look every tick
	local fine, err = pcall(credit_crafting, a, c)
	if not fine and not a.credit_err then
		a.credit_err = true
		to_claude { kind = "error", where = "credit_crafting", error = tostring(err) }
	end
	a.jobs = a.jobs or {}
	if a.repeats and a.repeats[1] then run_repeats(a) end
	local job = a.jobs[1]
	if not job then return end
	local ok, status, extra = pcall(job_step, a, c, job)
	if not ok then status, extra = "failed", { reason = tostring(status) } end
	-- re-read the queue after a craft job adds to it, so nothing is miscounted
	if job.type == "craft" then pcall(credit_crafting, a, c) end
	if status then
		table.remove(a.jobs, 1)
		a.path, a.path_req, a.path_goal, a.stuck, a.target_bi = nil, nil, nil, nil, nil
		stop_walking(c)
		extra = extra or {}
		extra.left = #a.jobs
		if status == "done" then add_warning(job, extra) end
		if job.repeat_last then repeat_round_done(a, job.repeat_id) end
		-- a repeat's rounds only speak up when something went wrong
		if not (job.quiet and status == "done" and not extra.warn) then agent_report(status, job, extra) end
		if status == "failed" then
			to_claude { kind = "alert", what = "job_failed", job = job.type, reason = extra.reason }
		end
	end
end)

---------------------------------------------------------------------------
-- Alerts: things going wrong near Claude's character or in a watched area,
-- written to the chat file so Claude doesn't have to poll for them. An
-- entity is reported when it goes bad, and again every five minutes while it
-- stays bad; never more than once a minute.

local ALERT_TYPES = { "mining-drill", "furnace", "assembling-machine", "boiler", "inserter", "lab" }
local ALERT_RADIUS = 48

local function alert_for(e)
	local st = status_name(e)
	if st == "no_fuel" then return "no_fuel" end
	if e.type == "mining-drill" then
		if st == "waiting_for_space_in_destination" then return "output_blocked" end
		if st == "no_minable_resources" then return "no_minable_resources" end
		local ok, target = pcall(function() return e.drop_target end)
		if ok and not target then return "dropping_on_ground" end
	elseif e.type == "furnace" or e.type == "assembling-machine" then
		if st == "full_output" then return "output_full" end
	end
end

script.on_nth_tick(300, function()
	local a = storage.agent
	local c = a and a.char and a.char.valid and a.char
	local areas = {}
	if c then
		local p = c.position
		areas[1] = { surface = c.surface, force = c.force,
			area = { { p.x - ALERT_RADIUS, p.y - ALERT_RADIUS }, { p.x + ALERT_RADIUS, p.y + ALERT_RADIUS } } }
	end
	for _, w in pairs(storage.watched or {}) do
		local surface, force = game.surfaces[w.surface], game.forces[w.force]
		if surface and force then areas[#areas + 1] = { surface = surface, force = force, area = w.area } end
	end
	if #areas == 0 then return end
	storage.alerts = storage.alerts or {}
	local seen, groups, tick = {}, {}, game.tick
	for _, w in ipairs(areas) do
		for _, e in pairs(w.surface.find_entities_filtered { area = w.area, force = w.force, type = ALERT_TYPES }) do
			local id = e.unit_number
			if id and not seen[id] then
				seen[id] = true
				local what, last = alert_for(e), storage.alerts[id]
				if not what then
					if last and tick - last.t >= 3600 then storage.alerts[id] = nil elseif last then last.s = nil end
				elseif not last or (last.s ~= what and tick - last.t >= 3600) or tick - last.t >= 18000 then
					storage.alerts[id] = { s = what, t = tick }
					local g = groups[what] or { count = 0, entities = {} }
					groups[what] = g
					g.count = g.count + 1
					if #g.entities < 15 then g.entities[#g.entities + 1] = { n = e.name, x = e.position.x, y = e.position.y } end
				end
			end
		end
	end
	for what, g in pairs(groups) do
		to_claude { kind = "alert", what = what, count = g.count, entities = g.entities }
	end
	if c then
		local free = c.get_main_inventory().count_empty_stacks()
		if free <= 5 and tick - (a.inv_alert or -3600) >= 3600 then
			a.inv_alert = tick
			to_claude { kind = "alert", what = "inventory_nearly_full", free_slots = free }
		end
	end
end)

-- {area} adds an area to watch for alerts (up to 10); {clear = true} forgets them all.
function handlers.watch(args)
	storage.watched = storage.watched or {}
	if args.clear then storage.watched = {} end
	if args.area then
		if #storage.watched >= 10 then error("already watching 10 areas; clear some first") end
		storage.watched[#storage.watched + 1] = { area = area_of(args, 32, 200), surface = surface_of(args).name,
			force = force_of(args).name }
	end
	local out = {}
	for _, w in ipairs(storage.watched) do out[#out + 1] = w.area end
	return { watching = out }
end

-- Tell Claude when its character dies; the queue is dropped with it.
script.on_event(defines.events.on_entity_died, function(event)
	local a = storage.agent
	if not (a and a.char and event.entity == a.char) then return end
	local job, pos = a.jobs and a.jobs[1], event.entity.position
	a.jobs, a.path, a.path_req, a.path_goal, a.stuck, a.target_bi = {}, nil, nil, nil, nil, nil
	agent_report("died", job, { cause = event.cause and event.cause.valid and event.cause.name or nil,
		position = { x = pos.x, y = pos.y } })
end, { { filter = "type", type = "character" } })

-- Player characters reveal the map around them; a player-less one doesn't,
-- so chart around Claude's character once a second (also keeps its map
-- marker visible, since chart-mode drawings only show on charted ground).
script.on_nth_tick(60, function()
	local a = storage.agent
	local c = a and a.char
	if not (c and c.valid) then return end
	local p = c.position
	c.force.chart(c.surface, { { p.x - 48, p.y - 48 }, { p.x + 48, p.y + 48 } })
end)

-- re-aims open /claude-watch windows; defined below with the watch commands
local point_cameras

function handlers.agent_spawn(args)
	local a = agent_state()
	local c = agent_char()
	if c then return { exists = true, position = c.position } end
	local surface = surface_of(args)
	local p = player_of(args)
	local want = pos_of(args.position) or (p and p.position) or { x = 0, y = 0 }
	-- search with a 2x2 box so the spot has real room around it, not a gap
	-- between machines that the pathfinder will refuse to start from
	-- (a 2x2 footprint sits on tile corners, so no force-to-tile-centre here)
	local pos = surface.find_non_colliding_position("stone-furnace", want, 100, 0.5)
		or surface.find_non_colliding_position("character", want, 100, 0.5)
	if pos then pos = { x = pos.x, y = pos.y } end
	if not pos then error("no room for a character near " .. want.x .. "," .. want.y) end
	c = surface.create_entity { name = "character", position = pos, force = force_of(args) }
	c.color = AGENT_COLOR
	a.char = c
	pcall(function()
		a.label = rendering.draw_text { text = "Claude", surface = surface, target = { entity = c, offset = { 0, -2.6 } },
			color = AGENT_COLOR, scale = 1.3, alignment = "center" }
	end)
	-- player-less characters don't show on the map, so draw a marker there that follows it
	pcall(function()
		a.map_dot = rendering.draw_circle { surface = surface, target = c, radius = 1.5, filled = true,
			color = AGENT_COLOR, render_mode = "chart" }
		a.map_label = rendering.draw_text { text = "Claude", surface = surface, target = { entity = c, offset = { 0, -3 } },
			color = AGENT_COLOR, scale = 3, alignment = "center", render_mode = "chart" }
	end)
	if a.bots_off then c.allow_dispatching_robots = false end
	point_cameras(c)
	say("I'm here! [gps=" .. math.floor(pos.x) .. "," .. math.floor(pos.y) .. "]")
	return { spawned = true, position = pos }
end

function handlers.agent_jobs(args)
	local a = agent_state()
	if not agent_char() then error("no agent: call agent_spawn first") end
	if args.replace then
		a.jobs, a.path, a.path_req, a.path_goal = {}, nil, nil, nil
		for _, r in pairs(a.repeats or {}) do r.pending = nil end
	end
	for _, j in ipairs(args.jobs or {}) do a.jobs[#a.jobs + 1] = j end
	return { queued = #a.jobs }
end

function handlers.agent_status()
	local a = agent_state()
	local c = agent_char()
	if not c then return { alive = false } end
	local items = {}
	for _, s in pairs(c.get_main_inventory().get_contents()) do items[s.name] = (items[s.name] or 0) + s.count end
	local job = a.jobs[1]
	local out = { alive = true, position = c.position, job = job and job.type, job_got = job and job.got, queued = #a.jobs,
		walking = c.walking_state.walking, crafting = c.crafting_queue_size, inventory = items,
		free_slots = c.get_main_inventory().count_empty_stacks() }
	if job then
		-- what the job is working on right now, and how far along it is
		local t = job.target or job.mining or (job.todo and a.target_bi and job.todo[a.target_bi])
		-- (a refuel job's `target` is a number: its fuel level, not an entity)
		if type(t) == "userdata" and t.valid then
			out.job_target = { n = t.type == "entity-ghost" and t.ghost_name or t.name, x = t.position.x, y = t.position.y }
		else
			local spot = pos_of(job.to or job.from or job.at)
			if spot then out.job_target = { x = spot.x, y = spot.y } end
		end
		out.job_done = job.got or job.made or job.moved
		if job.todo then out.job_todo_left = table_size(job.todo) end
		if job.progress and job.progress > 0 then out.job_mining_progress = round(job.progress, 2) end
	end
	if c.crafting_queue_size > 0 then
		out.crafting_queue = {}
		for _, q in pairs(c.crafting_queue) do
			out.crafting_queue[#out.crafting_queue + 1] = { recipe = q.recipe, count = q.count }
		end
	end
	if a.repeats and a.repeats[1] then
		out.repeats = {}
		for _, r in ipairs(a.repeats) do
			out.repeats[#out.repeats + 1] = { id = r.id, every_ticks = r.every, runs = r.runs,
				next_in = math.max(0, r.next_tick - game.tick), running = r.pending or false }
		end
	end
	return out
end

-- Unresearched technologies that unlock by doing something rather than by
-- science packs, with what they need. `made` is how many the force has made.
function handlers.research_triggers(args)
	local force = force_of(args)
	local stats = force.get_item_production_statistics(surface_of(args))
	local out = {}
	for name, tech in pairs(force.technologies) do
		local trig = tech.enabled and not tech.researched and tech.prototype.research_trigger
		if trig then
			local ready = true
			for _, pre in pairs(tech.prerequisites) do
				if not pre.researched then ready = false end
			end
			local row = { tech = name, type = trig.type, ready = ready }
			if trig.type == "craft-item" then
				row.item, row.count = id_name(trig.item), trig.count or 1
				row.made = row.item and stats.get_input_count(row.item) or nil
			elseif trig.type == "craft-fluid" then
				row.fluid, row.amount = trig.fluid, trig.amount
			else
				row.entity, row.item = id_name(trig.entity), id_name(trig.item)
			end
			out[#out + 1] = row
		end
	end
	return { triggers = out }
end

-- {enabled = bool}: lets the character's own construction robots work, or
-- holds them back so it builds its ghosts by hand in the order it's told.
function handlers.agent_bots(args)
	local a = agent_state()
	local c = agent_char()
	if not c then error("no agent") end
	if args.enabled ~= nil then
		a.bots_off = not args.enabled or nil
		c.allow_dispatching_robots = args.enabled and true or false
	end
	return { enabled = c.allow_dispatching_robots }
end

-- Adds the map marker to an agent spawned before markers existed.
function handlers.agent_mark()
	local a = agent_state()
	local c = agent_char()
	if not c then error("no agent") end
	for _, k in ipairs({ "map_dot", "map_label" }) do
		if a[k] and a[k].valid then a[k].destroy() end
	end
	a.map_dot = rendering.draw_circle { surface = c.surface, target = c, radius = 1.5, filled = true,
		color = AGENT_COLOR, render_mode = "chart" }
	a.map_label = rendering.draw_text { text = "Claude", surface = c.surface, target = { entity = c, offset = { 0, -3 } },
		color = AGENT_COLOR, scale = 3, alignment = "center", render_mode = "chart" }
	return { marked = true }
end

-- Gives the agent the same kit Simple Bot Start gives a player (power armor
-- mk2 with roboports, reactors, batteries and shields, plus 50 construction
-- robots), so its bots build ghosts around it. Only on Chris's say-so.
local AGENT_KIT = {
	"fission-reactor-equipment", "fission-reactor-equipment", "personal-roboport-mk2-equipment",
	"personal-roboport-mk2-equipment", "fission-reactor-equipment", "fission-reactor-equipment",
	"personal-roboport-mk2-equipment", "personal-roboport-mk2-equipment", "battery-mk2-equipment",
	"battery-mk2-equipment", "energy-shield-mk2-equipment", "energy-shield-mk2-equipment",
	"energy-shield-mk2-equipment", "energy-shield-mk2-equipment",
}

function handlers.agent_kit()
	local c = agent_char()
	if not c then error("no agent") end
	local armor = c.get_inventory(defines.inventory.character_armor)
	if armor[1].valid_for_read then return { already = armor[1].name } end
	armor.insert { name = "power-armor-mk2", count = 1 }
	local grid = armor[1].grid
	local placed = 0
	for _, name in ipairs(AGENT_KIT) do
		if grid.put { name = name } then placed = placed + 1 end
	end
	local bots = c.insert { name = "construction-robot", count = 50 }
	say("Suited up: power armor, roboports and " .. bots .. " construction bots.")
	return { equipment = placed, bots = bots }
end

-- {item, count}: credits items the character crafted before the mod kept
-- count (0.2.9), and researches anything that unlocks. The items must still
-- exist, carried or built, so this can't invent production.
function handlers.agent_credit(args)
	local c = agent_char()
	if not c then error("no agent") end
	local proto = prototypes.item[args.item or ""]
	if not proto then error("no item named " .. tostring(args.item)) end
	local n = args.count or 1
	local have = c.get_main_inventory().get_item_count(proto.name)
	local place = proto.place_result
	if place then have = have + c.surface.count_entities_filtered { name = place.name, force = c.force } end
	if have < n then error("only " .. have .. " " .. proto.name .. " exist to credit") end
	credit_item(c, proto.name, n)
	return { credited = n, researched = fire_triggers(c, "craft-item", proto.name) }
end

function handlers.agent_unstick()
	local c = agent_char()
	if not c then error("no agent") end
	local p = unstick(c)
	return { moved = p ~= nil, position = c.position }
end

-- Clears the queue and every repeat. {keep_repeats = true} keeps the repeats;
-- {repeat_id = n} stops just that repeat and leaves the rest alone.
function handlers.agent_stop(args)
	local a = agent_state()
	args = args or {}
	if args.repeat_id then
		for i, r in pairs(a.repeats or {}) do
			if r.id == args.repeat_id then table.remove(a.repeats, i) break end
		end
		for i = #a.jobs, 2, -1 do
			if a.jobs[i].repeat_id == args.repeat_id then table.remove(a.jobs, i) end
		end
		return { stopped = true, repeat_id = args.repeat_id }
	end
	if args.keep_repeats then
		for _, r in pairs(a.repeats or {}) do r.pending = nil end
	else
		a.repeats = nil
	end
	a.jobs, a.path, a.path_req, a.path_goal = {}, nil, nil, nil
	local c = agent_char()
	if c then stop_walking(c) end
	return { stopped = true }
end

-- Watching Claude's character.
--   /claude-follow         the whole view follows it (remote view centred on
--                          the character); run again, or press Esc, to return.
--   /claude-watch [zoom]   a small draggable camera window that follows it, so
--                          the player can keep working; run again to close.
local CAM_NAME = "claude_cam"

function point_cameras(c)
	for _, p in pairs(game.players) do
		local frame = p.gui.screen[CAM_NAME]
		if frame and frame.cam then
			frame.cam.surface_index = c.surface.index
			frame.cam.entity = c
		end
	end
end

local function no_character(p)
	p.print("Claude has no character on the map yet.", { color = AGENT_COLOR })
end

commands.add_command("claude-follow", { "command-help.claude-follow" }, function(cmd)
	local p = cmd.player_index and game.get_player(cmd.player_index)
	if not p then return end
	local c = agent_char()
	if p.controller_type == defines.controllers.remote and c and p.centered_on == c then
		p.exit_remote_view()
		return
	end
	if not c then return no_character(p) end
	p.centered_on = c
	p.print("Following Claude. Run /claude-follow again or press Esc to come back.", { color = AGENT_COLOR })
end)

commands.add_command("claude-watch", { "command-help.claude-watch" }, function(cmd)
	local p = cmd.player_index and game.get_player(cmd.player_index)
	if not p then return end
	local zoom = tonumber(cmd.parameter or "")
	local old = p.gui.screen[CAM_NAME]
	if old then
		if zoom and zoom > 0 and old.cam then old.cam.zoom = zoom else old.destroy() end
		return
	end
	local c = agent_char()
	if not c then return no_character(p) end
	local frame = p.gui.screen.add { type = "frame", name = CAM_NAME, caption = "Claude", direction = "vertical" }
	local cam = frame.add { type = "camera", name = "cam", position = c.position, surface_index = c.surface.index,
		zoom = (zoom and zoom > 0) and zoom or 0.5 }
	cam.style.width, cam.style.height = 360, 270
	cam.entity = c
	frame.location = { 20, 120 }
end)
