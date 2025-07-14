return {
	-- Disable `<leader>cs` keymap so it doesn't conflict with `outline.nvim`
	{
		"folke/trouble.nvim",
		optional = true,
		keys = {
			{ "<leader>cs", false },
		},
	},
	{
		"hedyhli/outline.nvim",
		keys = { { "<leader>cs", "<cmd>Outline<cr>", desc = "Toggle Outline" } },
		cmd = "Outline",
		opts = function()
			local defaults = require("outline.config").defaults
			local opts = {
				symbols = {
					icons = {},
					filter = vim.deepcopy(CradiyVim.kind_filter),
				},
				keymaps = {
					up_and_jump = "<up>",
					down_and_jump = "<down>",
				},
			}

			for kind, symbol in pairs(defaults.symbols.icons) do
				opts.symbols.icons[kind] = {
					icon = CradiyVim.icons.kinds[kind] or symbol.icon,
					hl = symbol.hl,
				}
			end
			return opts
		end,
	},

	-- edgy integration
	{
		"folke/edgy.nvim",
		optional = true,
		opts = function(_, opts)
			opts.right = opts.right or {}
			table.insert(opts.right, {
				title = "Outline",
				ft = "Outline",
				pinned = true,
				open = "Outline",
			})
		end,
	},
}
