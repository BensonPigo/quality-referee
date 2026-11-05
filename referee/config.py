"""讀取、驗證 .referee.json（version 1）。

設定檔寫錯不能默默變成預設值：沒有 version 或不是 1、未知的鍵、型別不對都直接報錯（結束碼 2）。
"""

import copy
import json
import os

from referee.errors import RefereeError

CONFIG_FILE = ".referee.json"
GATES = ["test", "crap", "mutation"]

DEFAULTS = {
    "version": 1,
    "base": "origin/main",
    "gates": ["test", "crap", "mutation"],
    "sources": [],
    "tests": [],
    "exclude": [],
    "test": {"command": None},
    "crap": {"threshold": 12, "inspector": None},
    "mutation": {
        "kill_rate_threshold": 80,
        "reach_rate_threshold": 50,  # 一定要有門檻：沒有門檻，新寫的程式完全沒有測試也能過關
        "exclude_mutators": [],
        "equivalents_file": ".referee-equivalents.json",
        "inspector": None,
    },
}


def load_config(root):
    path = os.path.join(root, CONFIG_FILE)
    if not os.path.exists(path):
        raise RefereeError("找不到 {}，請在專案根目錄執行".format(CONFIG_FILE))
    try:
        with open(path, encoding="utf-8-sig") as f:
            raw = json.load(f)
    except ValueError as e:
        raise RefereeError("{} 不是合法的 JSON：{}".format(CONFIG_FILE, e))
    return validate(raw)


def validate(raw):
    """檢查設定檔內容，回傳補上預設值的完整設定。"""
    if not isinstance(raw, dict):
        raise RefereeError("{} 的最外層必須是物件".format(CONFIG_FILE))
    if raw.get("version") != 1 or isinstance(raw.get("version"), bool):
        raise RefereeError("{} 的 version 必須是 1".format(CONFIG_FILE))

    problems = []
    cfg = copy.deepcopy(DEFAULTS)
    for key, value in raw.items():
        if key not in DEFAULTS:
            problems.append("不認得的鍵：{}".format(key))
        elif isinstance(DEFAULTS[key], dict):
            if not isinstance(value, dict):
                problems.append("{} 必須是物件".format(key))
                continue
            for sub, subvalue in value.items():
                if sub not in DEFAULTS[key]:
                    problems.append("不認得的鍵：{}.{}".format(key, sub))
                else:
                    cfg[key][sub] = subvalue
        else:
            cfg[key] = value

    if not problems:
        problems = _check_values(cfg)
    if problems:
        raise RefereeError("{} 有誤：\n  ".format(CONFIG_FILE) + "\n  ".join(problems))
    return cfg


def _check_values(cfg):
    problems = []

    def need(ok, message):
        if not ok:
            problems.append(message)

    gates = cfg["gates"]
    need(isinstance(gates, list) and all(g in GATES for g in gates) and len(set(gates)) == len(gates),
         "gates 必須是 {} 的子集合的陣列，不能重複".format("、".join(GATES)))
    need(isinstance(cfg["base"], str) and cfg["base"], "base 必須是分支名稱的字串")
    for key in ("sources", "tests", "exclude"):
        need(_str_list(cfg[key]), "{} 必須是字串陣列".format(key))
    need(_command(cfg["test"]["command"], True), "test.command 必須是非空字串組成的陣列（指令不經過 shell）")
    need(_number(cfg["crap"]["threshold"]), "crap.threshold 必須是數字")
    need(_command(cfg["crap"]["inspector"], True), "crap.inspector 必須是非空字串組成的陣列（指令不經過 shell）")
    m = cfg["mutation"]
    need(_number(m["kill_rate_threshold"]), "mutation.kill_rate_threshold 必須是數字")
    need(_number(m["reach_rate_threshold"]), "mutation.reach_rate_threshold 必須是數字")
    need(_str_list(m["exclude_mutators"]), "mutation.exclude_mutators 必須是字串陣列")
    need(isinstance(m["equivalents_file"], str) and m["equivalents_file"], "mutation.equivalents_file 必須是檔名的字串")
    need(_command(m["inspector"], True), "mutation.inspector 必須是非空字串組成的陣列（指令不經過 shell）")

    if not problems and isinstance(gates, list):
        if "test" in gates and cfg["test"]["command"] is None:
            problems.append("gates 有 test，test.command 必須設定")
        for g in ("crap", "mutation"):
            if g in gates and cfg[g]["inspector"] is None:
                problems.append("gates 有 {}，{}.inspector 必須設定".format(g, g))
        if ("crap" in gates or "mutation" in gates) and not cfg["sources"]:
            problems.append("gates 有 crap 或 mutation，sources 必須至少有一個樣式")
    return problems


def _str_list(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _command(v, allow_none):
    if v is None:
        return allow_none
    return isinstance(v, list) and len(v) > 0 and all(isinstance(x, str) and x for x in v)


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)
