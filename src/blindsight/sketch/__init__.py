"""Parametric sketch of the motor outline (constraint solver in CAD style).

Coordinate system. The origin is the axis of the threaded rod, unit mm, y up. The whole motor rotates
about this origin when placed. The gear sits fixed at (-centre distance, 0), its shaft runs parallel
to y.

The sketch is a convex polygon (points counter clockwise).
  Side i runs from point i to point i+1 (cyclic).
  The angle at point i is the interior angle between side i-1 and side i.

Constraints (field type, indices a and b, numbers value and value2, reference ref)
  length         side a has length value
  angle          interior angle at point a is value degrees (0 to 180, exclusive)
  angle_sides    angle between the directions of sides a and b is value degrees (0 to 180)
  parallel       sides a and b are parallel (also opposite)
  perpendicular  sides a and b are perpendicular
  equal          sides a and b have equal length
  horizontal     side a is parallel to the x axis
  vertical       side a is parallel to the y axis
  fix            point a lies at (value, value2)
  coord_x        point a has the x coordinate value
  coord_y        point a has the y coordinate value
  dist_point     distance of point a to the reference ref (rod or gear) is value
  dist_side      perpendicular distance of the line through side a to the reference ref is value

The solver solves the equations with Levenberg Marquardt (pure Python, no dependency) and moves the
points as little as possible. It reports degrees of freedom, redundant and conflicting constraints.

Modules
  constraints  registry of the constraint types (add new types here)
  structure    normalisation, structure check, inserting and deleting points, hull
  polygon      measures and validity of the outline, gear overlap
  numeric      Levenberg Marquardt, rank
  solver       solve and SolveResult
  motor        link to MotorSpec (housing outline, conversion of legacy values)
"""

from ..errors import SketchError
from ..geometry import signed_area
from .constraints import (
    CONSTRAINT_TYPES,
    EPS_LEN,
    REFS,
    SPEC,
    ConstraintType,
    SketchGeometry,
    compile_constraint,
    constraint_label,
    constraint_schema,
)
from .motor import check_sketch_motor, housing_polygon, legacy_to_sketch, sketch_from_outline
from .numeric import TOL_SOLVE
from .polygon import gear_box, gear_overlap_message, measures, penetration, polygon_report
from .solver import TIME_LIMIT_S, TOL_OK, SolveResult, solve
from .structure import (
    MAX_CONSTRAINTS,
    MAX_POINTS,
    MIN_POINTS,
    constraint_dict,
    delete_point,
    hull_sketch,
    insert_point,
    normalize_orientation,
    remap_vertices,
    sketch_dict,
    validate_structure,
)

__all__ = [
    "CONSTRAINT_TYPES", "ConstraintType", "EPS_LEN", "MAX_CONSTRAINTS", "MAX_POINTS", "MIN_POINTS", "REFS",
    "SPEC", "SketchError", "SketchGeometry", "SolveResult", "TIME_LIMIT_S", "TOL_OK", "TOL_SOLVE",
    "check_sketch_motor", "compile_constraint", "constraint_dict", "constraint_label", "constraint_schema",
    "delete_point", "gear_box", "gear_overlap_message", "housing_polygon", "hull_sketch", "insert_point",
    "legacy_to_sketch", "measures", "normalize_orientation", "penetration", "polygon_report", "remap_vertices",
    "signed_area", "sketch_dict", "sketch_from_outline", "solve", "validate_structure",
]
