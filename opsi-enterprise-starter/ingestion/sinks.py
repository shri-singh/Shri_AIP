"""Deterministic object keys; optional curated PG sink, checkpoint only after both complete."""
import json, tempfile
from pathlib import Path
import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from .config import BUCKET,REGION

def upload_parquet(source, rows, start, end, batch_no):
    if not BUCKET or BUCKET.startswith('replace-'):
        raise ValueError('Set OPSI_ARCHIVE_BUCKET to approved bucket')
    if not rows: return None
    s=start.strftime('%Y%m%dT%H%M%SZ'); e=end.strftime('%Y%m%dT%H%M%SZ')
    key=f'raw/{source}/dataset=events/dt={start:%Y-%m-%d}/window={s}_{e}/part-{batch_no:06d}.parquet'
    table=pa.Table.from_pylist(rows)
    with tempfile.TemporaryDirectory() as td:
        file=Path(td)/'batch.parquet'
        pq.write_table(table,file,compression='snappy')
        boto3.client('s3',region_name=REGION).upload_file(str(file),BUCKET,key,ExtraArgs={'ServerSideEncryption':'AES256'})
    return f's3://{BUCKET}/{key}'

def upsert_pg(rows):
    import os
    uri=os.environ.get('DATABASE_URL')
    if not uri: return 0  # S3-only mode
    from psycopg import connect
    from psycopg.types.json import Jsonb
    statement="""INSERT INTO opsi_ingest.incident_events
      (tenant_id,source,event_uid,event_time,severity,service_id,message,raw)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
      ON CONFLICT (tenant_id,source,event_uid) DO UPDATE SET
      event_time=excluded.event_time,severity=excluded.severity,
      service_id=excluded.service_id,message=excluded.message,raw=excluded.raw"""
    with connect(uri) as con:
        with con.cursor() as cur:
            cur.executemany(statement, [
                (r['tenant_id'],r['source'],r['event_uid'],r['event_time'],
                 r['severity'],r['service_id'],r['message'],Jsonb(json.loads(r['raw_json']))) for r in rows
            ])
    return len(rows)

def write_both(source, rows, start, end, batch_no):
    if not rows: return
    path=upload_parquet(source,rows,start,end,batch_no)
    count=upsert_pg(rows)
    print(f'source={source} batch={batch_no} rows={len(rows)} s3={path} postgres={count}',flush=True)
