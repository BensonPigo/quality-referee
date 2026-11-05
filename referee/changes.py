"""用 git diff 找出改到的行。

比較的起點是 base 和 HEAD 的分岔點，所以 base 之後別人合併進去的改動不會算進來；
比較的終點是工作目錄，所以還沒 commit 的改動和新增的檔案也會算進來。
換行字元 CRLF 和 LF 的差異不算改動。
"""

import math
from collections import defaultdict

from referee.errors import RefereeError
from referee.paths import normalize
from referee.proc import git


def changed_lines(base, root):
    """回傳 {檔案: [(起, 訖), ...]}，包含所有改到的檔案，不看 sources、tests、exclude（由呼叫端篩）。

    只刪除沒新增的 hunk，記成刪除位置前後兩行 (start, start + 1)。新增（untracked）的檔案整個算改到：(1, inf)。
    """
    try:
        merge_base = git(root, "merge-base", base, "HEAD").strip()
    except RefereeError as e:
        raise RefereeError("找不到 {} 和 HEAD 的分岔點（CI 上要把 git 歷史完整抓下來）\n{}".format(base, e))

    diff = git(root, "diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames", "--relative",
               "--ignore-cr-at-eol", merge_base, "--")
    changed = defaultdict(list)
    file = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:].rstrip("\t")
            file = None if name == "/dev/null" else normalize(name[len("b/"):])
        elif file and line.startswith("@@"):
            new = line.split()[2][1:]
            start, _, n = new.partition(",")
            start, n = int(start), int(n or 1)
            changed[file].append((start, start + 1) if n == 0 else (start, start + n - 1))

    for file in git(root, "ls-files", "--others", "--exclude-standard").splitlines():
        if file.strip():
            changed[normalize(file)].append((1, math.inf))
    return dict(changed)


def overlaps(spans, start, end):
    return any(a <= end and b >= start for a, b in spans or [])
