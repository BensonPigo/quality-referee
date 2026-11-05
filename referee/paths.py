"""路徑比對規則。docs/合約.md 的「路徑比對規則」就是這個檔案，檢查員可以照抄。

路徑一律相對於專案根目錄、用 / 分隔、大小寫有別。
樣式：* 比對任意個非 / 的字元；? 比對一個非 / 的字元；**/ 比對零層或多層目錄；
結尾或其他位置的 ** 比對任意字元（含 /）。
"""

import re

_cache = {}


def normalize(path):
    """路徑統一用 / 分隔，去掉開頭的 ./"""
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def glob_to_regex(pattern):
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z", re.DOTALL)


def matches(path, patterns):
    """path 是否比得到 patterns 裡任何一個樣式。"""
    for p in patterns:
        if p not in _cache:
            _cache[p] = glob_to_regex(p)
        if _cache[p].match(path):
            return True
    return False


def is_excluded(path, exclude):
    """path 等於 exclude 的某個目錄，或在它底下。結尾的 / 可寫可不寫。"""
    path = normalize(path)
    for e in exclude:
        e = normalize(e).rstrip("/")
        if path == e or path.startswith(e + "/"):
            return True
    return False


def in_scope(path, sources, tests, exclude):
    """在範圍內 = 比得到 sources、比不到 tests、不在 exclude 底下。"""
    return matches(path, sources) and not matches(path, tests) and not is_excluded(path, exclude)
