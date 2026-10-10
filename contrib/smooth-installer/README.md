# Kitty Smooth on an Apple Silicon Mac

Clone **only the Neovim fork** containing these changes, then run:

```sh
git clone https://github.com/idelice/neovim.git
cd neovim
./contrib/install-smooth-macos
```

The installer needs native Apple Silicon Homebrew and Apple Command Line Tools
(`xcode-select --install` if missing). It installs build tools with Homebrew,
fetches the pinned Kitty source, applies the bundled patch, and builds both forks.
No manual compilation is needed. Network access and the first build can take time.
These instructions require publishing the installer and Neovim changes first;
cloning an older revision will not include them.

Open **Kitty Smooth** in your home Applications folder, then use normally:

```sh
nvim .
```

Neovim runs in the same terminal and returns to the same shell when you quit.
It loads the Neovim config/plugins already on that Mac. This installer does not
copy another Mac's config, private plugins, language servers, or fonts.
Your regular Kitty config is reused; the launcher overrides only animation
settings and starts a zsh login shell. Stock apps and binaries are preserved.

The installer adds one conditional block to your `.zshrc`, with a backup. The
block routes `nvim` to the fork only inside Kitty Smooth, including overriding
an existing `nvim` alias/function there. Other terminals keep their existing
command. zsh is currently required. Custom `ZDOTDIR` is supported when exported
in the environment that runs the installer.

Builds live in `~/.local/share/kitty-smooth`. **Keep that folder.** The app uses
those sources and dependencies; it is not a self-contained transferable bundle.
You may delete the repository you cloned after installing. The official Kitty
app provides the Slang compiler; if absent, it is installed using Homebrew. An
existing app without that compiler is preserved and produces an update message.

## Adjust bounce

In your Neovim `init.lua` (or an early config module):

```lua
vim.g.kitty_smooth_bounce = {
  strength = 0.5,  -- 0 disables bounce; default 1; allowed 0..3
  duration = 1.5,  -- larger = slower; default 1; allowed 0.25..3
}
```

Try changes live with:

```vim
:SmoothBounce 0.5 1.5
```

This controls scrolling and pane/content settling. Cursor bounce and trails stay
disabled. The live command applies to this session; edit config to persist it.

## Check, update, and uninstall

Validate the checkout and patch without installing:

```sh
./contrib/install-smooth-macos --check
```

To update, pull the Neovim fork and run the installer again. Each successful run
creates a new build, then switches the managed `current` link. Failed builds
leave the active installation alone. Close old Kitty Smooth windows before
opening the updated app.

Uninstall app/shell routing, keeping builds and backups:

```sh
./contrib/install-smooth-macos --uninstall
```

You can run this from a fresh clone if you deleted the original. Homebrew
packages and stock applications are never removed. Backups are under
`~/.local/share/kitty-smooth/backups`.

## Maintainer: refresh the Kitty snapshot

The manifest pins Kitty's base commit and checksums `kitty.patch`. The patch
includes the tested working-tree changes, so a separate Kitty branch does not
have to be published. Before publishing new Kitty changes, run:

```sh
python3 contrib/smooth-installer/refresh-kitty-patch.py ../kitty
```

Publish the Neovim source changes, Lua bridge, installer, manifest, and patch
together. Do not substitute an arbitrary newer Kitty base without testing.
