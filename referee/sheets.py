"""記分表（檢查員交給裁判的 JSON）的格式驗證。格式見 docs/合約.md。

欄位多或少、型別不對都算錯，訊息指出哪一項哪個欄位。
"""

import json
import os

from referee.errors import RefereeError
from referee.model import (EQUIVALENT, EXCLUDED_MUTATOR, INSPECTOR_STATUSES, Function, Mutant)

FUNCTIONS_SCHEMA = "referee.functions/1"
MUTANTS_SCHEMA = "referee.mutants/1"

_FUNCTION_KEYS = ("file", "name", "start", "end", "complexity", "coverage")
_MUTANT_REQUIRED = ("file", "line", "mutator", "status")
_MUTANT_OPTIONAL = ("column", "original", "replacement")


def load_sheet(path, what):
    """讀記分表的 JSON。檔案不存在、不是合法 JSON 都丟 RefereeError。"""
    if not os.path.exists(path):
        raise RefereeError("檢查員結束碼是 0，但沒有寫出{}（REFEREE_OUT 指定的檔案不存在）".format(what))
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except ValueError as e:
        raise RefereeError("{}不是合法的 JSON：{}".format(what, e))


def parse_functions(data):
    """驗證函式表，回傳 (tools, settings, [Function])。"""
    errors = []
    _header(data, FUNCTIONS_SCHEMA, "functions", errors)
    funcs = []
    items = data.get("functions") if isinstance(data, dict) else None
    if isinstance(data, dict) and "functions" in data and not isinstance(items, list):
        errors.append("$.functions：應該是陣列")
    for i, item in enumerate(items if isinstance(items, list) else []):
        p = "$.functions[{}]".format(i)
        if not isinstance(item, dict):
            errors.append("{}：應該是物件".format(p))
            continue
        n = len(errors)
        _keys(item, _FUNCTION_KEYS, (), p, errors)
        _file(item, p, errors)
        _nonempty_str(item, "name", p, errors)
        for k in ("start", "end", "complexity"):
            _pos_int(item, k, p, errors)
        cov = item.get("coverage")
        if "coverage" in item and (isinstance(cov, bool) or not isinstance(cov, (int, float)) or not 0 <= cov <= 1):
            errors.append("{}.coverage：應該是 0～1 的數字（目前是 {!r}）".format(p, cov))
        if len(errors) == n and item["start"] > item["end"]:
            errors.append("{}：start（{}）不能大於 end（{}）".format(p, item["start"], item["end"]))
        if len(errors) == n:
            funcs.append(Function(item["file"], item["name"], item["start"], item["end"],
                                  item["complexity"], float(item["coverage"])))
    _raise(errors, "函式表")
    return data.get("tools", {}), data.get("settings"), funcs


def parse_mutants(data):
    """驗證改壞版本表，回傳 (tools, settings, [Mutant])。"""
    errors = []
    _header(data, MUTANTS_SCHEMA, "mutants", errors)
    mutants = []
    items = data.get("mutants") if isinstance(data, dict) else None
    if isinstance(data, dict) and "mutants" in data and not isinstance(items, list):
        errors.append("$.mutants：應該是陣列")
    for i, item in enumerate(items if isinstance(items, list) else []):
        p = "$.mutants[{}]".format(i)
        if not isinstance(item, dict):
            errors.append("{}：應該是物件".format(p))
            continue
        n = len(errors)
        _keys(item, _MUTANT_REQUIRED, _MUTANT_OPTIONAL, p, errors)
        _file(item, p, errors)
        _pos_int(item, "line", p, errors)
        _nonempty_str(item, "mutator", p, errors)
        if item.get("column") is not None:
            _pos_int(item, "column", p, errors)
        for k in ("original", "replacement"):
            if item.get(k) is not None and not isinstance(item[k], str):
                errors.append("{}.{}：應該是字串（目前是 {!r}）".format(p, k, item[k]))
        status = item.get("status")
        if "status" in item:
            if status in (EQUIVALENT, EXCLUDED_MUTATOR):
                errors.append("{}.status：{} 由裁判標記，檢查員不能交出這個狀態".format(p, status))
            elif status not in INSPECTOR_STATUSES:
                errors.append("{}.status：應該是 {} 其中之一（目前是 {!r}）".format(
                    p, "、".join(INSPECTOR_STATUSES), status))
        if len(errors) == n:
            mutants.append(Mutant(item["file"], item["line"], status, item["mutator"],
                                  item.get("column"), item.get("original"), item.get("replacement")))
    _raise(errors, "改壞版本表")
    return data.get("tools", {}), data.get("settings"), mutants


def _header(data, schema, list_key, errors):
    if not isinstance(data, dict):
        errors.append("$：最外層應該是物件")
        return
    if data.get("schema") != schema:
        errors.append("$.schema：應該是 {!r}（目前是 {!r}）".format(schema, data.get("schema")))
    _keys(data, ("schema", list_key), ("tools", "settings"), "$", errors)
    tools = data.get("tools", {})
    if not isinstance(tools, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in tools.items()):
        errors.append("$.tools：應該是物件，值是字串（工具名稱 → 版本）")
    settings = data.get("settings")
    if settings is not None and (not isinstance(settings, dict) or not all(
            isinstance(k, str) and (v is None or isinstance(v, (str, int, float, bool))) for k, v in settings.items())):
        errors.append("$.settings：應該是物件，值是字串、數字、布林或 null")


def _keys(item, required, optional, path, errors):
    for k in required:
        if k not in item:
            errors.append("{}：缺少欄位 {}".format(path, k))
    for k in item:
        if k not in required and k not in optional:
            errors.append("{}：多出欄位 {}".format(path, k))


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _pos_int(item, key, path, errors):
    if key in item and not (_is_int(item[key]) and item[key] > 0):
        errors.append("{}.{}：應該是正整數（目前是 {!r}）".format(path, key, item[key]))


def _nonempty_str(item, key, path, errors):
    if key in item and not (isinstance(item[key], str) and item[key].strip()):
        errors.append("{}.{}：應該是非空白的字串（目前是 {!r}）".format(path, key, item[key]))


def _file(item, path, errors):
    if "file" not in item:
        return
    f = item["file"]
    if not isinstance(f, str) or not f.strip():
        errors.append("{}.file：應該是非空白的字串（目前是 {!r}）".format(path, f))
    elif "\\" in f or f.startswith("/") or f.startswith("./") or ":" in f.split("/")[0] or ".." in f.split("/"):
        errors.append("{}.file：應該是相對專案根目錄、用 / 分隔的路徑（目前是 {!r}）".format(path, f))


def _raise(errors, what):
    if errors:
        raise RefereeError("{}格式有誤：\n  ".format(what) + "\n  ".join(errors))
