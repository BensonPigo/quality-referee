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


if __name__ == "__main__":
    unittest.main()
