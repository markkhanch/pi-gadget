"""
ui/options_menu.py
Context menu shown when KEY2 is pressed in LIST_VIEW.
Options adapt based on the selected entry type and clipboard state.
"""

from PIL import Image, ImageDraw
from ui.helpers import text_size as _text_size

BG      = (10,  10,  20)
HDR_BG  = (20,  20,  40)
SEL_BG  = (0,   80,  160)
WHITE   = (220, 235, 255)
DIM     = (100, 120, 150)
CYAN    = (0,   200, 240)
RED     = (255, 80,  80)
YELLOW  = (255, 200, 50)
GREEN   = (50,  200, 100)
PURPLE  = (160, 80,  255)

# Option IDs — main.py switches on these
OPT_BACK          = "Back"
OPT_CREATE_FOLDER = "Create folder"
OPT_DELETE        = "Delete"
OPT_RENAME        = "Rename"
OPT_COPY          = "Copy"
OPT_PASTE         = "Paste"
OPT_INFO          = "Info"


def build_options(entry_type: str | None, has_clipboard: bool) -> list:
    """
    Return list of applicable option strings for context.

    entry_type   — "folder" | "app" | "file" | None (empty dir)
    has_clipboard — True if clipboard has something to paste
    """
    opts = [OPT_BACK]

    # Always allow creating folder
    opts.append(OPT_CREATE_FOLDER)

    if entry_type is not None:
        opts.append(OPT_RENAME)
        opts.append(OPT_COPY)
        opts.append(OPT_DELETE)
        opts.append(OPT_INFO)

    if has_clipboard:
        opts.append(OPT_PASTE)

    return opts


# Option colors
_OPT_COLORS = {
    OPT_BACK:          DIM,
    OPT_CREATE_FOLDER: GREEN,
    OPT_RENAME:        YELLOW,
    OPT_COPY:          CYAN,
    OPT_PASTE:         CYAN,
    OPT_DELETE:        RED,
    OPT_INFO:          PURPLE,
}


def draw_options_menu(hw, fonts, options: list, selected_index: int,
                      clipboard_name: str = ""):
    """Draw the context/options menu."""
    font_big, font_small, font_label = fonts
    W, H = hw.W, hw.H

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    TOP_H = 26
    draw.rectangle([(0, 0), (W, TOP_H)], fill=HDR_BG)
    draw.rectangle([(0, 0), (3, TOP_H)], fill=CYAN)
    tw, th = _text_size(draw, "OPTIONS", font_label)
    draw.text((10, (TOP_H - th) // 2), "OPTIONS",
              font=font_label, fill=CYAN)

    # Show clipboard indicator
    if clipboard_name:
        clip = f"📋 {clipboard_name}"
        clip_t = clip[:22] + "…" if len(clip) > 22 else clip
        cw, ch = _text_size(draw, clip_t, font_label)
        draw.text((W - cw - 4, (TOP_H - ch) // 2), clip_t,
                  font=font_label, fill=DIM)

    draw.line([(0, TOP_H), (W, TOP_H)], fill=(40, 60, 100), width=1)

    ROW_H = 32
    y     = TOP_H + 4

    for i, opt in enumerate(options):
        is_sel = i == selected_index
        color  = _OPT_COLORS.get(opt, WHITE)

        if is_sel:
            draw.rectangle([(0, y), (W, y + ROW_H - 1)], fill=SEL_BG)
            draw.rectangle([(0, y), (3, y + ROW_H - 1)], fill=color)

        tw, th = _text_size(draw, opt, font_label)
        draw.text((12, y + (ROW_H - th) // 2), opt,
                  font=font_label,
                  fill=color if is_sel else (DIM if opt == OPT_BACK else WHITE))

        draw.line([(0, y + ROW_H - 1), (W, y + ROW_H - 1)],
                  fill=(25, 40, 70), width=1)
        y += ROW_H

    # Hint bar
    BOT_H = 18
    draw.line([(0, H - BOT_H), (W, H - BOT_H)], fill=(25, 45, 75), width=1)
    hint = "UP/DN:select  CTR:confirm  K3:back"
    hw_, hh = _text_size(draw, hint, font_label)
    draw.text(((W - hw_) // 2, H - hh - 2), hint,
              font=font_label, fill=(50, 75, 110))

    hw.show(img)
