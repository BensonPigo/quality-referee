"""templates/ 底下的檔案本身要是合法的：設定檔通過裁判的驗證，排除清單通過格式檢查，settings.json 指到 gate.sh。"""

import json
import os
import subprocess
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

    def test_shell_scripts_are_checked_out_with_lf(self):
        # 專案用 cp 複製 gate.sh；Windows 上 core.autocrlf=true 時，沒有 eol=lf 就會取出成 CRLF，bash 執行失敗
        files = subprocess.run(["git", "ls-files", "*.sh"], cwd=REPO, stdout=subprocess.PIPE,
                               universal_newlines=True, check=True).stdout.split()
        self.assertIn("templates/go/.claude/hooks/gate.sh", files)
        for f in files:
            attr = subprocess.run(["git", "check-attr", "eol", "--", f], cwd=REPO, stdout=subprocess.PIPE,
                                  universal_newlines=True, check=True).stdout
            self.assertTrue(attr.strip().endswith(": eol: lf"), attr)


CSHARP = os.path.join(REPO, "templates", "csharp")


def read_bytes(*parts):
    with open(os.path.join(*parts), "rb") as f:
        return f.read()


class CSharpTemplate(unittest.TestCase):
    def load(self, name):
        with open(os.path.join(CSHARP, name), encoding="utf-8") as f:
            return json.load(f)

    def test_referee_json_passes_config_validation(self):
        cfg = config.validate(self.load(".referee.json"))
        self.assertEqual(cfg["gates"], ["test", "crap", "mutation"])
        self.assertEqual(cfg["sources"], ["**/*.cs"])
        self.assertEqual(cfg["exclude"], ["tools/"])
        self.assertEqual(cfg["crap"]["inspector"], ["python", "tools/referee/inspectors/csharp.py", "functions"])
        self.assertEqual(cfg["mutation"]["inspector"], ["python", "tools/referee/inspectors/csharp.py", "mutants"])

    def test_equivalents_is_an_empty_valid_list(self):
        self.assertEqual(equivalents.validate(self.load(".referee-equivalents.json")), [])

    def test_hook_and_settings_are_the_same_as_go(self):
        # gate.sh 和 settings.json 跟語言無關，兩份範本要一模一樣，改一份就要改另一份
        for rel in ((".claude", "settings.json"), (".claude", "hooks", "gate.sh")):
            self.assertEqual(read_bytes(CSHARP, *rel), read_bytes(TEMPLATE, *rel), "/".join(rel))

    def test_gate_sh_is_executable_in_git(self):
        out = subprocess.run(["git", "ls-files", "-s", "templates/csharp/.claude/hooks/gate.sh"], cwd=REPO,
                             stdout=subprocess.PIPE, universal_newlines=True, check=True).stdout
        self.assertTrue(out.startswith("100755 "), out)

    def test_workflow(self):
        with open(os.path.join(CSHARP, "workflows", "csharp.yml"), encoding="utf-8") as f:
            text = f.read()
        for needed in ("actions/setup-dotnet@", "fetch-depth: 0", "submodules: true", "actions/setup-python@",
                       "python3 tools/referee/referee.py test",
                       "python3 tools/referee/referee.py crap --base origin/${{ github.base_ref }}",
                       "python3 tools/referee/referee.py mutation --base origin/${{ github.base_ref }}"):
            self.assertIn(needed, text)
        self.assertNotIn("setup-go", text)


if __name__ == "__main__":
    unittest.main()
