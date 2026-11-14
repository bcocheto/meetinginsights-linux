"""Colour tokens for the GUI: dark/light palettes, the GNOME accent colour and WCAG checks.

Pure Python (3.8+, no GTK at import) so it can be tested headless. The palettes mirror
Gavetta, Clima and Cadência; text colours are nudged until they reach 4.5:1 against what
they sit on.
"""
import math
import re
import subprocess

DARK = {
    "bg": "#222226", "bg_bar": "#1c1c20",
    "surface": "rgba(255,255,255,0.055)", "surface_hover": "rgba(255,255,255,0.10)",
    "field": "rgba(255,255,255,0.07)", "hairline": "rgba(255,255,255,0.10)",
    "accent": "#3584e4", "accent_soft": "#62a0ea",
    "text_primary": "#f2f2f2", "text_secondary": "rgba(255,255,255,0.55)",
    "danger": "#e01b24", "warn": "#f5c211", "ok": "#57e389", "cloud": "#ffa348",
    "ink": "255,255,255", "strong": "#ffffff",
}
LIGHT = {
    "bg": "#fafafb", "bg_bar": "#f0f0f3",
    "surface": "rgba(0,0,0,0.045)", "surface_hover": "rgba(0,0,0,0.08)",
    "field": "rgba(0,0,0,0.05)", "hairline": "rgba(0,0,0,0.12)",
    "accent": "#3584e4", "accent_soft": "#1c71d8",
    "text_primary": "#241f31", "text_secondary": "rgba(0,0,0,0.58)",
    "danger": "#c01c28", "warn": "#b8860b", "ok": "#1a7f4b", "cloud": "#b85c00",
    "ink": "0,0,0", "strong": "#000000",
}
# GNOME accent colours (libadwaita accent_bg_color); blue is the built-in palette
ACCENTS = {"teal": "#2190a4", "green": "#3a944a", "yellow": "#c88800", "orange": "#ed5b00",
           "red": "#e62d42", "pink": "#d56199", "purple": "#9141ac", "slate": "#6f8396"}
DARK_INK = "#241f31"
MIN_TEXT = 4.5


def _rgb(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)


def mix(color, other, amount):
    return _hex([c + (o - c) * amount for c, o in zip(_rgb(color), other)])


def over(fg, alpha, bg):
    """`fg` drawn at `alpha` on the opaque colour `bg`."""
    return mix(bg, _rgb(fg), alpha)


def luminance(h):
    c = [v / 255 for v in _rgb(h)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(fg, bg, minimum=MIN_TEXT, toward=(255, 255, 255)):
    """Move `fg` toward `toward` in small steps until it reaches `minimum`:1 on `bg`."""
    for _ in range(40):
        if contrast(fg, bg) >= minimum:
            break
        fg = mix(fg, toward, 0.06)
    return fg


def button_colors(accent):
    """(fill, hover fill, text) for an accent-coloured button, every pair >= 4.5:1."""
    fg = "#ffffff"
    fill = accent
    if contrast(fg, fill) < MIN_TEXT:
        if contrast(DARK_INK, fill) >= MIN_TEXT:
            fg = DARK_INK
        else:
            for _ in range(40):
                fill = mix(fill, (0, 0, 0), 0.05)
                if contrast(fg, fill) >= MIN_TEXT:
                    break
    toward = (0, 0, 0) if fg == "#ffffff" else (255, 255, 255)
    hover = mix(fill, toward, 0.12)
    if contrast(fg, hover) < MIN_TEXT:
        hover = fill
    return fill, hover, fg


def accent_from_name(name):
    """Hex for a GNOME accent-color name; None for blue/unknown (keep the built-in palette)."""
    return ACCENTS.get((name or "").strip().strip("'\""))


def build(dark, accent=None):
    """Complete token dict for the dark or light theme with an optional accent colour."""
    t = dict(DARK if dark else LIGHT)
    if accent:
        t["accent"] = accent
        t["accent_soft"] = mix(accent, (255, 255, 255), 0.30) if dark else mix(accent, (0, 0, 0), 0.12)
    bg = t["bg"]
    toward = (255, 255, 255) if dark else (0, 0, 0)
    t["accent_soft"] = ensure_contrast(t["accent_soft"], bg, MIN_TEXT, toward)
    t["accent_btn"], t["accent_btn_hover"], t["accent_fg"] = button_colors(t["accent"])
    t["danger_btn"] = t["danger"]          # solid fill behind white text
    t["danger"] = ensure_contrast(t["danger"], bg, MIN_TEXT, toward)
    for key in ("warn", "ok", "cloud"):    # text on its own 16% tint
        c = t[key]
        for _ in range(40):
            if contrast(c, over(c, 0.16, bg)) >= MIN_TEXT:
                break
            c = mix(c, toward, 0.06)
        t[key] = c
    return t


def themed(css, tokens):
    """Fill the %(token)s placeholders; overlays written as white become black on light."""
    css = css.replace("rgba(255,255,255,", "rgba(%(ink)s,").replace("rgba(255, 255, 255, ", "rgba(%(ink)s, ")
    return re.sub(r"%\((\w+)\)s", lambda m: tokens[m.group(1)], css)


def _portal(key):
    """org.freedesktop.appearance value through the settings portal (reachable inside
    Flatpak without extra permissions); None when the portal is absent."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        r = bus.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                          "org.freedesktop.portal.Settings", "ReadOne",
                          GLib.Variant("(ss)", ("org.freedesktop.appearance", key)),
                          None, Gio.DBusCallFlags.NONE, 1500, None)
        return r.unpack()[0]
    except Exception:  # noqa: BLE001 - no portal, no GI, no bus: fall back to gsettings
        return None


def _gsettings(key):
    try:
        return subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", key],
                              capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def portal_accent_name(rgb):
    """Nearest GNOME accent name for the portal's (r, g, b) floats; None when the value is
    malformed or outside [0, 1] (the portal uses out-of-range components for "no accent")."""
    try:
        if len(rgb) != 3 or not all(isinstance(c, (int, float)) and math.isfinite(c) and 0 <= c <= 1
                                    for c in rgb):
            return None
    except TypeError:
        return None
    pts = dict(ACCENTS, blue="#3584e4")
    return min(pts, key=lambda n: sum((a - b / 255) ** 2 for a, b in zip(rgb, _rgb(pts[n]))))


def system_is_dark(env_value=""):
    if env_value.lower() in ("dark", "light"):
        return env_value.lower() == "dark"
    scheme = _portal("color-scheme")           # 0 no preference, 1 dark, 2 light
    if scheme in (1, 2):
        return scheme == 1
    return "light" not in _gsettings("color-scheme")


def system_accent(env_value=""):
    """Hex of the user's GNOME accent colour, or None for blue/unknown.
    `env_value` (MINUTA_ACCENT, a GNOME accent name) overrides the system, like MINUTA_THEME."""
    if env_value:
        return accent_from_name(env_value.lower())
    name = portal_accent_name(_portal("accent-color"))
    if name:
        return accent_from_name(name)
    return accent_from_name(_gsettings("accent-color"))
