# NGINX

```bash
sudo nginx -t                                  # always before reload
sudo nginx -T | grep -n -E "server_name|listen|location|proxy_pass|include" | less
sudo systemctl reload nginx                    # graceful
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
sudo cp infrastructure/nginx/opsi-revamp.locations.conf /etc/nginx/snippets/
# zones (http{} level): /etc/nginx/conf.d/opsi-revamp-zones.conf with the two limit_req_zone lines
```

## SSE essentials (already in the snippet)
```
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_buffering off;          # or the backend's X-Accel-Buffering: no header
proxy_cache off;
proxy_read_timeout 300s;      # longer than the longest agent run; runtime keep-alives every 15 s
```
ALB/ELB in front? Raise its idle timeout to >= 300 s too.

## Debug a streaming request
```bash
curl -N -v https://opsi-revamp.corp.example/api/copilotkit/info -H "Authorization: Bearer $T"
# access log with timing: log_format timed '$remote_addr "$request" $status $body_bytes_sent rt=$request_time urt=$upstream_response_time';
```
Common errors: `502` upstream not listening (runtime down); `504` read timeout too short; `413` body too large
(`client_max_body_size`); `upstream prematurely closed` runtime crash - check `journalctl -u opsi-copilot-runtime`.

Local validation (no root needed): copy the snippet into a tiny test config and run `nginx -t -p <dir> -c <file>` (done
during kit build with nginx 1.28).
