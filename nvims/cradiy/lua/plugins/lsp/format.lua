return {
	"stevearc/conform.nvim",
	opts = {
		formatters_by_ft = {
			lua = { "stylua", lsp_format = "fallback" },
			-- Conform will run multiple formatters sequentially
			-- python = { "isort", "black" },
			-- You can customize some of the format options for the filetype (:help conform.format)
			rust = { "rustfmt", lsp_format = "fallback" },
			sh = { "shfmt", "-w", "-i", "2", "-bn", "-ci", lsp_format = "fallback" },
			-- Conform will run the first available formatter
			javascript = { "prettierd", "prettier", lsp_format = "fallback" },
			json = { "prettierd", "prettier", lsp_format = "fallback" },
			typescript = { "prettierd", "prettier", lsp_format = "fallback" },
			javascriptreact = { "prettierd", "prettier", lsp_format = "fallback" },
			typescriptreact = { "prettierd", "prettier", lsp_format = "fallback" },
		},
	},
	config = true,
}
