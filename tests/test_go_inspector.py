"""Go 標準檢查員的純函式測試（不執行 gremlins、gocyclo），加上套件清單的排除。"""

import os
import tempfile
import unittest

from inspectors import go
from tests.helpers import remove_tree, write


class GremlinsEnv(unittest.TestCase):
    def test_gremlins_goflags_appends_count_1(self):
        self.assertEqual(go.gremlins_env({}, "")["GOFLAGS"], "-count=1")
        self.assertEqual(go.gremlins_env({}, "-mod=mod")["GOFLAGS"], "-mod=mod -count=1")

    def test_goflags_from_go_env_has_trailing_newline(self):
        self.assertEqual(go.gremlins_env({}, "-mod=mod\n")["GOFLAGS"], "-mod=mod -count=1")

    def test_goflags_in_environ_is_replaced_not_kept(self):
        env = go.gremlins_env({"GOFLAGS": "-race", "PATH": "x"}, "-mod=mod")
        self.assertEqual(env["GOFLAGS"], "-mod=mod -count=1")
        self.assertEqual(env["PATH"], "x")


class GremlinsArgs(unittest.TestCase):
    def test_base_args_include_invert_logical(self):
        self.assertEqual(
            go.gremlins_args(None, "shipping", "/o.json"),
            ["unleash", "./shipping", "--timeout-coefficient", "30", "--invert-logical", "-o", "/o.json"])

    def test_invert_logical_is_always_present(self):
        for args in (go.gremlins_args(4, "a", "o", ["sub"], ["x.go"], "m/a,m/b"), go.gremlins_args(None, ".", "o")):
            self.assertIn("--invert-logical", args)

    def test_workers_module_subdirs_and_skip(self):
        self.assertEqual(
            go.gremlins_args(4, "internal/rundown", "o.json", ["testdata", "v1.2"], ["ee.go"], "m/a,m/b"),
            ["unleash", "./internal/rundown", "--timeout-coefficient", "30", "--invert-logical", "-o", "o.json",
             "--integration", "--coverpkg", "m/a,m/b", "--workers", "4",
             "-E", "^testdata[^a-zA-Z0-9_.-]", "-E", "^v1[.]2[^a-zA-Z0-9_.-]",
             "-E", "^ee\\x{2E}go$"])


class SkipPattern(unittest.TestCase):
    def test_anchored_at_both_ends(self):
        p = go.skip_pattern("ee.go")
        self.assertTrue(p.startswith("^") and p.endswith("$"))

    def test_non_alnum_become_code_points(self):
        self.assertEqual(go.skip_pattern("ee.go"), "^ee\\x{2E}go$")
        self.assertEqual(go.skip_pattern("a-b_c.go"), "^a\\x{2D}b_c\\x{2E}go$")
        self.assertEqual(go.skip_pattern("é.go"), "^\\x{E9}\\x{2E}go$")


class Describe(unittest.TestCase):
    def test_boundary(self):
        self.assertEqual(go.gremlins_describe("CONDITIONALS_BOUNDARY", "\tif total >= 1000 {", 11), (">=", ">"))

    def test_longest_token_first(self):
        self.assertEqual(go.gremlins_describe("INVERT_BWASSIGN", "x >>= 2", 3), (">>=", "<<="))
        self.assertEqual(go.gremlins_describe("INVERT_BITWISE", "x >> 2", 3), (">>", "<<"))

    def test_column_is_byte_offset(self):
        line = "if s == \"離島\" && n > 1 {"
        column = len(line.encode("utf-8")[:line.encode("utf-8").index(b"&&")]) + 1
        self.assertEqual(go.gremlins_describe("INVERT_LOGICAL", line, column), ("&&", "||"))

    def test_remove_self_assignment_and_loopctrl(self):
        self.assertEqual(go.gremlins_describe("REMOVE_SELF_ASSIGNMENTS", "n += 1", 3), ("+=", "="))
        self.assertEqual(go.gremlins_describe("INVERT_LOOPCTRL", "break", 1), ("break", "continue"))

    def test_rem_assign_maps_to_itself(self):
        self.assertEqual(go.gremlins_describe("INVERT_ASSIGNMENTS", "n %= 2", 3), ("%=", "%="))

    def test_unknown_or_missing(self):
        self.assertEqual(go.gremlins_describe("NO_SUCH", "a + b", 3), (None, None))
        self.assertEqual(go.gremlins_describe("ARITHMETIC_BASE", "a + b", None), (None, None))
        self.assertEqual(go.gremlins_describe("ARITHMETIC_BASE", "a + b", 1), (None, None))


class FuncEnd(unittest.TestCase):
    SRC = ["package x", "", "func A() int {", "\tif true {", "\t\treturn 1", "\t}", "\treturn 2", "}", "",
           "func B() int { return 1 }", "", "func C() {", "\tf := func() {", "\t}", "\tf()", "}"]

    def test_multi_line_function_ends_at_column_one_brace(self):
        self.assertEqual(go.func_end(self.SRC, 3), 8)

    def test_one_line_function(self):
        self.assertEqual(go.func_end(self.SRC, 10), 10)

    def test_nested_closure_does_not_end_function(self):
        self.assertEqual(go.func_end(self.SRC, 12), 16)

    def test_no_closing_brace_returns_start(self):
        self.assertEqual(go.func_end(["func A() {", "\tx()"], 1), 1)


class UnchangedFiles(unittest.TestCase):
    LISTING = ["fee.go", "ee.go", "fee_test.go", "README.md", "name.go"]

    def test_package_dir(self):
        self.assertEqual(go.unchanged_files("shipping", ["shipping/fee.go"], self.LISTING), ["ee.go", "name.go"])

    def test_root_package(self):
        self.assertEqual(go.unchanged_files(".", ["fee.go"], self.LISTING), ["ee.go", "name.go"])


class Packages(unittest.TestCase):
    def test_exclude_drops_packages_but_keeps_root_and_siblings(self):
        root = os.path.realpath(tempfile.mkdtemp(prefix="referee-go-"))
        self.addCleanup(remove_tree, root)
        write(root, "go.mod", "module shop\n\ngo 1.21\n")
        write(root, "main.go", "package shop\n")
        write(root, "web/broken/b.go", "package broken\n")
        write(root, "webx/w.go", "package webx\n")
        write(root, "shipping/s.go", "package shipping\n")
        old = os.getcwd()
        os.chdir(root)
        self.addCleanup(os.chdir, old)
        module = go.go_module()
        self.assertEqual(module, "shop")
        pkgs = go.go_packages(["web/"], module)
        self.assertEqual(sorted(d for _, d in pkgs), [".", "shipping", "webx"])
        self.assertEqual(sorted(p for p, _ in pkgs), ["shop", "shop/shipping", "shop/webx"])
        self.assertEqual(len(go.go_packages([], module)), 4)


class Profile(unittest.TestCase):
    TEXT = ("mode: set\n"
            "shop/f.go:3.25,4.9 1 1\n"
            "shop/f.go:5.13,6.14 1 0\n"
            "shop/f.go:5.13,6.14 1 1\n"  # -coverpkg 時同一個區塊會出現好幾次，有一次跑到就算
            "shop/sub/g.go:1.1,1.5 1 0\n")

    def test_parse_strips_module_and_merges_duplicates(self):
        p = go.parse_profile(self.TEXT, "shop")
        self.assertEqual(p["f.go"], [(3, 25, 4, 9, 1), (5, 13, 6, 14, 1)])
        self.assertEqual(p["sub/g.go"], [(1, 1, 1, 5, 0)])

    def test_in_block_geometry_matches_gremlins(self):
        blocks = [(3, 25, 4, 9, 1), (5, 13, 6, 14, 0), (8, 2, 10, 3, 1)]
        self.assertTrue(go.in_block(blocks, 4, 3))     # 多行區塊的最後一行，欄位在結尾之前
        self.assertFalse(go.in_block(blocks, 4, 10))   # 結尾之後
        self.assertFalse(go.in_block(blocks, 5, 9))    # case 條件：冒號之前，哪個區塊都不在
        self.assertTrue(go.in_block(blocks, 5, 13))    # 次數 0 的區塊也算在區塊裡（那是真的沒跑到）
        self.assertTrue(go.in_block(blocks, 9, 1))     # 多行區塊中間的行
        self.assertFalse(go.in_block(blocks, 7, 1))


class SwitchHeader(unittest.TestCase):
    SRC = ["package x", "",                                         # 1-2
           "func A(a, b int) int {",                                # 3
           "\tswitch {",                                            # 4
           "\tcase a > b:",                                         # 5
           "\t\tswitch a + 1 {",                                    # 6
           "\t\tcase b - 1:",                                       # 7
           "\t\t\treturn 3",                                        # 8
           "\t\t}",                                                 # 9
           "\t\treturn 1",                                          # 10
           "\tcase a > 10,",                                        # 11
           "\t\ta < -10:",                                          # 12
           "\t\treturn 9",                                          # 13
           "\t}",                                                   # 14
           "\treturn 2", "}"]                                       # 15-16

    def test_first_case(self):
        self.assertEqual(go.switch_header(self.SRC, 5), (4, 2))

    def test_later_case_skips_nested_switch_in_earlier_body(self):
        self.assertEqual(go.switch_header(self.SRC, 11), (4, 2))

    def test_continuation_line_of_case_list(self):
        self.assertEqual(go.switch_header(self.SRC, 12), (4, 2))

    def test_nested_tagged_switch(self):
        self.assertEqual(go.switch_header(self.SRC, 7), (6, 3))

    def test_comment_and_label_at_case_level_are_skipped(self):
        src = ["func A(a int) int {", "\tswitch {", "\tcase a > 1:", "\t\treturn 1", "\t// 說明",
               "\tloop:", "\tcase a > 2:", "\t\treturn 2", "\t}", "\treturn 0", "}"]
        self.assertEqual(go.switch_header(src, 7), (2, 2))

    def test_not_a_case_line(self):
        self.assertIsNone(go.switch_header(self.SRC, 15))
        self.assertIsNone(go.switch_header(self.SRC, 10))


class GapCandidates(unittest.TestCase):
    SRC = ["package x", "", "func A(a, b int) int {", "\tswitch {", "\tcase a > b:", "\t\treturn 1", "\t}",
           "\treturn 2", "}", "", "func B(a, b int) int {", "\tswitch {", "\tcase a > b:", "\t\treturn 1", "\t}",
           "\treturn 2", "}"]

    def setUp(self):
        go._lines["x.go"] = self.SRC
        self.addCleanup(go._lines.pop, "x.go", None)

    def item(self, line, column, status="NOT_COVERED"):
        return {"file": "x.go", "line": line, "column": column, "mutator": "CONDITIONALS_BOUNDARY",
                "status": status, "original": ">", "replacement": ">="}

    def test_only_gap_positions_whose_switch_ran(self):
        profile = {"x.go": [(3, 22, 4, 9, 1), (5, 13, 6, 11, 1), (8, 2, 8, 10, 1),
                            (11, 22, 12, 9, 0), (13, 13, 14, 11, 0), (16, 2, 16, 10, 0)]}
        a_gap = self.item(5, 9)
        b_gap = self.item(13, 9)               # B 的 switch 沒跑到：真的沒跑到
        a_block = self.item(8, 9)              # 在區塊裡，gremlins 的判定沒問題
        killed = self.item(5, 9, "KILLED")
        no_column = dict(self.item(5, 9), column=None)
        unknown = dict(self.item(5, 9), original=None)
        self.assertEqual(go.gap_candidates([a_gap, b_gap, a_block, killed, no_column, unknown], profile), [a_gap])

    def test_file_missing_from_profile(self):
        self.assertEqual(go.gap_candidates([self.item(5, 9)], {}), [])


class MutateSource(unittest.TestCase):
    def test_replaces_token_at_byte_column(self):
        src = "package x\n\nfunc f(s string, n int) bool {\n\tswitch {\n\tcase s == \"離島\" && n > 1:\n".encode("utf-8")
        line = src.split(b"\n")[4]
        column = line.index(b">") + 1
        out = go.mutate_source(src, 5, column, ">", ">=")
        self.assertEqual(out.split(b"\n")[4], line.replace(b"> 1", b">= 1"))
        self.assertEqual(out.split(b"\n")[:4], src.split(b"\n")[:4])

    def test_bom_is_not_counted_in_first_line_columns(self):
        out = go.mutate_source(b"\xef\xbb\xbfa > b\n", 1, 3, ">", "<=")
        self.assertEqual(out, b"\xef\xbb\xbfa <= b\n")

    def test_crlf_is_kept(self):
        self.assertEqual(go.mutate_source(b"x\r\na > b\r\n", 2, 3, ">", ">="), b"x\r\na >= b\r\n")

    def test_token_not_at_column_returns_none(self):
        self.assertIsNone(go.mutate_source(b"a > b\n", 1, 1, ">", ">="))
        self.assertIsNone(go.mutate_source(b"a > b\n", 3, 1, ">", ">="))


class GoTestStatus(unittest.TestCase):
    def test_same_mapping_as_gremlins(self):
        self.assertEqual(go.go_test_status(0), "LIVED")
        self.assertEqual(go.go_test_status(1), "KILLED")
        self.assertEqual(go.go_test_status(2), "NOT_VIABLE")
        self.assertEqual(go.go_test_status(3), "LIVED")

    def test_build_failure_is_not_viable(self):
        self.assertEqual(go.go_test_status(1, "FAIL\tshop [build failed]\n"), "NOT_VIABLE")
        self.assertEqual(go.go_test_status(1, "--- FAIL: TestF\nFAIL\tshop\t0.1s\n"), "KILLED")


class RecheckGaps(unittest.TestCase):
    """實際跑 go test（不需要 gremlins）：case 條件上被判成 NOT_COVERED 的改壞版本，補跑後得到真正的結果。"""

    SRC = ("package shop\n\nfunc F(a, b int) string {\n\tswitch {\n\tcase a > b:\n\t\treturn \"gt\"\n"
           "\tcase a == b:\n\t\treturn \"eq\"\n\t}\n\treturn \"lt\"\n}\n\n"
           "func Never(a int) int {\n\tswitch {\n\tcase a > 1:\n\t\treturn 1\n\t}\n\treturn 0\n}\n")
    TEST = ("package shop\n\nimport \"testing\"\n\nfunc TestF(t *testing.T) {\n"
            "\tif F(2, 1) != \"gt\" || F(1, 1) != \"eq\" || F(0, 1) != \"lt\" {\n\t\tt.Fatal(\"F\")\n\t}\n}\n")

    def setUp(self):
        root = os.path.realpath(tempfile.mkdtemp(prefix="referee-go-"))
        self.addCleanup(remove_tree, root)
        write(root, "go.mod", "module shop\n\ngo 1.21\n")
        write(root, "f.go", self.SRC)
        write(root, "f_test.go", self.TEST)
        old = os.getcwd()
        os.chdir(root)
        self.addCleanup(os.chdir, old)
        self.addCleanup(go._lines.clear)

    def mutant(self, line, column, mutator, original, replacement):
        return {"file": "f.go", "line": line, "column": column, "mutator": mutator, "status": "NOT_COVERED",
                "original": original, "replacement": replacement}

    def test_case_conditions_are_rerun(self):
        gt = self.mutant(5, 9, "CONDITIONALS_BOUNDARY", ">", ">=")     # F(1,1) 會回傳 gt：抓到
        eq = self.mutant(7, 9, "CONDITIONALS_NEGATION", "==", "!=")    # 抓到
        never = self.mutant(15, 9, "CONDITIONALS_BOUNDARY", ">", ">=")  # Never 沒被執行：維持 NOT_COVERED
        for scope in ("package", "module"):
            for m in (gt, eq, never):
                m["status"] = "NOT_COVERED"
            n = go.recheck_gaps([gt, eq, never], [("shop", ".")], scope == "module" and "shop" or None, "")
            self.assertEqual(n, 2, scope)
            self.assertEqual([gt["status"], eq["status"], never["status"]], ["KILLED", "KILLED", "NOT_COVERED"], scope)
        with open("f.go", encoding="utf-8") as f:
            self.assertEqual(f.read(), self.SRC)  # 原始碼沒被改動

    def test_symlinked_working_directory(self):
        """從 symlink 的路徑進專案：go 用 $PWD、Python 的 abspath 用真實路徑，overlay 對不上就會靜默失效。"""
        link = os.path.join(tempfile.mkdtemp(prefix="referee-link-"), "proj")
        self.addCleanup(remove_tree, os.path.dirname(link))
        os.symlink(os.getcwd(), link)
        os.chdir(link)
        old_pwd = os.environ.get("PWD")
        os.environ["PWD"] = link
        self.addCleanup(lambda: os.environ.__setitem__("PWD", old_pwd) if old_pwd else os.environ.pop("PWD", None))
        gt = self.mutant(5, 9, "CONDITIONALS_BOUNDARY", ">", ">=")
        go.recheck_gaps([gt], [("shop", ".")], None, "")
        self.assertEqual(gt["status"], "KILLED")

    def test_case_never_reached_in_executed_function_stays_not_covered(self):
        write(os.getcwd(), "h.go", "package shop\n\nfunc H(a, b int) int {\n\tif a > 0 {\n\t\treturn 1\n\t}\n"
                                   "\tswitch {\n\tcase b > 5:\n\t\treturn 2\n\t}\n\treturn 3\n}\n")
        write(os.getcwd(), "h_test.go", "package shop\n\nimport \"testing\"\n\n"
                                        "func TestH(t *testing.T) {\n\tif H(1, 0) != 1 {\n\t\tt.Fatal()\n\t}\n}\n")
        m = dict(self.mutant(8, 9, "CONDITIONALS_BOUNDARY", ">", ">="), file="h.go")
        self.assertEqual(go.recheck_gaps([m], [("shop", ".")], None, ""), 0)
        self.assertEqual(m["status"], "NOT_COVERED")

    def test_build_failure_is_not_viable(self):
        """改壞後編譯不過（例如 case 常數重複）不能算抓到：go test 的結束碼一樣是 1。"""
        write(os.getcwd(), "k.go", "package shop\n\nfunc K(x int) int {\n\tswitch x {\n\tcase 2 - 1:\n\t\treturn 1\n"
                                   "\tcase 3:\n\t\treturn 3\n\t}\n\treturn 0\n}\n")
        write(os.getcwd(), "k_test.go", "package shop\n\nimport \"testing\"\n\n"
                                        "func TestK(t *testing.T) {\n\tif K(3) != 3 {\n\t\tt.Fatal()\n\t}\n}\n")
        m = dict(self.mutant(5, 9, "ARITHMETIC_BASE", "-", "+"), file="k.go")  # 2 + 1 跟 case 3 重複
        go.recheck_gaps([m], [("shop", ".")], None, "")
        self.assertEqual(m["status"], "NOT_VIABLE")

    def test_goflags_overlay_refuses_instead_of_dropping_it(self):
        write(os.getcwd(), "o.json", "{\"Replace\": {}}")
        gt = self.mutant(5, 9, "CONDITIONALS_BOUNDARY", ">", ">=")
        with self.assertRaises(go.InspectorError) as e:
            go.recheck_gaps([gt], [("shop", ".")], None, "-overlay=" + os.path.join(os.getcwd(), "o.json"))
        self.assertIn("-overlay", str(e.exception))
        self.assertEqual(gt["status"], "NOT_COVERED")
        for quoted in ('"-overlay={}"', "'--overlay={}'"):  # go 也接受加了引號的寫法
            with self.assertRaises(go.InspectorError):
                go.recheck_gaps([gt], [("shop", ".")], None, quoted.format(os.path.join(os.getcwd(), "o.json")))

    def test_surviving_mutant_is_lived(self):
        write(os.getcwd(), "f_test.go", self.TEST.replace(" || F(1, 1) != \"eq\"", ""))
        gt = self.mutant(5, 9, "CONDITIONALS_BOUNDARY", ">", ">=")  # 沒測 a == b，改成 >= 測不出來
        go.recheck_gaps([gt], [("shop", ".")], None, "")
        self.assertEqual(gt["status"], "LIVED")

    def test_nothing_to_recheck_runs_nothing(self):
        killed = dict(self.mutant(5, 9, "CONDITIONALS_BOUNDARY", ">", ">="), status="KILLED")
        os.remove("f_test.go")  # 要是跑了 go test 也不會失敗，但不該跑
        self.assertEqual(go.recheck_gaps([killed], [("shop", ".")], None, ""), 0)


if __name__ == "__main__":
    unittest.main()
