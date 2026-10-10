# Kitty + Neovim smooth navigation prototype

Both forks are built. Open the forked Kitty once:

```sh
~/projects/neovim/contrib/smooth-nvim --terminal
```

In that shell, run this for each project; it uses the current terminal and returns
to the same shell on exit:

```sh
~/projects/neovim/contrib/smooth-nvim .
```

Your normal Neovim config and plugins load. To compare without plugins:

```sh
~/projects/neovim/contrib/smooth-nvim --clean path/to/long/file
```

Opening a new Kitty window to run Neovim is available explicitly with
`--new-window`; it is never the default. Existing Kitty processes must restart
once to export the fork capability marker. Shell configuration remains untouched.
The optional `contrib/bin/nvim` wrapper can be placed ahead of stock Neovim during
installation; user shell PATH precedence must be configured then.

## What to test

- Hold j/k, reverse direction, use Ctrl-D/U and Ctrl-E/Y.
- Jump with `gg`, `G`, a search, or a line number; recenter with `zz` and your
  centering mappings. Test inside a split as well as a single pane.
- Move the cursor across a stationary viewport using `H`, `M`, `L`, `w`, and `b`.
- Open/close explorers, pickers, completion and diagnostic floats. Navigate
  between their buffers, move or resize panes, and compare repeated actions.
  Check that old window contents do not remain behind moving windows.
- After navigating, run `:SmoothStats` to report mean render FPS and worst frame
  interval since the previous query. These are render timings, not measured
  monitor presentation times. A zero count means no animation was measured.

Native motions, counts, and mappings retain their normal logical destinations.
The session disables Snacks scroll animation (including after lazy startup) and
mini.animate cursor/scroll/window animations to avoid two animators competing. On-disk config
is untouched. Kitty now loads your normal configuration, including terminal
colors, fonts, background opacity and blur. The explicit terminal launcher overrides `cursor_trail=0`, `input_delay=1` and
`sync_to_monitor=yes`. Native motion follows display callbacks without being
capped by the ordinary terminal repaint delay. Without display callbacks it uses
a 4 ms fallback; synchronized displays have a 250 ms recovery wakeup rather
than polling every 2 ms. All springs in one uniform update sample the same clock.
Actual presentation remains limited by display refresh and rendering cost.

## Renderer

Kitty retains text above and below a rectangular scrolling pane, then uses an
analytic critically damped spring (omega=24) with continuous position/velocity
across input and reversals. Positions round to device pixels for crisp bitmap
text. Each native pane/grid owns its scroll spring, retained rows, and cache.
Several panes can animate concurrently without cancelling one another; clipping
keeps other panes and status bars stationary.

Large jumps that bypass Neovim's terminal scroll optimization now notify Kitty
before their replacement rows are drawn. Their animation retains a bounded old
viewport and the new destination; unseen intermediate text is not synthesized.
Native source notifications also cover floating grids and covered/blended panes.

The cursor has a separate two-dimensional spring (omega=32). Retargeting
preserves velocity, and logical scrolling compensates its position to avoid
moving it twice. During motion the text shader renders a block, beam, underline, or hollow
cursor at fractional coordinates, with its cursor/text colors applied to the
actual glyph fragments. The native cursor returns on the final frame. Cursor
position also follows the moving window geometry. Native focus identity prevents
a departing or overlapping window from taking cursor ownership. Changing a
window buffer invalidates only that window’s old scroll cache.

Window presentation uses native Neovim grids before terminal composition. The
base grid retains editor text beneath floats; each floating window and native
popup/message grid has its own retained contents. Native window handles provide
identity for layout changes and buffer replacement. No filetype, explorer name,
or plugin lifecycle callback selects an animation.

Every redraw publishes a complete geometry inventory and changed grid content.
Kitty commits these together at the synchronized-update boundary. Moving a
floating window reveals the actual underlying grid, rather than a screenshot
containing the previous floating window. Buffer changes replace a window's
content without creating a new window identity. Equal-z-index layers follow
Neovim's compositor order. Dense compositor ranks also preserve arbitrary high
z-indices without exceeding the terminal's priority range. Native clipping and blended highlights are exported.

The transport retains ANSI text shaping/highlights in independent Kitty buffers.
Regular splits remain crops of the base grid while live; floating surfaces are
independent. Width and height have their own critically damped springs, preserving
velocity across rapid geometry changes. Visible bounds and right/bottom borders
move while glyph pixels remain unscaled. Source content reflows at Neovim's
logical destination; presentation bounds interpolate continuously.

Closing windows dismiss at the synchronized redraw boundary. Surviving panes
continue to animate their updated geometry without a shrinking old window
covering the new layout. Background coverage and replacement compositing preserve
transparency without full-screen crossfades. Departed grids and scroll caches
are released at commit.
This is still a prototype: physical display pacing and visual transitions need
manual comparison, and graphics/images are outside the text-grid bridge.

Retained text participates in text-cache garbage collection. Resize, reset,
alternate-screen exit, and opt-out free snapshots. Graphics/images do not belong
to these retained text layers. Mouse hit testing follows Neovim's final cell-grid
layout while its presentation animates; keyboard use is the focus here.

## Private protocol

All behavior is opt-in through `NVIM_KITTY_SMOOTH` and the launcher Lua file.
Other terminals and normal Neovim launches receive no native bridge events.

- `9912;1`: enable; other payloads disable and free animation state.
- `9911;top;bottom;left;right;delta`: legacy departing-row scroll control.
  Bounds are zero-based/exclusive; the legacy three-field form is accepted.
- `9913;`: settle scrolling/focus while preserving opt-in.
- `9914;...` / `9915;...` / `9917;`: legacy scene/motion controls; the launcher
  no longer emits these to infer window lifecycle.
- `9916;`: query/reset render timings. Response:
  `9916;interval_count;mean_fps;worst_interval_ms`.
- `9918;`: begin native grid/layout inventory.
- `9919;id;top;bottom;left;right;priority;border_mask;buffer_id`: identify a native
  window/grid, borders and buffer lifecycle. The final two fields are optional.
- `9923;owner_id;top;bottom;left;right;delta`: retarget that native pane's own scroll.
- `9924;owner_id`: identify the native cursor/focus window.
- `9921;id;top;left;width;height;priority`: select retained backing surface;
  subsequent ANSI text updates this offscreen surface.
- `9922;`: restore terminal output destination and cursor state.
- `9920;`: finish inventory; commit at the synchronized redraw boundary and
  remove omitted windows promptly at the committed redraw. Unchanged backing
  grids are retained without resend,
  except one recovery resend after inventory identities change.

Kitty's custom shaders can add final-image effects, but cannot recover window
geometry or old text from a flattened terminal frame. These changes operate in
the cell renderer before postprocessing; no custom shader is required.

## Validation

Both native forks and the modified shader variants build. Native PTY regression
`python3 contrib/test-smooth-grids.py` creates overlapping windows with no
filetype, moves them, replaces buffers in place, and closes them. It verifies
stable identities, independent base/float content, lifecycle inventory, high-z-index
floats and the native completion menu.
Replaying its stream through Kitty checks actual retained buffers and removal.
`python3 contrib/test-smooth-scroll-owners.py` verifies independent source-owned
scroll events for two normal panes and an overlapping float, including opt-out.

Additional native checks cover wide/combining Unicode, highlight-only changes,
negative-coordinate clipping, native completion popup grids, normal scrolling,
large jumps, and opt-out. Kitty regression tests cover animation continuity,
independent layers, owner-specific scroll retention, synchronized commits and
reset/garbage collection. Session checks preserve normal user mappings and
configuration. Visual parity and physical display FPS still require manual
comparison; the computer-use tool does not permit inspecting Kitty.

## nvim-jls compatibility

The newer fork runtime no longer exposes the private LSP utility
`_get_line_byte_from_position`. The local nvim-jls plugin now uses the public
`vim.str_byteindex` API, with its earlier signature retained for Neovim 0.10.
Scheduled hints skip unloaded buffers and stale lines. A pushed-hint regression
test covers UTF-8/16/32 and disappearing buffers; it passes on this fork and the
installed Neovim 0.12.5. Restart the prototype to load the updated plugin module.

## Theme/transparency diagnosis

Cyberdream is selected by your normal Neovim config, true color is enabled, and
its `Normal` highlight has no background. The earlier launcher bypassed Kitty's
configuration with `--config NONE`, which removed the terminal transparency and
palette beneath that transparent highlight. It now loads your usual Kitty
config; configuration checks confirm your themed background, 80% opacity,
blur 30, and font settings load. `--clean` still selects clean Neovim settings
while retaining the terminal configuration. Final appearance requires manual
comparison on the desktop.

## Generic architecture regression check

Restart the launcher and test any explorer, picker, completion menu or diagnostic
float. Move between buffers and directories, open overlapping windows, and close
them in different orders. Verify that window contents remain separate and the
editor underneath is revealed immediately. No plugin-specific animation
classification is used. Existing session compatibility settings still disable
competing scroll animators; those settings do not select animation surfaces.

Up to 32 window/grid records animate. Larger layouts fall back to complete native
terminal output, with retained-grid presentation recovering when capacity permits.
Window bounds interpolate while glyphs remain crisp; buffer text reflow still
follows Neovim’s final logical layout. Graphics/images remain outside the
text-grid bridge. Automated checks do not replace the final desktop comparison.

Native panel transitions use a short slide and bounded settling from their attached
edge, inferred from window geometry. Panels render at their final size. Interior
splits and full-screen windows do not receive a guessed edge entrance; floating
windows use a subtle vertical entrance. Cursor movement within a pane remains
smooth, while pane focus transfers and layout shifts track the destination pane.

Cursor travel is smooth without bounce or trails, including rapid reversals.
Native pane/focus handoff suppresses intermediate cursor positions.

Scrolling has a restrained settling overshoot capped at 0.12 rows. Pane
translation is capped at 0.06 cells, with final dimensions held fixed. Buffer
replacement animates only the new content through a 0.2-row entrance. Departed
pane text disappears at commit while surviving panes settle into place. Surface
motion stops within 500ms, with a slower return and unchanged overshoot limits.

For installation on another Apple Silicon Mac, see
[the one-clone installer](smooth-installer/README.md).

Bounce can be adjusted in Neovim config with
`vim.g.kitty_smooth_bounce = { strength = 0.5, duration = 1.5 }`, or live with
`:SmoothBounce 0.5 1.5`. Strength 0 disables bounce; increasing duration slows
settling. Defaults are 1/1; cursor bounce/trails remain disabled.
