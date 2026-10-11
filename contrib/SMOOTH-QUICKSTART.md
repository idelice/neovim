# My smooth Kitty + Neovim setup

## Install on my M3 Mac

Requires Homebrew and Apple Command Line Tools. These changes must be pushed to
my Neovim fork first.

```sh
git clone https://github.com/idelice/neovim.git
cd neovim
./contrib/install-smooth-macos
```

Only clone Neovim: the installer fetches and builds Kitty too.

## Daily use

Open **Kitty Smooth** from `~/Applications`, then:

```sh
cd ~/projects/my-project
nvim .
```

Neovim opens inside the same terminal. It uses the config/plugins already on
that Mac. My regular Kitty and other terminals stay unchanged.

## Language server logs

Use `:JlsLog` for JLS, or `:lua vim.cmd.edit(vim.lsp.log.get_filename())`
for the active Neovim LSP log. This fork writes to
`~/.local/state/nvim/logs/lsp.log`; regular Neovim 0.12 writes to
`~/.local/state/nvim/lsp.log`. Watching the old path will miss the fork's output.

## Adjust bounce

Add to my Neovim `init.lua`:

```lua
vim.g.kitty_smooth_bounce = {
  strength = 0.5, -- amount: 0 disables it; default 1; range 0..3
  duration = 1.5, -- higher = slower; default 1; range 0.25..3
}
```

Try it live without restarting:

```vim
:SmoothBounce 0.5 1.5
```

Live changes last for this session. Save the Lua config to keep them.
Cursor bounce and trails remain disabled.

Keep `:set termsync` enabled: synchronized redraws commit grid content and scroll
origins together, preventing duplicated-text flicker. The bundled setup enables it.

Native scrolling keeps persistent position and velocity. At a synchronized commit,
the old motion advances to the commit time before new viewport rows rebase its
position, preserving velocity. Rendered frames then advance from that timestamp.
Window bounce is separate from scroll response. Configure the scroll response in seconds:

```lua
vim.g.kitty_smooth_scroll_length = 0.10
```

Or change it live with `:SmoothScroll 0.10` (range 0.025..1 seconds).
Smaller values follow input faster; larger values spread motion over more frames.


For cursor isolation, `:SmoothCursor off` hides cursor drawing and
`:SmoothCursor on` restores it within the same session. This allows comparison
after the font/glyph caches have warmed up, without restarting.

## Upgrade to latest stable Neovim + Kitty

Run only when I want an upstream upgrade. Commit my local changes first.

```sh
./contrib/upgrade-smooth-macos
```

Uses stable tags only. Prepares separate checkouts; conflicts stop the upgrade
and are printed in the terminal. My active installation stays in place on
conflict or build failure. On success, reopen Kitty Smooth.

If the new version has a visual regression:

```sh
./contrib/install-smooth-macos --rollback
```

Then reopen Kitty Smooth.

## Update my fork’s published changes

From my cloned Neovim repository:

```sh
git pull
./contrib/install-smooth-macos
```

Close old Kitty Smooth windows and reopen the app.

## Uninstall

```sh
./contrib/install-smooth-macos --uninstall
```

Removes the app and shell routing; keeps builds and backups.
Keep `~/.local/share/kitty-smooth` while using the app.

More details: [installer README](smooth-installer/README.md).
