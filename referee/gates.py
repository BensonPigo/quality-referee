"""三道關的判定流程。每一關回傳 (結束碼, JSON 報告)，文字輸出直接印出。"""

import os
import subprocess
import sys

from referee import changes, crap, equivalents, inspector, mutation, report
from referee.config import GATES
from referee.errors import RefereeError
from referee.model import KILLED, LIVED, NOT_COVERED, TIMED_OUT
from referee.paths import in_scope


def _scope_filter(items, cfg):
    """裁判一律再篩一次：丟掉不在 sources、在 tests、或在 exclude 底下的項目。檢查員多交了東西不影響結果。"""
    return [x for x in items if in_scope(x.file, cfg["sources"], cfg["tests"], cfg["exclude"])]


def _inspector_info(cfg, gate, tools, settings):
    return {"command": list(cfg[gate]["inspector"]), "tools": dict(tools),
            "settings": None if settings is None else dict(settings)}


def skipped_report(gate):
    return report.build_report(gate, None, "skipped")


# ---------- 第一關：單元測試 ----------

def run_test(cfg, root):
    command = cfg["test"]["command"]
    sys.stdout.flush()
    try:
        code = subprocess.call(command, cwd=root)
    except FileNotFoundError:
        raise RefereeError("找不到指令 {}，請確認已安裝並加入 PATH".format(command[0]))
    except OSError as e:
        raise RefereeError("無法執行 {}：{}".format(command[0], e))
    result = "pass" if code == 0 else "fail"
    return (0 if code == 0 else 1), report.build_report("test", None, result, {"command": list(command)})


# ---------- 第二關：CRAP ----------

def run_crap(base, cfg, root):
    threshold = cfg["crap"]["threshold"]
    changed = changes.changed_lines(base, root) if base else None
    tools, settings, funcs = inspector.run_inspector("crap", cfg, root, None)
    funcs = crap.score_functions(_scope_filter(funcs, cfg))

    untouched_over = None
    if base:
        touched = [f for f in funcs if changes.overlaps(changed.get(f.file), f.start, f.end)]
        untouched_over = sum(1 for f in funcs if f not in touched and f.crap > threshold)
        funcs = touched
        print("只檢查和 {} 相比有改到的函式（共 {} 個）\n".format(base, len(funcs)))

    failed = report.print_crap_table(funcs, threshold, with_advice=bool(base))
    print()
    if untouched_over:
        print("另有 {} 個沒改到的函式超過門檻，列為技術債，不計入這次判定。".format(untouched_over))
    print(report.settings_line(settings))
    if failed:
        print("FAIL：{} 個函式的 CRAP 超過門檻 {}".format(failed, threshold))
    elif base and not funcs:
        print("PASS：這次沒有改到任何函式")
    else:
        print("PASS：所有函式的 CRAP 都在門檻 {} 以內".format(threshold))

    rep = report.build_report(
        "crap", base, "fail" if failed else "pass", _inspector_info(cfg, "crap", tools, settings),
        crap_part=report.crap_json(funcs, threshold, untouched_over))
    return (1 if failed else 0), rep


# ---------- 第三關：抓錯檢查 ----------

def run_mutation(base, cfg, root):
    entries = equivalents.load(os.path.join(root, cfg["mutation"]["equivalents_file"]))
    if base:
        changed = changes.changed_lines(base, root)
        prod = {f: s for f, s in changed.items() if in_scope(f, cfg["sources"], cfg["tests"], cfg["exclude"])}
        if not prod:
            print("PASS：這次沒有改到正式程式碼")
            return _finish_mutation(base, cfg, "pass", [], [], {}, None)
        tools, settings, measured = inspector.run_inspector("mutation", cfg, root, sorted(prod))
        measured = _scope_filter(measured, cfg)
        mutants = [m for m in measured if changes.overlaps(prod.get(m.file), m.line, m.line)]
        scope = set(prod)
        print("只計算和 {} 相比有改到的行\n".format(base))
    else:
        tools, settings, measured = inspector.run_inspector("mutation", cfg, root, None)
        measured = mutants = _scope_filter(measured, cfg)
        scope = None

    unused = classify(measured, mutants, cfg, entries, scope, root)
    counts = mutation.count(mutants)
    report.print_mutation_result(mutants, counts, cfg, settings, unused)

    problems = mutation.judge(counts, cfg)
    print()
    for p in problems:
        print("FAIL：" + p)
    if not problems:
        if counts[KILLED] + counts[TIMED_OUT] + counts[LIVED] + counts[NOT_COVERED] == 0:
            print("PASS：改到的行沒有量到改壞的版本（沒有可以改的地方，或是所在的專案沒有測試，請看上方訊息）")
        else:
            print("PASS")
    return _finish_mutation(base, cfg, "fail" if problems else "pass", mutants, unused, tools, settings)


def classify(measured, mutants, cfg, entries, scope, root):
    """填入行原文，再依序做兩件事：設定排除的改法（EXCLUDED_MUTATOR）、排除清單比對（EQUIVALENT）。

    measured 是量到的全部改壞版本（已篩過範圍），mutants 是其中這次要計算的（用 --base 時只有改到的行）。
    排除清單有沒有用到要看全部量到的，所以兩者都標記，回傳排除清單裡沒用到的項目。
    """
    mutation.fill_line_text(measured, root)
    mutation.exclude_mutators(measured, cfg["mutation"]["exclude_mutators"])
    return equivalents.apply(mutants, entries, measured, scope)


def _finish_mutation(base, cfg, result, mutants, unused, tools, settings):
    counts = mutation.count(mutants)
    rep = report.build_report(
        "mutation", base, result, _inspector_info(cfg, "mutation", tools, settings),
        mutation_part=report.mutation_json(mutants, counts, cfg, unused))
    return (1 if result == "fail" else 0), rep


GATE_RUNNERS = {
    "test": lambda base, cfg, root: run_test(cfg, root),
    "crap": run_crap,
    "mutation": run_mutation,
}


def plan_gates(gates, skip):
    """回傳 (要跑的關, 略過的關, 還沒啟用的關)。順序固定是 test → crap → mutation，跟 gates 裡的排列無關。"""
    bad = [s for s in skip if s not in GATES]
    if bad:
        raise RefereeError("--skip 不認得的關：{}（可用：{}）".format("、".join(bad), "、".join(GATES)))
    ordered = [g for g in GATES if g in gates]
    run = [g for g in ordered if g not in skip]
    return run, [g for g in ordered if g in skip], [g for g in GATES if g not in gates]
