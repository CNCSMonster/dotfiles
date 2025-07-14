return {
	require("plugins.lsp.blink"),
	require("plugins.lsp.format"),
	require("plugins.lsp.lspconfig"),
	{
		"williamboman/mason.nvim",
		config = function()
			require("mason").setup({})
		end,
	},
	{
		"williamboman/mason-lspconfig.nvim",
		config = true,
		ensure_installed = { "pylsp", "lua_ls", "rust_analyzer", "ts_ls", "html", "cssls", "jsonls" },
	},
}
