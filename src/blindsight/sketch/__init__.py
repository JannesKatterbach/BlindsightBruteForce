"""Parametric sketch of the motor in top view (constraint solver in CAD style, modelled after Onshape).

Coordinate system. The origin is the axis of the threaded rod, unit mm, y up. The whole motor rotates
about this origin when placed.

The sketch holds points, entities (point, line, circle, arc) and constraints (relations and dimensions).
The housing is the convex hull of all normal entities, the gear is an axis parallel rectangle of lines with
role "gear" whose centre lies on the negative x axis. Gear diameter, gear width and centre distance come
from the sketch.

The solver solves the equations with Levenberg Marquardt (pure Python, no dependency) and moves the points
as little as possible. It reports degrees of freedom, redundant and conflicting constraints and which points
and entities are fully determined.

Modules
  entities     data, references, structure check, deleting entities
  constraints  registry of the constraint types (add new types here)
  numeric      Levenberg Marquardt, rank
  solver       solve and SolveResult
  profile      housing hull and gear of a solved sketch
  motor        link to MotorSpec (sketch from the motor fields or an outline, housing, derived fields)
"""

from ..errors import SketchError
from .constraints import CONSTRAINT_TYPES, ConstraintType, compile_constraint, constraint_label, constraint_schema, match
from .entities import (
    ENTITY_POINTS,
    MAX_CONSTRAINTS,
    MAX_ENTITIES,
    MAX_POINTS,
    ORIGIN,
    ROLE_GEAR,
    Vars,
    delete_entities,
    sketch_dict,
    validate_structure,
)
from .motor import Builder, check_sketch_motor, housing_polygon, motor_fields, sketch_from_motor, sketch_from_outline, sketch_profile
from .numeric import TOL_SOLVE
from .profile import Profile, profile
from .solver import TIME_LIMIT_S, TOL_OK, SolveResult, solve, structure_errors

__all__ = [
    "Builder", "CONSTRAINT_TYPES", "ConstraintType", "ENTITY_POINTS", "MAX_CONSTRAINTS", "MAX_ENTITIES", "MAX_POINTS",
    "ORIGIN", "Profile", "ROLE_GEAR", "SketchError", "SolveResult", "TIME_LIMIT_S", "TOL_OK", "TOL_SOLVE", "Vars",
    "check_sketch_motor", "compile_constraint", "constraint_label", "constraint_schema", "delete_entities",
    "housing_polygon", "match", "motor_fields", "profile", "sketch_dict", "sketch_from_motor", "sketch_from_outline",
    "sketch_profile", "solve", "structure_errors", "validate_structure",
]
