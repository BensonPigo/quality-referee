"""裁判內部用的資料。記分表驗證通過後轉成這些物件。"""

from dataclasses import dataclass
from typing import Optional

KILLED = "KILLED"
TIMED_OUT = "TIMED_OUT"
LIVED = "LIVED"
NOT_COVERED = "NOT_COVERED"
EQUIVALENT = "EQUIVALENT"
EXCLUDED_MUTATOR = "EXCLUDED_MUTATOR"
NOT_VIABLE = "NOT_VIABLE"
SKIPPED = "SKIPPED"

STATUSES = [KILLED, TIMED_OUT, LIVED, NOT_COVERED, EQUIVALENT, EXCLUDED_MUTATOR, NOT_VIABLE, SKIPPED]
# 檢查員可以交出來的狀態；EQUIVALENT、EXCLUDED_MUTATOR 由裁判標記
INSPECTOR_STATUSES = [KILLED, TIMED_OUT, LIVED, NOT_COVERED, NOT_VIABLE, SKIPPED]

STATUS_NAMES = {
    KILLED: "抓到",
    TIMED_OUT: "逾時（算抓到）",
    LIVED: "沒抓到",
    NOT_COVERED: "測試沒跑到",
    EQUIVALENT: "已排除：改了也沒差",
    EXCLUDED_MUTATOR: "已排除：設定排除的改法",
    NOT_VIABLE: "無效",
    SKIPPED: "略過",
}


@dataclass
class Function:
    file: str
    name: str
    start: int
    end: int
    complexity: int
    coverage: float
    crap: float = 0.0


@dataclass
class Mutant:
    file: str
    line: int
    status: str
    mutator: str
    column: Optional[int] = None
    original: Optional[str] = None
    replacement: Optional[str] = None
    line_text: str = ""
