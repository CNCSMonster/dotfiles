return {

	{
		"akinsho/toggleterm.nvim",
		version = "*",
		config = function()
			require("toggleterm").setup({
				open_mapping = [[<c-\>]],
				hide_numbers = true, -- hide the number column in toggleterm buffers
				shade_filetypes = {},
				shade_terminals = true,
				start_in_insert = true,
				insert_mappings = true, -- whether or not the open mapping applies in insert mode
				persist_size = true,
				-- direction = 'horizontal',
				direction = "float",
				float_opts = {
					border = "curved",
				},
			})
		end,
	},
	{
		"folke/edgy.nvim",
		---@module 'edgy'
		---@param opts Edgy.Config
		opts = function(_, opts)
			for _, pos in ipairs({ "top", "bottom", "left", "right" }) do
				opts[pos] = opts[pos] or {}
				table.insert(opts[pos], {
					ft = "snacks_terminal",
					size = { height = 0.4 },
					title = "🦀 LazyTerm",
					filter = function(_, win)
						return vim.w[win].snacks_win
							and vim.w[win].snacks_win.position == pos
							and vim.w[win].snacks_win.relative == "editor"
							and not vim.w[win].trouble_preview
					end,
				})
			end
		end,
	},
}
