import math
import pytest

from experiments import stats as S


def test_holm_hand_computed():
    assert S.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert S.holm([0.5]) == [0.5]
    assert S.holm([0.4, 0.6]) == pytest.approx([0.8, 0.8])


def test_wilcoxon_rank_biserial_hand_computed():
    # differences: +1,+2,+3,-1  -> |d| ranks: 1.5,3,4,1.5 ; R+=8.5, R-=1.5 ; r=(8.5-1.5)/10=0.7
    x = [2, 4, 6, 1]; y = [1, 2, 3, 2]
    r = S.paired_wilcoxon(x, y)
    assert r["n"] == 4 and r["rank_biserial"] == pytest.approx(0.7) and r["mean_diff"] == pytest.approx(1.25)


def test_wilcoxon_handles_nan_and_all_equal():
    r = S.paired_wilcoxon([1, float("nan"), 3], [1, 2, 3])
    assert r["n"] == 2 and r["p"] == 1.0 and r["rank_biserial"] == 0.0
    assert S.paired_wilcoxon([], [])["p"] is None


def test_bootstrap_ci_contains_mean_and_is_seeded():
    x = [1, 2, 3, 4, 5, 6]; y = [0.5, 1.4, 2.6, 3.1, 4.8, 5.0]
    ci1 = S.bootstrap_ci_mean_diff(x, y, n_boot=2000, seed=3)
    ci2 = S.bootstrap_ci_mean_diff(x, y, n_boot=2000, seed=3)
    assert ci1 == ci2 and ci1[0] < 0.7 < ci1[1]


def test_friedman_complete_cases():
    cols = {"A": [1, 2, 3, 4, float("nan")], "B": [2, 3, 4, 5, 9], "C": [3, 4, 5, 6, 9]}
    r = S.friedman(cols)
    assert r["n"] == 4 and r["p"] is not None and r["statistic"] == pytest.approx(8.0)


def test_krippendorff_interval_hand_computed():
    # two raters, units (1,1),(2,2),(3,4): alpha = 1 - 10/82
    a = S.krippendorff_alpha([[1, 2, 3], [1, 2, 4]], metric="interval")
    assert a == pytest.approx(1 - 10 / 82)
    assert S.krippendorff_alpha([[1, 2, 3], [1, 2, 3]], metric="ordinal") == pytest.approx(1.0)
    assert S.krippendorff_alpha([[1, 2, 3, None], [1, 2, 3, 4]], metric="nominal") == pytest.approx(1.0)
