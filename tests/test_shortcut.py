import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib"


@unittest.skipUnless(shutil.which("gsettings"), "needs gsettings")
class Shortcut(unittest.TestCase):
    """Runs against a throw-away keyfile backend, never the real dconf."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "GSETTINGS_BACKEND": "keyfile", "XDG_CONFIG_HOME": self.tmp.name}
        probe = subprocess.run(["gsettings", "get", "org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings"],
                               capture_output=True, text=True, env=self.env)
        if probe.returncode != 0:
            self.skipTest("media-keys schema not installed")

    def tearDown(self):
        self.tmp.cleanup()

    def run_sc(self, *a):
        return subprocess.run([sys.executable, "-I", str(LIB / "shortcut.py"), *a], capture_output=True, text=True, env=self.env)

    def test_set_show_remove_keeps_other_shortcuts(self):
        other = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/other/"
        gs = lambda *a: subprocess.run(["gsettings", *a], capture_output=True, text=True, env=self.env, check=True)
        item = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:" + other
        gs("set", item, "name", "Other"); gs("set", item, "command", "true"); gs("set", item, "binding", "<Super>period")
        gs("set", "org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings", f"['{other}']")

        self.assertEqual(self.run_sc("show").returncode, 1)
        self.assertEqual(self.run_sc("set", "<Super><Alt>r", "/usr/bin/minuta toggle").returncode, 0)
        self.assertEqual(self.run_sc("show").stdout.strip(), "<Super><Alt>r")
        listed = gs("get", "org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings").stdout
        self.assertIn("other/", listed); self.assertIn("minuta/", listed)

        clash = self.run_sc("set", "<Super>period", "x")
        self.assertEqual(clash.returncode, 1); self.assertIn("already used", clash.stderr)
        self.assertEqual(self.run_sc("set", "nonsense", "x").returncode, 1)

        self.assertEqual(self.run_sc("remove").returncode, 0)
        listed = gs("get", "org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings").stdout
        self.assertIn("other/", listed); self.assertNotIn("minuta/", listed)


if __name__ == "__main__":
    unittest.main()
