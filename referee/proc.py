"""執行外部指令。只用 Python 標準函式庫。"""

import subprocess

from referee.errors import RefereeError


def run(cmd, cwd=None, env=None):
    """執行指令並回傳 CompletedProcess，stdout 和 stderr 合在一起以文字保存。"""
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise RefereeError("找不到指令 {}，請確認已安裝並加入 PATH".format(cmd[0]))
    except OSError as e:
        raise RefereeError("無法執行 {}：{}".format(cmd[0], e))


def git(root, *args):
    r = run(["git", "-c", "core.quotepath=false"] + list(args), cwd=root)
    if r.returncode != 0:
        raise RefereeError("git {} 執行失敗：\n{}".format(" ".join(args), r.stdout))
    return r.stdout


def tail(text, n=40):
    return "\n".join(text.rstrip().splitlines()[-n:])
