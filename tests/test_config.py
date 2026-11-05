import unittest

from referee import config
from referee.errors import RefereeError

GOOD = {
    "version": 1,
    "sources": ["**/*.go"],
    "tests": ["**/*_test.go"],
    "exclude": ["vendor/"],
    "test": {"command": ["go", "test", "./..."]},
    "crap": {"inspector": ["python", "x.py", "functions"]},
    "mutation": {"inspector": ["python", "x.py", "mutants"]},
}


def with_(**changes):
    d = dict(GOOD)
    d.update(changes)
    return d


def fails(case, raw, text):
    with case.assertRaises(RefereeError) as cm:
        config.validate(raw)
    case.assertEqual(cm.exception.exit_code, 2)
    case.assertIn(text, str(cm.exception))


class ConfigTests(unittest.TestCase):
    def test_defaults_filled(self):
        cfg = config.validate(GOOD)
        self.assertEqual(cfg["base"], "origin/main")
        self.assertEqual(cfg["gates"], ["test", "crap", "mutation"])
        self.assertEqual(cfg["crap"]["threshold"], 12)
        self.assertEqual(cfg["mutation"]["kill_rate_threshold"], 80)
        self.assertEqual(cfg["mutation"]["reach_rate_threshold"], 50)
        self.assertEqual(cfg["mutation"]["equivalents_file"], ".referee-equivalents.json")

    def test_not_object(self):
        fails(self, [], "最外層必須是物件")

    def test_version_missing_or_wrong(self):
        fails(self, {}, "version 必須是 1")
        fails(self, with_(version=2), "version 必須是 1")
        fails(self, with_(version=True), "version 必須是 1")

    def test_unknown_key(self):
        fails(self, with_(language="go"), "不認得的鍵：language")

    def test_unknown_subkey(self):
        fails(self, with_(crap={"inspector": ["x"], "workers": 4}), "不認得的鍵：crap.workers")

    def test_section_must_be_object(self):
        fails(self, with_(crap=[]), "crap 必須是物件")

    def test_wrong_types(self):
        fails(self, with_(sources="**/*.go"), "sources 必須是字串陣列")
        fails(self, with_(exclude=[1]), "exclude 必須是字串陣列")
        fails(self, with_(gates=["test", "lint"]), "gates 必須是")
        fails(self, with_(gates=["test", "test"]), "不能重複")
        fails(self, with_(base=""), "base 必須是")
        fails(self, with_(crap={"threshold": "12", "inspector": ["x"]}), "crap.threshold 必須是數字")
        fails(self, with_(crap={"threshold": True, "inspector": ["x"]}), "crap.threshold 必須是數字")
        fails(self, with_(mutation={"kill_rate_threshold": None, "inspector": ["x"]}), "kill_rate_threshold")
        fails(self, with_(mutation={"exclude_mutators": "A", "inspector": ["x"]}), "exclude_mutators")
        fails(self, with_(mutation={"equivalents_file": "", "inspector": ["x"]}), "equivalents_file")

    def test_inspector_must_be_argv_array(self):
        fails(self, with_(crap={"inspector": "python x.py"}), "crap.inspector 必須是")
        fails(self, with_(crap={"inspector": []}), "crap.inspector 必須是")
        fails(self, with_(mutation={"inspector": ["x", ""]}), "mutation.inspector 必須是")
        fails(self, with_(test={"command": "go test"}), "test.command 必須是")

    def test_enabled_gate_needs_its_command(self):
        fails(self, with_(test={}), "test.command 必須設定")
        fails(self, with_(crap={}), "crap.inspector 必須設定")
        fails(self, with_(mutation={}), "mutation.inspector 必須設定")

    def test_disabled_gate_needs_no_command(self):
        cfg = config.validate({"version": 1, "gates": ["test"], "test": {"command": ["x"]}})
        self.assertEqual(cfg["gates"], ["test"])

    def test_sources_required_for_measured_gates(self):
        fails(self, with_(sources=[]), "sources 必須至少有一個樣式")


if __name__ == "__main__":
    unittest.main()
