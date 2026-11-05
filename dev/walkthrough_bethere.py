"""照 README 的步驟，在 BeThere 的暫存複本上把 quality-referee 掛起來走一遍。不屬於發布內容，只在開發時用。

    python dev/walkthrough_bethere.py [--source 路徑] [--keep]

流程：
  1. git clone BeThere 到暫存目錄（原 repo 只被讀取）
  2. git submodule add 本 repo 到 tools/referee。submodule 抓的是本 repo 已 commit 的 HEAD，
     所以工作目錄有沒 commit 的修改時，走一遍量到的不是修改後的版本：預設直接停下，--allow-dirty 才繼續
  3. 照 README 複製 templates/go/，.referee.json 換成 BeThere 的範圍（module 範圍、exclude 照 .quality.json）
  4. 照 README 的提醒，只在複本裡把 tools/referee/ 加進 internal/docscheck 的豁免清單，印出改了哪一行
  (a) check --base origin/main --skip mutation：預期結束碼 0，第一、二關通過，mutation 略過，沒有「停在第」
  (b) (a) 通過才做：改壞一個指定的測試，跑 gate.sh，預期結束碼 2、訊息有「第一關沒過」
  (c) BeThere 原 repo 的 HEAD 和 git status 跟開始前一樣
  最後刪掉暫存目錄。每一步印出結束碼和關鍵輸出行。

結束碼：0 全部符合預期，1 有一步不符，2 執行失敗。第 (a) 步沒過就停下，不做 (b)。
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
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import selftest  # noqa: E402

BETHERE = r"C:\Git\Personal\BeThere"
TARGET_TEST = "TestParseTheAcceptanceFormat"
TARGET_FILE = "internal/rundown/rundown_test.go"
DOCSCHECK = "internal/docscheck/docscheck_test.go"
TIMEOUT = 3600


class Stop(Exception):
    pass


def run(cmd, cwd, env=None, timeout=TIMEOUT):
    e = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    e.update(env or {})
    r = subprocess.run(cmd, cwd=cwd, env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       encoding="utf-8", errors="replace", timeout=timeout)
    r.stdout = r.stdout.replace("\r\n", "\n")
    r.stderr = r.stderr.replace("\r\n", "\n")
    return r


def git(cwd, *args, check=True):
    r = run(["git", "-c", "core.autocrlf=false", "-c", "protocol.file.allow=always"] + list(args), cwd)
    if check and r.returncode != 0:
        raise Stop("git {} 失敗（結束碼 {}）：\n{}".format(" ".join(args), r.returncode, (r.stdout + r.stderr)[-2000:]))
    return r


def tail(text, n=15):
    lines = text.strip().splitlines()
    return "\n".join("      " + line for line in lines[-n:])


def step(title, r):
    print("\n[{}] 結束碼 {}".format(title, r.returncode), flush=True)


def snapshot(repo):
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    return head, git(repo, "--no-optional-locks", "status", "--porcelain=v1").stdout


def force_remove(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def write_referee_config(proj):
    """範本的 .referee.json 換成 BeThere 的範圍：module 範圍，exclude 照 BeThere 的 .quality.json。"""
    with open(os.path.join(proj, ".quality.json"), encoding="utf-8") as f:
        quality = json.load(f)
    path = os.path.join(proj, ".referee.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["base"] = quality["base"]
    cfg["exclude"] = quality["exclude"]
    cfg["crap"]["threshold"] = quality["crap"]["threshold"]
    cfg["crap"]["inspector"] += ["--coverage-scope", "module"]
    cfg["mutation"]["inspector"] += ["--coverage-scope", "module"]
    cfg["mutation"]["kill_rate_threshold"] = quality["mutation"]["kill_rate_threshold"]
    cfg["mutation"]["reach_rate_threshold"] = quality["mutation"]["reach_rate_threshold"]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("  .referee.json：base {}、exclude {}、coverage-scope module、CRAP 門檻 {}".format(
        cfg["base"], cfg["exclude"], cfg["crap"]["threshold"]))


def copy_templates(proj):
    """README 的複製步驟，來源是剛掛上去的 tools/referee/templates/go/。"""
    tpl = os.path.join(proj, "tools", "referee", "templates", "go")
    for rel, dest in ((".referee.json", ".referee.json"), (".referee-equivalents.json", ".referee-equivalents.json"),
                      (".claude/settings.json", ".claude/settings.json"),
                      (".claude/hooks/gate.sh", ".claude/hooks/gate.sh"),
                      ("workflows/go.yml", ".github/workflows/referee.yml")):
        target = os.path.join(proj, dest)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy(os.path.join(tpl, rel), target)
        print("  複製 templates/go/{} -> {}".format(rel, dest))


def add_docscheck_exemption(proj):
    """README：專案裡有掃整個 repo 的檢查時，把 tools/referee/ 加進豁免。只改複本，印出改的那一行。"""
    path = os.path.join(proj, DOCSCHECK)
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    anchor = '\t"tools/quality/",'
    if text.count(anchor) != 1:
        raise Stop("{} 裡找不到唯一的 {!r}，豁免清單的格式變了".format(DOCSCHECK, anchor))
    nl = "\r\n" if "\r\n" in text else "\n"  # 沿用檔案原本的換行
    added = '\t"tools/referee/",'
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace(anchor, anchor + nl + added))
    line_no = text[:text.index(anchor)].count("\n") + 2
    print("  {} 第 {} 行新增：{}".format(DOCSCHECK, line_no, added.strip()))


def break_test(proj):
    """在 TARGET_TEST 的第一行插入 t.Fatal，讓它一定失敗。回傳插入的行號。"""
    path = os.path.join(proj, TARGET_FILE)
    with open(path, encoding="utf-8", newline="") as f:
        lines = f.read().split("\n")
    header = "func {}(t *testing.T) {{".format(TARGET_TEST)
    idx = next((i for i, line in enumerate(lines) if line.rstrip("\r") == header), None)
    if idx is None:
        raise Stop("{} 裡找不到 {}".format(TARGET_FILE, header))
    lines.insert(idx + 1, '\tt.Fatal("walkthrough: deliberately broken")')
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines))
    return idx + 2


def walk(source, tmp, allow_dirty):
    before = snapshot(source)
    print("BeThere 原 repo：HEAD {}，git status {}".format(before[0][:7], "乾淨" if not before[1] else "有未提交的修改"))
    dirty = git(ROOT, "status", "--porcelain=v1").stdout
    head = git(ROOT, "rev-parse", "--short", "HEAD").stdout.strip()
    print("quality-referee：HEAD {}（submodule 抓的就是這個 commit）".format(head))
    if dirty and not allow_dirty:
        raise Stop("quality-referee 有沒 commit 的修改，submodule 抓不到：\n{}\n先 commit，或加 --allow-dirty".format(dirty))

    ok = True
    proj = os.path.join(tmp, "BeThere")
    r = git(tmp, "clone", "-q", source, proj)
    step("clone BeThere", r)
    r = git(proj, "submodule", "add", "C:/Git/Personal/quality-referee", "tools/referee")
    step("git submodule add ... tools/referee", r)
    print(tail(r.stdout + r.stderr, 5))
    print("  tools/referee 的 HEAD：" + git(os.path.join(proj, "tools", "referee"), "rev-parse", "--short", "HEAD").stdout.strip())

    print("\n[複製範本]")
    copy_templates(proj)
    write_referee_config(proj)
    print("\n[docscheck 豁免]")
    add_docscheck_exemption(proj)
    print(tail(git(proj, "diff", "--", DOCSCHECK).stdout, 12))

    # (a)
    gate_cmd = [sys.executable, os.path.join("tools", "referee", "referee.py"), "check", "--base", "origin/main",
                "--skip", "mutation"]
    r = run(gate_cmd, proj)
    out = r.stdout + r.stderr
    step("(a) python tools/referee/referee.py check --base origin/main --skip mutation", r)
    print(tail(out, 25))
    expected = ["== 第 1 關：test ==", "== 第 2 關：crap ==", "PASS：這次沒有改到任何函式",
                "== 第 3 關：mutation（略過）==", "已啟用的 2 關都通過"]
    problems = []
    if r.returncode != 0:
        problems.append("結束碼 {}（預期 0）".format(r.returncode))
    problems += ["輸出缺少：" + e for e in expected if e not in out]
    if "停在第" in out:
        problems.append("輸出出現「停在第」")
    print("  (a) {}".format("符合預期" if not problems else "不符：" + "；".join(problems)))
    if problems:
        print("\n(a) 沒過，走一遍失敗，不做 (b)")
        return False, before

    # (b)
    line_no = break_test(proj)
    print("\n[(b) 改壞測試] {} 的 {}（在第 {} 行插入 t.Fatal）".format(TARGET_FILE, TARGET_TEST, line_no))
    r = selftest.run_shell(proj, ["{bash}", "{gate_sh}"], {})
    out = r.stdout + r.stderr
    step("(b) bash .claude/hooks/gate.sh", r)
    print(tail(out, 20))
    problems = []
    if r.returncode != 2:
        problems.append("結束碼 {}（預期 2）".format(r.returncode))
    if "第一關沒過" not in out:
        problems.append("輸出缺少：第一關沒過")
    print("  (b) {}".format("符合預期" if not problems else "不符：" + "；".join(problems)))
    ok = ok and not problems
    return ok, before


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="照 README 在 BeThere 的暫存複本上走一遍")
    parser.add_argument("--source", default=BETHERE, help="要 clone 的 repo，預設 " + BETHERE)
    parser.add_argument("--keep", action="store_true", help="保留暫存目錄")
    parser.add_argument("--allow-dirty", action="store_true", help="quality-referee 有沒 commit 的修改也繼續")
    args = parser.parse_args()

    tmp = tempfile.mkdtemp(prefix="walkthrough-")
    before = None
    ok = False
    try:
        ok, before = walk(args.source, tmp, args.allow_dirty)
    except Stop as e:
        print(e, file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired as e:
        print("逾時：{}".format(e.cmd), file=sys.stderr)
        return 2
    finally:
        if args.keep:
            print("暫存目錄：" + tmp)
        else:
            shutil.rmtree(tmp, onerror=force_remove)
        # (c)
        after = snapshot(args.source)
        if before is None:
            before = after
        same = after == before
        print("\n(c) BeThere 原 repo：HEAD {}，git status {}，{}".format(
            after[0][:7], "乾淨" if not after[1] else "有未提交的修改", "跟開始前一樣" if same else "跟開始前不同"))
        ok = ok and same
    print("\n{}".format("PASS：走一遍符合預期" if ok else "FAIL：有一步不符"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
