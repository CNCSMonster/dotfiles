local map = vim.api.nvim_set_keymap

map("n", "<leader>ce", ":RustLsp expandMacro<CR>", { desc = "Expand macro" })
