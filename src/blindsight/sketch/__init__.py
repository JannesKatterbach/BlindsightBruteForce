"""Parametrische Skizze fuer die Motorkontur (Constraint Solver im CAD Stil).

Koordinatensystem. Ursprung ist die Achse der Gewindestange, Einheit mm, y nach oben. Der ganze
Motor dreht bei der Platzierung um diesen Ursprung. Das Zahnrad liegt fest bei (-Achsabstand, 0),
seine Welle verlaeuft parallel zu y.

Die Skizze ist ein konvexes Polygon (Punkte gegen den Uhrzeigersinn).
  Seite i geht von Punkt i nach Punkt i+1 (zyklisch).
  Winkel an Punkt i ist der Innenwinkel zwischen Seite i-1 und Seite i.

Constraints (Feld type, Indizes a und b, Zahlenwerte value und value2, Referenz ref)
  length         Seite a hat die Laenge value
  angle          Innenwinkel an Punkt a ist value Grad (0 bis 180, exklusiv)
  angle_sides    Winkel zwischen den Richtungen der Seiten a und b ist value Grad (0 bis 180)
  parallel       Seiten a und b sind parallel (auch gegenlaeufig)
  perpendicular  Seiten a und b stehen senkrecht
  equal          Seiten a und b sind gleich lang
  horizontal     Seite a ist parallel zur x Achse
  vertical       Seite a ist parallel zur y Achse
  fix            Punkt a liegt bei (value, value2)
  coord_x        Punkt a hat die x Koordinate value
  coord_y        Punkt a hat die y Koordinate value
  dist_point     Abstand Punkt a zur Referenz ref (rod oder gear) ist value
  dist_side      Lotabstand der Geraden durch Seite a zur Referenz ref ist value

Der Solver loest die Gleichungen mit Levenberg Marquardt (reines Python, keine Abhaengigkeit) und
bewegt die Punkte dabei so wenig wie moeglich. Er meldet Freiheitsgrade, redundante und
widerspruechliche Constraints.

Module
  constraints  Register der Constraint Typen (neue Typen hier eintragen)
  structure    Normierung, Strukturpruefung, Punkte einfuegen und loeschen, Huelle
  polygon      Masse und Gueltigkeit der Kontur, Zahnrad Ueberlappung
  numeric      Levenberg Marquardt, Rang
  solver       solve und SolveResult
  motor        Verbindung zu MotorSpec (Gehaeusekontur, Umrechnung alter Angaben)
"""

from ..errors import SketchError
from ..geometry import signed_area
from .constraints import (
    CONSTRAINT_TYPES,
    EPS_LEN,
    LABELS,
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
    "CONSTRAINT_TYPES", "ConstraintType", "EPS_LEN", "LABELS", "MAX_CONSTRAINTS", "MAX_POINTS", "MIN_POINTS", "REFS",
    "SPEC", "SketchError", "SketchGeometry", "SolveResult", "TIME_LIMIT_S", "TOL_OK", "TOL_SOLVE",
    "check_sketch_motor", "compile_constraint", "constraint_dict", "constraint_label", "constraint_schema",
    "delete_point", "gear_box", "gear_overlap_message", "housing_polygon", "hull_sketch", "insert_point",
    "legacy_to_sketch", "measures", "normalize_orientation", "penetration", "polygon_report", "remap_vertices",
    "signed_area", "sketch_dict", "sketch_from_outline", "solve", "validate_structure",
]
