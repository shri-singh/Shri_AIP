"""Read-only source adapters. Source credentials never logged."""
import os, time
from datetime import datetime, timezone
from typing import Iterator
import requests
from elasticsearch import Elasticsearch, helpers
from .config import env, integer

def elastic(start: datetime,end: datetime) -> Iterator[tuple[str,dict]]:
    host=env('ELASTIC_URL'); pattern=env('ELASTIC_INDEX_PATTERN','logs-*')
    if not host: raise ValueError('ELASTIC_URL missing')
    api_key=env('ELASTIC_API_KEY')
    username=env('ELASTIC_USERNAME'); password=env('ELASTIC_PASSWORD')
    kwargs={'hosts':[host], 'request_timeout':120}
    if api_key: kwargs['api_key']=api_key
    elif username: kwargs['basic_auth']=(username,password)
    es=Elasticsearch(**kwargs)
    field=env('ELASTIC_TIMESTAMP_FIELD','@timestamp')
    q={'query':{'range':{field:{'gte':start.isoformat(),'lt':end.isoformat()}}}}
    for hit in helpers.scan(es,index=pattern,query=q,scroll='2m',size=500,request_timeout=120):
        yield f"{hit.get('_index')}:{hit.get('_id')}",hit.get('_source') or {}

def problems(start,end):
    base=env('DYNATRACE_ENV_URL').rstrip('/')
    token=env('DYNATRACE_API_TOKEN')
    if not base or not token: raise ValueError('DYNATRACE_ENV_URL or DYNATRACE_API_TOKEN missing')
    url=base+'/api/v2/problems'
    headers={'Authorization':'Api-Token '+token}
    params={'from':str(int(start.timestamp()*1000)), 'to':str(int(end.timestamp()*1000)), 'pageSize':500}
    while True:
        response=requests.get(url,headers=headers,params=params,timeout=60); response.raise_for_status()
        data=response.json()
        for item in data.get('problems',[]):
            yield str(item.get('problemId') or item.get('displayId') or ''),item
        nxt=data.get('nextPageKey')
        if not nxt: break
        params={'nextPageKey':nxt}  # subsequent pages: omit original filters per Dynatrace docs

def grail_logs(start,end):
    """Grail REST query starter. Hard cap to avoid silent truncation; split production windows."""
    base=env('DYNATRACE_PLATFORM_URL').rstrip('/')
    bearer=env('DYNATRACE_PLATFORM_BEARER_TOKEN')
    if not base or not bearer: raise ValueError('DYNATRACE_PLATFORM_URL or bearer token missing')
    limit=integer('DYNATRACE_GRAIL_RESULT_LIMIT',5000)
    url=base+'/platform/storage/query/v1/'
    headers={'Authorization':'Bearer '+bearer,'Content-Type':'application/json'}
    # DQL supports absolute timeframe range in ISO 8601 form; review per environment.
    interval=f'{start.isoformat().replace("+00:00","Z")}/{end.isoformat().replace("+00:00","Z")}'
    query=f'fetch logs, timeframe: "{interval}" | limit {limit}'
    r=requests.post(url+'query:execute',json={'query':query},headers=headers,timeout=65)
    r.raise_for_status(); state=r.json()
    for i in range(30):
        if state.get('state') == 'SUCCEEDED': break
        if state.get('state') in ('FAILED','CANCELLED','RESULT_GONE'):
            raise RuntimeError(f'Grail query failed, state={state.get("state")}')
        token=state.get('requestToken')
        if not token: raise RuntimeError('Grail query missing requestToken')
        time.sleep(2)
        r=requests.get(url+'query:poll',params={'request-token':token},headers=headers,timeout=65)
        r.raise_for_status(); state=r.json()
    else: raise TimeoutError('Grail query did not finish within polling budget')
    records=(state.get('result') or {}).get('records') or []
    if len(records)>=limit:
        raise RuntimeError('Grail result hit configured limit; split time windows before checkpointing')
    for item in records:
        if not isinstance(item,dict): continue
        # Event UID from Dynatrace if present, else stable payload hash.
        yield str(item.get('event.id') or item.get('id') or ''),item
