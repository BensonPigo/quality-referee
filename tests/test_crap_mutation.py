import json
import os
import unittest

from referee import crap, equivalents, mutation
from referee.errors import RefereeError
from referee.model import (EQUIVALENT, EXCLUDED_MUTATOR, KILLED, LIVED, NOT_COVERED, NOT_VIABLE, SKIPPED, TIMED_OUT,
                           Function, Mutant)
from tests.helpers import TempDirMixin, write

CFG = {"mutation": {"kill_rate_threshold": 80, "reach_rate_threshold": 50}}


class CrapTests(unittest.TestCase):
    def test_formula(self):
        self.assertAlmostEqual(crap.crap_score(3, 0.75), 9 * 0.25 ** 3 + 3)
        self.assertEqual(crap.crap_score(5, 1.0), 5)
        self.assertEqual(crap.crap_score(4, 0.0), 20)

    def test_sorted_high_to_low(self):
        funcs = crap.score_functions([Function("a", "lo", 1, 2, 2, 1.0), Function("a", "hi", 3, 4, 4, 0.0)])
        self.assertEqual([f.name for f in funcs], ["hi", "lo"])

    def test_advice_cover(self):
        # C=4：16 * (1-p)^3 + 4 <= 12 -> p >= 1 - (0.5)^(1/3) = 20.63% -> 21
        self.assertEqual(crap.advice(4, 12), ("cover", 21))
        self.assertEqual(crap.advice_text(4, 12), "覆蓋率要到 21%")

    def test_advice_exact_boundary(self):
        # C=2, 門檻 6：4 * (1-p)^3 + 2 <= 6 -> p >= 0
        self.assertEqual(crap.advice(2, 6), ("cover", 0))

    def test_advice_split_when_complexity_over_threshold(self):
        self.assertEqual(crap.advice(13, 12), ("split", None))
        self.assertEqual(crap.advice_text(13, 12), "要拆函式")

    def test_threshold_boundary_score(self):
        self.assertEqual(crap.crap_score(12, 1.0), 12)  # 等於門檻不算超標，由呼叫端用 > 判斷


def counts_of(**kw):
    c = {s: 0 for s in mutation.STATUSES}
    c.update(kw)
    return c


class RateTests(unittest.TestCase):
    def test_kill_rate_counts_timeout_as_detected(self):
        c = counts_of(KILLED=6, TIMED_OUT=2, LIVED=2)
        self.assertEqual(mutation.kill_rate(c), 80.0)

    def test_reach_rate(self):
        c = counts_of(KILLED=3, LIVED=1, NOT_COVERED=4)
        self.assertEqual(mutation.reach_rate(c), 50.0)

    def test_other_statuses_excluded_from_rates(self):
        c = counts_of(KILLED=1, EQUIVALENT=5, EXCLUDED_MUTATOR=5, NOT_VIABLE=5, SKIPPED=5)
        self.assertEqual(mutation.kill_rate(c), 100.0)
        self.assertEqual(mutation.reach_rate(c), 100.0)

    def test_no_data_is_none(self):
        self.assertIsNone(mutation.kill_rate(counts_of()))
        self.assertIsNone(mutation.reach_rate(counts_of(NOT_VIABLE=2)))
        self.assertIsNone(mutation.kill_rate(counts_of(NOT_COVERED=3)))

    def test_judge(self):
        self.assertEqual(mutation.judge(counts_of(KILLED=4, LIVED=1), CFG), [])  # 80% 剛好過
        self.assertEqual(len(mutation.judge(counts_of(KILLED=3, LIVED=1), CFG)), 1)
        low_reach = mutation.judge(counts_of(KILLED=1, NOT_COVERED=3), CFG)
        self.assertEqual(len(low_reach), 1)
        self.assertIn("測到率", low_reach[0])
        self.assertEqual(mutation.judge(counts_of(), CFG), [])

    def test_by_package_groups_by_directory(self):
        ms = [Mutant("main.go", 1, KILLED, "M"), Mutant("a/b.go", 1, LIVED, "M"), Mutant("a/c.go", 2, KILLED, "M")]
        pk = mutation.by_package(ms)
        self.assertEqual(sorted(pk), [".", "a"])
        self.assertEqual((pk["a"][KILLED], pk["a"][LIVED], pk["."][KILLED]), (1, 1, 1))

    def test_exclude_mutators_overrides_any_status(self):
        ms = [Mutant("a.go", 1, LIVED, "ARITHMETIC_BASE"), Mutant("a.go", 2, KILLED, "OTHER")]
        mutation.exclude_mutators(ms, ["ARITHMETIC_BASE"])
        self.assertEqual([m.status for m in ms], [EXCLUDED_MUTATOR, KILLED])

    def test_describe(self):
        self.assertEqual(mutation.describe(Mutant("a", 1, LIVED, "M", original=">=", replacement=">")), "把 `>=` 改成 `>`")
        self.assertEqual(mutation.describe(Mutant("a", 1, LIVED, "M", original="x", replacement="")), "把 `x` 刪掉")
        self.assertEqual(mutation.describe(Mutant("a", 1, LIVED, "M")), "改法 M")


class EquivalentsTests(TempDirMixin, unittest.TestCase):
    def mutants(self):
        return [
            Mutant("a.go", 5, LIVED, "CB", column=11, line_text="if x >= 1 {"),
            Mutant("a.go", 5, LIVED, "CB", column=20, line_text="if x >= 1 {"),
            Mutant("b.go", 2, LIVED, "CB", line_text="y := 2"),
        ]

    def entry(self, **kw):
        d = {"file": "a.go", "mutator": "CB", "line_text": "if x >= 1 {", "reason": "r", "approved_by": "me"}
        d.update(kw)
        return d

    def test_entry_without_column_matches_whole_line(self):
        ms = self.mutants()
        unused = equivalents.apply(ms, [self.entry()])
        self.assertEqual([m.status for m in ms], [EQUIVALENT, EQUIVALENT, LIVED])
        self.assertEqual(unused, [])

    def test_column_matches_only_that_column(self):
        ms = self.mutants()
        unused = equivalents.apply(ms, [self.entry(column=20)])
        self.assertEqual([m.status for m in ms], [LIVED, EQUIVALENT, LIVED])
        self.assertEqual(unused, [])

    def test_column_that_matches_nothing_is_unused(self):
        ms = self.mutants()
        entry = self.entry(column=99)
        self.assertEqual(equivalents.apply(ms, [entry]), [entry])
        self.assertTrue(all(m.status == LIVED for m in ms))

    def test_changed_line_text_makes_entry_unused(self):
        ms = self.mutants()
        entry = self.entry(line_text="if x > 1 {")
        self.assertEqual(equivalents.apply(ms, [entry]), [entry])

    def test_line_number_is_not_part_of_key_and_whitespace_trimmed(self):
        ms = [Mutant("a.go", 99, LIVED, "CB", line_text="if x >= 1 {")]
        equivalents.apply(ms, [self.entry(line_text="  if x >= 1 {  ", file="./a.go")])
        self.assertEqual(ms[0].status, EQUIVALENT)

    def test_excluded_mutator_not_rematched(self):
        ms = [Mutant("a.go", 5, EXCLUDED_MUTATOR, "CB", line_text="if x >= 1 {")]
        entry = self.entry()
        self.assertEqual(equivalents.apply(ms, [entry]), [entry])
        self.assertEqual(ms[0].status, EXCLUDED_MUTATOR)

    def test_scope_limits_unused_report_and_universe_counts_as_used(self):
        in_universe = Mutant("a.go", 5, LIVED, "CB", line_text="if x >= 1 {")
        entries = [self.entry(), self.entry(file="far.go")]
        unused = equivalents.apply([], entries, universe=[in_universe], scope={"a.go"})
        self.assertEqual(unused, [])  # a.go 的項目在 universe 對得上；far.go 不在範圍內，不算沒用到
        unused = equivalents.apply([], entries, universe=[], scope={"a.go"})
        self.assertEqual(unused, [entries[0]])

    def test_validate_errors(self):
        bad = [
            ({}, "最外層必須是陣列"),
            (["x"], "第 1 項必須是物件"),
            ([{"file": "a"}], "缺少必填欄位 mutator"),
            ([self.entry(extra=1)], "不認得的鍵：extra"),
            ([self.entry(reason=" ")], "reason 必須是非空白的字串"),
            ([self.entry(column=0)], "column 必須是正整數"),
            ([self.entry(column="3")], "column 必須是正整數"),
            ([self.entry(column=True)], "column 必須是正整數"),
            ([self.entry(function=3)], "function 必須是字串"),
        ]
        for data, text in bad:
            with self.subTest(text=text):
                with self.assertRaises(RefereeError) as cm:
                    equivalents.validate(data)
                self.assertIn(text, str(cm.exception))

    def test_validate_accepts_function_and_column(self):
        equivalents.validate([self.entry(function="F", column=3)])

    def test_load_missing_file_is_empty_and_bad_json_is_error(self):
        d = self.make_tmp()
        self.assertEqual(equivalents.load(os.path.join(d, "none.json")), [])
        write(d, "bad.json", "{oops")
        with self.assertRaises(RefereeError):
            equivalents.load(os.path.join(d, "bad.json"))
        write(d, "ok.json", json.dumps([self.entry(column=2)]))
        self.assertEqual(len(equivalents.load(os.path.join(d, "ok.json"))), 1)

    def test_fill_line_text(self):
        d = self.make_tmp()
        write(d, "a.go", "﻿one\n  two  \n")
        ms = [Mutant("a.go", 1, LIVED, "M"), Mutant("a.go", 2, LIVED, "M"), Mutant("a.go", 9, LIVED, "M"),
              Mutant("gone.go", 1, LIVED, "M")]
        mutation.fill_line_text(ms, d)
        self.assertEqual([m.line_text for m in ms], ["one", "two", "", ""])


if __name__ == "__main__":
    unittest.main()
