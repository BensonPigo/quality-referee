"""文字輸出和 JSON 報告。JSON 格式見 docs/合約.md，驗證見 schema.py。"""

import json

from referee import __version__, crap, mutation
from referee.model import EQUIVALENT, EXCLUDED_MUTATOR, KILLED, LIVED, NOT_COVERED, STATUS_NAMES, TIMED_OUT
from referee.schema import REPORT_SCHEMA


def pct(v):
    return "—" if v is None else "{:.2f}%".format(v)


# ---------- CRAP ----------

def print_crap_table(funcs, threshold):
    """印出 CRAP 表格，回傳超過門檻的函式數量。超標的函式後面附上改善方向。"""
    print("{:<8} {:<6} {:<8} {:<24} {}".format("CRAP", "C", "覆蓋率", "函式", "位置"))
    failed = 0
    for f in funcs:
        mark = "  "
        if f.crap > threshold:
            failed += 1
            mark = "❌ " + crap.advice_text(f.complexity, threshold)
        print("{:<8.1f} {:<6} {:<8} {:<24} {}:{} {}".format(
            f.crap, f.complexity, "{:.1f}%".format(f.coverage * 100), f.name, f.file, f.start, mark))
    return failed


def crap_json(funcs, threshold, untouched_over):
    items = []
    for f in funcs:
        over = f.crap > threshold
        kind, need = crap.advice(f.complexity, threshold) if over else (None, None)
        items.append({
            "file": f.file, "name": f.name, "start": f.start, "end": f.end,
            "complexity": f.complexity, "coverage": f.coverage, "crap": f.crap, "over": over,
            "advice": kind, "need_coverage": need,
        })
    return {"threshold": threshold, "functions": items, "untouched_over": untouched_over}


# ---------- 抓錯檢查 ----------

def location(m):
    """「檔案:行:欄」，檢查員沒回報欄位時是「檔案:行」。排除清單的 column 就照這裡的欄抄。"""
    if m.column is None:
        return "{}:{}".format(m.file, m.line)
    return "{}:{}:{}".format(m.file, m.line, m.column)


def _value(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def settings_line(settings):
    """「檢查員設定：workers 4、coverage_scope module」，沒有就是「檢查員設定：無」。"""
    if not settings:
        return "檢查員設定：無"
    return "檢查員設定：" + "、".join("{} {}".format(k, _value(v)) for k, v in settings.items())


def print_mutation_result(mutants, counts, cfg, settings, unused=()):
    """列出沒抓到和測試沒跑到的改壞版本，加上計數、抓錯率、測到率、檢查員設定、排除清單沒用到的項目。"""
    for m in sorted(mutants, key=lambda m: (m.file, m.line, m.column or 0)):
        if m.status in (LIVED, NOT_COVERED):
            print("{}  {}  {}  ｜ {}".format(
                STATUS_NAMES[m.status].split("（")[0], location(m), mutation.describe(m), m.line_text))

    k = cfg["mutation"]["kill_rate_threshold"]
    r = cfg["mutation"]["reach_rate_threshold"]
    print()
    print("抓到 {}、逾時 {}（算抓到）、沒抓到 {}、測試沒跑到 {}".format(
        counts[KILLED], counts[TIMED_OUT], counts[LIVED], counts[NOT_COVERED]))
    excluded = ["{} {}".format(STATUS_NAMES[s], counts[s]) for s in (EQUIVALENT, EXCLUDED_MUTATOR) if counts[s]]
    if excluded:
        print("、".join(excluded) + "（不算進抓錯率和測到率）")
    print("抓錯率：{}（門檻 {}%）".format(pct(mutation.kill_rate(counts)), k))
    print("測到率：{}（門檻 {}%）".format(pct(mutation.reach_rate(counts)), r))
    print(settings_line(settings))
    if unused:
        print()
        print("排除清單有 {} 項沒用到（那一行的原文或改法已經變了，請重新判斷，或從清單刪掉）：".format(len(unused)))
        for e in unused:
            column = "  欄 {}".format(e["column"]) if "column" in e else ""
            print("  {}  {}  {}{}".format(e["file"], e["mutator"], e["line_text"], column))


def mutation_json(mutants, counts, cfg, unused=()):
    m = cfg["mutation"]
    items = [{
        "file": x.file, "line": x.line, "column": x.column, "mutator": x.mutator, "status": x.status,
        "original": x.original, "replacement": x.replacement, "line_text": x.line_text,
    } for x in sorted(mutants, key=lambda x: (x.file, x.line, x.column or 0))]
    return {
        "kill_rate_threshold": m["kill_rate_threshold"],
        "reach_rate_threshold": m["reach_rate_threshold"],
        "exclude_mutators": list(m["exclude_mutators"]),
        "counts": counts,
        "kill_rate": mutation.kill_rate(counts),
        "reach_rate": mutation.reach_rate(counts),
        "packages": dict(sorted(mutation.by_package(mutants).items())),
        "mutants": items,
        "unused_equivalents": list(unused),
    }


# ---------- JSON 報告 ----------

def build_report(command, base, result, inspector=None, crap_part=None, mutation_part=None):
    """result 是 pass、fail、skipped。skipped 時 inspector、crap、mutation 都是 None。"""
    return {
        "schema": REPORT_SCHEMA,
        "referee_version": __version__,
        "command": command,
        "base": base,
        "result": result,
        "inspector": inspector,
        "crap": crap_part,
        "mutation": mutation_part,
    }


def write_json(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
