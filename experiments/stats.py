"""Small statistics helpers used by analyze.py and human_eval.py."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np
from scipy import stats


def holm(pvals: Sequence[float]) -> List[float]:
    """Holm-Bonferroni adjusted p-values (monotone), same order as input."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj


def paired_wilcoxon(x: Sequence[float], y: Sequence[float]) -> Dict[str, Optional[float]]:
    """Two-sided Wilcoxon signed-rank on pairs with both values defined.

    Returns n, p, matched-pairs rank-biserial r = (R+ - R-)/(R+ + R-)
    (positive when x > y), and the mean difference."""
    xs, ys = np.asarray(x, float), np.asarray(y, float)
    ok = ~(np.isnan(xs) | np.isnan(ys))
    xs, ys = xs[ok], ys[ok]
    d = xs - ys
    n = int(len(d))
    res = {"n": n, "mean_diff": float(d.mean()) if n else None, "p": None, "rank_biserial": None}
    nz = d[d != 0]
    if n == 0:
        return res
    if len(nz) == 0:
        res.update(p=1.0, rank_biserial=0.0)
        return res
    ranks = stats.rankdata(np.abs(nz))
    rp, rm = ranks[nz > 0].sum(), ranks[nz < 0].sum()
    res["rank_biserial"] = float((rp - rm) / (rp + rm))
    try:
        res["p"] = float(stats.wilcoxon(xs, ys, zero_method="wilcox", method="auto").pvalue)
    except ValueError:
        res["p"] = None
    return res


def bootstrap_ci_mean_diff(x: Sequence[float], y: Sequence[float], n_boot: int = 10000,
                           seed: int = 1, alpha: float = 0.05) -> Optional[List[float]]:
    xs, ys = np.asarray(x, float), np.asarray(y, float)
    ok = ~(np.isnan(xs) | np.isnan(ys))
    d = (xs - ys)[ok]
    if len(d) < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(n_boot, len(d)))
    means = d[idx].mean(axis=1)
    return [float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))]


def friedman(columns: Dict[str, Sequence[float]]) -> Dict[str, Optional[float]]:
    """Friedman test over complete cases (rows with no NaN in any column)."""
    names = list(columns)
    arr = np.column_stack([np.asarray(columns[n], float) for n in names])
    arr = arr[~np.isnan(arr).any(axis=1)]
    if arr.shape[0] < 3 or arr.shape[1] < 3:
        return {"n": int(arr.shape[0]), "statistic": None, "p": None}
    if np.all(arr == arr[:, [0]]):
        return {"n": int(arr.shape[0]), "statistic": 0.0, "p": 1.0}
    st = stats.friedmanchisquare(*[arr[:, j] for j in range(arr.shape[1])])
    return {"n": int(arr.shape[0]), "statistic": float(st.statistic), "p": float(st.pvalue)}


def krippendorff_alpha(ratings: Sequence[Sequence[Optional[float]]], metric: str = "interval") -> Optional[float]:
    """Krippendorff's alpha. ``ratings[r][u]`` = rater r's rating of unit u (None = missing).

    metric: "interval" (squared difference) or "ordinal" (cumulative-frequency
    based) or "nominal"."""
    units = list(zip(*ratings))
    coincid: Dict[tuple, float] = {}
    for unit in units:
        vals = [v for v in unit if v is not None]
        m = len(vals)
        if m < 2:
            continue
        for i, a in enumerate(vals):
            for j, b in enumerate(vals):
                if i != j:
                    coincid[(a, b)] = coincid.get((a, b), 0.0) + 1.0 / (m - 1)
    values = sorted({v for pair in coincid for v in pair})
    n_c = {v: sum(w for (a, _), w in coincid.items() if a == v) for v in values}
    n = sum(n_c.values())
    if n <= 1 or len(values) < 2:
        return None if n <= 1 else 1.0

    def delta2(a, b):
        if a == b:
            return 0.0
        if metric == "nominal":
            return 1.0
        if metric == "interval":
            return float((a - b) ** 2)
        if metric == "ordinal":
            lo, hi = (a, b) if a < b else (b, a)
            s = sum(n_c[v] for v in values if lo < v < hi) + (n_c[lo] + n_c[hi]) / 2.0
            return s * s
        raise ValueError(metric)

    do = sum(w * delta2(a, b) for (a, b), w in coincid.items()) / n
    de = sum(n_c[a] * n_c[b] * delta2(a, b) for a in values for b in values) / (n * (n - 1))
    return 1.0 if de == 0 else 1.0 - do / de
