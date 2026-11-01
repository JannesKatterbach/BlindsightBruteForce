"""Command line. Optimization without UI, for testing and automation.

  blindsight-cli examples/small_hex.json --svg out.svg --json out.json --rods rods.json
  python -m blindsight.cli examples/small_hex.json --time 20 --lang en

Exit codes
  0  solution found (and files written)
  1  no valid solution found
  2  configuration not readable or invalid (also after --time and --seed)
  3  output file could not be written
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import holes as hole_files
from .config import ConfigError, Project
from .export import JsonExporter, RodPositionsExporter, SvgExporter, build_geometry
from .i18n import LANGUAGES, normalize_language, tr, use_language
from .layout import Counter
from .model import Model
from .optimizers import run_optimizer
from .optimizers.base import ProgressInfo, StopToken

EXIT_OK, EXIT_NO_SOLUTION, EXIT_CONFIG, EXIT_OUTPUT = 0, 1, 2, 3
PROGRESS_INTERVAL_S = 1.0
LANGUAGE_ENV = "BLINDSIGHT_LANG"  # default language of the output if --lang is not given


def _language(argv: list[str]) -> str:
    """Language from --lang (read before the full parser so that its help texts are translated)."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang")
    known, _ = pre.parse_known_args(argv)
    return normalize_language(known.lang or os.environ.get(LANGUAGE_ENV))


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=tr("cli.description"))
    ap.add_argument("config", help=tr("cli.config"))
    ap.add_argument("--svg", help=tr("cli.svg"))
    ap.add_argument("--json", help=tr("cli.json"))
    ap.add_argument("--rods", help=tr("cli.rods"))
    ap.add_argument("--holes", help=tr("cli.holes"))
    ap.add_argument("--time", type=float, help=tr("cli.time"))
    ap.add_argument("--seed", type=int, help=tr("cli.seed"))
    ap.add_argument("--lang", choices=LANGUAGES, help=tr("cli.lang"))
    ap.add_argument("--quiet", action="store_true", help=tr("cli.quiet"))
    return ap


def _load(args: argparse.Namespace) -> Model:
    """Read the configuration, apply the overrides and check everything together (in the Model)."""
    project = Project.load(args.config)
    if args.time is not None:
        project.search.time_limit_s = args.time
    if args.seed is not None:
        project.search.seed = args.seed
    if args.holes:
        apply_hole_file(project, args.holes)
    return Model(project)


def apply_hole_file(project: Project, path: str) -> None:
    """Fixed holes switch to the optimizer fixed_holes, an own tile to the repeating pattern."""
    with open(path, encoding="utf-8") as fh:
        try:
            doc = hole_files.parse(json.load(fh))
        except json.JSONDecodeError as exc:
            raise ConfigError(tr("config.invalid_json", error=str(exc))) from exc
        except hole_files.HolesError as exc:
            raise ConfigError([tr("cli.holes_error", error=e) for e in exc.errors]) from exc
    if doc.holes:
        project.holes = doc.holes
        project.search.optimizer = "fixed_holes"
    else:
        project.search.custom_tile = doc.tile
        project.search.pattern = "custom"
        project.search.optimizer = "periodic_tile"


def _write(path: str, text: str, what: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(tr("cli.written", what=what, path=path))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    with use_language(_language(argv)):
        return _main(argv)


def _main(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        model = _load(args)
    except (ConfigError, OSError, UnicodeDecodeError) as exc:
        print(tr("cli.config_error", error=exc), file=sys.stderr)
        return EXIT_CONFIG
    project = model.project

    counter = Counter()
    stop = StopToken(project.search.time_limit_s, project.search.max_candidates, counter)
    last_report = [0.0]

    def progress(info: ProgressInfo) -> None:
        if not args.quiet and info.elapsed - last_report[0] > PROGRESS_INTERVAL_S:
            last_report[0] = info.elapsed
            print(tr("cli.progress", elapsed=info.elapsed, phase=info.phase, candidates=info.candidates, best=info.best_count))

    result = run_optimizer(model, progress, stop, counter)
    print(tr("cli.status", status=result.status, candidates=result.candidates, elapsed=result.elapsed))
    print(result.optimality_note)
    for message in result.messages:
        print(" -", message)
    if not result.best:
        return EXIT_NO_SOLUTION
    best = result.best
    print(tr("cli.best", count=len(best.placements), target=result.target, score=best.score.total))
    for name, value in best.score.terms.items():
        weight = best.score.weights.get(name)  # the count has precedence over the goals in the modes holes and pattern
        print(tr("cli.term", name=name, value=value, weight=weight) if weight is not None else tr("cli.term_first", name=name, value=value))
    geometry = build_geometry(model, best.placements)
    try:
        if args.svg:
            _write(args.svg, SvgExporter().export(geometry), tr("cli.what_svg"))
        if args.json:
            _write(args.json, JsonExporter().export(geometry), tr("cli.what_json"))
        if args.rods:
            _write(args.rods, RodPositionsExporter().export(geometry), tr("cli.what_rods"))
    except OSError as exc:
        print(tr("cli.output_error", error=exc), file=sys.stderr)
        return EXIT_OUTPUT
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
