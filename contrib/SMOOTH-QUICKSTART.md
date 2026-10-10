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
