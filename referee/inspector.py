"""啟動檢查員：給它 REFEREE_CONTEXT 和 REFEREE_OUT，讀回記分表。裁判不認得檢查員用什麼工具。"""

import json
import os
import shutil
import tempfile

from referee import sheets
from referee.errors import RefereeError
from referee.proc import run, tail

CONTEXT_SCHEMA = "referee.context/1"


def build_context(gate, cfg, changed_files):
    """changed_files：只有 mutation 加 --base 時是改到的原始碼檔案清單，其他情況一律 None。"""
    return {
        "schema": CONTEXT_SCHEMA,
        "gate": gate,
        "sources": list(cfg["sources"]),
        "tests": list(cfg["tests"]),
        "exclude": list(cfg["exclude"]),
        "changed_files": None if changed_files is None else sorted(changed_files),
    }


def run_inspector(gate, cfg, root, changed_files=None):
    """執行 cfg[gate]["inspector"]，回傳 (tools, settings, 項目清單)。"""
    command = cfg[gate]["inspector"]
    what = "函式表" if gate == "crap" else "改壞版本表"
    parse = sheets.parse_functions if gate == "crap" else sheets.parse_mutants
    tmp = tempfile.mkdtemp(prefix="referee-")
    try:
        context_path = os.path.join(tmp, "context.json")
        out_path = os.path.join(tmp, "sheet.json")
        with open(context_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(build_context(gate, cfg, changed_files), f, ensure_ascii=False)
        env = dict(os.environ, REFEREE_OUT=out_path, REFEREE_CONTEXT=context_path)
        r = run(command, cwd=root, env=env)
        if r.returncode != 0:
            raise RefereeError("檢查員（{}）量測失敗，結束碼 {}：\n{}".format(" ".join(command), r.returncode, tail(r.stdout)))
        return parse(sheets.load_sheet(out_path, what))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
