-- Session-only settings; your on-disk configuration is untouched.
vim.opt.mouse = 'a'
vim.opt.mousescroll = 'ver:1,hor:1'

local function apply_bounce()
  local config = vim.g.kitty_smooth_bounce or {}
  local strength = config.strength == nil and 1 or config.strength
  local duration = config.duration == nil and 1 or config.duration
  if type(strength) ~= 'number' or strength ~= strength or strength < 0 or strength > 3
      or type(duration) ~= 'number' or duration ~= duration or duration < 0.25 or duration > 3 then
    error('kitty_smooth_bounce: strength must be 0..3 and duration 0.25..3')
  end
  vim.api.nvim_ui_send(('\27]9926;%g;%g\27\\'):format(strength, duration))
end
apply_bounce()
local function apply_scroll()
  local length = vim.g.kitty_smooth_scroll_length or 0.10
  if type(length) ~= 'number' or length ~= length or length < 0.025 or length > 1 then
    error('kitty_smooth_scroll_length must be 0.025..1 seconds')
  end
  vim.api.nvim_ui_send(('\27]9927;%g\27\\'):format(length))
end
apply_scroll()
vim.api.nvim_create_user_command('SmoothScroll', function(args)
  local previous = vim.g.kitty_smooth_scroll_length
  local length = tonumber(args.args)
  if not length then error('Usage: SmoothScroll <seconds 0.025..1>') end
  vim.g.kitty_smooth_scroll_length = length
  local ok, err = pcall(apply_scroll)
  if not ok then vim.g.kitty_smooth_scroll_length = previous; error(err) end
end, { nargs = 1, desc = 'Adjust native scroll response time in seconds' })
vim.api.nvim_create_user_command('SmoothCursor', function(args)
  if args.args ~= 'on' and args.args ~= 'off' then error('Usage: SmoothCursor on|off') end
  vim.api.nvim_ui_send(('\27]9928;%d\27\\'):format(args.args == 'off' and 1 or 0))
end, { nargs = 1, complete = function() return { 'on', 'off' } end,
  desc = 'Show or hide cursor drawing for scroll diagnosis' })
vim.api.nvim_create_user_command('SmoothBounce', function(args)
  if #args.fargs ~= 2 then error('Usage: SmoothBounce <strength 0..3> <duration 0.25..3>') end
  local strength, duration = tonumber(args.fargs[1]), tonumber(args.fargs[2])
  if not strength or not duration then error('SmoothBounce expects two numbers') end
  local previous = vim.g.kitty_smooth_bounce
  vim.g.kitty_smooth_bounce = { strength = strength, duration = duration }
  local ok, err = pcall(apply_bounce)
  if not ok then vim.g.kitty_smooth_bounce = previous; error(err) end
end, { nargs = '*', desc = 'Adjust surface bounce strength and settling duration' })


-- The terminal owns animation. Prevent a second animator from repeatedly
-- changing Neovim's logical viewport, including after lazy plugin startup.
vim.g.snacks_scroll = false
local scroll = package.loaded['snacks.scroll']
if scroll then scroll.disable() end
local animate = package.loaded['mini.animate']
if animate and animate.config then
  for _, kind in ipairs({ 'scroll', 'cursor', 'resize', 'open', 'close' }) do
    if animate.config[kind] then animate.config[kind].enable = false end
  end
end

local group = vim.api.nvim_create_augroup('KittySmoothNavigation', { clear = true })
vim.api.nvim_create_autocmd('User', {
  group = group,
  pattern = 'VeryLazy',
  callback = function()
    apply_bounce()
    apply_scroll()
    vim.g.snacks_scroll = false
    local loaded = package.loaded['snacks.scroll']
    if loaded then loaded.disable() end
    local mini = package.loaded['mini.animate']
    if mini and mini.config then
      for _, kind in ipairs({ 'scroll', 'cursor', 'resize', 'open', 'close' }) do
        if mini.config[kind] then mini.config[kind].enable = false end
      end
    end
  end,
})
-- Native frames carry buffer and focused-window identity. Let their committed
-- inventory invalidate departed content and retarget the cursor. Resetting from
-- Lua autocmds happens before that commit and snaps the cursor on every edit,
-- mode transition, and window change (including temporary plugin windows).

-- Native Ctrl-D/U, j/k, counts, folds, and mappings remain intact. Kitty now
-- retains the departing rows and animates the full native viewport update.

-- Native redraw frames carry window identity, geometry, and retained grid
-- contents. Lua does not classify plugins or infer window lifecycle.
vim.opt.termsync = true

vim.api.nvim_create_user_command('SmoothStats', function()
  vim.api.nvim_ui_send('\27]9916;\27\\')
end, { desc = 'Show Kitty animation render FPS and worst frame interval' })
vim.api.nvim_create_autocmd('TermResponse', {
  group = group,
  callback = function(event)
    local response = event.data and event.data.sequence or vim.v.termresponse or ''
    local frames, fps, worst = response:match('9916;(%d+);([%d.]+);([%d.]+)')
    if frames then
      vim.notify(('Kitty: %s render FPS, worst frame %s ms (%s intervals). Display refresh limits presentation.'):format(fps, worst, frames))
    end
  end,
})

