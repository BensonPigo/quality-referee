"""C# 標準檢查員：不執行 dotnet 的純函式，以及建置複雜度工具的隔離（要有 dotnet，沒有就略過）。"""

import os
import shutil
import tempfile
import unittest

from inspectors import csharp
from referee import sheets
from tests.helpers import remove_tree, write

CTX = {"sources": ["**/*.cs"], "tests": ["**/*.Tests/**"], "exclude": ["tools/"]}


class Temp(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cs-")
        self.addCleanup(remove_tree, self.root)


class SourceFiles(Temp):
    def test_skips_bin_obj_generated_tests_and_exclude(self):
        for rel in ("Shop/Cart.cs", "Shop/obj/Debug/Gen.cs", "Shop/bin/X.cs", "Shop/Form1.Designer.cs",
                    "Shop/Api.g.cs", "Shop.Tests/CartTests.cs", "tools/referee/x.cs", "Shop/readme.md",
                    "Deep/a/b/obj/y.cs", "Deep/a/b/Z.cs"):
            write(self.root, rel, "")
        self.assertEqual(csharp.source_files(self.root, CTX), ["Deep/a/b/Z.cs", "Shop/Cart.cs"])

    def test_tools_dir_inside_project_is_skipped(self):
        # 工具快取目錄設在專案裡面時，裡面建置用的 Program.cs 不能算成專案的函式
        write(self.root, "Shop/Cart.cs", "")
        cache = os.path.join(self.root, "cache")
        csharp.materialize(os.path.join(cache, "csharp-complexity-x"))
        self.assertEqual(csharp.source_files(self.root, CTX, skip_dirs=[cache]), ["Shop/Cart.cs"])
        self.assertIn("cache/csharp-complexity-x/Program.cs", csharp.source_files(self.root, CTX))
        write(self.root, "App.slnx", "<Solution />")
        self.assertEqual(csharp.find_target(self.root), "App.slnx")


class FindTarget(Temp):
    def test_none(self):
        with self.assertRaisesRegex(csharp.InspectorError, "--target"):
            csharp.find_target(self.root)

    def test_single_sln_or_slnx(self):
        write(self.root, "App.sln", "")
        write(self.root, "sub/Other.slnx", "")
        self.assertEqual(csharp.find_target(self.root), "App.sln")

    def test_two_solutions(self):
        write(self.root, "A.sln", "")
        write(self.root, "B.slnx", "")
        with self.assertRaisesRegex(csharp.InspectorError, "A.sln、B.slnx"):
            csharp.find_target(self.root)

    def test_given(self):
        write(self.root, "src/App.Tests/App.Tests.csproj", "")
        self.assertEqual(csharp.find_target(self.root, "src\\App.Tests\\App.Tests.csproj"), "src/App.Tests/App.Tests.csproj")
        with self.assertRaisesRegex(csharp.InspectorError, "找不到"):
            csharp.find_target(self.root, "nope.csproj")


def cobertura(sources, classes):
    src = "".join("<source>{}</source>".format(s) for s in sources)
    cls = "".join('<class name="C" filename="{}"><methods /><lines>{}</lines></class>'.format(
        f, "".join('<line number="{}" hits="{}" branch="False" />'.format(n, h) for n, h in lines))
        for f, lines in classes)
    return ('<?xml version="1.0"?><coverage><sources>{}</sources><packages><package name="P"><classes>{}'
            '</classes></package></packages></coverage>').format(src, cls)


class Cobertura(Temp):
    def key(self, rel):
        return os.path.normcase(os.path.abspath(os.path.join(self.root, rel)))

    def test_relative_filenames_resolve_against_existing_source(self):
        write(self.root, "Shop/Cart.cs", "")
        other = os.path.join(self.root, "elsewhere") + os.sep
        text = cobertura([other, self.root + os.sep], [("Shop/Cart.cs", [(3, 1), (4, 0)])])
        self.assertEqual(csharp.parse_cobertura(text, self.root), {self.key("Shop/Cart.cs"): {3: 1, 4: 0}})

    def test_absolute_filename_and_same_file_in_two_classes(self):
        # async 和 lambda 會變成另外的類別，同一個檔案出現好幾次，同一行取最大值
        full = os.path.join(self.root, "Shop", "Cart.cs")
        text = cobertura([], [(full, [(3, 0), (4, 0)]), (full, [(4, 2), (5, 0)])])
        self.assertEqual(csharp.parse_cobertura(text, self.root), {self.key("Shop/Cart.cs"): {3: 0, 4: 2, 5: 0}})

    def test_merge_takes_max_hits(self):
        a = {"f": {1: 0, 2: 3}}
        b = {"f": {1: 1, 2: 0}, "g": {9: 0}}
        self.assertEqual(csharp.merge_coverage([a, b]), {"f": {1: 1, 2: 3}, "g": {9: 0}})


class FunctionCoverage(unittest.TestCase):
    def test_partial(self):
        self.assertEqual(csharp.function_coverage({10: 1, 11: 0, 12: 1, 13: 1, 20: 0}, 10, 13), 0.75)

    def test_file_in_no_report_is_zero(self):
        self.assertEqual(csharp.function_coverage(None, 1, 5), 0.0)
        self.assertEqual(csharp.function_coverage({}, 1, 5), 0.0)

    def test_no_coverable_line_in_range_is_zero(self):
        self.assertEqual(csharp.function_coverage({1: 1, 9: 1}, 3, 5), 0.0)


class Misc(unittest.TestCase):
    def test_is_generated(self):
        self.assertTrue(csharp.is_generated("Form1.Designer.cs"))
        self.assertTrue(csharp.is_generated("GlobalUsings.g.cs"))
        self.assertFalse(csharp.is_generated("Designer.cs"))

    def test_roslyn_version_read_from_csproj(self):
        with open(os.path.join(csharp.COMPLEXITY_SRC, "complexity.csproj.txt"), encoding="utf-8") as f:
            self.assertRegex(csharp.roslyn_version(f.read()), r"^\d+\.\d+\.\d+$")

    def test_sheet_shape_passes_validation(self):
        sheet = {"schema": sheets.FUNCTIONS_SCHEMA,
                 "tools": {csharp.ROSLYN_PACKAGE: "5.9.0", "dotnet-sdk": "10.0.101"},
                 "settings": {"target": "App.slnx"},
                 "functions": [{"file": "Shop/Cart.cs", "name": "Cart.Add", "start": 3, "end": 9, "complexity": 2,
                                "coverage": csharp.function_coverage(None, 3, 9)}]}
        sheets.parse_functions(sheet)

    def test_tool_source_is_not_buildable_in_place(self):
        # 放在 submodule 裡的工具原始碼不能是 .cs、.csproj，免得主機專案的建置把它掃進去
        names = os.listdir(csharp.COMPLEXITY_SRC)
        self.assertFalse([n for n in names if n.endswith((".cs", ".csproj"))], names)


SOURCE = "namespace Shop;\n    if (subtotal <= 0)\n    {\n        return 0;\n    }\n"


def stryker_mutant(line, col, end_line, end_col, status, mutator="Equality mutation", replacement="x", reason=None):
    m = {"id": "1", "mutatorName": mutator, "replacement": replacement, "status": status,
         "location": {"start": {"line": line, "column": col}, "end": {"line": end_line, "column": end_col}}}
    if reason:
        m["statusReason"] = reason
    return m


class StrykerReport(Temp):
    def report(self, mutants, path="Shop/Pricing.cs"):
        return {"schemaVersion": "2", "files": {os.path.join(self.root, *path.split("/")):
                                                {"language": "cs", "source": SOURCE, "mutants": mutants}}}

    def test_status_mapping_and_original_text(self):
        statuses = ["Killed", "Timeout", "Survived", "NoCoverage", "CompileError", "RuntimeError", "Ignored"]
        mutants = csharp.mutants_from_report(self.report([stryker_mutant(2, 9, 2, 22, s, replacement="subtotal < 0")
                                                          for s in statuses]), self.root)
        self.assertEqual([m["status"] for m in mutants],
                         ["KILLED", "TIMED_OUT", "LIVED", "NOT_COVERED", "NOT_VIABLE", "NOT_VIABLE", "SKIPPED"])
        self.assertEqual(mutants[0], {"file": "Shop/Pricing.cs", "line": 2, "column": 9, "mutator": "Equality mutation",
                                      "status": "KILLED", "original": "subtotal <= 0", "replacement": "subtotal < 0"})
        sheets.parse_mutants({"schema": sheets.MUTANTS_SCHEMA, "mutants": mutants})

    def test_multi_line_original(self):
        mutants = csharp.mutants_from_report(self.report([stryker_mutant(3, 5, 5, 6, "Survived", "Block removal mutation", "{}")]),
                                             self.root)
        self.assertEqual(mutants[0]["original"], "{\n        return 0;\n    }")

    def test_mutate_filter_dropped_but_other_ignored_kept(self):
        mutants = csharp.mutants_from_report(self.report([
            stryker_mutant(2, 9, 2, 22, "Ignored", reason=csharp.MUTATE_FILTER_REASON),
            stryker_mutant(2, 9, 2, 22, "Ignored", reason="Removed by block already covered filter"),
        ]), self.root)
        self.assertEqual([m["status"] for m in mutants], ["SKIPPED"])

    def test_unknown_status_is_an_error(self):
        with self.assertRaisesRegex(csharp.InspectorError, "Pending"):
            csharp.mutants_from_report(self.report([stryker_mutant(2, 9, 2, 22, "Pending")]), self.root)

    def test_files_outside_project_are_skipped(self):
        outside = os.path.join(os.path.dirname(self.root), "elsewhere", "X.cs")
        report = {"files": {outside: {"source": SOURCE, "mutants": [stryker_mutant(2, 9, 2, 22, "Killed")]}}}
        self.assertEqual(csharp.mutants_from_report(report, self.root), [])

    def test_span_out_of_range_has_no_original(self):
        mutants = csharp.mutants_from_report(self.report([stryker_mutant(99, 1, 99, 2, "Killed")]), self.root)
        self.assertNotIn("original", mutants[0])

    def test_mutate_patterns(self):
        self.assertEqual(csharp.mutate_patterns(["Shop/Pricing.cs"]), ["**/Shop/Pricing.cs"])
        self.assertEqual(csharp.mutate_patterns([]), [])


class WindowsPathLimit(unittest.TestCase):
    def test_limit(self):
        self.assertFalse(csharp.too_long_for_windows("C:\\" + "a" * 256, is_windows=True))  # 259 字元
        self.assertTrue(csharp.too_long_for_windows("C:\\" + "a" * 257, is_windows=True))
        self.assertFalse(csharp.too_long_for_windows("/" + "a" * 400, is_windows=False))


@unittest.skipUnless(shutil.which("dotnet"), "沒有 dotnet，略過建置工具的隔離測試")
class BuildIsolation(Temp):
    """上層目錄放惡意設定檔：沒有隔離檔時建置要失敗（反向對照），有隔離檔時建置要成功。"""

    def setUp(self):
        super().setUp()
        write(self.root, "global.json", '{"sdk": {"version": "1.0.0", "rollForward": "disable"}}\n')
        write(self.root, "Directory.Build.targets",
              '<Project><Target Name="Hostile" BeforeTargets="Restore;Build"><Error Text="hostile" /></Target></Project>\n')

    def test_without_isolation_files_build_fails(self):
        dest = os.path.join(self.root, "tool")
        csharp.materialize(dest, isolation=False)
        with self.assertRaises(csharp.InspectorError):
            csharp.build(dest)

    def test_with_isolation_files_build_succeeds(self):
        dest = os.path.join(self.root, "tool")
        csharp.materialize(dest)
        self.assertTrue(os.path.isfile(csharp.build(dest)))


if __name__ == "__main__":
    unittest.main()
