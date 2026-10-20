import pytest
from blindsight.layout import Counter, layout_from_placements
from blindsight.optimizers import get_optimizer
from blindsight.optimizers.base import StopToken
from helpers import make_model


def run(model, **kw):
    return get_optimizer().run(model)


def test_optimizer_returns_valid_layouts_with_target_count():
    m = make_model(target_count=8, bounds__xmax=100.0, bounds__ymax=100.0)
    m.project.search.time_limit_s = 4
    res = run(m)
    assert res.best is not None
    assert len(res.best.placements) == 8
    for sol in res.solutions:
        assert layout_from_placements(m, sol.placements).is_valid()
    assert res.proven_optimal is False  # Heuristik behauptet keine globale Optimalitaet
    assert "nicht als optimal bewiesen" in res.optimality_note


def test_optimizer_uses_multiple_planes():
    m = make_model(target_count=10)
    m.project.search.time_limit_s = 4
    res = run(m)
    assert len({p.plane for p in res.best.placements}) > 1


@pytest.mark.real_time
def test_deterministic_with_seed():
    def one():
        m = make_model(target_count=6)
        m.project.search.time_limit_s = 30
        m.project.search.max_candidates = 20000
        m.project.search.refine_fraction = 0.0
        return [p.as_dict() for p in get_optimizer().run(m).best.placements]

    assert one() == one()


def test_multiple_ranked_solutions_with_breakdown():
    m = make_model(target_count=6)
    m.project.search.time_limit_s = 4
    res = run(m)
    scores = [s.score.total for s in res.solutions]
    assert scores == sorted(scores, reverse=True)
    assert set(res.best.score.terms) == {"count", "area", "uniformity", "regularity"}


def test_weights_change_ranking():
    from blindsight.config import WeightsSpec
    from blindsight.scoring import evaluate

    m = make_model(target_count=40, bounds__xmax=90.0, bounds__ymax=90.0)
    m.project.search.time_limit_s = 1.5
    pl = run(m).best.placements
    a = evaluate(m, pl, WeightsSpec(count=1, area=0, uniformity=0, regularity=0), 40)
    b = evaluate(m, pl, WeightsSpec(count=0, area=1, uniformity=0, regularity=0), 40)
    assert a.total != b.total
    assert a.total == a.terms["count"] and b.total == b.terms["area"]


def test_cancel():
    m = make_model(target_count=30)
    c = Counter()
    stop = StopToken(60, 10**9, c)
    stop.cancel()
    res = get_optimizer().run(m, None, stop, c)
    assert res.status == "cancelled"


def test_candidate_limit():
    m = make_model(target_count=30)
    m.project.search.max_candidates = 500
    res = run(m)
    assert res.status in ("candidate_limit", "completed")
    assert res.candidates < 5000
