"""Run `python -m ingestion.run_once --source elastic|dynatrace_problems|dynatrace_grail`."""
import argparse, os
from datetime import datetime,timezone,timedelta
from .config import BATCH_SIZE,integer
from .checkpoints import read,write
from .model import normalize
from .sinks import write_both
from . import sources

ADAPTERS={'elastic':sources.elastic,'dynatrace_problems':sources.problems,'dynatrace_grail':sources.grail_logs}

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--source',choices=ADAPTERS,required=True)
    args=parser.parse_args()
    now=datetime.now(timezone.utc)
    end=now-timedelta(seconds=integer('INGEST_LAG_SECONDS',120))
    last=read(args.source)
    if last:
        start=last-timedelta(seconds=integer('INGEST_OVERLAP_SECONDS',60))
    else:
        start=end-timedelta(minutes=integer('INGEST_LOOKBACK_MINUTES',10))
    max_end=start+timedelta(minutes=integer('INGEST_WINDOW_MAX_MINUTES',10))
    end=min(end,max_end)
    if start>=end: print(f'No new window for {args.source}',flush=True); return
    print(f'Begin {args.source} UTC [{start.isoformat()}, {end.isoformat()})',flush=True)
    batch=[]; count=0; batch_no=0
    # Fail closed on any source/read/S3/DB exception. Only advance watermark after all complete.
    for identity, record in ADAPTERS[args.source](start,end):
        batch.append(normalize(args.source,record,identity or None))
        if len(batch)>=BATCH_SIZE:
            write_both(args.source,batch,start,end,batch_no)
            count+=len(batch); batch_no+=1; batch=[]
    if batch:
        write_both(args.source,batch,start,end,batch_no); count+=len(batch)
    write(args.source,end)
    print(f'Committed watermark {end.isoformat()} records={count}',flush=True)

if __name__=='__main__': main()
