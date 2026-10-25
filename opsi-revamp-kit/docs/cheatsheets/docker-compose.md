# Docker and Compose v2

```bash
docker compose version                         # need >= 2.24 for !reset / !override
docker info | sed -n '1,30p'
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
docker logs --tail 200 -f <container>
docker inspect <container> --format '{{json .HostConfig.PortBindings}}' | jq   # what is published where
docker inspect <container> --format '{{json .State.Health}}' | jq
docker stats --no-stream
docker system df; docker image prune -f        # cleanup (not volumes)
docker volume ls; docker volume inspect <v>     # data lives here - think before `down -v`
```

## Compose with the kit
```bash
scripts/compose_safe.sh opsi-revamp config      # render + exposure check (fails closed)
scripts/compose_safe.sh opsi-revamp up
scripts/compose_safe.sh opsi-revamp ps
TAIL=500 scripts/compose_safe.sh opsi-revamp logs
scripts/compose_safe.sh opsi-revamp down        # volumes kept
docker compose -p opsi-revamp --env-file /etc/opsi/revamp.env -f infrastructure/compose/opsi-revamp.compose.yml config --format json | jq '.services|keys'
```

## Override merge rules (why the lab override uses tags)
- Lists like `ports`, `expose`, `dns` are **appended** across files.
- `ports: !reset []` removes all ports from earlier files; `ports: !override [ ... ]` replaces them.
- Maps (`environment`) merge key by key - override values win.
- Verify: `docker compose -f base.yml -f override.yml config` and run `scripts/check_port_exposure.py` on the JSON.

## Port binding
`"127.0.0.1:8585:8585"` = loopback only. `"8585:8585"` = all interfaces, **bypassing host firewalls** (Docker iptables).
