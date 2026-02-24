from AppKit import NSColor, NSFont


_BODY_FONT_CANDIDATES = [
    "Graphik LC",
    "GraphikLC-Regular",
    "Graphik-Regular",
]
_BODY_FONT_STRONG_CANDIDATES = [
    "Graphik LC Semibold",
    "Graphik LC-Semibold",
    "GraphikLC-Semibold",
    "Graphik-Semibold",
    "Graphik LC Medium",
]
_DISPLAY_FONT_CANDIDATES = [
    "ALS Sector",
    "ALS Sector Bold",
    "ALSSector-Bold",
]
_MONO_FONT_CANDIDATES = [
    "Menlo-Regular",
    "SFMono-Regular",
]


def _color_from_hex(hex_value, alpha=1.0):
    value = str(hex_value or "").strip().lstrip("#")
    if len(value) != 6:
        return NSColor.blackColor().colorWithAlphaComponent_(alpha)
    try:
        r = int(value[0:2], 16) / 255.0
        g = int(value[2:4], 16) / 255.0
        b = int(value[4:6], 16) / 255.0
        return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha)
    except Exception:
        return NSColor.blackColor().colorWithAlphaComponent_(alpha)


COLORS = {
    "brand_blue": "#0050FF",
    "text_dark": "#282A32",
    "bg_primary": "#F2F3F5",
    "bg_secondary": "#E9EBEF",
    "highlight": "#DADADA",
    "divider": "#CCCCCE",
    "border": "#B4B5B7",
    "accent_light": "#F2F6FF",
    "accent_dark": "#CFDEFF",
    "success": "#27AE60",
    "warning": "#F2994A",
    "error": "#FF3A52",
}


def ui_color(token, alpha=1.0):
    return _color_from_hex(COLORS.get(token, "#000000"), alpha=alpha)


def color_hex(token, default="#000000"):
    return COLORS.get(token, default)


def _font(candidates, size, fallback_bold=False):
    for name in candidates:
        try:
            font = NSFont.fontWithName_size_(name, float(size))
            if font is not None:
                return font
        except Exception:
            continue
    if fallback_bold:
        return NSFont.boldSystemFontOfSize_(float(size))
    return NSFont.systemFontOfSize_(float(size))


def font_display(size):
    return _font(_DISPLAY_FONT_CANDIDATES, size, fallback_bold=True)


def font_heading(size):
    return _font(_BODY_FONT_STRONG_CANDIDATES + _BODY_FONT_CANDIDATES, size, fallback_bold=True)


def font_body(size, strong=False):
    if strong:
        return _font(_BODY_FONT_STRONG_CANDIDATES + _BODY_FONT_CANDIDATES, size, fallback_bold=True)
    return _font(_BODY_FONT_CANDIDATES, size, fallback_bold=False)


def font_mono(size):
    return _font(_MONO_FONT_CANDIDATES, size, fallback_bold=False)


def css_body_font_family():
    return '"Graphik LC", "GraphikLC-Regular", "Graphik-Regular", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'


def css_display_font_family():
    return '"ALS Sector", "ALS Sector Bold", "ALSSector-Bold", "Graphik LC", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
