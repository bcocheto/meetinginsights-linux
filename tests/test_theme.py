import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import theme  # noqa: E402


def _flat(tokens, key, bg):
    v = tokens[key]
    if v.startswith("rgba"):
        r, g, b, a = [float(x) for x in v[5:-1].split(",")]
        return theme.over("#%02x%02x%02x" % (int(r), int(g), int(b)), a, bg)
    return v


class Palettes(unittest.TestCase):
    def every_theme(self):
        for dark in (True, False):
            for name in [None] + list(theme.ACCENTS):
                yield dark, name, theme.build(dark, theme.ACCENTS.get(name))

    def test_text_contrast(self):
        for dark, name, t in self.every_theme():
            bg = t["bg"]
            label = f"dark={dark} accent={name}"
            for key in ("text_primary", "text_secondary", "accent_soft", "danger"):
                self.assertGreaterEqual(theme.contrast(_flat(t, key, bg), bg), 4.5, f"{label} {key}")
            hover = _flat(t, "surface_hover", bg)
            self.assertGreaterEqual(theme.contrast(
                theme.over("#ffffff" if dark else "#000000", 0.55 if dark else 0.58, hover), hover), 4.4, label)
            for key in ("warn", "ok", "cloud"):
                tint = theme.over(t[key], 0.16, bg)
                self.assertGreaterEqual(theme.contrast(t[key], tint), 4.5, f"{label} {key}")

    def test_button_pairs(self):
        for dark, name, t in self.every_theme():
            for fill in ("accent_btn", "accent_btn_hover"):
                self.assertGreaterEqual(theme.contrast(t["accent_fg"], t[fill]), 4.5, f"{name} {fill}")
            self.assertGreaterEqual(theme.contrast("#ffffff", t["danger_btn"]), 4.5)

    def test_default_blue_unchanged(self):
        t = theme.build(True)
        self.assertEqual(t["accent"], "#3584e4")
        self.assertEqual(t["accent_soft"], "#62a0ea")

    def test_yellow_gets_dark_text(self):
        self.assertEqual(theme.build(True, theme.ACCENTS["yellow"])["accent_fg"], theme.DARK_INK)

    def test_accent_names(self):
        self.assertEqual(theme.accent_from_name("'green'\n"), theme.ACCENTS["green"])
        self.assertIsNone(theme.accent_from_name("'blue'"))
        self.assertIsNone(theme.accent_from_name(""))
        self.assertEqual(theme.portal_accent_name((0x3a / 255, 0x94 / 255, 0x4a / 255)), "green")
        self.assertEqual(theme.portal_accent_name((0.21, 0.52, 0.89)), "blue")

    def test_portal_accent_rejects_invalid(self):
        nan, inf = float("nan"), float("inf")
        for bad in (None, (), (0.1, 0.2), (-1.0, -1.0, -1.0), (-1, 0.5, 0.5), (0.2, 1.01, 0.3),
                    (nan, 0.5, 0.5), (0.5, inf, 0.5), (0.5, 0.5, -inf), ("a", 0.5, 0.5), 5):
            self.assertIsNone(theme.portal_accent_name(bad), bad)
        self.assertEqual(theme.portal_accent_name((0.0, 0.0, 0.0)) is None, False)

    def test_system_accent_falls_back_when_portal_invalid(self):
        orig_portal, orig_gs = theme._portal, theme._gsettings
        try:
            theme._gsettings = lambda k: "'purple'"
            for bad in ((-1.0, -1.0, -1.0), (float("nan"), 0, 0), None):
                theme._portal = lambda k, bad=bad: bad
                self.assertEqual(theme.system_accent(""), theme.ACCENTS["purple"], bad)
        finally:
            theme._portal, theme._gsettings = orig_portal, orig_gs

    def test_themed_fills_and_flips_overlays(self):
        t = theme.build(False)
        out = theme.themed("a{background:rgba(255,255,255,0.1);color:%(accent_fg)s}", t)
        self.assertIn("rgba(0,0,0,0.1)", out)
        self.assertNotIn("%(", out)

    def test_accent_env_override(self):
        self.assertEqual(theme.system_accent("Green"), theme.ACCENTS["green"])
        self.assertIsNone(theme.system_accent("blue"))

    def test_env_override(self):
        self.assertTrue(theme.system_is_dark("dark"))
        self.assertFalse(theme.system_is_dark("LIGHT"))

    def test_python38_syntax(self):
        # no PEP 604 / match / walrus-only features: the package declares python3 >= 3.8
        import ast
        for f in (ROOT / "lib" / "theme.py", ROOT / "gui" / "minuta_gui.py"):
            ast.parse(f.read_text(), feature_version=(3, 8))
            self.assertNotIn(" | None", f.read_text(), f.name)


class SystemSettings(unittest.TestCase):
    def test_gsettings_fallback(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "gsettings"
            fake.write_text("#!/bin/sh\ncase \"$3\" in color-scheme) echo \"'prefer-light'\";; *) echo \"'purple'\";; esac\n")
            fake.chmod(0o755)
            code = ("import sys; sys.path.insert(0, %r); import theme; theme._portal = lambda k: None;"
                    "print(theme.system_is_dark(), theme.system_accent())" % str(ROOT / "lib"))
            out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                 env={**os.environ, "PATH": d + os.pathsep + os.environ["PATH"]}).stdout.split()
            self.assertEqual(out, ["False", theme.ACCENTS["purple"]])


if __name__ == "__main__":
    unittest.main()
