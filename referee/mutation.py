"""抓錯率、測到率和改壞版本的整理。

抓錯率 = (抓到 + 逾時) ÷ (抓到 + 逾時 + 沒抓到)：有測到的改壞版本裡，抓到幾成。
測到率 = (抓到 + 逾時 + 沒抓到) ÷ (抓到 + 逾時 + 沒抓到 + 測試沒跑到)：全部改壞版本裡，有幾成被測試跑到。
已排除（改了也沒差、設定排除的改法）、無效、略過，都不算進這兩個比例。
"""

import os
import posixpath
from collections import defaultdict

from referee.model import EXCLUDED_MUTATOR, KILLED, LIVED, NOT_COVERED, STATUSES, TIMED_OUT


def count(mutants):
    counts = {s: 0 for s in STATUSES}
    for m in mutants:
        counts[m.status] += 1
    return counts


def detected(counts):
    return counts[KILLED] + counts[TIMED_OUT]


def kill_rate(counts):
    covered = detected(counts) + counts[LIVED]
    return 100.0 * detected(counts) / covered if covered else None


def reach_rate(counts):
    covered = detected(counts) + counts[LIVED]
    total = covered + counts[NOT_COVERED]
    return 100.0 * covered / total if total else None


def judge(counts, cfg):
    """依門檻判斷，回傳沒過的原因（空串列代表通過）。"""
    m = cfg["mutation"]
    problems = []
    k, r = kill_rate(counts), reach_rate(counts)
    if k is not None and k < m["kill_rate_threshold"]:
        problems.append("抓錯率低於門檻，有改壞的版本沒被抓到：補測試把它抓出來；認為改了也沒差的，在 PR 裡說明")
    if r is not None and r < m["reach_rate_threshold"]:
        problems.append("測到率低於門檻：有改到的程式碼沒有測試")
    return problems


def package_of(file):
    """套件的分組鍵：檔案所在目錄，根目錄是 .。"""
    return posixpath.dirname(file) or "."


def by_package(mutants):
    packages = defaultdict(list)
    for m in mutants:
        packages[package_of(m.file)].append(m)
    return {p: count(ms) for p, ms in packages.items()}


def fill_line_text(mutants, root):
    """填入每個改壞版本所在那一行的原文（去頭尾空白）。檔案不見了就是空字串。"""
    cache = {}
    for m in mutants:
        if m.file not in cache:
            try:
                # utf-8-sig：檔案開頭有 BOM 時，第一行的欄位位置才跟工具回報的對得上
                with open(os.path.join(root, m.file), encoding="utf-8-sig", errors="replace") as f:
                    cache[m.file] = f.read().splitlines()
            except OSError:
                cache[m.file] = []
        lines = cache[m.file]
        m.line_text = lines[m.line - 1].strip() if 0 < m.line <= len(lines) else ""
    return mutants


def exclude_mutators(mutants, names):
    """名稱在 names 裡的改壞版本一律標成 EXCLUDED_MUTATOR，不看原本的狀態。"""
    names = set(names)
    for m in mutants:
        if m.mutator in names:
            m.status = EXCLUDED_MUTATOR
    return mutants


def describe(m):
    """一個改壞版本改了什麼，例如「把 `>=` 改成 `>`」。取不到改成什麼時，退回「改法 名稱」。"""
    if m.replacement is None or not m.original:
        return "改法 " + m.mutator
    if m.replacement == "":
        return "把 `{}` 刪掉".format(_one_line(m.original))
    return "把 `{}` 改成 `{}`".format(_one_line(m.original), _one_line(m.replacement))


def _one_line(text):
    lines = text.splitlines()
    return lines[0] + "…" if len(lines) > 1 else text
