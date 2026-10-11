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

Native scrolling translates text by physical pixels. Committed row changes feed
finite overlapping motion segments; steady key repeats blend into continuous
motion. Each active burst uses one shared smoothing interval. New content and its
pixel offset commit together, and release settles at the committed viewport.
Window bounce is separate from scroll smoothing. Configure its time scale:

```lua
vim.g.kitty_smooth_scroll_length = 0.10
```

Or change it live with `:SmoothScroll 0.10` (range 0.025..1 seconds).
Smaller values follow input faster; larger values spread motion over more frames.
The default is `0.10`; changes apply to the next scrolling burst.


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

## Diagnose pixel scrolling

From the Neovim checkout, run:

```sh
python3 contrib/diagnose-smooth-pixels.py
```

This opens an isolated clean Kitty/Neovim window with a long numbered buffer and
`termsync` enabled. Hold `j`, hold `k`, reverse direction, and release. Exit with
`:qa!`. The launcher reports its temporary log directory and a render timing
summary. Logs contain only motion metadata, held in bounded memory while scrolling and
written when Kitty exits normally. Close with `:qa!` to retain the capture.
Logging is disabled for ordinary launches. These records describe submitted render poses, not physical display
presentation or proof of visual smoothness.

To compare configuration effects while keeping the same numbered content and
centered viewport, add one flag at a time:

```sh
python3 contrib/diagnose-smooth-pixels.py --normal-kitty
python3 contrib/diagnose-smooth-pixels.py --normal-nvim
```

The first loads normal Kitty appearance with clean Neovim; the second loads
normal Neovim configuration/plugins with clean Kitty appearance. Both keep the
diagnostic's centered viewport and hidden numbers. A delayed `session.json`
records the executable, effective termsync and animation-plugin state. Automatic
mode bypasses key mappings; use manual mode when comparing mapped `j/k`.

If normal Kitty appearance is the slower profile, isolate compositing from font
geometry without editing configuration:

```sh
python3 contrib/diagnose-smooth-pixels.py --normal-kitty --normal-nvim --opaque
python3 contrib/diagnose-smooth-pixels.py --normal-kitty --normal-nvim --default-font
```

`--opaque` retains the configured font/row geometry and disables transparency and
blur. `--default-font` retains transparency/blur and uses the clean font, size and
cell height. `launch.json` records the exact invocation and overrides.

For degradation after several seconds, scroll for 30–45 seconds and press `F8`
(`Fn+F8` if needed) when the jumping first becomes visible. This adds a native
key timestamp; the diagnostic maps F8 to a no-op in Neovim. Exit with `:qa!`.
The temporary trace includes CoreVideo callback/output predictions, dispatch
latency, input/commit timing, CPU row shaping/copying, buffer-map durations,
submitted cursor/pane positions, swaps, and zero-wait GPU fence observations.
Early/late summaries and the marker allow those records to be compared with the
visual onset. Predicted output and fence observations do not confirm presentation.
Trace storage is bounded to 64 MiB/250,000 records, written only at normal exit;
a final summary reports truncation and logger overhead. Ordinary launches do
not enable tracing.
