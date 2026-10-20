from blindsight.optimizers import get_optimizer
from blindsight.service import JobManager
from helpers import make_model


def test_infeasible_config_reports_understandable_message():
    m = make_model(motor__height=40.0, motor__axis_height=20.0)
    res = get_optimizer().run(m)
    assert res.status == "infeasible"
    assert res.best is None
    text = " ".join(res.messages)
    assert "passt nicht" in text and "Keine Motorebene ist nutzbar" in text


def test_bounds_too_small_for_single_unit():
    m = make_model(bounds__xmax=20.0, bounds__ymax=20.0)
    res = get_optimizer().run(m)
    assert res.status == "infeasible"
    assert any("einzelne Einheit" in s for s in res.messages)


def test_partial_solution_is_reported_honestly():
    m = make_model(target_count=60, bounds__xmax=60.0, bounds__ymax=60.0)
    m.project.search.time_limit_s = 2
    res = get_optimizer().run(m)
    n = len(res.best.placements)
    assert 0 < n < 60
    assert not res.proven_optimal
    assert any(f"Nur {n} von 60" in s for s in res.messages)


def test_job_manager_runs_in_background():
    import time

    from blindsight.config import Project

    p = Project(target_count=4)
    p.search.time_limit_s = 2
    jm = JobManager()
    job = jm.start(p)
    for _ in range(100):
        if job.state in ("finished", "failed"):
            break
        time.sleep(0.1)
    assert job.state == "finished"
    assert job.result.best is not None
