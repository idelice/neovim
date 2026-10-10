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

## Upgrade upstream versions only when wanted

Commit local Neovim changes first, then run:

```sh
./contrib/upgrade-smooth-macos
```

The script selects the highest numeric stable tag from the official Neovim and
Kitty repositories, excluding nightly/prerelease tags. It transplants our custom
changes onto those exact tag commits in isolated checkouts, rather than merging
upstream master. This matters when our original base is newer than stable.

Conflicts stop before any build/install, print the affected files, and leave the
original checkout and active installation untouched. Prepared/conflicted sources
are retained under `~/.local/share/kitty-smooth-upgrades` for investigation. Nothing
is pushed. Commit custom changes before retrying; the script refuses dirty sources.

When both patches apply, the installer builds and smoke-tests both forks before
activation. Build failures retain the active version. Reopen Kitty Smooth after
success. Subsequent runs reuse the last successfully adapted source when the
original checkout has not changed. Keep the upgrades directory for that purpose.
If the original checkout changes, its committed changes are used instead.

A clean patch/build does not guarantee identical visual behavior. If manual
use exposes a regression, restore the previous build:

```sh
./contrib/install-smooth-macos --rollback
```

Close old Kitty Smooth windows and reopen. Rollback switches the managed build;
it does not change your original repository or config. To prepare sources without
building or activating anything, use `./contrib/upgrade-smooth-macos --prepare-only`.

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
includes committed and tracked working-tree changes relative to the recorded
upstream base, so a separate Kitty branch does not have to be published. Before publishing new Kitty changes, run:

```sh
python3 contrib/smooth-installer/refresh-kitty-patch.py ../kitty
# After deliberately changing the upstream base:
# python3 contrib/smooth-installer/refresh-kitty-patch.py ../kitty --base vX.Y.Z
```

Publish the Neovim source changes, Lua bridge, installer, manifest, and patch
together. Do not substitute an arbitrary newer Kitty base without testing.
