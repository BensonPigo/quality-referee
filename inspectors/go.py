"""Go 標準檢查員。

用法（工作目錄是 go.mod 所在的專案根目錄，由裁判設定 REFEREE_CONTEXT、REFEREE_OUT）：

    python inspectors/go.py functions [--coverage-scope package|module] [--workers N]
    python inspectors/go.py mutants   [--coverage-scope package|module] [--workers N]

functions：gocyclo 算複雜度，go test -coverprofile 算覆蓋率，交出函式表。
mutants：每個套件目錄各跑一次 gremlins unleash，交出改壞版本表。
量測工具用 go install 裝到快取目錄（REFEREE_TOOLS_DIR，預設 ~/.cache/quality-referee），裝過就直接執行。
結束碼 0 是量完了，其他值是量測失敗。
"""

import argparse
import json
import os
import posixpath
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from referee import paths, sheets  # noqa: E402
from referee.errors import RefereeError  # noqa: E402

GOCYCLO = "github.com/fzipp/gocyclo/cmd/gocyclo@v0.6.0"
GREMLINS = "github.com/go-gremlins/gremlins/cmd/gremlins@v0.6.0"

NO_RESULTS = "No results to report."  # gremlins 沒有任何改壞的版本時印這行，不寫結果檔
TIMEOUT_COEFFICIENT = "30"  # 測試很快時，gremlins 估的時限太短，會誤判成 TIMED OUT


class InspectorError(Exception):
    pass


# 下面兩張表照 gremlins v0.6.0 原始碼：
#   internal/mutator/mutator.go 的 Type.String()：報告裡 type 欄位的名稱
#   internal/engine/mappings.go 的 tokenMutations：每種 type 把哪個 token 換成哪個 token
# 報告只給 type 和位置，原本的 token 要回原始檔取，取出來之後查這張表就知道改成什麼。
_ASSIGN_OPS = ["+=", "&=", "&^=", "*=", "|=", "/=", "%=", "<<=", ">>=", "-=", "^="]
GREMLINS_TOKENS = {
    "ARITHMETIC_BASE": {"+": "-", "*": "/", "/": "*", "%": "*", "-": "+"},
    "CONDITIONALS_BOUNDARY": {">=": ">", ">": ">=", "<=": "<", "<": "<="},
    "CONDITIONALS_NEGATION": {"==": "!=", ">=": "<", ">": "<=", "<=": ">", "<": ">=", "!=": "=="},
    "INCREMENT_DECREMENT": {"--": "++", "++": "--"},
    # 原始碼裡 REM_ASSIGN 對到它自己（%= 改成 %=），照抄；這個改壞版本等於沒改
    "INVERT_ASSIGNMENTS": {"+=": "-=", "*=": "/=", "/=": "*=", "%=": "%=", "-=": "+="},
    "INVERT_BITWISE": {"&": "|", "|": "&", "^": "&", "&^": "&", "<<": ">>", ">>": "<<"},
    "INVERT_BWASSIGN": {"&=": "|=", "|=": "&=", "^=": "&=", "&^=": "&=", "<<=": ">>=", ">>=": "<<="},
    "INVERT_LOGICAL": {"&&": "||", "||": "&&"},
    "INVERT_LOOPCTRL": {"break": "continue", "continue": "break"},
    "INVERT_NEGATIVES": {"-": "+"},
    "REMOVE_SELF_ASSIGNMENTS": {op: "=" for op in _ASSIGN_OPS},
}


# ---------- 不執行任何東西的純函式 ----------

def gremlins_describe(mutator, line, column):
    """依 type 和欄位（從 1 起算的位元組位置）從該行取出原本的 token，回傳 (original, replacement)，取不到回傳 (None, None)。"""
    table = GREMLINS_TOKENS.get(mutator)
    if not table or not column:
        return None, None
    rest = line.encode("utf-8")[column - 1:].decode("utf-8", errors="replace")
    for token in sorted(table, key=len, reverse=True):  # 先比長的：>>= 在 >> 和 > 之前
        if rest.startswith(token):
            return token, table[token]
    return None, None


def skip_pattern(name):
    """比對整個檔名的 Go 正規表示式。ASCII 英數和 _ 以外的字元都寫成 \\x{碼位}，不用處理哪些字元要跳脫。

    gremlins 比對的是相對於套件目錄、用 / 分隔的路徑，套件目錄底下的檔案就是檔名本身。
    """
    return "^" + "".join(
        c if (c.isascii() and c.isalnum()) or c == "_" else "\\x{%X}" % ord(c) for c in name) + "$"


def gremlins_args(workers, d, out, subdirs=(), skip_files=(), coverpkg=None):
    """gremlins unleash 的命令列參數。

    subdirs：gremlins 掃一個目錄時會連子目錄一起掃，但子目錄的覆蓋率抓不到，全部算成 NOT COVERED，所以排除。
    skip_files：套件目錄底下不產生改壞版本的檔名（--base 時沒改到的檔案）。
    coverpkg 給了（coverage_scope = module）就用 --integration 加 --coverpkg：覆蓋率和每個改壞的版本都跑整個模組的測試。
    """
    args = ["unleash", "./" + d,
            "--timeout-coefficient", TIMEOUT_COEFFICIENT,
            "--invert-logical",  # 預設關閉的 && ↔ || 互換
            "-o", out]
    if coverpkg:
        args += ["--integration", "--coverpkg", coverpkg]
    if workers is not None:
        args += ["--workers", str(workers)]
    for sub in subdirs:
        args += ["-E", "^" + sub.replace(".", "[.]") + "[^a-zA-Z0-9_.-]"]
    for name in skip_files:
        args += ["-E", skip_pattern(name)]
    return args


def gremlins_env(environ, goflags):
    """執行 gremlins 用的環境變數：GOFLAGS 在目前生效的值後面接 -count=1，不讀測試快取。

    gremlins 先跑一次 go test 量覆蓋率，用花的時間 x --timeout-coefficient 當每個改壞版本的時限。
    那次 go test 讀快取時只花零點幾秒，時限跟著太短，改壞的版本要重新編譯，大量超時，
    其中測試全過的也被算成逾時（算抓到）。不讀快取後，時限依實際跑測試的時間計算。

    goflags 傳 go env GOFLAGS 的結果：環境變數會蓋掉 go env -w 寫進設定檔的 GOFLAGS，只看 environ 會弄丟設定檔的旗標。
    原字串不拆開；GOFLAGS 裡同一個旗標以後面的為準，使用者寫了 -count 也一律改成 1。
    """
    env = dict(environ)
    env["GOFLAGS"] = (goflags.strip() + " -count=1").strip()
    return env


def func_end(lines, start):
    """函式結尾的行號（start 從 1 起算）。程式碼經過 gofmt，頂層函式的結尾一定是單獨一行、從第一欄開始的 }。"""
    first = lines[start - 1].rstrip()
    if first.endswith("}") and first.count("{") == first.count("}"):  # 一行寫完的函式
        return start
    for i in range(start, len(lines)):
        if lines[i].rstrip() == "}":
            return i + 1
    return start


def unchanged_files(d, files, listing):
    """套件目錄 d 底下（不含子目錄）、不是 _test.go 的 .go 檔中，不在 files 裡的檔名，排序後回傳。

    listing 是 d 底下的檔名，files 是改到的檔案，相對專案根目錄、用 / 分隔。
    """
    changed = {paths.normalize(f) for f in files}
    return [n for n in sorted(listing)
            if n.endswith(".go") and not n.endswith("_test.go")
            and (n if d == "." else d + "/" + n) not in changed]


# ---------- 外部指令 ----------

def run(cmd, env=None):
    try:
        return subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise InspectorError("找不到指令 {}，請確認已安裝並加入 PATH".format(cmd[0]))
    except OSError as e:
        raise InspectorError("無法執行 {}：{}。如果它在工具快取目錄底下，刪掉它所在的目錄，下次執行會重新安裝".format(cmd[0], e))


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def tools_dir():
    return os.environ.get("REFEREE_TOOLS_DIR") or os.path.join(os.path.expanduser("~"), ".cache", "quality-referee")


def go_tool(spec):
    """回傳執行 Go 工具（spec 是 套件路徑@版本）的指令。第一次使用時 go install 到工具快取目錄，之後直接執行。

    不用 go run 套件@版本：它每次都向 GOPROXY 查版本資訊，GOPROXY=off 或斷網時失敗。
    目錄名稱帶工具版本和 Go 版本：工具用建置它的 Go 解析原始碼，Go 升級後要重裝，新語法才解析得了。
    先裝到暫存目錄再整個搬過去：Windows 上 go install 直接覆寫目標檔，中途中斷會留下寫一半的執行檔。
    GOBIN 必須是絕對路徑，所以快取目錄先轉成絕對路徑。
    """
    pkg, version = spec.rsplit("@", 1)
    name = pkg.rsplit("/", 1)[1]
    r = run(["go", "env", "GOVERSION"])
    if r.returncode != 0:
        raise InspectorError("go env GOVERSION 執行失敗：\n" + r.stderr)
    root = os.path.abspath(tools_dir())
    path = os.path.join(root, "{}-{}-{}".format(name, version, r.stdout.strip()))
    filename = name + (".exe" if os.name == "nt" else "")
    exe = os.path.join(path, filename)
    if not os.path.exists(exe):
        log("安裝 {} {}（只有第一次）...".format(name, version))
        os.makedirs(root, exist_ok=True)
        tmp = tempfile.mkdtemp(prefix=".{}-".format(name), dir=root)
        try:
            r = run(["go", "install", spec], env=dict(os.environ, GOBIN=tmp))
            if r.returncode != 0:
                raise InspectorError("{} 安裝失敗：\n{}{}".format(name, r.stdout, r.stderr))
            os.makedirs(path, exist_ok=True)
            os.replace(os.path.join(tmp, filename), exe)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return [exe]


def go_module():
    r = run(["go", "list", "-m"])
    if r.returncode != 0:
        raise InspectorError("讀不到模組名稱，請在 go.mod 所在的目錄執行：\n" + r.stderr)
    return r.stdout.strip()


def go_packages(exclude, module):
    """回傳 [(import path, 相對目錄)]，排除 exclude 底下的套件。"""
    r = run(["go", "list", "./..."])
    if r.returncode != 0:
        raise InspectorError("go list 執行失敗：\n" + r.stderr)
    pkgs = []
    for p in r.stdout.split():
        rel = p[len(module) + 1:] if p.startswith(module + "/") else "."
        if rel == "." or not paths.is_excluded(rel + "/", exclude):
            pkgs.append((p, rel))
    return pkgs


def subdirs(d):
    """套件目錄底下的子目錄名稱，gremlins_args 轉成 -E 的樣式。"""
    return [sub for sub in sorted(os.listdir(d)) if os.path.isdir(os.path.join(d, sub))]


_lines = {}


def read_lines(file):
    if file not in _lines:
        try:
            # utf-8-sig：檔案開頭有 BOM 時，第一行的欄位位置才跟 gremlins 回報的對得上
            with open(file, encoding="utf-8-sig", errors="replace") as f:
                _lines[file] = f.read().splitlines()
        except OSError:
            _lines[file] = []
    return _lines[file]


# ---------- functions ----------

def measure_functions(ctx, scope, workers):
    module = go_module()
    pkgs = go_packages(ctx["exclude"], module)
    coverpkg = []
    if scope == "module":
        # 用 import path 清單，不用 ./... 樣式：go list ./... 不會跳過 node_modules 這類目錄
        coverpkg = ["-coverpkg=" + ",".join(p for p, _ in pkgs)]
        log("覆蓋率：整個模組的測試都算（coverage_scope = module）")

    with tempfile.TemporaryDirectory() as tmp:
        profile = os.path.join(tmp, "cover.out")
        r = run(["go", "test", "-coverprofile=" + profile] + coverpkg + [p for p, _ in pkgs])
        sys.stderr.write(r.stdout)
        if r.returncode != 0:
            raise InspectorError("測試沒有全部通過，請先修好第一關（單元測試）再量 CRAP：\n" + r.stderr)
        r = run(["go", "tool", "cover", "-func=" + profile])
        if r.returncode != 0:
            raise InspectorError("go tool cover 執行失敗：\n" + r.stderr)

    # 每行格式：shop/shipping/fee.go:4:	Fee	40.0%，開頭的模組名稱去掉後就是相對路徑
    coverage = {}
    for line in r.stdout.splitlines():
        fields = line.split()
        if len(fields) != 3 or fields[0] == "total:":
            continue
        file, _, lineno = fields[0].rstrip(":").rpartition(":")
        file = file[len(module) + 1:] if file.startswith(module + "/") else file
        coverage[(file, int(lineno))] = float(fields[2].rstrip("%")) / 100

    # 每行格式：14 shop Checkout checkout.go:31:1
    r = run(go_tool(GOCYCLO) + ["."])
    if r.returncode != 0:
        raise InspectorError("gocyclo 執行失敗：\n" + r.stderr)
    funcs = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        file, lineno, _ = parts[-1].rsplit(":", 2)
        file, lineno = paths.normalize(file), int(lineno)
        if not paths.in_scope(file, ctx["sources"], ctx["tests"], ctx["exclude"]):
            continue
        funcs.append({
            "file": file,
            "name": " ".join(parts[2:-1]),
            "start": lineno,
            "end": func_end(read_lines(file), lineno),
            "complexity": int(parts[0]),
            "coverage": coverage.get((file, lineno), 0.0),
        })
    sheet = {"schema": sheets.FUNCTIONS_SCHEMA,
             "tools": {"gocyclo": GOCYCLO.rsplit("@", 1)[1]},
             "settings": {"coverage_scope": scope, "workers": workers},
             "functions": funcs}
    sheets.parse_functions(sheet)
    return sheet


# ---------- mutants ----------

def measure_mutants(ctx, scope, workers):
    module = go_module()
    all_pkgs = go_packages(ctx["exclude"], module)
    pkgs = all_pkgs
    changed = ctx.get("changed_files")
    if changed is not None:
        # 只跑有改到檔案的套件
        wanted = {posixpath.dirname(paths.normalize(f)) or "." for f in changed}
        pkgs = [(p, d) for p, d in all_pkgs if d in wanted]

    coverpkg = None
    if scope == "module":
        # 跟 CRAP 用同一份套件清單（已排除 exclude），--base 時也是全部套件，不只是改到的
        coverpkg = ",".join(p for p, _ in all_pkgs)
        log("抓錯檢查：整個模組的測試都算（coverage_scope = module），每個改壞的版本跑整個模組的測試")

    r = run(["go", "env", "GOFLAGS"])
    if r.returncode != 0:
        raise InspectorError("go env GOFLAGS 執行失敗：\n" + r.stderr)
    goflags = r.stdout
    gremlins = go_tool(GREMLINS)

    mutants = []
    for _, d in pkgs:
        if not os.path.isdir(d):
            continue
        log("抓錯檢查：{} ...".format(d))
        skip = unchanged_files(d, changed, os.listdir(d)) if changed is not None else []
        if skip:
            log("只對改到的檔案產生改壞的版本，略過 {} 個沒改到的檔案".format(len(skip)))
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "gremlins.json")
            r = run(gremlins + gremlins_args(workers, d, out, subdirs(d), skip, coverpkg),
                    env=gremlins_env(os.environ, goflags))
            if os.path.exists(out):
                with open(out, encoding="utf-8") as f:
                    result = json.load(f)
            elif NO_RESULTS in r.stdout + r.stderr:
                # 套件裡沒有可以改壞的地方（只有測試、常數、型別或 doc.go），gremlins 只在成功執行且沒有
                # 改壞的版本時印這行，不寫結果檔
                result = {}
            else:
                raise InspectorError("gremlins 執行失敗（{}）：\n{}{}".format(d, r.stdout, r.stderr))
        leaked = sorted({f["file_name"] for f in result.get("files") or []} & set(skip))
        if leaked:
            raise InspectorError("排除沒改到的檔案沒有生效：" + "、".join(leaked))

        # 檔名是相對於套件目錄的路徑
        for f in result.get("files") or []:
            file = paths.normalize(f["file_name"] if d == "." else d + "/" + f["file_name"])
            for m in f.get("mutations") or []:
                lines = read_lines(file)
                text = lines[m["line"] - 1] if 0 < m["line"] <= len(lines) else ""
                original, replacement = gremlins_describe(m["type"], text, m.get("column"))
                item = {"file": file, "line": m["line"], "mutator": m["type"],
                        "status": m["status"].replace(" ", "_")}
                if m.get("column"):
                    item["column"] = m["column"]
                if original is not None:
                    item["original"], item["replacement"] = original, replacement
                mutants.append(item)

    sheet = {"schema": sheets.MUTANTS_SCHEMA,
             "tools": {"gremlins": GREMLINS.rsplit("@", 1)[1]},
             "settings": {"coverage_scope": scope, "workers": workers},
             "mutants": mutants}
    sheets.parse_mutants(sheet)
    return sheet


def main(argv=None):
    parser = argparse.ArgumentParser(prog="go.py", description="Go 標準檢查員")
    parser.add_argument("mode", choices=["functions", "mutants"])
    parser.add_argument("--coverage-scope", choices=["package", "module"], default="package",
                        help="module：別的套件的測試跑到的程式也算覆蓋率")
    parser.add_argument("--workers", type=int, metavar="N", help="gremlins 同時跑幾個")
    args = parser.parse_args(argv)

    try:
        out = os.environ.get("REFEREE_OUT")
        context = os.environ.get("REFEREE_CONTEXT")
        if not out or not context:
            raise InspectorError("沒有 REFEREE_OUT 或 REFEREE_CONTEXT 環境變數，這支檢查員要由裁判啟動")
        with open(context, encoding="utf-8") as f:
            ctx = json.load(f)
        measure = measure_functions if args.mode == "functions" else measure_mutants
        sheet = measure(ctx, args.coverage_scope, args.workers)
    except (InspectorError, RefereeError) as e:
        print(e, file=sys.stderr)
        return 1
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(sheet, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
