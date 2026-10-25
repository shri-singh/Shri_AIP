"""Command line. Exit codes: 0 ok, 1 a window/index item failed, 2 configuration error.

Examples (run from services/ingestion with the venv active)::

    python -m opsi_ingest check-config --source elastic
    python -m opsi_ingest collect --source elastic --dry-run        # fetch 1 window, write nothing
    python -m opsi_ingest collect --source elastic                  # normal scheduled run
    python -m opsi_ingest index                                     # curated PG/OpenSearch from outbox
    python -m opsi_ingest status --hours 6
    python -m opsi_ingest backfill --source dynatrace_problems --from 2026-10-01T00:00:00Z --to 2026-10-02T00:00:00Z
    python -m opsi_ingest skip-window --source elastic --window-start 2026-10-24T10:05:00Z \
        --actor "jdoe" --reason "Elastic index deleted by retention; approved CHG-1234"
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime

from . import __version__
from .config import Settings, from_env
from .errors import ConfigError
from .logging_setup import configure
from .pipeline import BronzeStage, IndexStage
from .sinks.objectstore import DiscardObjectStore, open_store
from .sources import SOURCE_NAMES, build_source
from .state import open_state
from .timeutil import parse_timestamp, utcnow
from .windows import Window, windows_between

log = logging.getLogger("opsi_ingest")


def _ts(value: str) -> datetime:
    return parse_timestamp(value)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="opsi_ingest", description="Opsi bounded collectors")
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect", help="bronze stage: collect closed windows to S3")
    c.add_argument("--source", choices=SOURCE_NAMES, required=True)
    c.add_argument("--max-windows", type=int)
    c.add_argument("--dry-run", action="store_true", help="fetch one window, write nothing, print stats")

    b = sub.add_parser("backfill", help="bronze stage for an explicit historical range")
    b.add_argument("--source", choices=SOURCE_NAMES, required=True)
    b.add_argument("--from", dest="start", type=_ts, required=True)
    b.add_argument("--to", dest="end", type=_ts, required=True)
    b.add_argument("--dry-run", action="store_true")

    i = sub.add_parser("index", help="index stage: apply committed windows to curated sinks")
    i.add_argument("--source", choices=SOURCE_NAMES)
    i.add_argument("--limit", type=int, default=50)

    s = sub.add_parser("status", help="ledger/outbox overview and gap check")
    s.add_argument("--source", choices=SOURCE_NAMES)
    s.add_argument("--hours", type=int, default=24)
    s.add_argument("--json", action="store_true")

    k = sub.add_parser("skip-window", help="operator: mark one window as intentionally skipped (audited)")
    k.add_argument("--source", choices=SOURCE_NAMES, required=True)
    k.add_argument("--window-start", type=_ts, required=True)
    k.add_argument("--actor", required=True)
    k.add_argument("--reason", required=True)

    r = sub.add_parser("requeue-dead", help="operator: retry dead-lettered index items (audited)")
    r.add_argument("--source", choices=SOURCE_NAMES)
    r.add_argument("--actor", required=True)
    r.add_argument("--reason", required=True)

    w = sub.add_parser("reset-watermark", help="DANGEROUS operator action: move a watermark (audited)")
    w.add_argument("--source", choices=SOURCE_NAMES, required=True)
    w.add_argument("--to", dest="to", type=_ts, required=True)
    w.add_argument("--actor", required=True)
    w.add_argument("--reason", required=True)
    w.add_argument("--yes", action="store_true", help="confirm you read docs/runbooks.md#reset-watermark")

    cc = sub.add_parser("check-config", help="validate settings for a source without network calls")
    cc.add_argument("--source", choices=SOURCE_NAMES, required=True)
    return p


def _sinks(settings: Settings) -> list:
    sinks = []
    if settings.database_url:
        from .sinks.postgres_curated import PostgresCuratedSink
        sinks.append(PostgresCuratedSink(settings.database_url, settings.curated_max_samples_per_signature))
    if settings.opensearch_url:
        from .sinks.opensearch import OpenSearchSink
        sinks.append(OpenSearchSink(settings.opensearch_url, settings.opensearch_index, settings.opensearch_username,
                                    settings.opensearch_password, settings.opensearch_ca_certs,
                                    max_samples=settings.curated_max_samples_per_signature))
    return sinks


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    configure(args.log_level.upper())
    try:
        settings = from_env()
        return _dispatch(args, settings)
    except ConfigError as exc:
        log.error("config_error", extra={"audit": {"error": str(exc)}})
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "check-config":
        source = build_source(args.source, settings)
        print(json.dumps({"ok": True, "source": source.name, "dataset": source.dataset,
                          "settings": repr(settings)}, indent=1))
        return 0

    if args.command in ("collect", "backfill"):
        source = build_source(args.source, settings)
        dry = args.dry_run
        state = None if dry and args.command == "backfill" else open_state(settings)
        store = DiscardObjectStore() if dry else open_store(settings)
        try:
            stage = BronzeStage(settings, source, state, store)
            if args.command == "backfill":
                if args.end <= args.start:
                    raise ConfigError("--to must be after --from")
                windows = windows_between(args.start, args.end, settings.window)
                summary = stage.run(windows=windows[:1] if dry else windows, dry_run=dry)
            else:
                summary = stage.run(max_windows=args.max_windows, dry_run=dry)
        finally:
            source.close()
            if state is not None:
                state.close()
        print(json.dumps({
            "run_id": summary.run_id, "source": summary.source, "ok": summary.ok, "records": summary.records,
            "committed_until": summary.committed_until.isoformat() if summary.committed_until else None,
            "windows": [{"window": str(o.window), "scan": o.scan_kind, "ok": o.ok, "records": o.records,
                         "quarantined": o.quarantined, "duplicates": o.duplicates, "splits": o.splits,
                         "error": o.error} for o in summary.outcomes],
            "dry_run_objects": getattr(store, "objects", None) if dry else None,
        }, indent=1, default=str))
        return 0 if summary.ok else 1

    state = open_state(settings)
    try:
        now = utcnow()
        if args.command == "index":
            sinks = _sinks(settings)
            if not sinks:
                raise ConfigError("no curated sink configured: set DATABASE_URL and/or OPENSEARCH_URL")
            summary = IndexStage(settings, state, open_store(settings), sinks).run(limit=args.limit,
                                                                                 source=args.source)
            print(json.dumps({"processed": summary.processed, "failed": summary.failed, "dead": summary.dead},
                             indent=1))
            return 0 if summary.failed == 0 else 1
        if args.command == "status":
            return _status(state, args, now)
        if args.command == "skip-window":
            source = build_source(args.source, settings)
            window = Window(args.window_start, args.window_start + settings.window)
            state.mark_skipped(source.name, source.dataset, window, now, args.actor, args.reason)
            state.advance_watermark(source.name, source.dataset, now)
            print(f"skipped {window} for {source.name}/{source.dataset}")
            return 0
        if args.command == "requeue-dead":
            count = state.requeue_dead(now, args.actor, args.reason, args.source)
            print(f"requeued {count} dead outbox item(s)")
            return 0
        if args.command == "reset-watermark":
            if not args.yes:
                raise ConfigError("refusing without --yes; read docs/runbooks.md 'Reset a watermark' first")
            source = build_source(args.source, settings)
            state.reset_watermark(source.name, source.dataset, args.to, now, args.actor, args.reason)
            print(f"watermark for {source.name}/{source.dataset} set to {args.to.isoformat()}")
            return 0
    finally:
        state.close()
    return 2


def _status(state, args: argparse.Namespace, now: datetime) -> int:
    from datetime import timedelta

    since = now - timedelta(hours=args.hours)
    rows = state.recent_windows(args.source, since)
    by_key: dict[tuple[str, str], list] = {}
    for row in rows:
        by_key.setdefault((row.source, row.dataset), []).append(row)
    report = {"outbox": state.outbox_counts(), "sources": []}
    for (source, dataset), items in sorted(by_key.items()):
        statuses: dict[str, int] = {}
        for item in items:
            statuses[item.status] = statuses.get(item.status, 0) + 1
        gaps = []
        ordered = sorted(items, key=lambda r: r.window.start)
        for prev, nxt in zip(ordered, ordered[1:], strict=False):
            if prev.window.end != nxt.window.start:
                gaps.append(f"{prev.window.end.isoformat()} -> {nxt.window.start.isoformat()}")
        report["sources"].append({
            "source": source, "dataset": dataset,
            "committed_until": (state.committed_until(source, dataset) or now).isoformat(),
            "windows": statuses, "records": sum(i.record_count for i in items),
            "quarantined": sum(i.quarantined_count for i in items),
            "failed_windows": [{"window": str(i.window), "attempts": i.attempts, "error": i.last_error}
                               for i in items if i.status == "failed"],
            "ledger_gaps": gaps,
        })
    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print(f"outbox: {report['outbox']}")
        for s in report["sources"]:
            print(f"- {s['source']}/{s['dataset']}: committed_until={s['committed_until']} windows={s['windows']} "
                  f"records={s['records']} quarantined={s['quarantined']}")
            for f in s["failed_windows"]:
                print(f"    FAILED {f['window']} attempts={f['attempts']}: {f['error']}")
            for g in s["ledger_gaps"]:
                print(f"    GAP {g}")
    failing = any(s["failed_windows"] for s in report["sources"]) or report["outbox"].get("dead", 0)
    return 1 if failing else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
