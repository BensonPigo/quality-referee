"""和 quality-tools v2.4.0 的對照。不屬於發布內容，只在開發時用。

同一份專案複本，分別用 quality-tools（唯讀，只執行它的 quality.py）和 quality-referee 的 Go 標準檢查員量一遍，比對：

- 整個專案的 CRAP 表：每一列（CRAP 取一位小數、C、覆蓋率取一位小數、函式名稱、檔案:行），順序也要一樣。
- 整個專案的抓錯計數：抓到+逾時的合計、沒抓到、測試沒跑到。抓到和逾時會因為機器負載互換
  （測試卡住的時限差一點點，結果就從抓到變逾時），所以合計比對。

    python dev/parity_qt.py sample [--scope package module]     # 範例專案，預設兩種範圍各比一次
    python dev/parity_qt.py bethere [--source 路徑] [--only crap|mutation]

bethere：先 git clone 到暫存目錄，不動原 repo。兩個工具都用原 repo 的 .quality.json 設定（coverage_scope、exclude、
門檻）。抓錯計數只比 internal/rundown 這一個套件，做法是兩個工具的 exclude 都另外加入其他所有套件。
抓錯檢查的門檻一律設成 0，只比計數，不比通過與否。

抓錯計數有差異時，自動把兩個工具各重跑一次，仍然不同才算有差異。
所有工作都在暫存目錄裡，quality-tools 和 BeThere 原 repo 只會被讀取。

結束碼：0 一致，1 有差異，2 執行失敗。
"""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import selftest  # noqa: E402

QT = r"C:\Git\Personal\quality-tools"
BETHERE = r"C:\Git\Personal\BeThere"
GO_INSPECTOR = os.path.join(ROOT, "inspectors", "go.py")
REFEREE = os.path.join(ROOT, "referee.py")
TARGET_PKG = "internal/rundown"

CRAP_ROW = re.compile(r"^(\d+\.\d)\s+(\d+)\s+(\d+\.\d)%\s+(.+?)\s+(\S+:\d+)(?:\s+❌.*)?\s*$")


class ParityError(Exception):
    pass


def run(cmd, cwd, check=True):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")  # 不要在 quality-tools 目錄留下 .pyc
    r = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise ParityError("{} 失敗（結束碼 {}）：\n{}".format(" ".join(cmd), r.returncode, (r.stdout + r.stderr)[-3000:]))
    return r


def write_json(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def git_init(proj):
    ident = ["-c", "user.name=parity", "-c", "user.email=parity@example.com", "-c", "core.autocrlf=false"]
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "parity"]):
        run(["git"] + ident + cmd, proj)


# ---------- 設定檔 ----------

def qt_config(exclude, coverage_scope, mutation_thresholds=False):
    return {
        "version": 2, "language": "go", "base": "origin/main", "gates": ["test", "crap", "mutation"],
        "go": {"coverage_scope": coverage_scope},
        "exclude": exclude,
        "crap": {"threshold": 12},
        "mutation": {"kill_rate_threshold": 0, "reach_rate_threshold": 0},
    }


def referee_config(exclude, coverage_scope, threshold=12):
    return {
        "version": 1, "base": "origin/main", "gates": ["test", "crap", "mutation"],
        "sources": ["**/*.go"], "tests": ["**/*_test.go"], "exclude": exclude,
        "test": {"command": ["go", "test", "./..."]},
        "crap": {"threshold": threshold,
                 "inspector": [sys.executable, GO_INSPECTOR, "functions", "--coverage-scope", coverage_scope]},
        "mutation": {"kill_rate_threshold": 0, "reach_rate_threshold": 0,
                     "inspector": [sys.executable, GO_INSPECTOR, "mutants", "--coverage-scope", coverage_scope]},
    }


def write_configs(proj, exclude, coverage_scope):
    write_json(os.path.join(proj, ".quality.json"), qt_config(exclude, coverage_scope))
    write_json(os.path.join(proj, ".referee.json"), referee_config(exclude, coverage_scope))


# ---------- 量測和解析 ----------

def parse_crap_rows(text):
    """表格是從表頭（CRAP 開頭的那行）到第一個空行。每一列都要解析得出來，列數不符就失敗，不默默略過。"""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("CRAP ")), None)
    if start is None:
        return []
    table = []
    for line in lines[start + 1:]:
        if not line.strip():
            break
        table.append(line)
    rows = []
    for line in table:
        m = CRAP_ROW.match(line.strip())
        if m:
            rows.append(m.groups())
    if len(rows) != len(table):
        raise ParityError("CRAP 表有 {} 列，只解析出 {} 列：\n{}".format(len(table), len(rows), "\n".join(table)))
    return rows


def measure_crap(tool, proj):
    cmd = [sys.executable, os.path.join(QT, "quality.py") if tool == "qt" else REFEREE, "crap"]
    r = run(cmd, proj, check=False)
    if r.returncode not in (0, 1):
        raise ParityError("{} crap 失敗（結束碼 {}）：\n{}".format(tool, r.returncode, (r.stdout + r.stderr)[-3000:]))
    rows = parse_crap_rows(r.stdout)
    if not rows:
        raise ParityError("{} crap 的輸出裡找不到 CRAP 表：\n{}".format(tool, r.stdout[-2000:]))
    return rows


def measure_mutation(tool, proj):
    out = os.path.join(proj, "parity-{}-mut.json".format(tool))
    cmd = [sys.executable, os.path.join(QT, "quality.py") if tool == "qt" else REFEREE, "mutation", "--json", out]
    r = run(cmd, proj, check=False)
    if r.returncode not in (0, 1) or not os.path.exists(out):
        raise ParityError("{} mutation 失敗（結束碼 {}）：\n{}".format(tool, r.returncode, (r.stdout + r.stderr)[-3000:]))
    with open(out, encoding="utf-8") as f:
        counts = json.load(f)["mutation"]["counts"]
    return {"抓到+逾時": counts["KILLED"] + counts["TIMED_OUT"], "沒抓到": counts["LIVED"],
            "測試沒跑到": counts["NOT_COVERED"]}


# ---------- 比對 ----------

def compare_crap(label, qt_rows, ref_rows):
    print("  CRAP 表（{} 列）：{}".format(len(qt_rows), "一致" if qt_rows == ref_rows else "有差異"))
    if qt_rows == ref_rows:
        for row in qt_rows:
            print("    {}".format(" | ".join(row)))
        return True
    print("    quality-tools：")
    for row in qt_rows:
        print("      " + " | ".join(row))
    print("    quality-referee：")
    for row in ref_rows:
        print("      " + " | ".join(row))
    return False


def compare_mutation(label, proj):
    qt = measure_mutation("qt", proj)
    ref = measure_mutation("ref", proj)
    if qt != ref:
        print("  抓錯計數有差異，兩個工具各重跑一次：qt {} / referee {}".format(qt, ref), flush=True)
        qt, ref = measure_mutation("qt", proj), measure_mutation("ref", proj)
    ok = qt == ref
    print("  抓錯計數：{}".format("一致" if ok else "有差異"))
    print("    quality-tools   {}".format(qt))
    print("    quality-referee {}".format(ref))
    return ok


def check_project(label, proj, only):
    print("== {}".format(label), flush=True)
    ok = True
    if only in (None, "crap"):
        ok &= compare_crap(label, measure_crap("qt", proj), measure_crap("ref", proj))
    if only in (None, "mutation"):
        ok &= compare_mutation(label, proj)
    return ok


# ---------- 專案 ----------

def run_sample(scopes, only, tmp):
    ok = True
    for scope in scopes:
        proj = os.path.join(tmp, "sample-" + scope)
        selftest.unpack("go", proj)
        os.remove(os.path.join(proj, ".referee.json"))
        write_configs(proj, ["tools/", "vendor/", "node_modules/"], scope)
        git_init(proj)
        ok &= check_project("Go 範例，coverage_scope {}".format(scope), proj, only)
    return ok


def go_package_dirs(proj):
    r = run(["go", "list", "./..."], proj)
    module = run(["go", "list", "-m"], proj).stdout.strip()
    return [p[len(module) + 1:] if p.startswith(module + "/") else "." for p in r.stdout.split()]


def run_bethere(source, only, tmp):
    proj = os.path.join(tmp, "BeThere")
    run(["git", "clone", "-q", source, proj], tmp)
    with open(os.path.join(proj, ".quality.json"), encoding="utf-8") as f:
        original = json.load(f)
    scope = original.get("go", {}).get("coverage_scope", "package")
    exclude = original["exclude"]
    threshold = original["crap"]["threshold"]
    print("BeThere 設定：coverage_scope {}、exclude {}、CRAP 門檻 {}".format(scope, exclude, threshold))

    ok = True
    if only in (None, "crap"):
        write_json(os.path.join(proj, ".quality.json"), dict(qt_config(exclude, scope), crap={"threshold": threshold}))
        write_json(os.path.join(proj, ".referee.json"), referee_config(exclude, scope, threshold))
        ok &= check_project("BeThere 整個專案的 CRAP，coverage_scope {}".format(scope), proj, "crap")
    if only in (None, "mutation"):
        others = [d for d in go_package_dirs(proj) if d != TARGET_PKG and not TARGET_PKG.startswith(d + "/")]
        if "." in others:
            raise ParityError("根目錄有 Go 套件，exclude 排除不了它（兩個工具都一律保留根目錄的套件）")
        narrowed = exclude + [d + "/" for d in others]
        print("抓錯計數只比 {}：exclude 另外加入其他 {} 個套件".format(TARGET_PKG, len(others)))
        write_configs(proj, narrowed, scope)
        ok &= check_project("BeThere {} 的抓錯計數，coverage_scope {}".format(TARGET_PKG, scope), proj, "mutation")
    return ok


def _force_remove(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="和 quality-tools v2.4.0 對照")
    sub = parser.add_subparsers(dest="target", required=True)
    p = sub.add_parser("sample", help="Go 範例專案")
    p.add_argument("--scope", nargs="+", choices=["package", "module"], default=["package", "module"])
    p.add_argument("--only", choices=["crap", "mutation"])
    p = sub.add_parser("bethere", help="BeThere 的暫存複本")
    p.add_argument("--source", default=BETHERE, help="要 clone 的 repo，預設 " + BETHERE)
    p.add_argument("--only", choices=["crap", "mutation"])
    p.add_argument("--keep", action="store_true", help="保留暫存目錄")
    args = parser.parse_args()

    tmp = tempfile.mkdtemp(prefix="parity-")
    try:
        if args.target == "sample":
            ok = run_sample(args.scope, args.only, tmp)
        else:
            ok = run_bethere(args.source, args.only, tmp)
    except ParityError as e:
        print(e, file=sys.stderr)
        return 2
    finally:
        if getattr(args, "keep", False):
            print("暫存目錄：" + tmp)
        else:
            shutil.rmtree(tmp, onerror=_force_remove)
    print("\n{}".format("PASS：和 quality-tools 完全一致" if ok else "FAIL：有差異"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
