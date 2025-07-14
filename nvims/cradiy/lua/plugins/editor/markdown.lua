return {
	"MeanderingProgrammer/render-markdown.nvim",
	dependencies = { "nvim-treesitter/nvim-treesitter", "nvim-tree/nvim-web-devicons" }, -- if you prefer nvim-web-devicons
	opts = {},
	config = function()
		require("render-markdown").setup({
			file_types = { "markdown", "copilot-chat", "Avante" },
			heading = {
				-- Turn on / off heading icon & background rendering
				enabled = false,
			},
		})
	end,
}
