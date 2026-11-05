import os
import unittest

from referee import sheets
from referee.errors import RefereeError
from tests.helpers import TempDirMixin, fn, functions_sheet, mu, mutants_sheet


def bad_functions(case, data, text):
    with case.assertRaises(RefereeError) as cm:
        sheets.parse_functions(data)
    case.assertIn(text, str(cm.exception))


def bad_mutants(case, data, text):
    with case.assertRaises(RefereeError) as cm:
        sheets.parse_mutants(data)
    case.assertIn(text, str(cm.exception))


def with_item(base, **changes):
    d = dict(base)
    d.update(changes)
    return d


GOOD_FN = fn("a/b.go", "F", 3, 9, 3, 0.75)
GOOD_MU = mu("a/b.go", 5, "LIVED", column=11, original=">=", replacement=">")


class FunctionSheet(unittest.TestCase):
    def test_valid(self):
        tools, settings, funcs = sheets.parse_functions(
            functions_sheet([GOOD_FN], tools={"gocyclo": "v0.6.0"}, settings={"workers": 4, "x": None}))
        self.assertEqual(tools, {"gocyclo": "v0.6.0"})
        self.assertEqual(settings, {"workers": 4, "x": None})
        self.assertEqual((funcs[0].file, funcs[0].complexity, funcs[0].coverage), ("a/b.go", 3, 0.75))

    def test_not_object(self):
        bad_functions(self, [], "最外層應該是物件")

    def test_wrong_schema(self):
        bad_functions(self, dict(functions_sheet([]), schema="referee.functions/2"), "$.schema")
        bad_functions(self, dict(functions_sheet([]), schema="referee.mutants/1"), "$.schema")

    def test_missing_functions_list(self):
        bad_functions(self, {"schema": "referee.functions/1"}, "缺少欄位 functions")

    def test_functions_not_list(self):
        bad_functions(self, dict(functions_sheet([]), functions={}), "$.functions：應該是陣列")

    def test_extra_top_level_key(self):
        bad_functions(self, dict(functions_sheet([]), extra=1), "多出欄位 extra")

    def test_item_not_object(self):
        bad_functions(self, functions_sheet(["x"]), "$.functions[0]：應該是物件")

    def test_missing_field(self):
        item = dict(GOOD_FN)
        del item["coverage"]
        bad_functions(self, functions_sheet([GOOD_FN, item]), "$.functions[1]：缺少欄位 coverage")

    def test_extra_field(self):
        bad_functions(self, functions_sheet([with_item(GOOD_FN, crap=1)]), "多出欄位 crap")

    def test_wrong_types(self):
        for field, value in (("file", 1), ("name", ""), ("start", "3"), ("start", 0), ("end", 2.5),
                             ("complexity", 0), ("complexity", True), ("coverage", "1"), ("coverage", True)):
            with self.subTest(field=field, value=value):
                with self.assertRaises(RefereeError) as cm:
                    sheets.parse_functions(functions_sheet([with_item(GOOD_FN, **{field: value})]))
                self.assertIn("$.functions[0]." + field, str(cm.exception))

    def test_coverage_out_of_range(self):
        bad_functions(self, functions_sheet([with_item(GOOD_FN, coverage=1.5)]), "0～1")
        bad_functions(self, functions_sheet([with_item(GOOD_FN, coverage=-0.1)]), "0～1")

    def test_start_after_end(self):
        bad_functions(self, functions_sheet([with_item(GOOD_FN, start=10, end=9)]), "start（10）不能大於 end（9）")

    def test_file_path_form(self):
        for f in ("a\\b.go", "/a/b.go", "./a/b.go", "C:/a/b.go", "../b.go"):
            with self.subTest(f=f):
                bad_functions(self, functions_sheet([with_item(GOOD_FN, file=f)]), ".file")

    def test_tools_and_settings_types(self):
        bad_functions(self, dict(functions_sheet([]), tools={"x": 1}), "$.tools")
        bad_functions(self, dict(functions_sheet([]), tools=[]), "$.tools")
        bad_functions(self, dict(functions_sheet([]), settings={"x": [1]}), "$.settings")
        bad_functions(self, dict(functions_sheet([]), settings=[]), "$.settings")


class MutantSheet(unittest.TestCase):
    def test_valid_with_and_without_optionals(self):
        _, _, ms = sheets.parse_mutants(mutants_sheet([GOOD_MU, mu("a/b.go", 6, "KILLED")]))
        self.assertEqual((ms[0].column, ms[0].original, ms[0].replacement), (11, ">=", ">"))
        self.assertEqual((ms[1].column, ms[1].original), (None, None))

    def test_every_inspector_status_accepted(self):
        for s in ("KILLED", "TIMED_OUT", "LIVED", "NOT_COVERED", "NOT_VIABLE", "SKIPPED"):
            sheets.parse_mutants(mutants_sheet([mu("a.go", 1, s)]))

    def test_invalid_status(self):
        bad_mutants(self, mutants_sheet([mu("a.go", 1, "SURVIVED")]), "$.mutants[0].status")

    def test_inspector_must_not_hand_in_equivalent(self):
        bad_mutants(self, mutants_sheet([mu("a.go", 1, "EQUIVALENT")]), "EQUIVALENT 由裁判標記")

    def test_inspector_must_not_hand_in_excluded_mutator(self):
        bad_mutants(self, mutants_sheet([mu("a.go", 1, "EXCLUDED_MUTATOR")]), "EXCLUDED_MUTATOR 由裁判標記")

    def test_missing_field(self):
        item = mu("a.go", 1, "LIVED")
        del item["mutator"]
        bad_mutants(self, mutants_sheet([item]), "$.mutants[0]：缺少欄位 mutator")
        item = mu("a.go", 1, "LIVED")
        del item["status"]
        bad_mutants(self, mutants_sheet([item]), "缺少欄位 status")

    def test_extra_field_including_line_text(self):
        bad_mutants(self, mutants_sheet([mu("a.go", 1, "LIVED", line_text="x")]), "多出欄位 line_text")

    def test_wrong_types(self):
        for field, value in (("file", 3), ("line", 0), ("line", "1"), ("mutator", ""), ("status", 1),
                             ("column", 0), ("column", "1"), ("original", 1), ("replacement", [])):
            with self.subTest(field=field, value=value):
                with self.assertRaises(RefereeError) as cm:
                    sheets.parse_mutants(mutants_sheet([with_item(GOOD_MU, **{field: value})]))
                self.assertIn("$.mutants[0]." + field, str(cm.exception))

    def test_wrong_schema_and_shape(self):
        bad_mutants(self, dict(mutants_sheet([]), schema="referee.functions/1"), "$.schema")
        bad_mutants(self, {"schema": "referee.mutants/1"}, "缺少欄位 mutants")
        bad_mutants(self, dict(mutants_sheet([]), mutants="x"), "$.mutants：應該是陣列")


class LoadSheet(TempDirMixin, unittest.TestCase):
    def test_missing_file(self):
        with self.assertRaises(RefereeError) as cm:
            sheets.load_sheet(os.path.join(self.make_tmp(), "nope.json"), "函式表")
        self.assertIn("沒有寫出函式表", str(cm.exception))

    def test_invalid_json(self):
        path = os.path.join(self.make_tmp(), "s.json")
        with open(path, "w") as f:
            f.write("{not json")
        with self.assertRaises(RefereeError) as cm:
            sheets.load_sheet(path, "改壞版本表")
        self.assertIn("改壞版本表不是合法的 JSON", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
