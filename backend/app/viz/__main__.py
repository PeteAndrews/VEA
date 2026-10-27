"""Offline graph visualisation: python -m app.viz assessment|response|judgement ..."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.representation.instance import load_instance
from app.viz.filters import VizFilter
from app.viz.networkx_adapter import to_networkx
from app.viz.render import render_formats, write_dot


def _parse_csv(value: str | None) -> frozenset[str] | None:
    if not value:
        return None
    return frozenset(part.strip() for part in value.split(",") if part.strip())


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    from app.paths import DATA_DIR

    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument("--assessment-id", required=True)
    parser.add_argument("--output-dir", default=str(DATA_DIR / "debug" / "graphs"))
    parser.add_argument("--format", default="svg,png", help="Comma-separated: svg,png,pdf")
    parser.add_argument("--no-structural", action="store_true")
    parser.add_argument("--node-types")
    parser.add_argument("--relations")
    parser.add_argument("--criterion", help="Seed node for ego filter")
    parser.add_argument("--hops", type=int, default=2)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    _add_common_args(common)

    parser = argparse.ArgumentParser(prog="python -m app.viz")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "assessment",
        parents=[common],
        help="Layer 1 only",
        description="Export assessment graph (mark scheme + question).",
    )

    response = sub.add_parser(
        "response",
        parents=[common],
        help="Layer 1 + Layer 2",
        description="Assessment plus candidate response segments.",
    )
    response.add_argument("--response-id", required=True)

    judgement = sub.add_parser(
        "judgement",
        parents=[common],
        help="Layer 1 + Layer 2 + Layer 3",
        description="Assessment, response, and one examiner judgement session.",
    )
    judgement.add_argument("--response-id", required=True)
    judgement.add_argument("--session", dest="marking_session_id", required=True)
    judgement.add_argument("--include-history", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    response_id = getattr(args, "response_id", None)
    marking_session_id = getattr(args, "marking_session_id", None)
    include_history = getattr(args, "include_history", False)

    instance = load_instance(
        data_dir=args.data_dir,
        assessment_id=args.assessment_id,
        response_id=response_id,
        marking_session_id=marking_session_id,
        include_judgement_history=include_history,
    )

    nx_graph = to_networkx(instance, include_structural=not args.no_structural)
    seeds = frozenset({args.criterion}) if args.criterion else None
    filt = VizFilter(
        node_types=_parse_csv(args.node_types),
        relations=_parse_csv(args.relations),
        include_structural=not args.no_structural,
        seed_node_ids=seeds,
        hops=args.hops if seeds else None,
    )
    nx_graph = filt.apply(nx_graph)

    stem = f"{args.assessment_id}_{args.command}"
    if response_id:
        stem += f"_{response_id}"
    if marking_session_id:
        stem += f"_{marking_session_id}"
    if args.criterion:
        stem += f"_{args.criterion}"

    out_dir = Path(args.output_dir)
    dot_path = out_dir / f"{stem}.dot"
    try:
        write_dot(nx_graph, dot_path)
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    formats = [part.strip() for part in args.format.split(",") if part.strip()]
    rendered = render_formats(dot_path, formats)
    print(str(dot_path.resolve()))
    for path in rendered:
        print(str(path.resolve()))
    if not rendered and formats:
        sys.stderr.write("Graphviz 'dot' not found; .dot file written only.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
