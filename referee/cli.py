"""指令解析和各指令的流程。

用法（在專案根目錄執行，設定檔是 .referee.json）：

    python referee.py test [--json 檔名]
    python referee.py crap [--base origin/main] [--json 檔名]
    python referee.py mutation [--base origin/main] [--json 檔名]
    python referee.py check [--base origin/main] [--skip 關...] [--json 目錄]

結束碼：0 通過，1 沒過門檻，2 量測失敗或設定有誤。
"""

import argparse
import os
import sys

from referee import config, gates, report
from referee.errors import RefereeError


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="referee", description="裁判：三道檢查的共用判定")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("test", help="第一關：單元測試")
    p.add_argument("--json", metavar="檔名", help="另外寫一份 JSON 報告")
    p = sub.add_parser("crap", help="第二關：CRAP")
    p.add_argument("--base", help="只檢查和這個分支相比有改到的函式，例如 origin/main")
    p.add_argument("--json", metavar="檔名", help="另外寫一份 JSON 報告")
    p = sub.add_parser("mutation", help="第三關：抓錯檢查")
    p.add_argument("--base", help="只計算和這個分支相比有改到的行，例如 origin/main")
    p.add_argument("--json", metavar="檔名", help="另外寫一份 JSON 報告")
    p = sub.add_parser("check", help="依 gates 依序跑，第一個沒過就停")
    p.add_argument("--base", help="比較基準，沒給就用 .referee.json 的 base")
    p.add_argument("--skip", nargs="+", default=[], metavar="名稱", help="這次不跑的關：{}".format("、".join(config.GATES)))
    p.add_argument("--json", metavar="目錄", help="每一關各寫一份 JSON 報告（test.json、crap.json、mutation.json）到這個目錄")
    args = parser.parse_args(argv)

    root = os.path.realpath(os.getcwd())
    os.chdir(root)
    try:
        cfg = config.load_config(root)
        if args.command == "check":
            return cmd_check(args, cfg, root)
        return cmd_gate(args.command, args, cfg, root)
    except RefereeError as e:
        sys.stdout.flush()
        print(e, file=sys.stderr)
        return e.exit_code


def cmd_gate(gate, args, cfg, root):
    """單獨執行一關。這一關不在 gates 裡：印「還沒啟用」，有 --json 就寫 result 為 skipped 的報告，結束碼 0。"""
    if gate not in cfg["gates"]:
        print("第 {} 關（{}）還沒啟用：{} 的 gates 沒有 {}".format(
            config.GATES.index(gate) + 1, gate, config.CONFIG_FILE, gate))
        code, rep = 0, gates.skipped_report(gate)
    else:
        code, rep = gates.GATE_RUNNERS[gate](getattr(args, "base", None), cfg, root)
    if args.json:
        report.write_json(args.json, rep)
    return code


def cmd_check(args, cfg, root):
    """依序跑 test、crap、mutation。沒啟用或被 --skip 的關只印一行；第一個沒過就停。"""
    run, skipped, disabled = gates.plan_gates(cfg["gates"], args.skip)
    base = args.base or cfg["base"]
    print("比較基準：" + base)
    if args.json:
        os.makedirs(args.json, exist_ok=True)

    def write(gate, rep):
        if args.json:
            report.write_json(os.path.join(args.json, gate + ".json"), rep)

    for gate in config.GATES:
        n = config.GATES.index(gate) + 1
        if gate not in run:
            print("== 第 {} 關：{}（{}）==".format(n, gate, "略過" if gate in skipped else "還沒啟用"))
            write(gate, gates.skipped_report(gate))
            continue
        print("== 第 {} 關：{} ==".format(n, gate), flush=True)
        try:
            code, rep = gates.GATE_RUNNERS[gate](base, cfg, root)
        except RefereeError as e:
            sys.stdout.flush()
            print(e, file=sys.stderr, flush=True)
            print("\n停在第 {} 關".format(n))
            return e.exit_code
        write(gate, rep)
        if code != 0:
            print("\n停在第 {} 關".format(n))
            return code
    print("\nPASS：已啟用的 {} 關都通過（略過：{}；還沒啟用：{}）".format(
        len(run), "、".join(skipped) or "無", "、".join(disabled) or "無"))
    return 0
