from blindsight.config import Project
from blindsight.layout import Placement
from blindsight.model import Model


def make_model(**overrides) -> Model:
    p = Project()
    p.search.time_limit_s = 3
    for k, v in overrides.items():
        obj = p
        parts = k.split("__")
        for name in parts[:-1]:
            obj = getattr(obj, name)
        setattr(obj, parts[-1], v)
    return Model(p)


def pl(x, y, plane=1, angle=0.0):
    return Placement(x, y, plane, angle)
