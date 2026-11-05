"""JSON 報告（referee.report/1）的格式驗證，selftest 和單元測試都用它。

欄位多或少都算錯：多出來的欄位代表程式和 docs/合約.md 對不上，應該在這裡補上，不能默默放行。

描述方式：
    str / int / bool       該型別（int 不收 bool）
    Num                    int 或 float（不收 bool）
    Opt(x)                 x 或 null
    Lst(x)                 x 的陣列
    Dic(x)                 字串鍵、x 值的物件
    Enum(a, b, ...)        其中之一
    {欄位: 描述, ...}      物件，欄位要完全一致；欄位名開頭是 ? 代表選填
"""

from referee.model import STATUSES

REPORT_SCHEMA = "referee.report/1"


class Num:
    pass


class Opt:
    def __init__(self, spec):
        self.spec = spec


class Lst:
    def __init__(self, spec):
        self.spec = spec


class Dic:
    def __init__(self, spec):
        self.spec = spec


class Enum:
    def __init__(self, *values):
        self.values = values


class Scalar:
    """字串、數字、布林或 null（settings 的值）。"""


COUNTS = Dic(int)

CRAP_FUNCTION = {
    "file": str, "name": str, "start": int, "end": int, "complexity": int,
    "coverage": Num, "crap": Num, "over": bool,
    "advice": Opt(Enum("split", "cover")), "need_coverage": Opt(Num),
}

MUTANT = {
    "file": str, "line": int, "column": Opt(int), "mutator": str, "status": str,
    "original": Opt(str), "replacement": Opt(str), "line_text": str,
}

REPORT = {
    "schema": Enum(REPORT_SCHEMA),
    "referee_version": str,
    "command": Enum("test", "crap", "mutation"),
    "base": Opt(str),
    "result": Enum("pass", "fail", "skipped"),
    "inspector": Opt({"command": Lst(str), "?tools": Dic(str), "?settings": Opt(Dic(Scalar))}),
    "crap": Opt({
        "threshold": Num,
        "functions": Lst(CRAP_FUNCTION),
        "untouched_over": Opt(int),
    }),
    "mutation": Opt({
        "kill_rate_threshold": Num,
        "reach_rate_threshold": Num,
        "exclude_mutators": Lst(str),
        "counts": COUNTS,
        "kill_rate": Opt(Num),
        "reach_rate": Opt(Num),
        "packages": Dic(COUNTS),
        "mutants": Lst(MUTANT),
        "unused_equivalents": Lst(dict),
    }),
}


def validate(data):
    """回傳錯誤訊息的串列，空串列代表格式正確。"""
    errors = []
    _check(data, REPORT, "$", errors)
    if errors:
        return errors

    cmd, result = data["command"], data["result"]
    # 該關有跑（result 不是 skipped）時，只有那一關自己的區塊有值；skipped 時兩個區塊都是 null
    want_crap = cmd == "crap" and result != "skipped"
    want_mutation = cmd == "mutation" and result != "skipped"
    if (data["crap"] is not None) != want_crap:
        errors.append("$.crap：command 是 {}、result 是 {} 時，應該{}".format(cmd, result, "有值" if want_crap else "是 null"))
    if (data["mutation"] is not None) != want_mutation:
        errors.append("$.mutation：command 是 {}、result 是 {} 時，應該{}".format(cmd, result, "有值" if want_mutation else "是 null"))
    if (data["inspector"] is None) != (result == "skipped"):
        errors.append("$.inspector：result 是 skipped 時應該是 null，其他情況應該有值")
    elif data["inspector"] is not None:
        has = ("tools" in data["inspector"], "settings" in data["inspector"])
        if cmd == "test" and any(has):
            errors.append("$.inspector：test 的 inspector 只有 command")
        if cmd != "test" and not all(has):
            errors.append("$.inspector：{} 的 inspector 要有 command、tools、settings".format(cmd))
    if data["mutation"] is not None:
        for k in ("counts",):
            if sorted(data["mutation"][k]) != sorted(STATUSES):
                errors.append("$.mutation.{}：鍵必須剛好是 {}".format(k, "、".join(STATUSES)))
        for p, c in data["mutation"]["packages"].items():
            if sorted(c) != sorted(STATUSES):
                errors.append("$.mutation.packages.{}：鍵必須剛好是 {}".format(p, "、".join(STATUSES)))
        for i, m in enumerate(data["mutation"]["mutants"]):
            if m["status"] not in STATUSES:
                errors.append("$.mutation.mutants[{}].status：不認得的狀態 {!r}".format(i, m["status"]))
    return errors


def _check(value, spec, path, errors):
    if isinstance(spec, Opt):
        if value is not None:
            _check(value, spec.spec, path, errors)
    elif isinstance(spec, dict):
        if not isinstance(value, dict):
            errors.append("{}：應該是物件".format(path))
            return
        keys = {k.lstrip("?"): v for k, v in spec.items()}
        for k in spec:
            if not k.startswith("?") and k not in value:
                errors.append("{}：缺少欄位 {}".format(path, k))
        for k in value:
            if k not in keys:
                errors.append("{}：多出欄位 {}".format(path, k))
            else:
                _check(value[k], keys[k], "{}.{}".format(path, k), errors)
    elif isinstance(spec, Lst):
        if not isinstance(value, list):
            errors.append("{}：應該是陣列".format(path))
            return
        for i, item in enumerate(value):
            _check(item, spec.spec, "{}[{}]".format(path, i), errors)
    elif isinstance(spec, Dic):
        if not isinstance(value, dict):
            errors.append("{}：應該是物件".format(path))
            return
        for k, item in value.items():
            _check(item, spec.spec, "{}.{}".format(path, k), errors)
    elif isinstance(spec, Enum):
        if value not in spec.values:
            errors.append("{}：應該是 {} 其中之一（目前是 {!r}）".format(path, "、".join(map(repr, spec.values)), value))
    elif spec is Scalar:
        if value is not None and not isinstance(value, (str, int, float, bool)):
            errors.append("{}：應該是字串、數字、布林或 null".format(path))
    elif spec is Num:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append("{}：應該是數字（目前是 {!r}）".format(path, value))
    elif spec is dict:
        if not isinstance(value, dict):
            errors.append("{}：應該是物件".format(path))
    elif spec is int:
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append("{}：應該是整數（目前是 {!r}）".format(path, value))
    elif spec is bool:
        if not isinstance(value, bool):
            errors.append("{}：應該是 true 或 false（目前是 {!r}）".format(path, value))
    elif spec is str:
        if not isinstance(value, str):
            errors.append("{}：應該是字串（目前是 {!r}）".format(path, value))
