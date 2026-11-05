import copy
import unittest

from referee import report, schema
from referee.model import STATUSES


def counts():
    return {s: 0 for s in STATUSES}


def crap_report():
    return report.build_report("crap", None, "pass", {"command": ["x"], "tools": {}, "settings": None},
                               crap_part={"threshold": 12, "functions": [], "untouched_over": None})


def mutation_report():
    part = {"kill_rate_threshold": 80, "reach_rate_threshold": 50, "exclude_mutators": [], "counts": counts(),
            "kill_rate": None, "reach_rate": None, "packages": {"a": counts()}, "mutants": [],
            "unused_equivalents": []}
    return report.build_report("mutation", "main", "fail", {"command": ["x"], "tools": {"g": "1"}, "settings": {"w": 4}},
                               mutation_part=part)


class ReportSchema(unittest.TestCase):
    def test_valid_reports(self):
        self.assertEqual(schema.validate(crap_report()), [])
        self.assertEqual(schema.validate(mutation_report()), [])
        self.assertEqual(schema.validate(report.build_report("test", None, "pass", {"command": ["go", "test"]})), [])
        for cmd in ("test", "crap", "mutation"):
            self.assertEqual(schema.validate(report.build_report(cmd, None, "skipped")), [])

    def test_missing_and_extra_fields(self):
        r = crap_report()
        del r["base"]
        self.assertTrue(any("缺少欄位 base" in e for e in schema.validate(r)))
        r = crap_report()
        r["language"] = "go"
        self.assertTrue(any("多出欄位 language" in e for e in schema.validate(r)))

    def test_command_check_not_allowed(self):
        r = crap_report()
        r["command"] = "check"
        self.assertTrue(schema.validate(r))

    def test_blocks_must_match_command_and_result(self):
        r = crap_report()
        r["mutation"] = mutation_report()["mutation"]
        self.assertTrue(any("$.mutation" in e for e in schema.validate(r)))
        r = report.build_report("crap", None, "skipped")
        r["crap"] = crap_report()["crap"]
        self.assertTrue(any("$.crap" in e for e in schema.validate(r)))
        r = crap_report()
        r["inspector"] = None
        self.assertTrue(any("$.inspector" in e for e in schema.validate(r)))

    def test_test_inspector_has_only_command(self):
        r = report.build_report("test", None, "pass", {"command": ["x"], "tools": {}, "settings": None})
        self.assertTrue(any("只有 command" in e for e in schema.validate(r)))

    def test_counts_keys_and_types(self):
        r = mutation_report()
        r["mutation"]["counts"].pop("KILLED")
        self.assertTrue(any("counts" in e for e in schema.validate(r)))
        r = mutation_report()
        r["mutation"]["packages"]["a"]["KILLED"] = "3"
        self.assertTrue(schema.validate(r))
        r = mutation_report()
        r["mutation"]["kill_rate"] = "80"
        self.assertTrue(schema.validate(copy.deepcopy(r)))

    def test_result_enum(self):
        r = crap_report()
        r["result"] = "ok"
        self.assertTrue(schema.validate(r))


if __name__ == "__main__":
    unittest.main()
