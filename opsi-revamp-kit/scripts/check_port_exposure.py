#!/usr/bin/env python3
"""Fail closed if a merged Compose config publishes ports beyond loopback.

Reads the JSON produced by ``docker compose ... config --format json`` (stdin or file)
and exits 1 when any published port binds to 0.0.0.0 / :: / no explicit host_ip, or
when a service uses host networking without being on the allowlist.

    docker compose -f a.yml -f b.yml config --format json | python3 scripts/check_port_exposure.py
    python3 scripts/check_port_exposure.py merged.json --allow-host-network copilot-runtime

Docker publishes ports by inserting its own iptables rules, which BYPASS host firewalls such
as firewalld/ufw. Binding to 127.0.0.1 is therefore the only reliable host-level control;
security groups are the second layer.
"""
from __future__ import annotations

import argparse
import json
import sys

DANGEROUS_PORTS = {5432: "PostgreSQL", 9200: "Elasticsearch/OpenSearch HTTP", 9300: "OpenSearch transport",
                   5005: "JVM remote debugger (JDWP)", 8080: "Airflow UI", 6379: "Redis", 2375: "Docker API"}


def check(config: dict, allow_host_network: set[str]) -> list[str]:
    problems: list[str] = []
    for name, svc in (config.get("services") or {}).items():
        if svc.get("network_mode") == "host" and name not in allow_host_network:
            problems.append(f"{name}: network_mode=host (not allowlisted)")
        for port in svc.get("ports") or []:
            if isinstance(port, str):  # short syntax should not survive `config`, but be safe
                problems.append(f"{name}: unparsed port spec {port!r}")
                continue
            host_ip = port.get("host_ip") or ""
            published = port.get("published")
            target = port.get("target")
            if published in (None, ""):
                continue
            if host_ip not in ("127.0.0.1", "::1"):
                label = DANGEROUS_PORTS.get(int(target or 0), "")
                problems.append(f"{name}: port {published}->{target} bound to '{host_ip or '0.0.0.0'}'"  # noqa: S104
                                f"{' (' + label + ')' if label else ''}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", help="merged config JSON (default: stdin)")
    ap.add_argument("--allow-host-network", action="append", default=[])
    args = ap.parse_args()
    raw = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
    problems = check(json.loads(raw), set(args.allow_host_network))
    if problems:
        print("PORT EXPOSURE CHECK FAILED:")
        for p in problems:
            print(f"  - {p}")
        print("Bind to 127.0.0.1 (\"127.0.0.1:HOST:CONTAINER\") or remove the port; see docs/deployments.md.")
        return 1
    print("port exposure check passed: nothing published beyond loopback")
    return 0


if __name__ == "__main__":
    sys.exit(main())
