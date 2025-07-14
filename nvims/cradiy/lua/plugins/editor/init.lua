return {
	-- require("plugins.editor.neo-tree"),
	require("plugins.editor.yazi"),
	require("plugins.editor.comments"),
	require("plugins.editor.treesitter"),
	require("plugins.editor.fzf"),
	require("plugins.editor.outline"),
	require("plugins.editor.terminal"),
	require("plugins.editor.markdown"),
	require("plugins.editor.git"),
	require("plugins.editor.move"),
	require("plugins.editor.search"),
	{
		"windwp/nvim-ts-autotag",
		config = function()
			require("nvim-ts-autotag").setup({
				opts = {
					-- Defaults
					enable_close = true, -- Auto close tags
					enable_rename = true, -- Auto rename pairs of tags
					enable_close_on_slash = true, -- Auto close on trailing </
				},
			})
		end,
	},
	{
		"windwp/nvim-autopairs",
		event = "InsertEnter",
		config = function()
			require("nvim-autopairs").setup({
				check_ts = true,
				disable_filetype = { "TelescopePrompt", "vim" },
				fast_wrap = {
					chars = { "{", "[", "(", '"', "'" },
					pattern = string.gsub([[ [%'%"%)%>%]%)%}%,] ]], "%s+", ""),
					end_key = "$",
					keys = "qwertyuiopzxcvbnmasdfghjkl",
					check_comma = true,
					highlight = "Search",
					highlight_grey = "Comment",
				},
			})
		end,
	},
}
