from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.evidence import EvidencePipeline
from app.graph_service import GraphService
from app.responses import load_response, response_id_from_segment
from app.retrieval import RetrievalService


def _print(data: object) -> None:
    json.dump(data, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _resolve_criterion_id(args: argparse.Namespace) -> str:
    if args.criterion_id_flag:
        return args.criterion_id_flag
    if args.criterion_id:
        return args.criterion_id
    # With span flags, argparse assigns the trailing positional to response_segment_id.
    using_span = (
        args.response_id is not None
        and args.start is not None
        and args.end is not None
    )
    if using_span and args.response_segment_id:
        return args.response_segment_id
    raise ValueError("classify requires criterion_id (positional or --criterion-id)")


def _resolve_evidence_args(args: argparse.Namespace):
    pipeline = EvidencePipeline(data_dir=args.data_dir, assessment_id=args.assessment_id)
    if args.response_id and args.start is not None and args.end is not None:
        return pipeline.resolve_evidence(
            response_id=args.response_id,
            start_char=args.start,
            end_char=args.end,
        )
    if args.response_segment_id:
        return pipeline.resolve_evidence_from_segment(args.response_segment_id)
    raise ValueError("Provide response_segment_id or --response-id with --start and --end")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--assessment-id", default="C-JUN25-8464C1H-02_3")

    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest-assessment")
    ingest.add_argument("assessment_id", nargs="?")
    ingest.add_argument("--all", action="store_true")
    ingest.add_argument("--rebuild", action="store_true")

    provision = sub.add_parser("provision-participant")
    provision.add_argument("--study-id", required=True)
    provision.add_argument("--participant-id", required=True)
    provision.add_argument("--token")
    provision.add_argument("--condition", required=True)
    provision.add_argument("--subject", required=True)
    provision.add_argument("--assessment-id", action="append", dest="assessment_ids")

    import_participants = sub.add_parser("import-participants")
    import_participants.add_argument("--study-id", required=True)

    sub.add_parser("summary")

    node = sub.add_parser("node")
    node.add_argument("node_id")

    kind_choices = ["assessment", "structural", "all"]

    neighbors = sub.add_parser("neighbors")
    neighbors.add_argument("node_id")
    neighbors.add_argument("--relation")
    neighbors.add_argument("--kind", choices=kind_choices, default="all")

    incoming = sub.add_parser("incoming")
    incoming.add_argument("node_id")
    incoming.add_argument("--relation")
    incoming.add_argument("--kind", choices=kind_choices, default="all")

    outgoing = sub.add_parser("outgoing")
    outgoing.add_argument("node_id")
    outgoing.add_argument("--relation")
    outgoing.add_argument("--kind", choices=kind_choices, default="all")

    context = sub.add_parser("context")
    context.add_argument("node_id")
    context.add_argument("--include-structural", action="store_true")

    path = sub.add_parser("path")
    path.add_argument("source_id")
    path.add_argument("target_id")
    path.add_argument("--relation")
    path.add_argument("--kind", choices=kind_choices, default="all")

    response = sub.add_parser("response")
    response_sub = response.add_subparsers(dest="response_command", required=True)
    response_ingest = response_sub.add_parser("ingest")
    response_ingest.add_argument("txt_path")
    response_show = response_sub.add_parser("show")
    response_show.add_argument("response_id")

    scope_choices = ["criteria", "commentary", "question", "all"]

    similar = sub.add_parser("similar")
    similar.add_argument("response_segment_id")
    similar.add_argument("--top-k", type=int, default=5)
    similar.add_argument("--scope", choices=scope_choices, default="criteria")

    response_context = sub.add_parser("response-context")
    response_context.add_argument("response_segment_id")
    response_context.add_argument("--top-k", type=int, default=5)
    response_context.add_argument("--scope", choices=scope_choices, default="criteria")

    classify = sub.add_parser("classify")
    classify.add_argument("response_segment_id", nargs="?")
    classify.add_argument("criterion_id", nargs="?")
    classify.add_argument("--criterion-id", dest="criterion_id_flag")
    classify.add_argument("--response-id")
    classify.add_argument("--start", type=int)
    classify.add_argument("--end", type=int)
    classify.add_argument("--save", action="store_true")

    classify_top = sub.add_parser("classify-top")
    classify_top.add_argument("response_segment_id", nargs="?")
    classify_top.add_argument("--response-id")
    classify_top.add_argument("--start", type=int)
    classify_top.add_argument("--end", type=int)
    classify_top.add_argument("--top-k", type=int, default=3)
    classify_top.add_argument("--scope", choices=scope_choices, default="criteria")
    classify_top.add_argument("--save", action="store_true")

    sub.add_parser("prepare")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.command in {"similar", "response-context", "response"}:
            if args.command == "response" and args.response_command == "ingest":
                retrieval = RetrievalService.from_data_dir(
                    data_dir=args.data_dir,
                    assessment_id=args.assessment_id,
                )
                _print(retrieval.ingest_response(args.txt_path, assessment_id=args.assessment_id))
                return 0
            if args.command == "response" and args.response_command == "show":
                _print(load_response(args.response_id, responses_dir=Path(args.data_dir) / "responses"))
                return 0

            response_id = response_id_from_segment(args.response_segment_id)
            retrieval = RetrievalService.from_data_dir(
                data_dir=args.data_dir,
                assessment_id=args.assessment_id,
                response_id=response_id,
            )
            if args.command == "similar":
                _print(retrieval.similar(args.response_segment_id, top_k=args.top_k, scope=args.scope))
            else:
                _print(retrieval.response_context(args.response_segment_id, top_k=args.top_k, scope=args.scope))
            return 0

        if args.command == "ingest-assessment":
            from app.assessment_ingestion import ingest_all, ingest_assessment

            if args.all:
                _print({"results": ingest_all(args.data_dir, rebuild=args.rebuild)})
            elif args.assessment_id:
                _print(ingest_assessment(args.data_dir, args.assessment_id, rebuild=args.rebuild))
            else:
                raise ValueError("Provide assessment_id or --all")
            return 0

        if args.command == "provision-participant":
            from app.dependencies import study_service
            from app.study.store import StudyStore

            token = args.token or StudyStore.generate_token()
            result = study_service().provision_participant(
                study_id=args.study_id,
                participant_id=args.participant_id,
                token=token,
                condition=args.condition,
                subject=args.subject,
                assessment_ids=args.assessment_ids,
            )
            result["token"] = token
            _print(result)
            return 0

        if args.command == "import-participants":
            from app.dependencies import study_service

            _print(study_service().import_participants_file(args.study_id))
            return 0

        if args.command == "prepare":
            from app.views import list_assessment_ids

            summary = {"assessments": [], "responses_ingested": [], "cache_built": []}
            for assessment_id in list_assessment_ids(args.data_dir):
                retrieval = RetrievalService.from_data_dir(
                    data_dir=args.data_dir,
                    assessment_id=assessment_id,
                )
                summary["cache_built"].append(assessment_id)
            responses_dir = Path(args.data_dir) / "responses"
            for txt_path in sorted(responses_dir.glob("*.txt")):
                response_id = txt_path.stem
                json_path = responses_dir / f"{response_id}.json"
                pt_path = responses_dir / f"{response_id}.pt"
                if not json_path.exists() or not pt_path.exists():
                    retrieval = RetrievalService.from_data_dir(
                        data_dir=args.data_dir,
                        assessment_id=args.assessment_id,
                    )
                    retrieval.ingest_response(txt_path)
                    summary["responses_ingested"].append(response_id)
            _print(summary)
            return 0

        if args.command in {"classify", "classify-top"}:
            pipeline = EvidencePipeline(data_dir=args.data_dir, assessment_id=args.assessment_id)
            evidence = _resolve_evidence_args(args)
            if args.command == "classify":
                criterion_id = _resolve_criterion_id(args)
                _print(pipeline.classify(evidence, criterion_id, save=args.save))
            else:
                _print(
                    pipeline.classify_top(
                        evidence,
                        top_k=args.top_k,
                        scope=args.scope,
                        save=args.save,
                    )
                )
            return 0

        service = GraphService.from_data_dir(data_dir=args.data_dir, assessment_id=args.assessment_id)
        if args.command == "summary":
            _print(service.summary())
        elif args.command == "node":
            _print(service.get_node(args.node_id))
        elif args.command == "neighbors":
            _print(service.get_neighbors(args.node_id, relation=args.relation, kind=args.kind))
        elif args.command == "incoming":
            _print(service.get_incoming(args.node_id, relation=args.relation, kind=args.kind))
        elif args.command == "outgoing":
            _print(service.get_outgoing(args.node_id, relation=args.relation, kind=args.kind))
        elif args.command == "context":
            _print(service.get_context(args.node_id, include_structural=args.include_structural))
        elif args.command == "path":
            _print(service.find_path(args.source_id, args.target_id, relation=args.relation, kind=args.kind))
    except KeyError as exc:
        sys.stderr.write(f"Unknown id: {exc}\n")
        return 1
    except (RuntimeError, ValueError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
