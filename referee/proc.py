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


def check_ref(root, ref, option):
    """ref 要指得到 commit，而且只有一種解讀；不然丟 RefereeError。

    git 解析名稱時 tag 排在分支前面：有人推一個叫 origin/main 的 tag，「origin/main」就會指到那個 tag，
    比較基準和設定檔的來源就被換掉了。所以同名的分支和 tag 並存時直接停下，要對方寫完整的名稱或 commit。
    """
    if run(["git", "rev-parse", "--verify", "--quiet", "--end-of-options", ref + "^{commit}"], cwd=root).returncode != 0:
        raise RefereeError("{}：找不到 {}（CI 上要把 git 歷史完整抓下來）".format(option, ref))
    names = git(root, "for-each-ref", "--format=%(refname)",
                "refs/heads/" + ref, "refs/tags/" + ref, "refs/remotes/" + ref).split()
    if len(names) > 1:
        raise RefereeError("{}：{} 同時是 {}，請寫完整的名稱（例如 {}）或 commit".format(
            option, ref, "、".join(names), names[0]))


def tail(text, n=40):
    return "\n".join(text.rstrip().splitlines()[-n:])
