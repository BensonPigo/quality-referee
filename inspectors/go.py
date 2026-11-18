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
import re
import shutil
import subprocess
import sys
import tempfile
import time

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


def parse_profile(text, module):
    """go test -coverprofile 的內容 → {相對路徑: [(起行, 起欄, 迄行, 迄欄, 次數)]}。

    -coverpkg 時同一個區塊會出現好幾次（每個測試套件一次），合併成一個，次數取最大值（有一次跑到就算跑到）。
    """
    merged = {}
    for line in text.splitlines()[1:]:
        try:
            name, rest = line.rsplit(":", 1)
            span, _, count = rest.split()
            start, end = span.split(",")
            sl, sc = (int(x) for x in start.split("."))
            el, ec = (int(x) for x in end.split("."))
            count = int(count)
        except ValueError:
            continue
        file = name[len(module) + 1:] if name.startswith(module + "/") else name
        key = (file, sl, sc, el, ec)
        merged[key] = max(merged.get(key, 0), count)
    profile = {}
    for (file, sl, sc, el, ec), count in merged.items():
        profile.setdefault(file, []).append((sl, sc, el, ec, count))
    return profile


def _contains(block, line, column):
    """區塊的範圍照 gremlins v0.6.0 internal/coverage/profile.go 判斷。"""
    sl, sc, el, ec, _ = block
    if sl < line < el:
        return True
    if sl == el == line:
        return sc <= column <= ec
    return sl < el and ((line == sl and column >= sc) or (line == el and column <= ec))


def in_block(blocks, line, column):
    """位置是否落在任何一個覆蓋率區塊裡（不管次數）。"""
    return any(_contains(b, line, column) for b in blocks)


def _indent(text):
    return len(text) - len(text.lstrip("\t"))


def switch_header(lines, line):
    """第 line 行的 case 條件所屬 switch 的 (行, 欄)，找不到回傳 None。

    程式碼經過 gofmt：case 跟 switch 同一層縮排。分成好幾行的 case 清單，前一行一定以逗號結尾。
    往上找 switch 時碰到比 case 淺的縮排、或同一層不是 case／default／switch 的行，就是走出了這個 switch，放棄。
    """
    i = line
    while not lines[i - 1].lstrip("\t").startswith("case "):  # 多行 case 清單：往上找到 case 那一行
        i -= 1
        if i == 0 or not lines[i - 1].rstrip().endswith(","):
            return None
    level = _indent(lines[i - 1])
    for j in range(i - 1, 0, -1):
        text = lines[j - 1]
        if not text.strip() or _indent(text) > level:
            continue
        word = text.strip()
        if _indent(text) == level and (word.startswith("//") or re.fullmatch(r"\w+:", word)):
            continue  # 同一層的註解，或 case 主體裡的 label（gofmt 把 label 往外縮一層）
        if _indent(text) < level or not word.startswith(("case ", "default:", "switch")):
            return None
        if word.startswith("switch"):
            return j, level + 1
    return None


def gap_candidates(items, profile):
    """gremlins 判成 NOT_COVERED、但其實是 Go 覆蓋率不記錄的位置、而且有被執行到的改壞版本。

    go test -coverprofile 的區塊不包含 switch 的 case 條件（區塊從冒號後面開始），gremlins 用區塊判斷有沒有跑到，
    所以 case 條件上的改壞版本一律被判成 NOT_COVERED，不跑測試。switch 這個敘述本身在它前面的區塊裡，
    那個區塊有跑到，case 條件才算被執行到。在次數 0 的區塊裡的才是真的沒跑到，不在候選裡。
    取不到原本 token 的（original 是 None）沒辦法自己改壞，也不在候選裡。
    """
    out = []
    for m in items:
        if m["status"] != "NOT_COVERED" or not m.get("column") or m.get("original") is None:
            continue
        blocks = profile.get(m["file"])
        lines = read_lines(m["file"])
        if not blocks or not 0 < m["line"] <= len(lines) or in_block(blocks, m["line"], m["column"]):
            continue
        header = switch_header(lines, m["line"])
        if header and any(b[4] > 0 and _contains(b, *header) for b in blocks):
            out.append(m)
    return out


def mutate_source(data, line, column, original, replacement):
    """把原始檔（bytes）第 line 行、第 column 個位元組起的 original 換成 replacement。位置上不是 original 時回傳 None。

    欄位不含檔案開頭的 BOM（跟 read_lines 用 utf-8-sig 讀、gremlins 回報的一致）。
    """
    lines = data.split(b"\n")
    if not 0 < line <= len(lines):
        return None
    text = lines[line - 1]
    offset = column - 1 + (3 if line == 1 and text.startswith(b"\xef\xbb\xbf") else 0)
    old, new = original.encode("utf-8"), replacement.encode("utf-8")
    if text[offset:offset + len(old)] != old:
        return None
    lines[line - 1] = text[:offset] + new + text[offset + len(old):]
    return b"\n".join(lines)


def go_test_status(returncode, output=""):
    """go test 的結束碼 → 狀態，照 gremlins v0.6.0 internal/engine/executor.go 的 getTestFailedStatus。

    只有一處不同：編譯不過或 go vet 擋下時，go test 的結束碼也是 1，gremlins 算成 KILLED，這裡看輸出的 [build failed]
    算成 NOT_VIABLE（測試根本沒跑）。補跑的對象是 case 條件，改壞後跟別的 case 常數重複而編譯不過的情況特別多，算抓到會灌高抓錯率。
    """
    if returncode == 1 and "[build failed]" in output:
        return "NOT_VIABLE"
    return {0: "LIVED", 1: "KILLED", 2: "NOT_VIABLE"}.get(returncode, "LIVED")


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


def ignored_files(d):
    """套件目錄 d 底下、因為 build constraint 在這個平台不編譯的 .go 檔名。

    gremlins 照樣會對這些檔案產生改壞的版本，但測試一定跑不到，全部算成 NOT COVERED，補測試也沒有用，所以不產生。
    """
    r = run(["go", "list", "-f", "{{range .IgnoredGoFiles}}{{.}}\n{{end}}", "./" + d])
    if r.returncode != 0:
        raise InspectorError("go list 執行失敗（{}）：\n{}".format(d, r.stderr))
    return r.stdout.split()


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
             # 量 CRAP 不跑 gremlins，--workers 不生效，不寫進 settings
             "settings": {"coverage_scope": scope},
             "functions": funcs}
    sheets.parse_functions(sheet)
    return sheet


# ---------- mutants ----------

def recheck_gaps(items, pkgs, coverpkg, goflags):
    """gap_candidates 挑出的改壞版本自己補跑測試，就地改掉 status，回傳補跑了幾個。

    跟 gremlins 跑法一致：覆蓋率和測試的範圍相同（coverpkg 給了就是整個模組的 ./...，否則是改壞版本所在的套件），
    GOFLAGS 加 -count=1，結束碼的對應照 go_test_status。時限是量覆蓋率那次花的時間（至少 1 秒）x TIMEOUT_COEFFICIENT；
    package 範圍時所有套件一起量，所以時限不會比 gremlins 每個套件各自量的短，只會少判逾時（算抓到）。
    改壞的檔案用 go test -overlay 換進去，不動工作目錄裡的原始碼。
    一次只跑一個：gremlins 每個 worker 在自己複製的目錄裡跑，這裡是在專案目錄裡跑，同時跑的話，
    寫同一個檔案的測試會互相干擾而失敗，被算成抓到。
    沒有任何 NOT_COVERED 時不量覆蓋率，什麼都不跑。
    """
    if not any(m["status"] == "NOT_COVERED" for m in items):
        return 0
    env = gremlins_env(os.environ, goflags)
    module = go_module()
    by_dir = dict((d, p) for p, d in pkgs)
    counts = {}
    with tempfile.TemporaryDirectory() as tmp:
        profile_path = os.path.join(tmp, "cover.out")
        cmd = ["go", "test", "-coverprofile=" + profile_path]
        cmd += ["-coverpkg=" + coverpkg, "./..."] if coverpkg else [p for p, _ in pkgs]
        started = time.monotonic()
        r = run(cmd, env=env)
        limit = max(time.monotonic() - started, 1.0) * float(TIMEOUT_COEFFICIENT)
        if r.returncode != 0:
            raise InspectorError("補跑 case 條件前量覆蓋率失敗：\n{}{}".format(r.stdout, r.stderr))
        with open(profile_path, encoding="utf-8") as f:
            profile = parse_profile(f.read(), module)
        todo = gap_candidates(items, profile)
        if not todo:
            return 0
        if any(f.strip("\x27\"").lstrip("-").startswith("overlay") for f in goflags.split()):
            # 命令列的 -overlay 會蓋掉 GOFLAGS 裡的，使用者的 overlay 被丟掉後編譯不過，全部會被算成抓到
            raise InspectorError("GOFLAGS 裡有 -overlay，跟補跑 switch case 條件用的 -overlay 衝突，"
                                 "請拿掉 GOFLAGS 的 -overlay 再跑（go env GOFLAGS 查看）")
        log("gremlins 把 {} 個 switch case 條件上的改壞版本判成測試沒跑到（Go 的覆蓋率不記錄那個位置），"
            "這些 switch 有被執行，自己補跑測試 ...".format(len(todo)))
        src = os.path.join(tmp, "mutated.go")
        overlay = os.path.join(tmp, "overlay.json")
        # 用相對路徑：go 以 $PWD 解析，從 symlink 的路徑進專案時，abspath 拿到的真實路徑對不上，overlay 會靜默失效
        for m in todo:
            target = "./..." if coverpkg else by_dir.get(posixpath.dirname(m["file"]) or ".")
            try:
                with open(m["file"], "rb") as f:
                    mutated = mutate_source(f.read(), m["line"], m["column"], m["original"], m["replacement"])
                if mutated is None or target is None:
                    log("{}:{}:{} 沒辦法補跑（位置上不是 {}，或找不到所在的套件），維持測試沒跑到".format(
                        m["file"], m["line"], m["column"], m["original"]))
                    continue
                with open(src, "wb") as f:
                    f.write(mutated)
                with open(overlay, "w", encoding="utf-8") as f:
                    json.dump({"Replace": {m["file"]: src}}, f)
                args = ["go", "test", "-overlay=" + overlay, "-timeout", "{}s".format(int(limit) + 2), "-failfast", target]
                try:
                    r = subprocess.run(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       encoding="utf-8", errors="replace", timeout=limit)
                    status = go_test_status(r.returncode, r.stdout)
                except subprocess.TimeoutExpired:
                    status = "TIMED_OUT"
            except OSError as e:
                raise InspectorError("補跑 {}:{} 失敗：{}".format(m["file"], m["line"], e))
            m["status"] = status
            counts[status] = counts.get(status, 0) + 1
    log("補跑結果：" + ("、".join("{} {}".format(k, v) for k, v in sorted(counts.items())) or "沒有"))
    return len(todo)


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
        ignored = ignored_files(d)
        if ignored:
            log("略過 {} 個在這個平台不編譯的檔案：{}".format(len(ignored), "、".join(ignored)))
            skip = sorted(set(skip) | set(ignored))
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

    recheck_gaps(mutants, pkgs, coverpkg, goflags)

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
