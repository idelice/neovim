// Compositor: merge floating grids with the main grid for display in
// TUI and non-multigrid UIs.
//
// Layer-based compositing: https://en.wikipedia.org/wiki/Digital_compositing

#include <assert.h>
#include <inttypes.h>
#include <limits.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <uv.h>

#include "klib/kvec.h"
#include "nvim/api/private/defs.h"
#include "nvim/ascii_defs.h"
#include "nvim/buffer_defs.h"
#include "nvim/globals.h"
#include "nvim/garray.h"
#include "nvim/mbyte.h"
#include "nvim/strings.h"
#include "nvim/grid.h"
#include "nvim/highlight.h"
#include "nvim/highlight_defs.h"
#include "nvim/highlight_group.h"
#include "nvim/log.h"
#include "nvim/macros_defs.h"
#include "nvim/memory.h"
#include "nvim/message.h"
#include "nvim/option_vars.h"
#include "nvim/os/time.h"
#include "nvim/types_defs.h"
#include "nvim/ui.h"
#include "nvim/ui_compositor.h"

#include "ui_compositor.c.generated.h"

static int composed_uis = 0;
static kvec_t(ScreenGrid *) layers = KV_INITIAL_VALUE;

static size_t bufsize = 0;
static schar_T *linebuf;
static sattr_T *attrbuf;

#ifndef NDEBUG
static int chk_width = 0, chk_height = 0;
#endif

static ScreenGrid *curgrid;
// Cursor placement can target a non-current window (for example an external
// command-line UI). Keep its source grid, rather than assuming curwin owns it.
static int kitty_cursor_grid_handle;

static bool valid_screen = true;
static int msg_current_row = INT_MAX;
static bool msg_was_scrolled = false;

static int msg_sep_row = -1;
static schar_T msg_sep_char = schar_from_ascii(' ');

static int dbghl_normal, dbghl_clear, dbghl_composed, dbghl_recompose;

// The terminal bridge exports the compositor's source grids, never a screenshot
// of its already flattened output. Thus an overlapping float cannot become part
// of another window's retained contents.
static int kitty_grid_priority(ScreenGrid *grid)
{
  // The compositor already orders layers by z-index and insertion order.
  // Export that dense rank rather than multiplying arbitrary user z-indices:
  // valid high-z-index floats otherwise exceed the terminal's priority range.
  return (int)MIN(grid->comp_index + 1, 1000000);
}

static int kitty_grid_identity(ScreenGrid *grid)
{
  FOR_ALL_WINDOWS_IN_TAB(wp, curtab) {
    if (grid == &wp->w_grid_alloc) {
      return wp->handle;
    }
  }
  return -grid->handle;
}

typedef struct {
  int id;
  uint64_t hash;
  bool seen;
} KittyGridVersion;
static kvec_t(KittyGridVersion) kitty_grid_versions = KV_INITIAL_VALUE;
static uint64_t kitty_previous_inventory_hash;
static size_t kitty_previous_inventory_count;

static uint64_t kitty_hash_bytes(uint64_t hash, const void *bytes, size_t len)
{
  const unsigned char *data = bytes;
  for (size_t i = 0; i < len; i++) {
    hash = (hash ^ data[i]) * UINT64_C(1099511628211);
  }
  return hash;
}

static void kitty_grid_cell(ScreenGrid *grid, int row, int col, schar_T *text, int *attr)
{
  size_t offset = grid->line_offset[row] + (size_t)col;
  *text = grid->chars[offset];
  *attr = MAX(grid->attrs[offset], 0);
  int screen_row = grid == &default_grid ? row : grid->comp_row + row;
  int screen_col = grid == &default_grid ? col : grid->comp_col + col;
  if (grid->blending && screen_row >= 0 && screen_row < default_grid.rows
      && screen_col >= 0 && screen_col < default_grid.cols) {
    size_t back = default_grid.line_offset[screen_row] + (size_t)screen_col;
    bool through = (*text == schar_from_ascii(' ') || *text == schar_from_char(L'\u2800'))
                   && default_grid.chars[back] != NUL;
    *attr = hl_blend_attrs(default_grid.attrs[back], *attr, &through);
    if (through) {
      *text = default_grid.chars[back];
    }
  }
}

static void kitty_grid_export(garray_T *out, ScreenGrid *grid, int id, int top, int left,
                             int priority)
{
  char escape[256];
  int source_row = MAX(-top, 0);
  int source_col = MAX(-left, 0);
  int source_height = grid == &default_grid ? grid->rows : MIN(grid->rows, grid->comp_height);
  int source_width = grid == &default_grid ? grid->cols : MIN(grid->cols, grid->comp_width);
  int height = MIN(source_height - source_row, Rows - MAX(top, 0));
  int width = MIN(source_width - source_col, Columns - MAX(left, 0));
  top = MAX(top, 0);
  left = MAX(left, 0);
  if (!grid->chars || height <= 0 || width <= 0) {
    return;
  }
  uint64_t hash = UINT64_C(14695981039346656037);
  const int geometry[] = { top, left, width, height, priority };
  hash = kitty_hash_bytes(hash, geometry, sizeof(geometry));
  for (int row = 0; row < height; row++) {
    for (int col = 0; col < width; col++) {
      schar_T text;
      int attr;
      kitty_grid_cell(grid, row + source_row, col + source_col, &text, &attr);
      HlAttrs hl = syn_attr2entry(attr);
      hash = kitty_hash_bytes(hash, &text, sizeof(text));
      hash = kitty_hash_bytes(hash, &hl, sizeof(hl));
    }
  }
  KittyGridVersion *version = NULL;
  for (size_t i = 0; i < kitty_grid_versions.size; i++) {
    if (kitty_grid_versions.items[i].id == id) {
      version = &kitty_grid_versions.items[i];
      break;
    }
  }
  if (version && version->hash == hash) {
    version->seen = true;
    return;
  }
  if (!version) {
    kv_push(kitty_grid_versions, ((KittyGridVersion){ .id = id }));
    version = &kv_last(kitty_grid_versions);
  }
  version->hash = hash;
  version->seen = true;
  int len = snprintf(escape, sizeof(escape), "\x1b]9921;%d;%d;%d;%d;%d;%d\x1b\\",
                     id, top, left, width, height, priority);
  ga_concat_len(out, escape, (size_t)len);
  int previous_attr = -1;
  for (int row = 0; row < height; row++) {
    len = snprintf(escape, sizeof(escape), "\x1b[%d;%dH", top + row + 1, left + 1);
    ga_concat_len(out, escape, (size_t)len);
    for (int col = 0; col < width; col++) {
      schar_T cell;
      int attr;
      kitty_grid_cell(grid, row + source_row, col + source_col, &cell, &attr);
      if (attr != previous_attr) {
        HlAttrs hl = syn_attr2entry(attr);
        GA_CONCAT_LITERAL(out, "\x1b[0m");
        int flags = hl.rgb_ae_attr;
        if (flags & HL_BOLD) {
          GA_CONCAT_LITERAL(out, "\x1b[1m");
        }
        if (flags & HL_DIM) {
          GA_CONCAT_LITERAL(out, "\x1b[2m");
        }
        if (flags & HL_ITALIC) {
          GA_CONCAT_LITERAL(out, "\x1b[3m");
        }
        if (flags & (HL_INVERSE | HL_STANDOUT)) {
          GA_CONCAT_LITERAL(out, "\x1b[7m");
        }
        if (flags & HL_ALTFONT) {
          GA_CONCAT_LITERAL(out, "\x1b[11m");
        }
        if (flags & HL_BLINK) {
          GA_CONCAT_LITERAL(out, "\x1b[5m");
        }
        if (flags & HL_CONCEALED) {
          GA_CONCAT_LITERAL(out, "\x1b[8m");
        }
        if (flags & HL_STRIKETHROUGH) {
          GA_CONCAT_LITERAL(out, "\x1b[9m");
        }
        if (flags & HL_OVERLINE) {
          GA_CONCAT_LITERAL(out, "\x1b[53m");
        }
        int underline = (flags & HL_UNDERLINE_MASK) >> 3;
        if (underline) {
          // Neovim and SGR underline style enumerations differ for curl/double.
          const int styles[] = { 0, 1, 3, 2, 4, 5 };
          len = snprintf(escape, sizeof(escape), "\x1b[4:%dm", styles[MIN(underline, 5)]);
          ga_concat_len(out, escape, (size_t)len);
        }
        const int colors[] = { hl.rgb_fg_color, hl.rgb_bg_color, hl.rgb_sp_color };
        const int codes[] = { 38, 48, 58 };
        for (int i = 0; i < 3; i++) {
          if (colors[i] >= 0) {
            len = snprintf(escape, sizeof(escape), "\x1b[%d;2;%d;%d;%dm", codes[i],
                           (colors[i] >> 16) & 255, (colors[i] >> 8) & 255, colors[i] & 255);
            ga_concat_len(out, escape, (size_t)len);
          }
        }
        previous_attr = attr;
      }
      char text[MAX_SCHAR_SIZE];
      size_t textlen = schar_get(text, cell);
      // Empty cells are the trailing half of a double-width glyph.
      if (textlen) {
        ga_concat_len(out, text, textlen);
      } else if (col == 0) {
        // A clipped leading half of a wide glyph still occupies a screen cell.
        GA_CONCAT_LITERAL(out, " ");
      }
    }
  }
  GA_CONCAT_LITERAL(out, "\x1b]9922;\x1b\\");
}

/// Publish one complete native layout and its independent backing grids.
/// The receiving terminal commits it at the synchronized-update boundary.
void ui_comp_kitty_frame(void)
{
  if (getenv("NVIM_KITTY_SMOOTH") == NULL || curtab == NULL) {
    return;
  }
  for (size_t i = 0; i < kitty_grid_versions.size; i++) {
    kitty_grid_versions.items[i].seen = false;
  }
  garray_T out;
  ga_init(&out, 1, 8192);
  GA_CONCAT_LITERAL(&out, "\x1b]9918;\x1b\\");
  char escape[256];
  int cursor_owner = curwin->handle;
  for (size_t i = 1; i < layers.size; i++) {
    ScreenGrid *grid = layers.items[i];
    if (!grid->comp_disabled && grid->handle == kitty_cursor_grid_handle) {
      cursor_owner = kitty_grid_identity(grid);
      break;
    }
  }
  int focus_len = snprintf(escape, sizeof(escape), "\x1b]9924;%d\x1b\\", cursor_owner);
  ga_concat_len(&out, escape, (size_t)focus_len);
  size_t window_count = 0;
  uint64_t inventory_hash = 0;
  FOR_ALL_WINDOWS_IN_TAB(wp, curtab) {
    if (wp->w_config.hide || wp->w_config.external || wp->w_height_outer <= 0
        || wp->w_width_outer <= 0) {
      continue;
    }
    int top = MAX(wp->w_winrow, 0);
    int bottom = MIN(wp->w_winrow + wp->w_height_outer, Rows);
    int left = MAX(wp->w_wincol, 0);
    int right = MIN(wp->w_wincol + wp->w_width_outer, Columns);
    if (top >= bottom || left >= right) {
      continue;
    }
    window_count++;
    inventory_hash ^= kitty_hash_bytes(UINT64_C(14695981039346656037),
                                       &wp->handle, sizeof(wp->handle));
    int priority = wp->w_floating ? kitty_grid_priority(&wp->w_grid_alloc) : 0;
    unsigned border_mask = 0;
    if (wp->w_floating) {
      if (wp->w_border_adj[0] && top == wp->w_winrow) { border_mask |= 1; }
      if (wp->w_border_adj[1] && right == wp->w_wincol + wp->w_width_outer) { border_mask |= 2; }
      if (wp->w_border_adj[2] && bottom == wp->w_winrow + wp->w_height_outer) { border_mask |= 4; }
      if (wp->w_border_adj[3] && left == wp->w_wincol) { border_mask |= 8; }
    }
    int len = snprintf(escape, sizeof(escape), "\x1b]9919;%d;%d;%d;%d;%d;%d;%u;%d\x1b\\",
                       wp->handle, top, bottom, left, right, priority, border_mask, wp->w_buffer->handle);
    ga_concat_len(&out, escape, (size_t)len);
  }
  kitty_grid_export(&out, &default_grid, 1, 0, 0, 0);
  for (size_t i = 1; i < layers.size; i++) {
    ScreenGrid *grid = layers.items[i];
    if (grid->comp_disabled) {
      continue;
    }
    int id = kitty_grid_identity(grid);
    int priority = kitty_grid_priority(grid);
    if (id < 0) {
      int top = MAX(grid->comp_row, 0);
      int bottom = MIN(grid->comp_row + MIN(grid->rows, grid->comp_height), Rows);
      int left = MAX(grid->comp_col, 0);
      int right = MIN(grid->comp_col + MIN(grid->cols, grid->comp_width), Columns);
      if (top >= bottom || left >= right) {
        continue;
      }
      window_count++;
      inventory_hash ^= kitty_hash_bytes(UINT64_C(14695981039346656037), &id, sizeof(id));
      int len = snprintf(escape, sizeof(escape), "\x1b]9919;%d;%d;%d;%d;%d;%d\x1b\\",
                         id, top, bottom, left, right, priority);
      ga_concat_len(&out, escape, (size_t)len);
    }
    kitty_grid_export(&out, grid, id, grid->comp_row, grid->comp_col, priority);
  }
  GA_CONCAT_LITERAL(&out, "\x1b]9920;\x1b\\");
  ui_call_ui_send((String){ .data = out.ga_data, .size = (size_t)out.ga_len });
  ga_clear(&out);
  if (window_count > 32 || inventory_hash != kitty_previous_inventory_hash
      || window_count != kitty_previous_inventory_count) {
    // Kitty may retain departing windows until the frame commits, temporarily
    // exhausting its layer slots even when the new inventory fits. Repeat the
    // backing surfaces once after any identity change so fallback can recover.
    kitty_grid_versions.size = 0;
  }
  kitty_previous_inventory_hash = inventory_hash;
  kitty_previous_inventory_count = window_count;
  for (size_t i = 0; i < kitty_grid_versions.size;) {
    if (!kitty_grid_versions.items[i].seen) {
      kitty_grid_versions.items[i] = kv_last(kitty_grid_versions);
      kitty_grid_versions.size--;
    } else {
      i++;
    }
  }
}

void ui_comp_init(void)
{
  kv_push(layers, &default_grid);
  curgrid = &default_grid;
}

#ifdef EXITFREE
void ui_comp_free_all_mem(void)
{
  kv_destroy(layers);
  kv_destroy(kitty_grid_versions);
  xfree(linebuf);
  xfree(attrbuf);
}
#endif

void ui_comp_syn_init(void)
{
  dbghl_normal = syn_check_group(S_LEN("RedrawDebugNormal"));
  dbghl_clear = syn_check_group(S_LEN("RedrawDebugClear"));
  dbghl_composed = syn_check_group(S_LEN("RedrawDebugComposed"));
  dbghl_recompose = syn_check_group(S_LEN("RedrawDebugRecompose"));
}

void ui_comp_attach(RemoteUI *ui)
{
  // A newly attached terminal has no retained backing surfaces.
  kitty_grid_versions.size = 0;
  kitty_previous_inventory_hash = 0;
  kitty_previous_inventory_count = 0;
  composed_uis++;
  ui->composed = true;
}

void ui_comp_detach(RemoteUI *ui)
{
  composed_uis--;
  if (composed_uis == 0) {
    XFREE_CLEAR(linebuf);
    XFREE_CLEAR(attrbuf);
    bufsize = 0;
  }
  ui->composed = false;
}

bool ui_comp_should_draw(void)
{
  return composed_uis != 0 && valid_screen;
}

/// Raises or lowers the layer, syncing comp_index with zindex.
///
/// This function adjusts the position of a layer in the layers array
/// based on its zindex, either raising or lowering it.
///
/// @param[in]  layer_idx  Index of the layer to be raised or lowered.
/// @param[in]  raise      Raise the layer if true, else lower it.
void ui_comp_layers_adjust(size_t layer_idx, bool raise)
{
  size_t size = layers.size;
  ScreenGrid *layer = layers.items[layer_idx];

  if (raise) {
    while (layer_idx < size - 1 && layer->zindex > layers.items[layer_idx + 1]->zindex) {
      layers.items[layer_idx] = layers.items[layer_idx + 1];
      layers.items[layer_idx]->comp_index = layer_idx;
      layers.items[layer_idx]->pending_comp_index_update = true;
      layer_idx++;
    }
  } else {
    while (layer_idx > 0 && layer->zindex < layers.items[layer_idx - 1]->zindex) {
      layers.items[layer_idx] = layers.items[layer_idx - 1];
      layers.items[layer_idx]->comp_index = layer_idx;
      layers.items[layer_idx]->pending_comp_index_update = true;
      layer_idx--;
    }
  }
  layers.items[layer_idx] = layer;
  layer->comp_index = layer_idx;
  layer->pending_comp_index_update = true;
}

/// Places `grid` at (col,row) position with (width * height) size.
/// Adds `grid` as the top layer if it is a new layer.
///
/// TODO(bfredl): later on the compositor should just use win_float_pos events,
/// though that will require slight event order adjustment: emit the win_pos
/// events in the beginning of update_screen(), rather than in ui_flush()
bool ui_comp_put_grid(ScreenGrid *grid, int row, int col, int height, int width, bool valid,
                      bool on_top)
{
  bool moved;
  grid->pending_comp_index_update = true;

  if (grid->comp_index != 0) {
    moved = (row != grid->comp_row) || (col != grid->comp_col);
    if (ui_comp_should_draw()) {
      // Redraw the area covered by the old position, and is not covered
      // by the new position. Disable the grid so that compose_area() will not
      // use it.
      grid->comp_disabled = true;
      compose_area(grid->comp_row, row,
                   grid->comp_col, grid->comp_col + grid->comp_width);
      if (grid->comp_col < col) {
        compose_area(MAX(row, grid->comp_row),
                     MIN(row + height, grid->comp_row + grid->comp_height),
                     grid->comp_col, col);
      }
      if (col + width < grid->comp_col + grid->comp_width) {
        compose_area(MAX(row, grid->comp_row),
                     MIN(row + height, grid->comp_row + grid->comp_height),
                     col + width, grid->comp_col + grid->comp_width);
      }
      compose_area(row + height, grid->comp_row + grid->comp_height,
                   grid->comp_col, grid->comp_col + grid->comp_width);
      grid->comp_disabled = false;
    }
    grid->comp_row = row;
    grid->comp_col = col;
  } else {
    moved = true;
#ifndef NDEBUG
    for (size_t i = 0; i < kv_size(layers); i++) {
      if (kv_A(layers, i) == grid) {
        abort();
      }
    }
#endif

    size_t insert_at = kv_size(layers);
    while (insert_at > 0 && kv_A(layers, insert_at - 1)->zindex > grid->zindex) {
      insert_at--;
    }

    if (curwin && kv_A(layers, insert_at - 1) == &curwin->w_grid_alloc
        && kv_A(layers, insert_at - 1)->zindex == grid->zindex
        && !on_top) {
      insert_at--;
    }
    // not found: new grid
    kv_pushp(layers);
    for (size_t i = kv_size(layers) - 1; i > insert_at; i--) {
      kv_A(layers, i) = kv_A(layers, i - 1);
      kv_A(layers, i)->comp_index = i;
      kv_A(layers, i)->pending_comp_index_update = true;
    }
    kv_A(layers, insert_at) = grid;

    grid->comp_row = row;
    grid->comp_col = col;
    grid->comp_index = insert_at;
    grid->pending_comp_index_update = true;
  }

  grid->comp_height = height;
  grid->comp_width = width;
  if (moved && valid && ui_comp_should_draw()) {
    compose_area(grid->comp_row, grid->comp_row + grid->rows,
                 grid->comp_col, grid->comp_col + grid->cols);
  }
  return moved;
}

void ui_comp_remove_grid(ScreenGrid *grid)
{
  assert(grid != &default_grid);
  if (grid->comp_index == 0) {
    // grid wasn't present
    return;
  }

  if (curgrid == grid) {
    curgrid = &default_grid;
  }

  for (size_t i = grid->comp_index; i < kv_size(layers) - 1; i++) {
    kv_A(layers, i) = kv_A(layers, i + 1);
    kv_A(layers, i)->comp_index = i;
    kv_A(layers, i)->pending_comp_index_update = true;
  }
  (void)kv_pop(layers);
  grid->comp_index = 0;
  grid->pending_comp_index_update = true;

  // recompose the area under the grid
  // inefficient when being overlapped: only draw up to grid->comp_index
  ui_comp_compose_grid(grid);
}

bool ui_comp_set_grid(handle_T handle)
{
  if (curgrid->handle == handle) {
    return true;
  }
  ScreenGrid *grid = NULL;
  for (size_t i = 0; i < kv_size(layers); i++) {
    if (kv_A(layers, i)->handle == handle) {
      grid = kv_A(layers, i);
      break;
    }
  }
  if (grid != NULL) {
    curgrid = grid;
    return true;
  }
  return false;
}

void ui_comp_raise_grid(ScreenGrid *grid, size_t new_index)
{
  size_t old_index = grid->comp_index;
  for (size_t i = old_index; i < new_index; i++) {
    kv_A(layers, i) = kv_A(layers, i + 1);
    kv_A(layers, i)->comp_index = i;
    kv_A(layers, i)->pending_comp_index_update = true;
  }
  kv_A(layers, new_index) = grid;
  grid->comp_index = new_index;
  grid->pending_comp_index_update = true;
  for (size_t i = old_index; i < new_index; i++) {
    ScreenGrid *grid2 = kv_A(layers, i);
    int startcol = MAX(grid->comp_col, grid2->comp_col);
    int endcol = MIN(grid->comp_col + grid->cols,
                     grid2->comp_col + grid2->cols);
    compose_area(MAX(grid->comp_row, grid2->comp_row),
                 MIN(grid->comp_row + grid->rows, grid2->comp_row + grid2->rows),
                 startcol, endcol);
  }
}

void ui_comp_grid_cursor_goto(Integer grid_handle, Integer r, Integer c)
{
  if (!ui_comp_set_grid((int)grid_handle)) {
    return;
  }
  int cursor_row = curgrid->comp_row + (int)r;
  int cursor_col = curgrid->comp_col + (int)c;

  // TODO(bfredl): maybe not the best time to do this, for efficiency we
  // should configure all grids before entering win_update()
  if (curgrid != &default_grid) {
    size_t new_index = kv_size(layers) - 1;

    while (new_index > 1 && kv_A(layers, new_index)->zindex > curgrid->zindex) {
      new_index--;
    }

    if (curgrid->comp_index < new_index) {
      ui_comp_raise_grid(curgrid, new_index);
    }
  }

  if (cursor_col >= default_grid.cols || cursor_row >= default_grid.rows) {
    // TODO(bfredl): this happens with 'writedelay', refactor?
    // abort();
    return;
  }
  kitty_cursor_grid_handle = (int)grid_handle;
  ui_composed_call_grid_cursor_goto(1, cursor_row, cursor_col);
}

ScreenGrid *ui_comp_mouse_focus(int row, int col)
{
  for (ssize_t i = (ssize_t)kv_size(layers) - 1; i > 0; i--) {
    ScreenGrid *grid = kv_A(layers, i);
    if (grid->mouse_enabled
        && row >= grid->comp_row && row < grid->comp_row + grid->rows
        && col >= grid->comp_col && col < grid->comp_col + grid->cols) {
      return grid;
    }
  }
  if (ui_has(kUIMultigrid)) {
    FOR_ALL_WINDOWS_IN_TAB(wp, curtab) {
      ScreenGrid *grid = &wp->w_grid_alloc;
      if (grid->mouse_enabled && row >= wp->w_winrow && row < wp->w_winrow + grid->rows
          && col >= wp->w_wincol && col < wp->w_wincol + grid->cols) {
        return grid;
      }
    }
  }
  return NULL;
}

/// Compute which grid is on top at supplied screen coordinates
ScreenGrid *ui_comp_get_grid_at_coord(int row, int col)
{
  for (ssize_t i = (ssize_t)kv_size(layers) - 1; i > 0; i--) {
    ScreenGrid *grid = kv_A(layers, i);
    if (row >= grid->comp_row && row < grid->comp_row + grid->rows
        && col >= grid->comp_col && col < grid->comp_col + grid->cols) {
      return grid;
    }
  }

  FOR_ALL_WINDOWS_IN_TAB(wp, curtab) {
    ScreenGrid *grid = &wp->w_grid_alloc;
    if (row >= grid->comp_row && row < grid->comp_row + grid->rows
        && col >= grid->comp_col && col < grid->comp_col + grid->cols
        && !wp->w_config.hide) {
      return grid;
    }
  }
  return &default_grid;
}

/// Baseline implementation. This is always correct, but we can sometimes
/// do something more efficient (where efficiency means smaller deltas to
/// the downstream UI.)
static void compose_line(Integer row, Integer startcol, Integer endcol, LineFlags flags)
{
  // If rightleft is set, startcol may be -1. In such cases, the assertions
  // will fail because no overlap is found. Adjust startcol to prevent it.
  startcol = MAX(startcol, 0);
  // in case we start on the right half of a double-width char, we need to
  // check the left half. But skip it in output if it wasn't doublewidth.
  int skipstart = 0;
  int skipend = 0;
  if (startcol > 0 && (flags & kLineFlagInvalid)) {
    startcol--;
    skipstart = 1;
  }
  if (endcol < default_grid.cols && (flags & kLineFlagInvalid)) {
    endcol++;
    skipend = 1;
  }

  int col = (int)startcol;
  ScreenGrid *grid = NULL;
  schar_T *bg_line = &default_grid.chars[default_grid.line_offset[row]
                                         + (size_t)startcol];
  sattr_T *bg_attrs = &default_grid.attrs[default_grid.line_offset[row]
                                          + (size_t)startcol];

  while (col < endcol) {
    int until = 0;
    for (size_t i = 0; i < kv_size(layers); i++) {
      ScreenGrid *g = kv_A(layers, i);
      // compose_line may have been called after a shrinking operation but
      // before the resize has actually been applied. Therefore, we need to
      // first check to see if any grids have pending updates to width/height,
      // to ensure that we don't accidentally put any characters into `linebuf`
      // that have been invalidated.
      int grid_width = MIN(g->cols, g->comp_width);
      int grid_height = MIN(g->rows, g->comp_height);
      if (g->comp_row > row || row >= g->comp_row + grid_height
          || g->comp_disabled) {
        continue;
      }
      if (g->comp_col <= col && col < g->comp_col + grid_width) {
        grid = g;
        until = g->comp_col + grid_width;
      } else if (g->comp_col > col) {
        until = MIN(until, g->comp_col);
      }
    }
    until = MIN(until, (int)endcol);

    assert(grid != NULL);
    assert(until > col);
    assert(until <= default_grid.cols);
    size_t n = (size_t)(until - col);

    if (row == msg_sep_row && grid->comp_index <= msg_grid.comp_index) {
      // TODO(bfredl): when we implement borders around floating windows, then
      // msgsep can just be a border "around" the message grid.
      grid = &msg_grid;
      sattr_T msg_sep_attr = (sattr_T)HL_ATTR(HLF_MSGSEP);
      for (int i = col; i < until; i++) {
        linebuf[i - startcol] = msg_sep_char;
        attrbuf[i - startcol] = msg_sep_attr;
      }
    } else {
      size_t off = grid->line_offset[row - grid->comp_row]
                   + (size_t)(col - grid->comp_col);
      memcpy(linebuf + (col - startcol), grid->chars + off, n * sizeof(*linebuf));
      memcpy(attrbuf + (col - startcol), grid->attrs + off, n * sizeof(*attrbuf));
      if (grid->comp_col + grid->cols > until
          && grid->chars[off + n] == NUL) {
        linebuf[until - 1 - startcol] = schar_from_ascii(' ');
        if (col == startcol && n == 1) {
          skipstart = 0;
        }
      }
    }

    // 'pumblend' and 'winblend'
    if (grid->blending) {
      int width;
      for (int i = col - (int)startcol; i < until - startcol; i += width) {
        width = 1;
        // negative space
        bool thru = (linebuf[i] == schar_from_ascii(' ')
                     || linebuf[i] == schar_from_char(L'\u2800')) && bg_line[i] != NUL;
        if (i + 1 < endcol - startcol && bg_line[i + 1] == NUL) {
          width = 2;
          thru &= (linebuf[i + 1] == schar_from_ascii(' ')
                   || linebuf[i + 1] == schar_from_char(L'\u2800'));
        }
        attrbuf[i] = (sattr_T)hl_blend_attrs(bg_attrs[i], attrbuf[i], &thru);
        if (width == 2) {
          attrbuf[i + 1] = (sattr_T)hl_blend_attrs(bg_attrs[i + 1],
                                                   attrbuf[i + 1], &thru);
        }
        if (thru) {
          memcpy(linebuf + i, bg_line + i, (size_t)width * sizeof(linebuf[i]));
        }
      }
    }

    // Tricky: if overlap caused a doublewidth char to get cut-off, must
    // replace the visible half with a space.
    if (linebuf[col - startcol] == NUL) {
      linebuf[col - startcol] = schar_from_ascii(' ');
      if (col == endcol - 1) {
        skipend = 0;
      }
    } else if (col == startcol && n > 1 && linebuf[1] == NUL) {
      skipstart = 0;
    }

    col = until;
  }
  if (linebuf[endcol - startcol - 1] == NUL) {
    skipend = 0;
  }

  assert(endcol <= chk_width);
  assert(row < chk_height);

  if (!(grid && (grid == &default_grid || (grid->comp_col == 0 && grid->cols == Columns)))) {
    flags = flags & ~kLineFlagWrap;
  }

  for (int i = skipstart; i < (endcol - skipend) - startcol; i++) {
    if (attrbuf[i] < 0) {
      if (rdb_flags & kOptRdbFlagInvalid) {
        abort();
      } else {
        attrbuf[i] = 0;
      }
    }
  }
  ui_composed_call_raw_line(1, row, startcol + skipstart,
                            endcol - skipend, endcol - skipend, 0, flags,
                            (const schar_T *)linebuf + skipstart,
                            (const sattr_T *)attrbuf + skipstart);
}

static void compose_debug(Integer startrow, Integer endrow, Integer startcol, Integer endcol,
                          int syn_id, bool delay)
{
  if (!(rdb_flags & kOptRdbFlagCompositor) || startcol >= endcol) {
    return;
  }

  endrow = MIN(endrow, default_grid.rows);
  endcol = MIN(endcol, default_grid.cols);
  int attr = syn_id2attr(syn_id);

  if (delay) {
    debug_delay(endrow - startrow);
  }

  for (int row = (int)startrow; row < endrow; row++) {
    ui_composed_call_raw_line(1, row, startcol, startcol, endcol, attr, false,
                              (const schar_T *)linebuf,
                              (const sattr_T *)attrbuf);
  }

  if (delay) {
    debug_delay(endrow - startrow);
  }
}

static void debug_delay(Integer lines)
{
  ui_call_flush();
  uint64_t wd = (uint64_t)llabs(p_wd);
  uint64_t factor = (uint64_t)MAX(MIN(lines, 5), 1);
  os_sleep(factor * wd);
}

static void compose_area(Integer startrow, Integer endrow, Integer startcol, Integer endcol)
{
  compose_debug(startrow, endrow, startcol, endcol, dbghl_recompose, true);
  endrow = MIN(endrow, default_grid.rows);
  endcol = MIN(endcol, default_grid.cols);
  if (endcol <= startcol) {
    return;
  }
  for (int r = (int)startrow; r < endrow; r++) {
    compose_line(r, startcol, endcol, kLineFlagInvalid);
  }
}

/// compose the area under the grid.
///
/// This is needed when some option affecting composition is changed,
/// such as 'pumblend' for popupmenu grid.
void ui_comp_compose_grid(ScreenGrid *grid)
{
  if (ui_comp_should_draw()) {
    compose_area(grid->comp_row, grid->comp_row + grid->rows,
                 grid->comp_col, grid->comp_col + grid->cols);
  }
}

void ui_comp_raw_line(Integer grid, Integer row, Integer startcol, Integer endcol, Integer clearcol,
                      Integer clearattr, LineFlags flags, const schar_T *chunk,
                      const sattr_T *attrs)
{
  if (!ui_comp_should_draw() || !ui_comp_set_grid((int)grid)) {
    return;
  }

  row += curgrid->comp_row;
  startcol += curgrid->comp_col;
  endcol += curgrid->comp_col;
  clearcol += curgrid->comp_col;
  if (curgrid != &default_grid) {
    flags = flags & ~kLineFlagWrap;
  }

  assert(endcol <= clearcol);

  // TODO(bfredl): this should not really be necessary. But on some condition
  // when resizing nvim, a window will be attempted to be drawn on the older
  // and possibly larger global screen size.
  if (row >= default_grid.rows) {
    DLOG("compositor: invalid row %" PRId64 " on grid %" PRId64, row, grid);
    return;
  }
  if (clearcol > default_grid.cols) {
    DLOG("compositor: invalid last column %" PRId64 " on grid %" PRId64,
         clearcol, grid);
    if (startcol >= default_grid.cols) {
      return;
    }
    clearcol = default_grid.cols;
    endcol = MIN(endcol, clearcol);
  }

  bool covered = curgrid_covered_above((int)row, (int)row, (int)startcol, (int)clearcol);
  // TODO(bfredl): eventually should just fix compose_line to respect clearing
  // and optimize it for uncovered lines.
  if (flags & kLineFlagInvalid || covered || curgrid->blending) {
    compose_debug(row, row + 1, startcol, clearcol, dbghl_composed, true);
    compose_line(row, startcol, clearcol, flags);
  } else {
    compose_debug(row, row + 1, startcol, endcol, dbghl_normal, endcol >= clearcol);
    compose_debug(row, row + 1, endcol, clearcol, dbghl_clear, true);
#ifndef NDEBUG
    for (int i = 0; i < endcol - startcol; i++) {
      assert(attrs[i] >= 0);
    }
#endif
    ui_composed_call_raw_line(1, row, startcol, endcol, clearcol, clearattr,
                              flags, chunk, attrs);
  }
}

/// The screen is invalid and will soon be cleared
///
/// Don't redraw floats until screen is cleared
bool ui_comp_set_screen_valid(bool valid)
{
  bool old_val = valid_screen;
  valid_screen = valid;
  if (!valid) {
    msg_sep_row = -1;
  }
  return old_val;
}

void ui_comp_msg_set_pos(Integer grid, Integer row, Boolean scrolled, String sep_char,
                         Integer zindex, Integer compindex)
{
  msg_grid.pending_comp_index_update = true;
  msg_grid.comp_row = (int)row;
  if (scrolled && row > 0) {
    msg_sep_row = (int)row - 1;
    if (sep_char.data) {
      msg_sep_char = schar_from_buf(sep_char.data, sep_char.size);
    }
  } else {
    msg_sep_row = -1;
  }

  if (row > msg_current_row && ui_comp_should_draw()) {
    compose_area(MAX(msg_current_row - 1, 0), row, 0, default_grid.cols);
  } else if (row < msg_current_row && ui_comp_should_draw()
             && (msg_current_row < Rows || (scrolled && !msg_was_scrolled))) {
    int delta = msg_current_row - (int)row;
    if (msg_grid.blending) {
      int first_row = MAX((int)row - (scrolled ? 1 : 0), 0);
      compose_area(first_row, Rows - delta, 0, Columns);
    } else {
      // scroll separator together with message text
      int first_row = MAX((int)row - (msg_was_scrolled ? 1 : 0), 0);
      ui_composed_call_grid_scroll(1, first_row, Rows, 0, Columns, delta, 0);
      if (scrolled && !msg_was_scrolled && row > 0) {
        compose_area(row - 1, row, 0, Columns);
      }
    }
  }

  msg_current_row = (int)row;
  msg_was_scrolled = scrolled;
}

/// check if curgrid is covered by any other grid within the rectangle
static bool curgrid_covered_above(int top, int bot, int left, int right)
{
  // check all layers above curgrid. if any intersect with the given rectangle, then consider the
  // curgrid covered. account for the msg_sep_row if the msg_grid layer was scrolled.
  for (size_t i = curgrid->comp_index + 1; i < kv_size(layers); i++) {
    ScreenGrid *g = kv_A(layers, i);
    int grid_top = g->comp_row - (g == &msg_grid && msg_was_scrolled ? 1 : 0);
    int grid_bot = g->comp_row + g->comp_height - 1;
    int grid_left = g->comp_col;
    int grid_right = g->comp_col + g->comp_width - 1;

    if (right >= grid_left && left <= grid_right && bot >= grid_top && top <= grid_bot) {
      return true;
    }
  }

  return false;
}

// Emit source ownership before compositing. Covered and blended windows may
// be redrawn as ordinary lines downstream, losing the original scroll event.
static void kitty_source_scroll(ScreenGrid *grid, int top, int bottom, int left, int right,
                                int delta)
{
  if (getenv("NVIM_KITTY_SMOOTH") == NULL || delta == 0) {
    return;
  }
  top = MAX(top, 0);
  bottom = MIN(bottom, Rows);
  left = MAX(left, 0);
  right = MIN(right, Columns);
  if (top >= bottom || left >= right) {
    return;
  }
  int owner = grid == &default_grid ? 1 : kitty_grid_identity(grid);
  if (grid == &default_grid) {
    FOR_ALL_WINDOWS_IN_TAB(wp, curtab) {
      if (!wp->w_floating && !wp->w_config.hide
          && top >= wp->w_winrow && bottom <= wp->w_winrow + wp->w_height_outer
          && left >= wp->w_wincol && right <= wp->w_wincol + wp->w_width_outer) {
        owner = wp->handle;
        break;
      }
    }
  }
  char sequence[128];
  int len = snprintf(sequence, sizeof(sequence), "\x1b]9923;%d;%d;%d;%d;%d;%d\x1b\\",
                     owner, top, bottom, left, right, delta);
  ui_call_ui_send((String){ .data = sequence, .size = (size_t)len });
}

void ui_comp_grid_scroll(Integer grid, Integer top, Integer bot, Integer left, Integer right,
                         Integer rows, Integer cols)
{
  if (!ui_comp_should_draw() || !ui_comp_set_grid((int)grid)) {
    return;
  }
  top += curgrid->comp_row;
  bot += curgrid->comp_row;
  left += curgrid->comp_col;
  right += curgrid->comp_col;
  kitty_source_scroll(curgrid, (int)top, (int)bot, (int)left, (int)right, (int)rows);
  bool covered = curgrid_covered_above((int)top, (int)bot, (int)left, (int)right);

  if (covered || curgrid->blending) {
    // TODO(bfredl):
    // 1. check if rectangles actually overlap
    // 2. calculate subareas that can scroll.
    compose_debug(top, bot, left, right, dbghl_recompose, true);
    for (int r = (int)(top + MAX(-rows, 0)); r < bot - MAX(rows, 0); r++) {
      // TODO(bfredl): workaround for win_update() performing two scrolls in a
      // row, where the latter might scroll invalid space created by the first.
      // ideally win_update() should keep track of this itself and not scroll
      // the invalid space.
      if (curgrid->attrs[curgrid->line_offset[r - curgrid->comp_row]
                         + (size_t)left - (size_t)curgrid->comp_col] >= 0) {
        compose_line(r, left, right, 0);
      }
    }
  } else {
    ui_composed_call_grid_scroll(1, top, bot, left, right, rows, cols);
    if (rdb_flags & kOptRdbFlagCompositor) {
      debug_delay(2);
    }
  }
}

void ui_comp_grid_resize(Integer grid, Integer width, Integer height)
{
  if (grid == 1) {
    ui_composed_call_grid_resize(1, width, height);
#ifndef NDEBUG
    chk_width = (int)width;
    chk_height = (int)height;
#endif
    size_t new_bufsize = (size_t)width;
    if (bufsize != new_bufsize) {
      xfree(linebuf);
      xfree(attrbuf);
      linebuf = xmalloc(new_bufsize * sizeof(*linebuf));
      attrbuf = xmalloc(new_bufsize * sizeof(*attrbuf));
      bufsize = new_bufsize;
    }
  }
}
