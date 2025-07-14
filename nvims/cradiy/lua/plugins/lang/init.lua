return {
	require("plugins.lang.rust"),
	require("plugins.lang.lua"),
	{
		"cradiy/inlay-hints.nvim",
		event = "LspAttach",
		dependencies = { "neovim/nvim-lspconfig" },
		config = function()
			require("inlay-hints").setup()
		end,
	},
	"mfussenegger/nvim-dap",
}
