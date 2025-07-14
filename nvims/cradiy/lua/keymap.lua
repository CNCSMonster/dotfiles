local map = vim.api.nvim_set_keymap

local opts = { noremap = true, silent = true }

map("t", "<C-]>", "<C-\\><C-n>", opts)
map("n", "<C-z>", "", opts)
map("t", "<C-z>", "", opts)

vim.keymap.set("n", "<leader>+", "<C-w>+")
vim.keymap.set("n", "<leader>-", "<C-w>-")
vim.keymap.set("n", "<leader>>", "<C-w>>")
vim.keymap.set("n", "<leader><", "<C-w><")
map("n", "<C-+>", "<C-w>+", {})
map("n", "<leader>ga", ":DiffviewOpen<CR>", { desc = "Open diff view" })
map("n", "<leader>gF", ":DiffviewFileHistory<CR>", { desc = "Diff view file history" })
map("n", "<leader>gd", ":DiffviewClose<CR>", { desc = "Close diffview panel" })
map("n", "<C-h>", "<C-w>h", { noremap = true, silent = true })
map("n", "<C-l>", "<C-w>l", { noremap = true, silent = true })
map("n", "<C-j>", "<C-w>j", { noremap = true, silent = true })
map("n", "<C-k>", "<C-w>k", { noremap = true, silent = true })

map("i", "<C-r>", "", { noremap = true, silent = true })

map("n", "<leader>cr", ":lua vim.lsp.buf.rename()<CR>", { desc = "Lsp rename" })
map("n", "<leader>ca", ":FzfLua lsp_code_actions<CR>", { desc = "Code action" })

-- map("n", "gr", ":FzfLua lsp_references<CR>", { desc = "References" })
-- map("n", "gD", ":FzfLua lsp_declarations<CR>", { desc = "Goto Declaration" })
-- map("n", "gd", ":FzfLua lsp_definitions<CR>", { desc = "Goto Definition" })
-- map("n", "gy", ":lua vim.lsp.buf.type_definition()<CR>", { desc = "Goto T[y]pe Definition" })
-- map("n", "gI", ":FzfLua lsp_implementations<CR>", { desc = "Goto Implementation" })

map("n", "<leader>bd", ":lua Snacks.bufdelete()<CR>", { desc = "Delete Buffer" })

map("n", "<C-Up>", "<cmd>resize +2<cr>", { desc = "Increase Window Height" })
map("n", "<C-Down>", "<cmd>resize -2<cr>", { desc = "Decrease Window Height" })
map("n", "<C-Left>", "<cmd>vertical resize +2<cr>", { desc = "Increase Window Width" })
map("n", "<C-Right>", "<cmd>vertical resize -2<cr>", { desc = "Decrease Window Width" })

map("n", "<S-h>", "<cmd>bprevious<cr>", { desc = "Prev Buffer" })
map("n", "<S-l>", "<cmd>bnext<cr>", { desc = "Next Buffer" })

map("v", "<", "<gv", opts)
map("v", ">", ">gv", opts)

map("n", "<leader>l", "<cmd>Lazy<cr>", { desc = "Lazy" })

map("n", "<C-/>", ":lua Snacks.terminal()<cr>", { desc = "Snacks terminal" })
map("t", "<C-/>", "<cmd>close<cr>", { desc = "Hide Terminal" })
