"""回歸測試：用範例專案跑一遍 referee.py，比對結束碼和輸出。

    python selftest.py go                    # 跑 go 範例的全部情境
    python selftest.py go --only 排除        # 只跑名稱含「排除」的情境（初始檢查也會跑）
    python selftest.py go --list             # 列出情境名稱
    python selftest.py --update go           # 確認新的 CRAP 表格是對的之後，用它更新快照
    python selftest.py --unpack go 暫存目錄/go    # 解開範例，用來修改
    python selftest.py --pack 暫存目錄/go go      # 改完存回

範例專案打包成 selftest/<範例>.sample.txt，情境寫在 selftest/<範例>.json。每個範例的流程：
1. 解開到暫存目錄、git init 並 commit 到 main
2. test 要通過；crap（整個專案）的表格要跟 selftest/<範例>.crap.txt 一致
3. 依序執行 scenarios：每個情境先把整個 repo 還原成初始 commit，再照 commit_edits（改完 commit 到 main）、
   edits（改完不 commit）改檔案，執行 steps 或單一步驟

步驟 {run, exit, contains, not_contains, in_order, equals, json, json_values, shell, env}：
run 是 referee.py 的參數；shell 是直接執行的指令（不經過殼層）；exit 可以是數字或可接受的數字串列；
json 是該步 --json 寫出的檔名（可以是串列），讀檔後用 referee.schema.validate 驗證格式；
json_values 是 {"欄位.路徑": 預期值}，路徑用 . 分隔，陣列裡數字是索引，欄位=值 是找第一個符合的元素。
設定檔和 edits 的字串裡 {python}、{go_inspector} 換成直譯器和 Go 檢查員的路徑。
範例專案需要的語言工具（Go）要先裝好。
"""

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from referee import schema  # noqa: E402

CASES = os.path.join(HERE, "selftest")
REFEREE = os.path.join(HERE, "referee.py")
GO_INSPECTOR = os.path.join(HERE, "inspectors", "go.py")
FILE_MARK = "--- file: "
PACK_SKIP = {".git", "__pycache__", "bin", "obj", "coverage", "reports"}
GIT_ID = ["-c", "user.name=selftest", "-c", "user.email=selftest@example.com", "-c", "core.autocrlf=false"]


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="用範例專案測試 referee 和標準檢查員")
    parser.add_argument("samples", nargs="*", help="要跑的範例，預設全部")
    parser.add_argument("--update", action="store_true", help="把 crap 表格寫回快照，不比對")
    parser.add_argument("--keep", action="store_true", help="保留暫存目錄，方便查問題")
    parser.add_argument("--only", metavar="文字", help="只跑名稱含這段文字的情境")
    parser.add_argument("--list", action="store_true", help="列出情境名稱")
    parser.add_argument("--unpack", nargs=2, metavar=("範例", "目錄"))
    parser.add_argument("--pack", nargs=2, metavar=("目錄", "範例"))
    args = parser.parse_args()

    if args.unpack:
        unpack(args.unpack[0], args.unpack[1])
        return
    if args.pack:
        pack(args.pack[0], args.pack[1])
        return

    names = args.samples or sorted(f[:-len(".json")] for f in os.listdir(CASES) if f.endswith(".json"))
    if args.list:
        for name in names:
            for sc in load_case(name)["scenarios"]:
                print(sc["name"])
        return
    failed = []
    for name in names:
        print("=== {}".format(name), flush=True)
        failed += ["{}：{}".format(name, c) for c in run_sample(name, args)]
    print()
    if failed:
        print("FAIL：{} 項沒過".format(len(failed)))
        for f in failed:
            print("  " + f)
        sys.exit(1)
    print("PASS：{} 個範例全部通過".format(len(names)))


def load_case(name):
    with open(os.path.join(CASES, name + ".json"), encoding="utf-8") as fp:
        return json.load(fp)


def subst(text):
    """{python}、{go_inspector} 換成路徑。字串會放進 JSON，所以反斜線要跳脫。"""
    esc = lambda s: json.dumps(s)[1:-1]  # noqa: E731
    return text.replace("{python}", esc(sys.executable)).replace("{go_inspector}", esc(GO_INSPECTOR))


def run_sample(name, args):
    case = load_case(name)
    tmp = tempfile.mkdtemp(prefix="rs-")
    proj = os.path.join(tmp, name)
    failed = []
    try:
        unpack(name, proj)
        cfg = os.path.join(proj, ".referee.json")
        with open(cfg, encoding="utf-8") as fp:
            text = fp.read()
        with open(cfg, "w", encoding="utf-8", newline="") as fp:
            fp.write(subst(text))
        for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "init"]):
            run(["git"] + GIT_ID + cmd, proj, check=True)

        failed += check("test", proj, ["test"], 0)

        r = referee(proj, ["crap"])
        table = crap_table(r.stdout)
        snapshot = os.path.join(CASES, name + ".crap.txt")
        if args.update:
            with open(snapshot, "w", encoding="utf-8", newline="\n") as fp:
                fp.write(table)
            print("  已更新 " + os.path.relpath(snapshot, HERE))
        else:
            with open(snapshot, encoding="utf-8") as fp:
                expected = fp.read()
            failed += report("crap 整個專案，表格要跟快照一致", r, table == expected, "預期：\n" + expected)

        init_commit = run(["git", "rev-parse", "HEAD"], proj, check=True).stdout.strip()
        for sc in case["scenarios"]:
            if args.only and args.only not in sc["name"]:
                continue
            run(["git", "reset", "-q", "--hard", init_commit], proj, check=True)
            run(["git", "clean", "-fdq"], proj, check=True)
            problem = apply_edits(proj, sc.get("commit_edits", []))
            if problem is None and sc.get("commit_edits"):
                run(["git"] + GIT_ID + ["add", "-A"], proj, check=True)
                run(["git"] + GIT_ID + ["commit", "-q", "-m", "selftest"], proj, check=True)
            problem = problem or apply_edits(proj, sc.get("edits", []))
            if problem:
                failed.append("{}：{}".format(sc["name"], problem))
                continue
            steps = sc.get("steps") or [sc]
            for i, step in enumerate(steps, 1):
                title = sc["name"] if len(steps) == 1 else "{}（步驟 {}）".format(sc["name"], i)
                failed += check(title, proj, step.get("run"), step["exit"], step.get("contains", []),
                                step.get("not_contains", []), step.get("json"), step.get("json_values"),
                                step.get("shell"), step.get("env"), step.get("in_order", []), step.get("equals"))
    finally:
        if args.keep:
            print("  暫存目錄：" + proj)
        else:
            shutil.rmtree(tmp, onerror=_force_remove)
    return failed


def apply_edits(proj, edits):
    """照 edits 改檔案：delete 是刪檔，old 是取代唯一的一處，否則 content 是整份內容（新增或換掉）。成功回傳 None。"""
    for e in edits:
        path = os.path.join(proj, e["file"])
        if e.get("delete"):
            os.remove(path)
            continue
        if "old" in e:
            with open(path, encoding="utf-8", newline="") as fp:
                text = fp.read()
            old = subst(e["old"]) if e["file"] == ".referee.json" else e["old"]
            new = subst(e["new"]) if e["file"] == ".referee.json" else e["new"]
            if text.count(old) != 1:
                return "{} 裡找不到唯一的 {!r}".format(e["file"], old)
            text = text.replace(old, new)
        else:
            text = subst(e["content"]) if e["file"] == ".referee.json" else e["content"]
            os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fp:
            fp.write(text)
    return None


def unpack(name, dest):
    """把 selftest/<name>.sample.txt 解開到 dest。"""
    with open(os.path.join(CASES, name + ".sample.txt"), encoding="utf-8") as fp:
        lines = fp.read().split("\n")
    files, current = {}, None
    for line in lines[1:]:  # 第一行是說明
        if line.startswith(FILE_MARK):
            current = line[len(FILE_MARK):]
            files[current] = []
        elif current is not None:
            files[current].append(line)
    for path, content in files.items():
        if content and content[-1] == "":  # 檔案之間的分隔空行
            content.pop()
        target = os.path.join(dest, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as fp:
            fp.write("\n".join(content) + "\n" if content else "")


def pack(src, name):
    """把 src 目錄打包成 selftest/<name>.sample.txt。檔案一律用 LF 換行、以換行結尾。"""
    out = ["# 範例專案 {}。不要直接編輯，用 python selftest.py --unpack {} <目錄> 解開，改完用 --pack 存回".format(name, name)]
    for root, dirs, names in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in PACK_SKIP)
        for n in sorted(names):
            path = os.path.join(root, n)
            with open(path, encoding="utf-8", newline="") as fp:
                text = fp.read().replace("\r\n", "\n")
            if any(line.startswith(FILE_MARK) for line in text.split("\n")):
                sys.exit("{} 裡有以 {!r} 開頭的行，沒辦法打包".format(path, FILE_MARK))
            if text and not text.endswith("\n"):
                text += "\n"
            out.append(FILE_MARK + os.path.relpath(path, src).replace("\\", "/"))
            out.append(text)
    with open(os.path.join(CASES, name + ".sample.txt"), "w", encoding="utf-8", newline="\n") as fp:
        fp.write("\n".join(out))
    print("已存回 selftest/{}.sample.txt".format(name))


def crap_table(stdout):
    """crap 輸出裡的表格：從表頭到第一個空行。前面是檢查員印的測試輸出，含執行時間，每次都不一樣。"""
    lines = stdout.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.startswith("CRAP ")), len(lines))
    end = next((i for i in range(start, len(lines)) if not lines[i].strip()), len(lines))
    return "".join(lines[start:end])


def check(title, proj, cmd, code, contains=(), not_contains=(), json_file=None, json_values=None, shell=None,
          env=None, in_order=(), equals=None):
    r = run_shell(proj, shell, env or {}) if shell is not None else referee(proj, cmd)
    output = r.stdout + r.stderr
    problems = []
    codes = code if isinstance(code, list) else [code]
    if r.returncode not in codes:
        problems.append("結束碼 {}（預期 {}）".format(r.returncode, " 或 ".join(map(str, codes))))
    missing = [c for c in contains if c not in output]
    if missing:
        problems.append("輸出缺少：" + "、".join(missing))
    unexpected = [c for c in not_contains if c in output]
    if unexpected:
        problems.append("輸出不該出現：" + "、".join(unexpected))
    if equals is not None and output.strip() != equals:
        problems.append("輸出是 {!r}（預期 {!r}）".format(output.strip(), equals))
    pos = 0
    for c in in_order:
        found = output.find(c, pos)
        if found < 0:
            problems.append("輸出沒有依序出現：" + "、".join(in_order))
            break
        pos = found + len(c)
    for name in [json_file] if isinstance(json_file, str) else json_file or ():
        problems += json_problems(os.path.join(proj, name), name, json_values or {})
    return report(title, r, not problems, "；".join(problems))


def json_problems(path, name, values):
    if not os.path.exists(path):
        return ["沒有寫出 " + name]
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    problems = ["{} 格式不符：{}".format(name, e) for e in schema.validate(data)]
    for dotted, expected in values.items():
        actual = data
        for key in dotted.split("."):
            actual = step_into(actual, key)
        if actual != expected:
            problems.append("{} 的 {} 是 {!r}（預期 {!r}）".format(name, dotted, actual, expected))
    return problems


def step_into(value, key):
    """路徑的一步：物件取欄位；陣列用數字取索引，或用 欄位=值 找第一個符合的元素。找不到回傳 None。"""
    if isinstance(value, dict):
        return value.get(key)
    if isinstance(value, list):
        if key.isdigit():
            return value[int(key)] if int(key) < len(value) else None
        field, _, wanted = key.partition("=")
        return next((x for x in value if isinstance(x, dict) and str(x.get(field)) == wanted), None)
    return None


def report(title, r, ok, detail):
    print("  {} {}".format("OK  " if ok else "FAIL", title), flush=True)
    if ok:
        return []
    print("     " + detail.replace("\n", "\n     "))
    print("     實際輸出：\n     " + (r.stdout + r.stderr)[-3000:].replace("\n", "\n     "))
    return [title]


def run_shell(proj, cmd, extra_env):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    env.update(extra_env)
    r = subprocess.run(cmd, cwd=proj, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       encoding="utf-8", errors="replace")
    r.stdout = r.stdout.replace("\r\n", "\n")
    r.stderr = r.stderr.replace("\r\n", "\n")
    return r


def referee(proj, cmd):
    return run([sys.executable, REFEREE] + cmd, proj)


def run(cmd, cwd, check=False):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError("{} 失敗：\n{}".format(" ".join(cmd), r.stdout + r.stderr))
    r.stdout = r.stdout.replace("\r\n", "\n")
    return r


def _force_remove(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)


if __name__ == "__main__":
    main()
