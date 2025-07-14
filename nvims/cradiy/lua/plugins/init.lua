return {
	{ "nvim-lua/plenary.nvim", lazy = true },
	require("plugins.lsp"),
	require("plugins.lang"),
	require("plugins.editor"),
	require("plugins.ui"),
}
