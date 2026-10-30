from app.services.bkt_parameters import BKTParameters, fit_bkt_parameters


def test_sparse_data_uses_configured_fallback():
    defaults = BKTParameters(0.25, 0.12, 0.18, 0.08)
    fitted = fit_bkt_parameters(
        [[True, False], [True, True]],
        defaults,
        min_responses=100,
        min_sequences=10,
    )
    assert fitted.source == "configured_fallback"
    assert (fitted.p_initial, fitted.p_learn, fitted.p_guess, fitted.p_slip) == (
        defaults.p_initial, defaults.p_learn, defaults.p_guess, defaults.p_slip
    )


def test_sufficient_data_triggers_bounded_em_calibration():
    # Independent learner-goal-skill sequences of mixed difficulty/outcomes.
    sequences = []
    patterns = [
        [False, False, True, False, True, True],
        [True, False, True, True, True, True],
        [False, True, False, True, False, True],
        [True, True, True, False, True, False],
    ]
    for i in range(20):
        sequences.append(patterns[i % len(patterns)])
    fitted = fit_bkt_parameters(
        sequences,
        BKTParameters(0.20, 0.15, 0.20, 0.10),
        min_responses=100,
        min_sequences=10,
    )
    assert fitted.source == "empirical_em"
    assert fitted.response_count == 120
    assert fitted.sequence_count == 20
    assert 0.02 <= fitted.p_initial <= 0.98
    assert 0.001 <= fitted.p_learn <= 0.50
    assert 0.01 <= fitted.p_guess <= 0.40
    assert 0.01 <= fitted.p_slip <= 0.40
