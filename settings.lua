data:extend({
	{
		-- Which chat lines are passed to Claude. /claude always is.
		type = "string-setting",
		name = "claude-companion-chat-mode",
		setting_type = "runtime-global",
		default_value = "all",
		allowed_values = { "all", "mentions", "command" },
		order = "a",
	},
	{
		-- Lets Claude run arbitrary Lua and place entities instantly. Off by
		-- default: with it on, anything on this PC that can send a UDP packet
		-- to the game can run code in it.
		type = "bool-setting",
		name = "claude-companion-allow-cheats",
		setting_type = "runtime-global",
		default_value = false,
		order = "b",
	},
})
