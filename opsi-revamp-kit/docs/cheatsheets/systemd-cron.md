# systemd and cron

## Install / manage the kit's units
```bash
sudo cp infrastructure/systemd/*.service infrastructure/systemd/*.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/opsi-collect@.service     # syntax check
sudo systemctl daemon-reload
sudo systemctl enable --now opsi-collect@elastic.timer opsi-index.timer opsi-ingest-status.timer
systemctl list-timers --all | grep opsi
sudo systemctl start opsi-collect@elastic.service      # run once now (oneshot)
systemctl status opsi-collect@elastic.service --no-pager
sudo systemctl disable --now opsi-collect@elastic.timer
systemctl cat opsi-collect@elastic.service              # effective unit
sudo systemctl edit opsi-collect@.service               # drop-in override (e.g. MemoryMax)
```

## Logs (journald)
```bash
journalctl -u opsi-collect@elastic -n 100 --no-pager
journalctl -u opsi-copilot-runtime -f
journalctl -t opsi-alert --since yesterday
journalctl -u opsi-index --since "2026-10-24 10:00" --until "2026-10-24 11:00" -o json-pretty | jq '.MESSAGE' | head
```
The collectors log JSON lines; filter: `journalctl -u opsi-collect@elastic -o cat | jq -c 'select(.event=="window_failed")'`.

## Timer syntax
`OnCalendar=*:0/5` every 5 minutes; `*:2/5` minutes 2,7,12...; `*-*-* 06:15:00 UTC` daily; test with
`systemd-analyze calendar '*:2/5'`.

## Cron (lab)
```bash
crontab -l > /tmp/cron.bak            # backup first
crontab -e                            # add lines from infrastructure/cron/crontab.example
grep CRON /var/log/cron 2>/dev/null || journalctl -u crond --since -1h
/usr/bin/flock -n /var/lib/opsi-ingest/collect-elastic.lock true && echo "lock free"
sudo logrotate -d /etc/logrotate.d/opsi-ingest     # dry-run rotation
```
Cron runs with a minimal PATH/env: always use absolute paths and source the env file in the wrapper.
