return {
	"neovim/nvim-lspconfig",
	dependencies = { "saghen/blink.cmp" },

	opts = function()
		---@class PluginLspOpts
		local ret = {
			-- options for vim.diagnostic.config()
			---@type vim.diagnostic.Opts
			diagnostics = {
				underline = true,
				update_in_insert = false,
				virtual_text = {
					spacing = 4,
					source = "if_many",
					prefix = "●",
					-- this will set set the prefix to a function that returns the diagnostics icon based on the severity
					-- this only works on a recent 0.10.0 build. Will be set to "●" when not supported
					-- prefix = "icons",
				},
				severity_sort = true,
				signs = {
					text = {
						[vim.diagnostic.severity.ERROR] = CradiyVim.icons.diagnostics.Error,
						[vim.diagnostic.severity.WARN] = CradiyVim.icons.diagnostics.Warn,
						[vim.diagnostic.severity.HINT] = CradiyVim.icons.diagnostics.Hint,
						[vim.diagnostic.severity.INFO] = CradiyVim.icons.diagnostics.Info,
					},
				},
			},
			-- Enable this to enable the builtin LSP inlay hints on Neovim >= 0.10.0
			-- Be aware that you also will need to properly configure your LSP server to
			-- provide the inlay hints.
			inlay_hints = {
				enabled = true,
				exclude = { "vue" }, -- filetypes for which you don't want to enable inlay hints
			},
			-- Enable this to enable the builtin LSP code lenses on Neovim >= 0.10.0
			-- Be aware that you also will need to properly configure your LSP server to
			-- provide the code lenses.
			codelens = {
				enabled = false,
			},
			-- add any global capabilities here
			capabilities = {
				workspace = {
					fileOperations = {
						didRename = true,
						willRename = true,
					},
				},
			},
			-- options for vim.lsp.buf.format
			-- `bufnr` and `filter` is handled by the LazyVim formatter,
			-- but can be also overridden when specified
			format = {
				formatting_options = nil,
				timeout_ms = nil,
			},
			-- LSP Server Settings
			servers = {
				lua_ls = {
					settings = {
						Lua = {
							workspace = {
								checkThirdParty = false,
							},
							codeLens = {
								enable = true,
							},
							completion = {
								callSnippet = "Replace",
							},
							doc = {
								privateName = { "^_" },
							},
							hint = {
								enable = true,
								setType = false,
								paramType = true,
								paramName = true,
								semicolon = "Disable",
								arrayIndex = "Disable",
							},
						},
					},
				},
				html = {},
				ruff = {},
				basedpyright = {},
				taplo = {
					on_attach = function(client, bufnr)
						local filename = vim.api.nvim_buf_get_name(bufnr)
						if filename:match("Cargo.toml$") then
							client.server_capabilities.hoverProvider = false
						end
					end,
				},
				bashls = {},
				wgsl_analyzer = {},
				jsonls = {
					-- lazy-load schemastore when needed
					on_new_config = function(new_config)
						new_config.settings.json.schemas = new_config.settings.json.schemas or {}
						vim.list_extend(new_config.settings.json.schemas, require("schemastore").json.schemas())
					end,
					settings = {
						json = {
							format = {
								enable = true,
							},
							validate = { enable = true },
							schemas = {
								{
									description = "Package.json configuration file",
									fileMatch = { "package.json" },
									url = "https://json.schemastore.org/package.json",
								},
								{
									description = "ESLint config",
									fileMatch = { ".eslintrc", ".eslintrc.json" },
									url = "https://json.schemastore.org/eslintrc.json",
								},
								{
									description = "Prettier config",
									fileMatch = { ".prettierrc", ".prettierrc.json" },
									url = "https://json.schemastore.org/prettierrc",
								},
							},
						},
					},
				},
				vtsls = {},
				cssls = {},
			},
			-- you can do any additional lsp server setup here
			-- return true if you don't want this server to be setup with lspconfig
			---@type table<string, fun(server:string, opts:_.lspconfig.options):boolean?>
			setup = {},
		}
		return ret
	end,
	config = function(_, opts)
		local lspconfig = require("lspconfig")
		for server, config in pairs(opts.servers) do
			-- passing config.capabilities to blink.cmp merges with the capabilities in your
			-- `opts[server].capabilities, if you've defined it
			config.capabilities = require("blink.cmp").get_lsp_capabilities(config.capabilities)
			lspconfig[server].setup(config)
		end
	end,
}
