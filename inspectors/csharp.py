"""C# 標準檢查員（.NET 6 以上、SDK 風格的專案）。

用法（工作目錄是專案根目錄，由裁判設定 REFEREE_CONTEXT、REFEREE_OUT）：

    python inspectors/csharp.py functions [--target 方案或專案檔]
    python inspectors/csharp.py mutants   [--target 方案或專案檔] [--workers N]

functions：內附的 Roslyn 工具依原始碼算複雜度，dotnet test 加 coverlet 算覆蓋率，交出函式表。
mutants：Stryker.NET 把程式改壞再跑測試，交出改壞版本表。有改到的檔案清單時只改壞那些檔案。
--target 是要測試的 .sln、.slnx 或 .csproj（相對於專案根目錄）；沒給時用專案根目錄唯一的 .sln 或 .slnx。
mutants 的 --target 是 .csproj 時，要是測試專案。--workers 是 Stryker 同時跑幾個（--concurrency）。

需求：PATH 上有 .NET SDK 6 以上；測試專案引用 coverlet.collector（dotnet new xunit、mstest、nunit 的範本預設就有）。
複雜度工具第一次執行時從原始碼建置、Stryker.NET 第一次執行時用 dotnet tool install 裝到快取目錄
（REFEREE_TOOLS_DIR，預設 ~/.cache/quality-referee），要網路；之後直接執行。
結束碼 0 是量完了，其他值是量測失敗。
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from referee import paths, sheets  # noqa: E402
from referee.errors import RefereeError  # noqa: E402

COMPLEXITY_SRC = os.path.join(HERE, "csharp", "complexity")
COMPLEXITY_DLL = "referee-csharp-complexity.dll"
ROSLYN_PACKAGE = "Microsoft.CodeAnalysis.CSharp"
STRYKER_PACKAGE = "dotnet-stryker"
STRYKER_VERSION = "5.0.0"

# Stryker.NET 報告（mutation-testing-elements 格式）的狀態 → 合約的狀態
STRYKER_STATUS = {
    "Killed": "KILLED",
    "Timeout": "TIMED_OUT",
    "Survived": "LIVED",
    "NoCoverage": "NOT_COVERED",
    "CompileError": "NOT_VIABLE",
    "RuntimeError": "NOT_VIABLE",
    "Ignored": "SKIPPED",
}
# --mutate 篩掉的改壞版本也會出現在報告裡（Ignored），但它們根本沒有量，不交給裁判
MUTATE_FILTER_REASON = "Removed by mutate filter"

SKIP_DIRS = {"bin", "obj", ".git", ".vs", "node_modules"}  # 任何一層都跳過；exclude 只能寫相對專案根目錄的路徑
GENERATED_SUFFIXES = (".g.cs", ".g.i.cs", ".designer.cs")

# 複雜度工具建置目錄裡的隔離檔：擋住建置目錄上層的 Directory.Build.*、中央套件管理、global.json、NuGet 來源。
# MSBuild、NuGet、dotnet 都從專案目錄往上找這些檔案，找到最近的一個就停（NuGet.config 是全部合併，靠 <clear/> 清掉上層的來源）。
ISOLATION_FILES = {
    "Directory.Build.props": "<Project />\n",
    "Directory.Build.targets": "<Project />\n",
    "Directory.Build.rsp": "",
    "Directory.Packages.props": "<Project>\n  <PropertyGroup>\n"
                                "    <ManagePackageVersionsCentrally>false</ManagePackageVersionsCentrally>\n"
                                "  </PropertyGroup>\n</Project>\n",
    "NuGet.config": '<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n  <packageSources>\n    <clear />\n'
                    '    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />\n'
                    '  </packageSources>\n</configuration>\n',
    # 任何 6.0.100 以上的正式版 SDK 都可以，不用預覽版
    "global.json": '{"sdk": {"version": "6.0.100", "rollForward": "latestMajor", "allowPrerelease": false}}\n',
}


class InspectorError(Exception):
    pass


# ---------- 不執行任何東西的純函式 ----------

def is_generated(name):
    return name.lower().endswith(GENERATED_SUFFIXES)


def source_files(root, ctx, skip_dirs=()):
    """專案裡要量的 .cs 檔（相對路徑、/ 分隔、排序過）。

    跳過 bin、obj 這類目錄（任何一層）、產生的檔案（*.g.cs、*.Designer.cs），以及 skip_dirs（絕對路徑，
    例如工具快取目錄設在專案裡面時）。其餘依 context 的 sources、tests、exclude 篩。
    """
    skip = {os.path.normcase(os.path.abspath(d)) for d in skip_dirs}
    found = []
    for dirpath, dirs, names in os.walk(root):
        rel_dir = paths.normalize(os.path.relpath(dirpath, root))
        kept = []
        for d in sorted(dirs):
            full = os.path.join(dirpath, d)
            rel = d if rel_dir == "." else rel_dir + "/" + d
            if d in SKIP_DIRS or os.path.normcase(os.path.abspath(full)) in skip or paths.is_excluded(rel, ctx["exclude"]):
                continue
            kept.append(d)
        dirs[:] = kept
        for n in sorted(names):
            if not n.endswith(".cs") or is_generated(n):
                continue
            rel = n if rel_dir == "." else rel_dir + "/" + n
            if paths.in_scope(rel, ctx["sources"], ctx["tests"], ctx["exclude"]):
                found.append(rel)
    return sorted(found)


def find_target(root, given=None):
    """要測試的方案或專案檔（相對路徑）。沒指定時找專案根目錄唯一的 .sln 或 .slnx。"""
    if given:
        given = paths.normalize(given)  # 先統一成 /：Linux 上 \ 不是路徑分隔字元
        if not os.path.isfile(os.path.join(root, given)):
            raise InspectorError("找不到 --target 指定的 {}".format(given))
        return given
    found = sorted(n for n in os.listdir(root) if n.endswith((".sln", ".slnx")) and os.path.isfile(os.path.join(root, n)))
    if not found:
        raise InspectorError("專案根目錄沒有 .sln 或 .slnx，請在檢查員指令加 --target <方案或專案檔>")
    if len(found) > 1:
        raise InspectorError("專案根目錄有好幾個方案檔（{}），請在檢查員指令加 --target 指定一個".format("、".join(found)))
    return found[0]


def parse_cobertura(text, base_dir):
    """讀一份 Cobertura 報告，回傳 {檔案的 normcase 絕對路徑: {行號: 執行次數}}。

    coverlet 的 filename 可能是絕對路徑，也可能相對於 <sources> 裡的某個 source；相對的就逐一接上 source，
    取存在的那個（都不存在就用第一個 source，或 base_dir）。
    """
    tree = ET.fromstring(text)
    sources = [s.text for s in tree.iter("source") if s.text]
    result = {}
    for cls in tree.iter("class"):
        name = cls.get("filename")
        if not name:
            continue
        if os.path.isabs(name):
            full = name
        else:
            candidates = [os.path.join(s, name) for s in sources] or [os.path.join(base_dir, name)]
            full = next((c for c in candidates if os.path.exists(c)), candidates[0])
        lines = result.setdefault(os.path.normcase(os.path.abspath(full)), {})
        for ln in cls.iter("line"):
            number, hits = int(ln.get("number")), int(ln.get("hits", "0"))
            lines[number] = max(lines.get(number, 0), hits)
    return result


def merge_coverage(reports):
    """多份 parse_cobertura 的結果合併：同一檔同一行取最大的執行次數。"""
    merged = {}
    for rep in reports:
        for f, lines in rep.items():
            target = merged.setdefault(f, {})
            for n, h in lines.items():
                target[n] = max(target.get(n, 0), h)
    return merged


def function_coverage(lines, start, end):
    """start～end 行之間，有執行到的可執行行 ÷ 可執行行。檔案不在任何報告裡（lines 是 None）或範圍裡沒有可執行行，都是 0.0。"""
    if not lines:
        return 0.0
    coverable = [h for n, h in lines.items() if start <= n <= end]
    if not coverable:
        return 0.0
    return sum(1 for h in coverable if h > 0) / len(coverable)


def span_text(lines, start, end):
    """依報告的位置（行、欄都從 1 起算，結尾的欄不含）從原始碼取出那一段。"""
    (l0, c0), (l1, c1) = start, end
    if not 1 <= l0 <= l1 <= len(lines):
        return None
    if l0 == l1:
        return lines[l0 - 1][c0 - 1:c1 - 1]
    return "\n".join([lines[l0 - 1][c0 - 1:]] + lines[l0:l1 - 1] + [lines[l1 - 1][:c1 - 1]])


def mutate_patterns(changed_files):
    """改到的檔案 → Stryker 的 --mutate 樣式。Stryker 用專案的路徑比對，**/ 開頭才比得到相對於專案根目錄的路徑。"""
    return ["**/" + f for f in changed_files]


def mutants_from_report(report, root):
    """Stryker 的 JSON 報告 → 合約的改壞版本串列。--mutate 篩掉的不列；不認得的狀態丟 InspectorError。"""
    mutants = []
    for full, info in sorted(report.get("files", {}).items()):
        rel = paths.normalize(os.path.relpath(full, root))
        if rel.startswith("../"):
            continue
        lines = (info.get("source") or "").splitlines()
        for m in info.get("mutants", []):
            status = m.get("status")
            if status == "Ignored" and m.get("statusReason") == MUTATE_FILTER_REASON:
                continue
            if status not in STRYKER_STATUS:
                raise InspectorError("Stryker 報告裡有不認得的狀態 {!r}（{}:{}）".format(status, rel, m["location"]["start"]["line"]))
            start, end = m["location"]["start"], m["location"]["end"]
            item = {"file": rel, "line": start["line"], "column": start["column"], "mutator": m["mutatorName"],
                    "status": STRYKER_STATUS[status]}
            original = span_text(lines, (start["line"], start["column"]), (end["line"], end["column"]))
            if original is not None:
                item["original"] = original
            if m.get("replacement") is not None:
                item["replacement"] = m["replacement"]
            mutants.append(item)
    return mutants


WINDOWS_MAX_PATH = 260


def too_long_for_windows(path, is_windows=None):
    """Stryker.NET 用 Win32 的 FileVersionInfo 讀自己的版本，路徑（含結尾的 NUL）到 260 字元就讀不到。"""
    if is_windows is None:
        is_windows = os.name == "nt"
    return is_windows and len(path) >= WINDOWS_MAX_PATH


def roslyn_version(csproj_text):
    marker = 'Include="{}" Version="'.format(ROSLYN_PACKAGE)
    i = csproj_text.find(marker)
    if i < 0:
        raise InspectorError("complexity.csproj.txt 裡找不到 {} 的版本".format(ROSLYN_PACKAGE))
    i += len(marker)
    return csproj_text[i:csproj_text.index('"', i)]


# ---------- 外部指令 ----------

def run(cmd, cwd=None, stdin=None):
    env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1")
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise InspectorError("找不到指令 {}，請確認已安裝 .NET SDK 並加入 PATH".format(cmd[0]))


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def tools_dir():
    return os.path.abspath(os.environ.get("REFEREE_TOOLS_DIR") or os.path.join(os.path.expanduser("~"), ".cache", "quality-referee"))


def dotnet_version(cwd):
    r = run(["dotnet", "--version"], cwd=cwd)
    if r.returncode != 0:
        raise InspectorError("dotnet --version 執行失敗（在 {}）：\n{}{}".format(cwd, r.stdout, r.stderr))
    return r.stdout.strip()


def materialize(dest, isolation=True):
    """把複雜度工具的原始碼（和隔離檔）寫到 dest。isolation=False 只給測試用：確認沒有隔離檔時，上層的設定會弄壞建置。"""
    os.makedirs(dest, exist_ok=True)
    shutil.copy(os.path.join(COMPLEXITY_SRC, "Program.cs.txt"), os.path.join(dest, "Program.cs"))
    shutil.copy(os.path.join(COMPLEXITY_SRC, "complexity.csproj.txt"), os.path.join(dest, "complexity.csproj"))
    if isolation:
        for name, content in ISOLATION_FILES.items():
            with open(os.path.join(dest, name), "w", encoding="utf-8", newline="\n") as f:
                f.write(content)


def build(src_dir):
    """在 src_dir 建置複雜度工具，輸出到 src_dir/out。失敗丟 InspectorError。"""
    r = run(["dotnet", "publish", "complexity.csproj", "-c", "Release", "-o", "out", "--nologo"], cwd=src_dir)
    if r.returncode != 0:
        raise InspectorError("複雜度工具建置失敗：\n{}{}".format(r.stdout[-4000:], r.stderr[-2000:]))
    return os.path.join(src_dir, "out", COMPLEXITY_DLL)


def complexity_tool():
    """回傳複雜度工具 dll 的路徑。第一次使用時建置到工具快取目錄，之後直接用。

    建置目錄在快取目錄底下（不在專案裡），再加上隔離檔，專案和快取目錄上層的 Directory.Build.*、
    中央套件管理、global.json、NuGet.config 都不會影響建置。
    目錄名稱帶原始碼的雜湊和建置用的 SDK 版本（在建置目錄執行 dotnet --version）：任一個變了就重建。
    先建置到暫存目錄再整個搬過去，中途中斷不會留下建置一半的工具。
    """
    root = tools_dir()
    os.makedirs(root, exist_ok=True)
    digest = hashlib.sha256()
    for name in ("Program.cs.txt", "complexity.csproj.txt"):
        with open(os.path.join(COMPLEXITY_SRC, name), "rb") as f:
            digest.update(f.read())
    for name in sorted(ISOLATION_FILES):
        digest.update(name.encode("utf-8") + ISOLATION_FILES[name].encode("utf-8"))
    tmp = tempfile.mkdtemp(prefix=".csharp-complexity-", dir=root)
    try:
        materialize(tmp)
        sdk = dotnet_version(tmp)
        path = os.path.join(root, "csharp-complexity-{}-sdk{}".format(digest.hexdigest()[:12], sdk))
        dll = os.path.join(path, "out", COMPLEXITY_DLL)
        if os.path.exists(dll):
            return dll
        log("建置 C# 複雜度工具（只有第一次，要網路）...")
        build(tmp)
        shutil.rmtree(path, ignore_errors=True)
        os.replace(tmp, path)
        tmp = None
        return dll
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def stryker_tool():
    """回傳 dotnet-stryker 的路徑。第一次使用時 dotnet tool install 到工具快取目錄，之後直接執行。

    安裝在帶隔離檔（NuGet.config、global.json）的目錄執行，不受專案的 NuGet 來源和 SDK 釘選影響。
    dotnet tool install 裝好的工具記著安裝位置的絕對路徑，不能裝完再搬，所以直接裝到最後的目錄；
    裝成功才寫 .installed，中途中斷的目錄下次會整個刪掉重裝。
    """
    path = os.path.join(tools_dir(), "{}-{}".format(STRYKER_PACKAGE, STRYKER_VERSION))
    exe = os.path.join(path, "bin", STRYKER_PACKAGE + (".exe" if os.name == "nt" else ""))
    marker = os.path.join(path, ".installed")
    if os.path.exists(marker):
        return exe
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    for name, content in ISOLATION_FILES.items():
        with open(os.path.join(path, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    log("安裝 {} {}（只有第一次，要網路）...".format(STRYKER_PACKAGE, STRYKER_VERSION))
    r = run(["dotnet", "tool", "install", STRYKER_PACKAGE, "--version", STRYKER_VERSION, "--tool-path", "bin"], cwd=path)
    if r.returncode != 0:
        raise InspectorError("{} 安裝失敗：\n{}{}".format(STRYKER_PACKAGE, r.stdout, r.stderr))
    longest = max((os.path.realpath(os.path.join(d, n)) for d, _, names in os.walk(path) for n in names), key=len)
    if too_long_for_windows(longest):
        shutil.rmtree(path, ignore_errors=True)
        raise InspectorError(
            "工具快取目錄的路徑太長：Stryker.NET 裝在 {} 時，最長的檔案路徑有 {} 個字元，超過 Windows 的 {} 字元上限，"
            "Stryker.NET 會讀不到自己的檔案而當掉。請把 REFEREE_TOOLS_DIR 設到短一點的路徑（例如 C:\\referee-tools）".format(
                path, len(longest), WINDOWS_MAX_PATH))
    with open(marker, "w", encoding="utf-8") as f:
        f.write(STRYKER_VERSION + "\n")
    return exe


def measure_complexity(root, files):
    r = run(["dotnet", complexity_tool(), root], stdin="\n".join(files) + "\n")
    if r.returncode != 0:
        raise InspectorError("複雜度工具執行失敗：\n" + r.stderr)
    return json.loads(r.stdout)


def measure_coverage(root, target):
    with tempfile.TemporaryDirectory() as results:
        r = run(["dotnet", "test", target, "--collect:XPlat Code Coverage", "--results-directory", results, "--nologo"],
                cwd=root)
        sys.stderr.write(r.stdout)
        if r.returncode != 0:
            raise InspectorError("測試沒有全部通過，請先修好第一關（單元測試）再量 CRAP：\n" + r.stderr)
        reports = []
        for dirpath, _, names in os.walk(results):
            for n in names:
                if n == "coverage.cobertura.xml":
                    with open(os.path.join(dirpath, n), encoding="utf-8") as f:
                        reports.append(parse_cobertura(f.read(), root))
    if not reports:
        log("沒有任何覆蓋率報告：測試專案要引用 coverlet.collector，所有函式的覆蓋率都會是 0")
    return merge_coverage(reports)


# ---------- functions ----------

def measure_functions(ctx, target):
    root = os.getcwd()
    target = find_target(root, target)
    files = source_files(root, ctx, skip_dirs=[tools_dir()])
    members = measure_complexity(root, files) if files else []
    coverage = measure_coverage(root, target)
    funcs = []
    for m in members:
        lines = coverage.get(os.path.normcase(os.path.abspath(os.path.join(root, m["file"]))))
        funcs.append(dict(m, coverage=function_coverage(lines, m["start"], m["end"])))
    with open(os.path.join(COMPLEXITY_SRC, "complexity.csproj.txt"), encoding="utf-8") as f:
        roslyn = roslyn_version(f.read())
    sheet = {"schema": sheets.FUNCTIONS_SCHEMA,
             "tools": {ROSLYN_PACKAGE: roslyn, "dotnet-sdk": dotnet_version(root)},
             "settings": {"target": target},
             "functions": funcs}
    sheets.parse_functions(sheet)
    return sheet


# ---------- mutants ----------

def measure_mutants(ctx, target, workers):
    root = os.getcwd()
    target = find_target(root, target)
    stryker = stryker_tool()
    with tempfile.TemporaryDirectory() as out:
        # --break-on-initial-test-failure：沒有這個，Stryker 會把一開始就失敗的測試擱著繼續跑，抓錯檢查照樣通過
        cmd = [stryker, "--reporter", "json", "--output", out, "--skip-version-check", "--break-on-initial-test-failure"]
        cmd += ["--test-project", target] if target.endswith(".csproj") else ["--solution", target]
        if workers is not None:
            cmd += ["--concurrency", str(workers)]
        for pattern in mutate_patterns(ctx.get("changed_files") or []):
            cmd += ["--mutate", pattern]
        r = run(cmd, cwd=root)
        sys.stderr.write(r.stdout)
        if r.returncode != 0:
            raise InspectorError("Stryker.NET 執行失敗（測試沒有全部通過時也會這樣，請先修好第一關）：\n" + r.stderr)
        report = os.path.join(out, "reports", "mutation-report.json")
        if os.path.exists(report):
            with open(report, encoding="utf-8") as f:
                mutants = mutants_from_report(json.load(f), root)
        else:
            log("Stryker.NET 沒有產生報告（沒有可以改壞的地方，或要改壞的檔案不在任何被測試的專案裡）")
            mutants = []
    sheet = {"schema": sheets.MUTANTS_SCHEMA,
             "tools": {STRYKER_PACKAGE: STRYKER_VERSION, "dotnet-sdk": dotnet_version(root)},
             "settings": {"target": target, "workers": workers},
             "mutants": mutants}
    sheets.parse_mutants(sheet)
    return sheet


def main(argv=None):
    parser = argparse.ArgumentParser(prog="csharp.py", description="C# 標準檢查員")
    parser.add_argument("mode", choices=["functions", "mutants"])
    parser.add_argument("--target", metavar="檔案", help="要測試的 .sln、.slnx 或 .csproj")
    parser.add_argument("--workers", type=int, metavar="N", help="mutants：Stryker.NET 同時跑幾個")
    args = parser.parse_args(argv)

    try:
        out = os.environ.get("REFEREE_OUT")
        context = os.environ.get("REFEREE_CONTEXT")
        if not out or not context:
            raise InspectorError("沒有 REFEREE_OUT 或 REFEREE_CONTEXT 環境變數，這支檢查員要由裁判啟動")
        with open(context, encoding="utf-8") as f:
            ctx = json.load(f)
        if args.mode == "functions":
            sheet = measure_functions(ctx, args.target)
        else:
            sheet = measure_mutants(ctx, args.target, args.workers)
    except (InspectorError, RefereeError) as e:
        print(e, file=sys.stderr)
        return 1
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(sheet, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
