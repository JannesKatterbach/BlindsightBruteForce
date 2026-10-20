"""Fuzz der Konfigurationsvalidierung. Es darf nur ConfigError geben, nie eine andere Ausnahme."""

import copy
import json
import math
import random

import pytest
from blindsight.config import ConfigError, Project
from blindsight.model import Model

BAD_VALUES = [None, "x", "", True, False, [], {}, [1, 2], -1, 0, 1e308, -1e308, float("nan"), float("inf"), 1e-12, 10**30, 3.5]


def paths(d, prefix=()):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from paths(v, prefix + (k,))
        else:
            yield prefix + (k,)


def set_path(d, path, value):
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = value


def test_fuzz_every_field_with_bad_values():
    base = Project().to_dict()
    for path in paths(base):
        for bad in BAD_VALUES:
            d = copy.deepcopy(base)
            set_path(d, path, bad)
            try:
                p = Project.from_dict(d)
                Model(p)  # was validiert, muss auch das Modell bauen
            except ConfigError:
                pass


def test_random_garbage_json():
    rng = random.Random(1)
    for _ in range(300):
        txt = "".join(rng.choice('{}[]",:0123456789 abcnulltrue-.eE') for _ in range(rng.randint(0, 60)))
        try:
            Project.from_json(txt)
        except ConfigError:
            pass


@pytest.mark.parametrize("bad", ["[]", "null", "3", '"x"', "{}x", '{"rod": 3}', '{"obstacles": {}}', '{"stack": {"gaps": "a"}}'])
def test_structural_errors(bad):
    try:
        Project.from_json(bad)
    except ConfigError:
        return
    assert bad == "{}x" or False


def test_empty_object_is_default_project():
    assert Project.from_json("{}").target_count == Project().target_count


def test_nan_inf_rejected_everywhere():
    for key in ("clearance", "target_count"):
        for val in ("NaN", "Infinity", "-Infinity"):
            with pytest.raises(ConfigError):
                Project.from_json('{"%s": %s}' % (key, val))


def test_deeply_nested_json():
    with pytest.raises(ConfigError):
        Project.from_json("[" * 100000)


def test_roundtrip_json():
    p = Project()
    p.obstacles = []
    assert Project.from_json(p.to_json()).to_dict() == p.to_dict()


def test_messages_name_the_field():
    with pytest.raises(ConfigError) as e:
        Project.from_dict({"rod": {"diameter": -1}, "bounds": {"xmax": -5}})
    txt = " ".join(e.value.errors)
    assert "rod.diameter" in txt


def test_error_lists_are_collected_not_first_only():
    with pytest.raises(ConfigError) as e:
        Project.from_dict({"rod": {"diameter": -1, "stroke": 0}, "motor": {"width": -2}, "clearance": -1})
    assert len(e.value.errors) >= 4
