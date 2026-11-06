"""端到端：暫存 git repo + 假檢查員，跑 python referee.py，檢查結束碼、輸出、context 和 JSON 報告。"""

import json
import os
import sys
import unittest

from referee import __version__, schema
from tests.helpers import (FAKE, TempDirMixin, commit_all, dump, fn, functions_sheet, git, init_repo, lines, load, mu,
                           mutants_sheet, remove_tree, run_referee, write)

PY = sys.executable
PASS_CMD = [PY, "-c", "import sys; sys.exit(0)"]
FAIL_CMD = [PY, "-c", "import sys; sys.exit(1)"]

LINE5 = "if total >= 1000 {"


def fee_go(changed):
    out = lines(10)
    if changed:
        out = out.replace("line 4\n", "total := a + b\n").replace("line 5\n", LINE5 + "\n")
    return out


CRAP_TOOLS = {"gocyclo": "v0.6.0"}
CRAP_SETTINGS = {"coverage_scope": "module"}

# 不加 --base：vendor、測試檔、sources 以外的檔案都要被裁判丟掉
CRAP_NOBASE = functions_sheet([
    fn("main.go", "Main", 1, 5, 2, 1.0),
    fn("shipping/fee.go", "Fee", 3, 9, 3, 0.75),
    fn("vendor/x.go", "V", 1, 5, 20, 0.0),
    fn("shipping/fee_test.go", "T", 1, 5, 20, 0.0),
    fn("docs/gen.py", "G", 1, 5, 20, 0.0),
], tools=CRAP_TOOLS, settings=CRAP_SETTINGS)

# 多一個沒改到、超過門檻的舊函式
CRAP_WITH_LEGACY = functions_sheet(CRAP_NOBASE["functions"] + [fn("other/old.go", "Legacy", 1, 10, 15, 0.0)],
                                   tools=CRAP_TOOLS, settings=CRAP_SETTINGS)

MUTANTS = mutants_sheet([
    mu("shipping/fee.go", 4, "KILLED"),
    mu("shipping/fee.go", 5, "LIVED", column=11, original=">=", replacement=">"),
    mu("shipping/fee.go", 9, "KILLED"),
    mu("main.go", 2, "KILLED"),
    mu("other/old.go", 3, "KILLED"),
    mu("vendor/x.go", 1, "LIVED"),
    mu("shipping/fee_test.go", 1, "LIVED"),
    mu("docs/gen.py", 1, "LIVED"),
], tools={"gremlins": "v0.6.0"}, settings={"workers": 4})


class E2E(TempDirMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = init_repo({
            "main.go": lines(10),
            "shipping/fee.go": fee_go(False),
            "other/old.go": lines(10),
            "vendor/x.go": lines(5),
            "shipping/fee_test.go": lines(5),
        })
        git(cls.root, "checkout", "-q", "-b", "feature")
        write(cls.root, "main.go", lines(10).replace("line 2\n", "changed\n"))
        write(cls.root, "shipping/fee.go", fee_go(True))
        write(cls.root, "vendor/x.go", lines(5).replace("line 1\n", "changed\n"))
        write(cls.root, "shipping/fee_test.go", lines(5).replace("line 1\n", "changed\n"))
        commit_all(cls.root)
        write(cls.root, "shipping/new.go", lines(3))  # 還沒加入 git 的新檔案

    @classmethod
    def tearDownClass(cls):
        remove_tree(cls.root)

    def setUp(self):
        self.out = self.make_tmp()
        self.config(None)

    # ---------- 輔助 ----------

    def config(self, extra, **raw):
        cfg = {
            "version": 1, "base": "main",
            "sources": ["**/*.go"], "tests": ["**/*_test.go"], "exclude": ["vendor/"],
            "test": {"command": PASS_CMD},
            "crap": {"threshold": 12, "inspector": [PY, FAKE, "crap"]},
            "mutation": {"kill_rate_threshold": 60, "reach_rate_threshold": 50,
                         "inspector": [PY, FAKE, "mutation"]},
        }
        cfg.update(extra or {})
        cfg.update(raw)
        dump(os.path.join(self.root, ".referee.json"), cfg)
        return cfg

    def run_cli(self, args, crap=None, mutation=None, **env):
        e = {"FAKE_OUT_DIR": self.out}
        if crap is not None:
            dump(os.path.join(self.out, "crap-sheet.json"), crap)
            e["FAKE_SHEET_CRAP"] = os.path.join(self.out, "crap-sheet.json")
        if mutation is not None:
            dump(os.path.join(self.out, "mut-sheet.json"), mutation)
            e["FAKE_SHEET_MUTATION"] = os.path.join(self.out, "mut-sheet.json")
        e.update(env)
        return run_referee(self.root, args, e)

    def json_path(self, name="report.json"):
        return os.path.join(self.out, name)

    def report(self, name="report.json"):
        data = load(self.json_path(name))
        self.assertEqual(schema.validate(data), [], name)
        return data

    def context(self, gate):
        return load(os.path.join(self.out, "ctx-{}.json".format(gate)))

    # ---------- context ----------

    def test_mutation_base_context_lists_changed_source_files(self):
        code, out, err = self.run_cli(["mutation", "--base", "main"], mutation=MUTANTS)
        self.assertEqual(code, 0, out + err)
        ctx = self.context("mutation")
        self.assertEqual(ctx["schema"], "referee.context/1")
        self.assertEqual(ctx["gate"], "mutation")
        # 改到的檔案：main.go、fee.go、新檔案；不含 vendor、測試檔
        self.assertEqual(ctx["changed_files"], ["main.go", "shipping/fee.go", "shipping/new.go"])
        self.assertEqual((ctx["sources"], ctx["tests"], ctx["exclude"]),
                         (["**/*.go"], ["**/*_test.go"], ["vendor/"]))

    def test_mutation_without_base_context_changed_files_null(self):
        self.run_cli(["mutation"], mutation=MUTANTS)
        self.assertIsNone(self.context("mutation")["changed_files"])

    def test_crap_context_changed_files_always_null(self):
        code, out, err = self.run_cli(["crap", "--base", "main"], crap=CRAP_WITH_LEGACY)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.context("crap")["gate"], "crap")
        self.assertIsNone(self.context("crap")["changed_files"])
        self.run_cli(["crap"], crap=CRAP_NOBASE)
        self.assertIsNone(self.context("crap")["changed_files"])

    # ---------- 一律再篩一次 ----------

    def test_crap_without_base_refilters_vendor_tests_and_non_sources(self):
        code, out, err = self.run_cli(["crap", "--json", self.json_path()], crap=CRAP_NOBASE)
        self.assertEqual(code, 0, out + err)  # vendor 和測試檔裡的函式 CRAP 很高，沒被丟掉就會 FAIL
        rep = self.report()
        self.assertEqual([f["name"] for f in rep["crap"]["functions"]], ["Fee", "Main"])
        for name in ("vendor/x.go", "fee_test.go", "gen.py"):
            self.assertNotIn(name, out)

    def test_mutation_without_base_refilters_vendor_tests_and_non_sources(self):
        code, out, err = self.run_cli(["mutation", "--json", self.json_path()], mutation=MUTANTS)
        self.assertEqual(code, 0, out + err)
        rep = self.report()
        files = {m["file"] for m in rep["mutation"]["mutants"]}
        self.assertEqual(files, {"shipping/fee.go", "main.go", "other/old.go"})
        c = rep["mutation"]["counts"]
        self.assertEqual((c["KILLED"], c["LIVED"]), (4, 1))
        for name in ("vendor/x.go", "fee_test.go", "gen.py"):
            self.assertNotIn(name, out)

    def test_root_level_main_go_survives_with_and_without_base(self):
        for base in ([], ["--base", "main"]):
            with self.subTest(base=base):
                code, out, err = self.run_cli(["crap"] + base + ["--json", self.json_path()], crap=CRAP_WITH_LEGACY)
                self.assertIn("Main", [f["name"] for f in self.report()["crap"]["functions"]])
                code, out, err = self.run_cli(["mutation"] + base + ["--json", self.json_path()], mutation=MUTANTS)
                self.assertIn("main.go", {m["file"] for m in self.report()["mutation"]["mutants"]})

    # ---------- --base ----------

    def test_crap_base_only_counts_touched_and_reports_untouched_over(self):
        code, out, err = self.run_cli(["crap", "--base", "main", "--json", self.json_path()], crap=CRAP_WITH_LEGACY)
        self.assertEqual(code, 0, out + err)
        self.assertIn("只檢查和 main 相比有改到的函式（共 2 個）", out)
        self.assertIn("另有 1 個沒改到的函式超過門檻", out)
        self.assertIn("PASS", out)
        self.assertNotIn("Legacy", out)
        rep = self.report()
        self.assertEqual(rep["crap"]["untouched_over"], 1)
        self.assertEqual(rep["base"], "main")
        self.assertEqual([f["name"] for f in rep["crap"]["functions"]], ["Fee", "Main"])

    def test_crap_without_base_counts_everything_and_untouched_over_is_null(self):
        code, out, err = self.run_cli(["crap", "--json", self.json_path()], crap=CRAP_WITH_LEGACY)
        self.assertEqual(code, 1, out + err)
        self.assertIn("FAIL：1 個函式的 CRAP 超過門檻 12", out)
        rep = self.report()
        self.assertIsNone(rep["crap"]["untouched_over"])
        self.assertIsNone(rep["base"])
        self.assertEqual(rep["result"], "fail")

    def test_crap_without_base_also_prints_advice(self):
        sheet = functions_sheet([fn("shipping/fee.go", "Fee", 3, 9, 4, 0.0), fn("other/old.go", "Legacy", 1, 10, 13, 1.0)])
        code, out, err = self.run_cli(["crap"], crap=sheet)
        self.assertEqual(code, 1, out + err)
        self.assertIn("覆蓋率要到 21%", out)
        self.assertIn("要拆函式", out)

    def test_crap_base_advice_cover_and_split(self):
        sheet = functions_sheet([fn("shipping/fee.go", "Fee", 3, 9, 4, 0.0), fn("main.go", "Main", 1, 5, 13, 1.0)])
        code, out, err = self.run_cli(["crap", "--base", "main", "--json", self.json_path()], crap=sheet)
        self.assertEqual(code, 1, out + err)
        self.assertIn("覆蓋率要到 21%", out)
        self.assertIn("要拆函式", out)
        funcs = {f["name"]: f for f in self.report()["crap"]["functions"]}
        self.assertEqual((funcs["Fee"]["advice"], funcs["Fee"]["need_coverage"], funcs["Fee"]["over"]), ("cover", 21, True))
        self.assertEqual((funcs["Main"]["advice"], funcs["Main"]["need_coverage"]), ("split", None))

    def test_mutation_base_ignores_untouched_lines_and_out_of_range_files(self):
        code, out, err = self.run_cli(["mutation", "--base", "main", "--json", self.json_path()], mutation=MUTANTS)
        self.assertEqual(code, 0, out + err)
        rep = self.report()
        got = sorted((m["file"], m["line"]) for m in rep["mutation"]["mutants"])
        self.assertEqual(got, [("main.go", 2), ("shipping/fee.go", 4), ("shipping/fee.go", 5)])
        m = rep["mutation"]
        self.assertEqual((m["counts"]["KILLED"], m["counts"]["LIVED"]), (2, 1))
        self.assertAlmostEqual(m["kill_rate"], 66.6666, places=2)
        self.assertEqual(m["reach_rate"], 100.0)
        self.assertIn("沒抓到  shipping/fee.go:5:11  把 `>=` 改成 `>`  ｜ " + LINE5, out)

    def test_mutation_base_out_of_range_files_only_still_judged_on_changed_part(self):
        # 檢查員交出整個專案的結果（忽略 changed_files），裁判照樣只算改到的部分
        code, out, err = self.run_cli(["mutation", "--base", "main"], mutation=MUTANTS)
        self.assertIn("抓到 2、逾時 0（算抓到）、沒抓到 1、測試沒跑到 0", out)

    def test_unknown_base_is_exit_2(self):
        code, out, err = self.run_cli(["crap", "--base", "nope"], crap=CRAP_NOBASE)
        self.assertEqual(code, 2)
        self.assertIn("找不到 nope 和 HEAD 的分岔點", err)

    # ---------- JSON 報告內容 ----------

    def test_report_inspector_tools_settings_and_packages(self):
        code, out, err = self.run_cli(["mutation", "--json", self.json_path()], mutation=MUTANTS)
        rep = self.report()
        self.assertEqual(rep["inspector"], {"command": [PY, FAKE, "mutation"], "tools": {"gremlins": "v0.6.0"},
                                            "settings": {"workers": 4}})
        self.assertEqual((rep["schema"], rep["referee_version"], rep["command"], rep["result"]),
                         ("referee.report/1", __version__, "mutation", "pass"))
        self.assertIsNone(rep["crap"])
        pk = rep["mutation"]["packages"]
        self.assertEqual(sorted(pk), [".", "other", "shipping"])
        self.assertEqual((pk["shipping"]["KILLED"], pk["shipping"]["LIVED"]), (2, 1))
        self.assertEqual((pk["."]["KILLED"], pk["."]["LIVED"]), (1, 0))
        self.assertEqual((pk["other"]["KILLED"], pk["other"]["LIVED"]), (1, 0))
        self.assertEqual(sum(sum(c.values()) for c in pk.values()), 5)
        self.assertIn("檢查員設定：workers 4", out)
        fee5 = [m for m in rep["mutation"]["mutants"] if m["line"] == 5][0]
        self.assertEqual((fee5["column"], fee5["original"], fee5["replacement"], fee5["line_text"]),
                         (11, ">=", ">", LINE5))
        self.assertEqual(rep["mutation"]["kill_rate_threshold"], 60)
        self.assertEqual(rep["mutation"]["exclude_mutators"], [])
        self.assertEqual(rep["mutation"]["unused_equivalents"], [])

    def test_crap_report_inspector_and_settings_line(self):
        code, out, err = self.run_cli(["crap", "--json", self.json_path()], crap=CRAP_NOBASE)
        rep = self.report()
        self.assertEqual(rep["inspector"], {"command": [PY, FAKE, "crap"], "tools": CRAP_TOOLS,
                                            "settings": CRAP_SETTINGS})
        self.assertIsNone(rep["mutation"])
        self.assertEqual(rep["crap"]["threshold"], 12)
        self.assertIn("檢查員設定：coverage_scope module\n", out)

    def test_no_settings_prints_none_and_report_null(self):
        sheet = functions_sheet([fn("main.go", "Main", 1, 5, 2, 1.0)])
        code, out, err = self.run_cli(["crap", "--json", self.json_path()], crap=sheet)
        self.assertIn("檢查員設定：無", out)
        self.assertIsNone(self.report()["inspector"]["settings"])
        self.assertEqual(self.report()["inspector"]["tools"], {})

    def test_test_report(self):
        code, out, err = self.run_cli(["test", "--json", self.json_path()])
        self.assertEqual(code, 0, out + err)
        rep = self.report()
        self.assertEqual(rep["inspector"], {"command": PASS_CMD})
        self.assertEqual((rep["command"], rep["result"], rep["crap"], rep["mutation"]), ("test", "pass", None, None))

    def test_test_failure_is_exit_1(self):
        self.config({"test": {"command": FAIL_CMD}})
        code, out, err = self.run_cli(["test", "--json", self.json_path()])
        self.assertEqual(code, 1)
        self.assertEqual(self.report()["result"], "fail")

    def test_test_command_not_found_is_exit_2(self):
        self.config({"test": {"command": ["definitely-not-a-command-xyz"]}})
        code, out, err = self.run_cli(["test"])
        self.assertEqual(code, 2)
        self.assertIn("找不到指令", err)

    def test_equivalents_with_column(self):
        entry = {"file": "shipping/fee.go", "mutator": "CONDITIONALS_BOUNDARY", "line_text": LINE5,
                 "reason": "r", "approved_by": "me", "column": 11}
        dump(os.path.join(self.root, ".referee-equivalents.json"), [entry])
        self.addCleanup(os.remove, os.path.join(self.root, ".referee-equivalents.json"))
        code, out, err = self.run_cli(["mutation", "--base", "main", "--json", self.json_path()], mutation=MUTANTS)
        self.assertEqual(code, 0, out + err)
        rep = self.report()
        self.assertEqual(rep["mutation"]["counts"]["EQUIVALENT"], 1)
        self.assertEqual(rep["mutation"]["counts"]["LIVED"], 0)
        self.assertEqual(rep["mutation"]["kill_rate"], 100.0)
        self.assertIn("已排除：改了也沒差 1", out)
        # 欄位對不上：沒用到
        entry["column"] = 12
        dump(os.path.join(self.root, ".referee-equivalents.json"), [entry])
        code, out, err = self.run_cli(["mutation", "--base", "main", "--json", self.json_path()], mutation=MUTANTS)
        self.assertEqual(len(self.report()["mutation"]["unused_equivalents"]), 1)
        self.assertIn("排除清單有 1 項沒用到", out)
        self.assertIn("欄 12", out)

    def test_mutation_fails_below_threshold_exit_1(self):
        self.config({"mutation": {"kill_rate_threshold": 80, "inspector": [PY, FAKE, "mutation"]}})
        code, out, err = self.run_cli(["mutation", "--base", "main", "--json", self.json_path()], mutation=MUTANTS)
        self.assertEqual(code, 1)
        self.assertIn("FAIL：抓錯率低於門檻", out)
        self.assertEqual(self.report()["result"], "fail")

    # ---------- 還沒啟用 ----------

    def test_gate_not_in_gates_prints_not_enabled_and_writes_skipped_report(self):
        self.config(None, gates=["test"])
        code, out, err = self.run_cli(["crap", "--json", self.json_path()])
        self.assertEqual(code, 0, out + err)
        self.assertIn("第 2 關（crap）還沒啟用", out)
        rep = self.report()
        self.assertEqual((rep["result"], rep["crap"], rep["mutation"], rep["inspector"]), ("skipped", None, None, None))

    # ---------- check ----------

    def files_in(self, d):
        return sorted(os.listdir(d))

    def test_check_all_pass_with_skip_mutation(self):
        d = os.path.join(self.out, "reports")
        code, out, err = self.run_cli(["check", "--skip", "mutation", "--json", d], crap=CRAP_WITH_LEGACY)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.files_in(d), ["crap.json", "mutation.json", "test.json"])
        t, c, m = (self.report(os.path.join("reports", n + ".json")) for n in ("test", "crap", "mutation"))
        self.assertEqual((t["command"], t["result"]), ("test", "pass"))
        self.assertEqual((c["command"], c["result"], c["base"]), ("crap", "pass", "main"))
        self.assertEqual(c["crap"]["untouched_over"], 1)
        self.assertEqual((m["command"], m["result"], m["crap"], m["mutation"]), ("mutation", "skipped", None, None))
        self.assertIn("略過：mutation", out)
        self.assertNotIn("ctx-mutation.json", self.files_in(self.out))

    def test_check_runs_all_three_gates(self):
        d = os.path.join(self.out, "reports")
        code, out, err = self.run_cli(["check", "--json", d], crap=CRAP_WITH_LEGACY, mutation=MUTANTS)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.files_in(d), ["crap.json", "mutation.json", "test.json"])
        m = self.report(os.path.join("reports", "mutation.json"))
        self.assertEqual(m["result"], "pass")
        self.assertEqual(self.context("mutation")["changed_files"], ["main.go", "shipping/fee.go", "shipping/new.go"])
        self.assertIsNone(self.context("crap")["changed_files"])

    def test_check_test_failure_writes_only_test_json(self):
        self.config({"test": {"command": FAIL_CMD}})
        d = os.path.join(self.out, "reports")
        code, out, err = self.run_cli(["check", "--json", d], crap=CRAP_WITH_LEGACY, mutation=MUTANTS)
        self.assertEqual(code, 1)
        self.assertEqual(self.files_in(d), ["test.json"])
        self.assertEqual(self.report(os.path.join("reports", "test.json"))["result"], "fail")
        self.assertIn("停在第 1 關", out)
        self.assertNotIn("ctx-crap.json", self.files_in(self.out))

    def test_check_crap_failure_stops_before_mutation(self):
        d = os.path.join(self.out, "reports")
        sheet = functions_sheet([fn("main.go", "Main", 1, 5, 13, 1.0)])
        code, out, err = self.run_cli(["check", "--json", d], crap=sheet, mutation=MUTANTS)
        self.assertEqual(code, 1)
        self.assertEqual(self.files_in(d), ["crap.json", "test.json"])
        self.assertEqual(self.report(os.path.join("reports", "crap.json"))["result"], "fail")

    def test_check_inspector_failure_is_exit_2_and_stops(self):
        d = os.path.join(self.out, "reports")
        code, out, err = self.run_cli(["check", "--json", d], crap=CRAP_WITH_LEGACY, FAKE_EXIT="3")
        self.assertEqual(code, 2)
        self.assertEqual(self.files_in(d), ["test.json"])
        self.assertIn("fake inspector boom", err)

    def test_check_disabled_gates_written_as_skipped(self):
        self.config(None, gates=["test"])
        d = os.path.join(self.out, "reports")
        code, out, err = self.run_cli(["check", "--json", d])
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.files_in(d), ["crap.json", "mutation.json", "test.json"])
        for n in ("crap", "mutation"):
            self.assertEqual(self.report(os.path.join("reports", n + ".json"))["result"], "skipped")
        self.assertIn("還沒啟用：crap、mutation", out)

    def test_check_unknown_skip_is_exit_2(self):
        code, out, err = self.run_cli(["check", "--skip", "lint"])
        self.assertEqual(code, 2)
        self.assertIn("--skip 不認得的關", err)

    # ---------- 檢查員失敗 ----------

    def test_inspector_nonzero_exit(self):
        for gate, kw in (("crap", {"crap": CRAP_NOBASE}), ("mutation", {"mutation": MUTANTS})):
            with self.subTest(gate=gate):
                code, out, err = self.run_cli([gate], FAKE_EXIT="3", **kw)
                self.assertEqual(code, 2)
                self.assertIn("量測失敗，結束碼 3", err)
                self.assertIn("fake inspector boom", err)

    def test_inspector_wrote_no_sheet(self):
        code, out, err = self.run_cli(["crap"], crap=CRAP_NOBASE, FAKE_NOWRITE="1")
        self.assertEqual(code, 2)
        self.assertIn("沒有寫出函式表", err)
        code, out, err = self.run_cli(["mutation"], mutation=MUTANTS, FAKE_NOWRITE="1")
        self.assertEqual(code, 2)
        self.assertIn("沒有寫出改壞版本表", err)

    def test_inspector_command_not_found(self):
        self.config({"crap": {"inspector": ["definitely-not-a-command-xyz"]}})
        code, out, err = self.run_cli(["crap"])
        self.assertEqual(code, 2)
        self.assertIn("找不到指令", err)

    def test_sheet_not_json(self):
        path = os.path.join(self.out, "junk.json")
        with open(path, "w") as f:
            f.write("not json")
        code, out, err = self.run_cli(["crap"], FAKE_SHEET_CRAP=path)
        self.assertEqual(code, 2)
        self.assertIn("不是合法的 JSON", err)

    def test_sheet_format_errors_name_item_and_field(self):
        bad_fn = functions_sheet([fn("main.go", "Main", 1, 5, 2, 1.0), dict(fn("main.go", "B", 1, 5, 2, 1.0), coverage=2)])
        code, out, err = self.run_cli(["crap"], crap=bad_fn)
        self.assertEqual(code, 2)
        self.assertIn("$.functions[1].coverage", err)
        bad_mu = mutants_sheet([mu("main.go", 1, "EQUIVALENT")])
        code, out, err = self.run_cli(["mutation"], mutation=bad_mu)
        self.assertEqual(code, 2)
        self.assertIn("$.mutants[0].status", err)
        self.assertIn("由裁判標記", err)
        bad_mu = mutants_sheet([mu("main.go", 1, "SURVIVED")])
        code, out, err = self.run_cli(["mutation", "--base", "main"], mutation=bad_mu)
        self.assertEqual(code, 2)
        self.assertIn("$.mutants[0].status", err)

    def test_sheet_of_wrong_kind(self):
        code, out, err = self.run_cli(["crap"], crap=MUTANTS)
        self.assertEqual(code, 2)
        self.assertIn("$.schema", err)

    # ---------- 設定檔 ----------

    def test_missing_config_is_exit_2(self):
        os.remove(os.path.join(self.root, ".referee.json"))
        code, out, err = self.run_cli(["crap"])
        self.assertEqual(code, 2)
        self.assertIn("找不到 .referee.json", err)

    def test_bad_config_is_exit_2(self):
        self.config(None, language="go")
        code, out, err = self.run_cli(["crap"])
        self.assertEqual(code, 2)
        self.assertIn("不認得的鍵：language", err)


if __name__ == "__main__":
    unittest.main()
