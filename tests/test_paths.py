import unittest

from referee.paths import in_scope, is_excluded, matches

SOURCES = ["**/*.go"]
TESTS = ["**/*_test.go"]
EXCLUDE = ["vendor/", "tools"]


def scope(path):
    return in_scope(path, SOURCES, TESTS, EXCLUDE)


class PathMatching(unittest.TestCase):
    def test_root_level_file_in_scope(self):
        self.assertTrue(scope("main.go"))

    def test_nested_file_in_scope(self):
        self.assertTrue(scope("a/b.go"))
        self.assertTrue(scope("a/b/c.go"))

    def test_test_file_out(self):
        self.assertFalse(scope("a/b_test.go"))
        self.assertFalse(scope("main_test.go"))

    def test_vendor_out(self):
        self.assertFalse(scope("vendor/x.go"))
        self.assertFalse(scope("vendor"))
        self.assertFalse(scope("tools/x.go"))

    def test_exclude_is_directory_prefix_not_string_prefix(self):
        self.assertTrue(scope("vendors/x.go"))
        self.assertTrue(scope("toolsbox/x.go"))
        self.assertTrue(is_excluded("vendor", ["vendor/"]))
        self.assertTrue(is_excluded("vendor", ["vendor"]))

    def test_non_source_out(self):
        self.assertFalse(scope("a/b.py"))

    def test_star_does_not_cross_slash(self):
        self.assertTrue(matches("a/b.go", ["a/*.go"]))
        self.assertFalse(matches("a/c/b.go", ["a/*.go"]))

    def test_question_mark(self):
        self.assertTrue(matches("a1.go", ["a?.go"]))
        self.assertFalse(matches("a/.go", ["a?.go"]))

    def test_double_star_zero_or_more_dirs(self):
        self.assertTrue(matches("x.go", ["**/x.go"]))
        self.assertTrue(matches("a/b/x.go", ["**/x.go"]))
        self.assertTrue(matches("src/a/b.go", ["src/**/*.go"]))
        self.assertTrue(matches("src/b.go", ["src/**/*.go"]))

    def test_case_sensitive(self):
        self.assertFalse(matches("Main.GO", ["**/*.go"]))

    def test_regex_chars_are_literal(self):
        self.assertFalse(matches("axgo", ["a.go"]))
        self.assertTrue(matches("a(1).go", ["a(1).go"]))


if __name__ == "__main__":
    unittest.main()
