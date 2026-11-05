"""CRAP 分數、門檻判斷、改善方向。"""

import math


def crap_score(complexity, coverage):
    return complexity * complexity * (1 - coverage) ** 3 + complexity


def score_functions(funcs):
    """算好每個函式的 CRAP，由高到低排序。"""
    for f in funcs:
        f.crap = crap_score(f.complexity, f.coverage)
    funcs.sort(key=lambda f: -f.crap)
    return funcs


def advice(complexity, threshold):
    """超標函式的改善方向，回傳 (種類, 要補到的覆蓋率百分比)。

    CRAP 最低就是 C，所以 C 超過門檻時，補測試沒有用，只能拆函式：("split", None)。
    """
    if complexity > threshold:
        return "split", None
    # 解 C² × (1 − p)³ + C ≤ 門檻，得到 p ≥ 1 − ∛((門檻 − C) / C²)
    need = 1 - ((threshold - complexity) / (complexity * complexity)) ** (1 / 3)
    return "cover", math.ceil(round(need * 100, 6))


def advice_text(complexity, threshold):
    kind, need = advice(complexity, threshold)
    return "要拆函式" if kind == "split" else "覆蓋率要到 {}%".format(need)
