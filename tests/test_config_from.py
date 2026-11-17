"""--config-from：設定檔改讀指定分支上的版本。CI 用它讀 base 分支的設定，PR 自己改鬆的門檻不會生效。"""

import os
import sys
import unittest

from tests.helpers import (FAKE, TempDirMixin, commit_all, dump, fn, functions_sheet, git, init_repo, lines, remove_tree,
                           run_referee, write)

PY = sys.executable


def config(threshold):
    return {"version": 1, "base": "main", "gates": ["crap"], "sources": ["**/*.go"],
            "crap": {"threshold": threshold, "inspector": [PY, FAKE, "crap"]}}


# C=4、覆蓋率 0：CRAP 20。門檻 12 沒過，門檻 30 會過
SHEET = functions_sheet([fn("a.go", "F", 1, 5, 4, 0.0)])


class ConfigFrom(TempDirMixin, unittest.TestCase):
    def setUp(self):
        self.root = init_repo({"a.go": lines(5)})
        self.addCleanup(remove_tree, self.root)
        self.out = self.make_tmp()
        dump(os.path.join(self.out, "sheet.json"), SHEET)

    def commit_config(self, threshold):
        dump(os.path.join(self.root, ".referee.json"), config(threshold))
        commit_all(self.root)

    def run_cli(self, *args):
        return run_referee(self.root, args, {"FAKE_OUT_DIR": self.out,
                                             "FAKE_SHEET_CRAP": os.path.join(self.out, "sheet.json")})

    def loosen_on_feature_branch(self, committed):
        self.commit_config(12)
        git(self.root, "checkout", "-q", "-b", "feature")
        write(self.root, "a.go", lines(5).replace("line 2\n", "changed\n"))
        dump(os.path.join(self.root, ".referee.json"), config(30))
        if committed:
            commit_all(self.root)

    def test_without_the_option_the_branch_config_is_used(self):
        self.loosen_on_feature_branch(committed=True)
        code, out, err = self.run_cli("crap", "--base", "main")
        self.assertEqual(code, 0, out + err)
        self.assertIn("門檻 30", out)

    def test_threshold_loosened_in_the_branch_does_not_take_effect(self):
        for committed in (True, False):
            with self.subTest(committed=committed):
                self.setUp()
                self.loosen_on_feature_branch(committed)
                for cmd in (["crap", "--base", "main"], ["check", "--base", "main"]):
                    code, out, err = self.run_cli(*cmd, "--config-from", "main")
                    self.assertEqual(code, 1, out + err)
                    self.assertIn("超過門檻 12", out)
                    self.assertIn("這個分支上的 .referee.json 和 main 的不一樣，這次不採用", out)

    def test_same_config_prints_where_it_was_read_from_without_the_warning(self):
        self.commit_config(12)
        code, out, err = self.run_cli("crap", "--config-from", "main")
        self.assertEqual(code, 1, out + err)
        self.assertIn("設定檔：讀 main 的 .referee.json", out)
        self.assertNotIn("不採用", out)

    def test_config_deleted_in_the_branch_still_uses_the_ref(self):
        self.commit_config(12)
        os.remove(os.path.join(self.root, ".referee.json"))
        code, out, err = self.run_cli("crap", "--config-from", "main")
        self.assertEqual(code, 1, out + err)
        self.assertIn("超過門檻 12", out)
        self.assertIn("不採用", out)

    def test_ref_without_a_config_falls_back_to_the_branch_and_says_so(self):
        # 第一次導入：base 分支還沒有設定檔
        git(self.root, "checkout", "-q", "-b", "feature")
        dump(os.path.join(self.root, ".referee.json"), config(30))
        code, out, err = self.run_cli("crap", "--config-from", "main")
        self.assertEqual(code, 0, out + err)
        self.assertIn("main 還沒有 .referee.json，改用這個分支上的", out)

    def test_ambiguous_ref_is_exit_2(self):
        # 同名的 tag 指到還沒有設定檔的 commit：不能因此退回這個分支上的設定
        first = git(self.root, "rev-parse", "HEAD").strip()
        self.loosen_on_feature_branch(committed=True)
        git(self.root, "tag", "main", first)
        code, out, err = self.run_cli("crap", "--base", "refs/heads/main", "--config-from", "main")
        self.assertEqual(code, 2, out + err)
        self.assertIn("main 同時是", err)
        code, out, err = self.run_cli("crap", "--base", "refs/heads/main", "--config-from", "refs/heads/main")
        self.assertEqual(code, 1, out + err)
        self.assertIn("超過門檻 12", out)

    def test_commit_sha_works_as_the_ref(self):
        self.commit_config(12)
        sha = git(self.root, "rev-parse", "HEAD").strip()
        write(self.root, "a.go", lines(5).replace("line 2\n", "changed\n"))
        dump(os.path.join(self.root, ".referee.json"), config(30))
        code, out, err = self.run_cli("crap", "--base", sha, "--config-from", sha)
        self.assertEqual(code, 1, out + err)
        self.assertIn("超過門檻 12", out)

    def test_git_failure_while_looking_for_the_config_is_exit_2_not_a_fallback(self):
        # 只有「那個分支上確定沒有這個檔案」才退回；設定檔在那個分支上是目錄，不算沒有
        write(self.root, ".referee.json/x", "{}")
        commit_all(self.root)
        git(self.root, "checkout", "-q", "-b", "feature")
        git(self.root, "rm", "-rq", ".referee.json")
        dump(os.path.join(self.root, ".referee.json"), config(30))
        code, out, err = self.run_cli("crap", "--config-from", "main")
        self.assertEqual(code, 2, out + err)
        self.assertNotIn("改用這個分支上的", out)

    def test_config_that_is_a_directory_is_exit_2(self):
        os.makedirs(os.path.join(self.root, ".referee.json"))
        code, out, err = self.run_cli("crap")
        self.assertEqual(code, 2, out + err)
        self.assertNotIn("Traceback", err)

    def test_every_command_takes_the_option(self):
        self.commit_config(12)
        for cmd in ("test", "mutation"):
            code, out, err = self.run_cli(cmd, "--config-from", "main")
            self.assertEqual(code, 0, out + err)  # gates 只有 crap：印「還沒啟用」
            self.assertIn("設定檔：讀 main 的 .referee.json", out)

    def test_entries_added_to_the_equivalents_list_are_pointed_out(self):
        entry = {"file": "a.go", "mutator": "M", "line_text": "x", "reason": "r", "approved_by": "me"}
        dump(os.path.join(self.root, ".referee-equivalents.json"), [entry])
        self.commit_config(12)
        code, out, err = self.run_cli("crap", "--config-from", "main")
        self.assertNotIn("排除清單", out)
        dump(os.path.join(self.root, ".referee-equivalents.json"), [entry, dict(entry, line_text="y"), dict(entry, line_text="z")])
        code, out, err = self.run_cli("crap", "--config-from", "main")
        self.assertIn("注意：排除清單比 main 多了 2 項，這些項目要人核准", out)

    def test_unknown_ref_is_exit_2(self):
        self.commit_config(12)
        code, out, err = self.run_cli("crap", "--config-from", "origin/nope")
        self.assertEqual(code, 2, out + err)
        self.assertIn("找不到 origin/nope", err)

    def test_invalid_config_at_the_ref_is_exit_2(self):
        write(self.root, ".referee.json", "{")
        commit_all(self.root)
        git(self.root, "checkout", "-q", "-b", "feature")
        dump(os.path.join(self.root, ".referee.json"), config(30))
        code, out, err = self.run_cli("crap", "--config-from", "main")
        self.assertEqual(code, 2, out + err)
        self.assertIn("不是合法的 JSON", err)

    def test_works_from_a_project_in_a_subdirectory_of_the_repo(self):
        os.makedirs(os.path.join(self.root, "svc"))
        dump(os.path.join(self.root, "svc", ".referee.json"), config(12))
        write(self.root, "svc/a.go", lines(5))
        commit_all(self.root)
        dump(os.path.join(self.root, "svc", ".referee.json"), config(30))
        code, out, err = run_referee(os.path.join(self.root, "svc"), ["crap", "--config-from", "main"],
                                     {"FAKE_OUT_DIR": self.out, "FAKE_SHEET_CRAP": os.path.join(self.out, "sheet.json")})
        self.assertEqual(code, 1, out + err)
        self.assertIn("超過門檻 12", out)


if __name__ == "__main__":
    unittest.main()
