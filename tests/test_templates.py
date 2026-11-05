"""templates/go/ 的檔案本身要是合法的：設定檔通過裁判的驗證，排除清單通過格式檢查，settings.json 指到 gate.sh。"""

import json
import os
import unittest

from referee import config, equivalents
from tests.helpers import REPO

TEMPLATE = os.path.join(REPO, "templates", "go")


def load(name):
    with open(os.path.join(TEMPLATE, name), encoding="utf-8") as f:
        return json.load(f)


class GoTemplate(unittest.TestCase):
    def test_referee_json_passes_config_validation(self):
        cfg = config.validate(load(".referee.json"))
        self.assertEqual(cfg["gates"], ["test", "crap", "mutation"])
        self.assertEqual(cfg["exclude"], ["tools/", "vendor/"])
        for gate in ("crap", "mutation"):
            self.assertIn("tools/referee/inspectors/go.py", cfg[gate]["inspector"])

    def test_equivalents_is_an_empty_valid_list(self):
        self.assertEqual(equivalents.validate(load(".referee-equivalents.json")), [])

    def test_settings_points_the_stop_hook_at_gate_sh_and_denies_config_edits(self):
        settings = load(".claude/settings.json")
        command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn(".claude/hooks/gate.sh", command)
        deny = settings["permissions"]["deny"]
        for path in ("/.referee.json", "/.referee-equivalents.json", "/.gitmodules", "/tools/referee/**",
                     "/.github/**", "/.gitea/**", "/.claude/**"):
            self.assertIn("Edit({})".format(path), deny)
        self.assertTrue(os.path.isfile(os.path.join(TEMPLATE, ".claude", "hooks", "gate.sh")))


if __name__ == "__main__":
    unittest.main()
