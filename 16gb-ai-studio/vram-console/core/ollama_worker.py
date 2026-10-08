"""One-shot delegated RPC; request comes from immutable original task intent."""
import json
from pathlib import Path
import sys
import urllib.request
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.task_store import TaskStore
from core.workload_profile import workload_fingerprint


def execute(path,task_id,request_sha256,fetch=None):
    task=TaskStore(path).get(task_id)
    if (not task or task['status']!='submitting' or task['intent'].get('source')!='ollama'
            or task['intent'].get('workflow_sha256')!=request_sha256):
        raise ValueError('delegated task identity/state mismatch')
    request=task['intent']['effective_workflow']
    if workload_fingerprint(request)!=request_sha256 or request['model']!=task['intent']['model']:
        raise ValueError('delegated immutable request mismatch')
    if fetch is None:
        rpc=urllib.request.Request('http://127.0.0.1:11434/api/generate',data=json.dumps(request).encode(),
                                   headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(rpc,timeout=300) as response: result=json.load(response)
    else:
        result=fetch(request)
    # Bound durable command output, including JSON escaping. The full response
    # still needs validation by the parent/recovery adapter before releasing GPU.
    payload=json.dumps(result,ensure_ascii=True,allow_nan=False)
    if len(payload)>60000: raise ValueError('response exceeds durable receipt limit')
    return payload


if __name__=='__main__':
    print(execute(sys.argv[1],sys.argv[2],sys.argv[3]))
