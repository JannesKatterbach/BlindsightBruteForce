import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def pytest_configure(config):
    config.addinivalue_line("markers", "real_time: Test laeuft mit den echten Zeitlimits ohne Stagnationsabbruch")


@pytest.fixture(autouse=True)
def fast_stagnation(request, monkeypatch):
    """Haelt die Testlaufzeit klein. Sobald die Zielanzahl erreicht ist und 0.5 s keine Verbesserung kommt, endet die Suche."""
    if request.node.get_closest_marker("real_time"):
        return
    from blindsight.model import Model

    orig = Model.__init__

    def patched(self, project, *a, **k):
        se = project.search
        if se.stagnation_s is None or se.stagnation_s > 0.5:
            se.stagnation_s = 0.5
        orig(self, project, *a, **k)

    monkeypatch.setattr(Model, "__init__", patched)
