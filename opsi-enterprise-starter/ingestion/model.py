"""Normalize only essential fields; keep source record in JSON for later mappings."""
import json, hashlib
from datetime import datetime, timezone
from .config import TENANT

def utc_string(value):
    if isinstance(value,(float,int)):
        # vendor millisecond timestamps
        return datetime.fromtimestamp(value/1000 if value > 100_000_000_000 else value, timezone.utc).isoformat()
    if value is None: return datetime.now(timezone.utc).isoformat()
    if isinstance(value,datetime): return value.astimezone(timezone.utc).isoformat()
    if isinstance(value,str):
        try: return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc).isoformat()
        except ValueError: return value
    return str(value)

def normalize(source, raw, origin_id=None):
    stable = origin_id or hashlib.sha256(json.dumps(raw,sort_keys=True,default=str).encode()).hexdigest()
    event_uid = hashlib.sha256(f'{source}:{stable}'.encode()).hexdigest()
    timestamp = raw.get('@timestamp') or raw.get('timestamp') or raw.get('startTime') or raw.get('startTimeMs')
    return {
      'tenant_id':TENANT,'source':source,'event_uid':event_uid,'event_time':utc_string(timestamp),
      'severity':str(raw.get('loglevel') or raw.get('status') or raw.get('severity') or 'UNKNOWN'),
      'service_id':str(raw.get('dt.entity.service') or raw.get('service.name') or raw.get('serviceId') or ''),
      'message':str(raw.get('content') or raw.get('displayName') or raw.get('message') or '')[:4000],
      'raw_json':json.dumps(raw,ensure_ascii=False,default=str),
    }
