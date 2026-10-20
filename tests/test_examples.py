"""Alle Beispielkonfigurationen muessen laden und gueltige oder verstaendlich abgelehnte Ergebnisse liefern."""

import glob
import os

import pytest
from blindsight.config import Project
from blindsight.layout import layout_from_placements
from blindsight.model import Model
from blindsight.optimizers import run_optimizer

FILES = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "examples", "*.json")))


def test_examples_exist():
    assert len(FILES) >= 8


@pytest.mark.parametrize("path", FILES, ids=[os.path.basename(f) for f in FILES])
def test_example_runs_and_is_valid(path):
    proj = Project.load(path)
    proj.search.time_limit_s = min(proj.search.time_limit_s, 2.0)
    model = Model(proj)
    res = run_optimizer(model)
    if "infeasible" in path:
        assert res.status == "infeasible" and res.messages
        return
    assert res.best is not None
    lay = layout_from_placements(model, res.best.placements)
    assert lay.all_collisions() == []
    # Regeln je Ebene werden eingehalten
    for plane, cap in model.capacity.items():
        assert sum(1 for p in res.best.placements if p.plane == plane) <= cap
    for p in res.best.placements:
        assert round(p.angle % 360, 6) in model.angles_for(p.plane) or any(abs(p.angle - a) < 1e-4 for a in model.angles_for(p.plane))
