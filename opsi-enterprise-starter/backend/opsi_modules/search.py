"""Read-only exact/lexical incident retrieval; tenant filter mandatory."""
from typing import Any
import requests

def search_incidents(base_url:str,index:str,query:str,tenant_id:str,minutes:int=60,limit:int=25,
                     auth:tuple[str,str]|None=None)->dict[str,Any]:
    if not tenant_id or not index.startswith('opsi-'):
        raise ValueError('Tenant and Opsi-owned index are required')
    if not 1<=limit<=100 or not 1<=minutes<=10080:
        raise ValueError('Query window/size outside allowed range')
    body={'size':limit,'query':{'bool':{
       'must':[{'multi_match':{'query':query,'fields':['message^2','service_id','severity']}}],
       'filter':[{'term':{'tenant_id.keyword':tenant_id}},
                 {'range':{'event_time':{'gte':f'now-{minutes}m','lte':'now'}}}]
    }},'sort':[{'event_time':'desc'}]}
    resp=requests.post(f'{base_url.rstrip("/")}/{index}/_search',json=body,auth=auth,timeout=20)
    resp.raise_for_status(); return resp.json()
