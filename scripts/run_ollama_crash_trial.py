"""Kill only this trial's owned controller during a real delegated GPU request."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from measure_comfy_workload import APP,gpu_sample,prepare_unloaded_condition,validate_trial_preflight
from core.process_ownership import ProcessOwnership
from core.task_store import TaskStore
from core.operation_journal import OperationJournal
from engine import queue
from engine.coordinator import restore_resource_operations,get_coordinator,reconcile_uncertain
from run_profiled_ollama_trial import redact


def windows_identity(handle=None):
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    handle=handle if handle is not None else kernel.GetCurrentProcess()
    times=[wintypes.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]): raise OSError('process time unavailable')
    size=wintypes.DWORD(32768);buffer=ctypes.create_unicode_buffer(size.value)
    if not kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)): raise OSError('process image unavailable')
    return dict(creation_time=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime,
                image=os.path.normcase(os.path.realpath(buffer.value)))


class OwnedController:
    """Keep a native handle, fencing PID reuse and Windows venv redirectors."""
    def __init__(self,process,identity):
        self.process=process;self.handle=None
        if identity['pid']!=process.pid and identity.get('parent_pid')!=process.pid:
            raise ValueError('controller is not the launched process or its child')
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes
            self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            self.kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            self.kernel.OpenProcess.restype=wintypes.HANDLE
            self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            self.kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
            self.kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
            self.handle=self.kernel.OpenProcess(0x1000|0x0001|0x00100000,False,identity['pid'])
            if not self.handle: raise OSError('owned process handle unavailable')
            observed=windows_identity(self.handle)
            expected_image=os.path.normcase(os.path.realpath(sys._base_executable))
            if observed['creation_time']!=identity['creation_time'] or observed['image']!=expected_image:
                self.close();raise ValueError('native creation time or executable mismatch')
        elif identity['pid']!=process.pid:
            raise ValueError('unexpected controller indirection')

    def terminate(self):
        if self.handle is not None:
            if not self.kernel.TerminateProcess(self.handle,1): raise OSError('owned termination failed')
            if self.kernel.WaitForSingleObject(self.handle,10000)!=0: raise TimeoutError('owned process still live')
        else: self.process.terminate()
        return self.process.wait(timeout=10)

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle);self.handle=None


def parent(args):
    owner=ProcessOwnership(APP/'data/tasks.sqlite3').acquire()
    store=TaskStore(APP/'data/tasks.sqlite3');journal=OperationJournal(store.path)
    restore_resource_operations();validate_trial_preflight(store,journal)
    prepare_unloaded_condition(12800)
    request=json.loads(Path(args.raw).read_bytes())['request']
    accepted=queue.queue_enqueue_ollama(request)
    if not accepted.get('ok'): raise ValueError('parent acceptance failed')
    task_id=accepted['task']['id']
    with Path(args.parent_status).open('x',encoding='utf-8') as file:
        identity=dict(pid=os.getpid(),parent_pid=os.getppid(),task_id=task_id)
        if os.name=='nt': identity.update(windows_identity())
        json.dump(identity,file)
    while queue._store().get(task_id)['status'] not in TaskStore.TERMINAL:
        time.sleep(0.1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',required=True);parser.add_argument('--profile-dir',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--parent',action='store_true')
    parser.add_argument('--parent-status')
    args=parser.parse_args()
    os.environ['GMAE_PROFILE_DIR']=str(Path(args.profile_dir).resolve())
    if args.parent: return parent(args)
    output=Path(args.output)
    marker=output.with_name(output.stem+'-parent.json')
    if output.exists() or marker.exists(): raise ValueError('refusing evidence overwrite')
    output.parent.mkdir(parents=True,exist_ok=True)
    store=TaskStore(APP/'data/tasks.sqlite3');journal=OperationJournal(store.path)
    validate_trial_preflight(store,journal)
    document=dict(kind='real_ollama_controller_crash_trial',recorded_at=datetime.now(timezone.utc).isoformat(),
                  samples=[],sampling_errors=[])
    options=dict(stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
    if os.name=='nt': options['creationflags']=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP
    else: options['start_new_session']=True
    process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--parent','--parent-status',str(marker),
        '--raw',args.raw,'--profile-dir',args.profile_dir,'--output',args.output],**options)
    document['launcher_pid']=process.pid
    stop=threading.Event()
    def sample():
        while not stop.is_set():
            try: document['samples'].append(gpu_sample())
            except Exception as error: document['sampling_errors'].append(type(error).__name__)
            stop.wait(0.2)
    worker=threading.Thread(target=sample);worker.start();owner=None;controller=None
    try:
        deadline=time.monotonic()+240
        while True:
            if process.poll() is not None: raise RuntimeError('controller ended before fault injection')
            if marker.exists():
                identity=json.loads(marker.read_text());task_id=identity['task_id']
                if controller is None:
                    controller=OwnedController(process,identity)
                    document['controller_pid']=identity['pid']
                    document['controller_creation_time']=identity.get('creation_time')
                records=[r for r in journal.pending() if r['intent']['owner']=='job:'+task_id]
                if records:
                    operation=records[0];commands=journal.commands(operation['id'])
                    delegated=[c for c in commands if len(c['intent'])==5 and c['intent'][-2]==task_id
                               and Path(c['intent'][1]).name=='ollama_worker.py']
                    physical=gpu_sample()
                    if (len(delegated)==1 and delegated[0]['state']=='inflight'
                            and journal.command_result(delegated[0]['id']) is None
                            and store.get(task_id)['status']=='submitting' and physical['used_mb']>=4096):
                        command=delegated[0]
                        document['before_crash']=dict(task_id=task_id,task_status='submitting',gpu=physical,
                            command_id=command['id'],command_state=command['state'],
                            command_intent_sha256=hashlib.sha256(json.dumps(command['intent']).encode()).hexdigest(),
                            durable_response_present=False)
                        break
            if time.monotonic()>deadline: raise TimeoutError('fault boundary not observed; do not replay')
            time.sleep(0.1)
        # This handle belongs to the controller launched above. No service or
        # unrelated process is stopped. Independent supervisor remains alive.
        document['controller_exit_code']=controller.terminate()
        owner=ProcessOwnership(APP/'data/tasks.sqlite3').acquire()
        document['gpu_ownership_reacquired']=True
        restore_resource_operations();queue.queue_restore()
        document['after_restore']=dict(task_status=store.get(task_id)['status'],active=get_coordinator().snapshot()['active'])
        document['initial_reconcile']=reconcile_uncertain()
        deadline=time.monotonic()+180
        while journal.command_result(command['id']) is None:
            if time.monotonic()>deadline: raise TimeoutError('observe existing supervisor; no replay')
            time.sleep(0.1)
        document['reconcile']=reconcile_uncertain()
        task=store.get(task_id)
        if task['status']!='done' or get_coordinator().snapshot()['active'] is not None or journal.pending():
            raise ValueError('exact durable recovery not confirmed')
        result=task['checkpoint'].get('result',{})
        result.pop('response',None)
        document.update(status='success',task_after=task,operation_after=journal.get(operation['id']),
                        commands_after=journal.commands(operation['id']),coordination_after=None,pending_operations_after=0)
        for row in document['commands_after']:
            row['intent_sha256']=hashlib.sha256(json.dumps(row.pop('intent')).encode()).hexdigest()
    except Exception as error:
        document.update(status='failed',error=str(error));raise
    finally:
        stop.set();worker.join(15);document['sampler_stopped']=not worker.is_alive()
        if controller is not None: controller.close()
        if document['samples']:
            document['observed_whole_device_peak_mb']=max(max(s['used_mb'],s['total_mb']-s['free_mb']) for s in document['samples'])
        with output.open('x',encoding='utf-8',newline='\n') as file: json.dump(redact(document),file,indent=2,allow_nan=False)
        print(json.dumps({key:document.get(key) for key in ('status','controller_exit_code','observed_whole_device_peak_mb')}))


if __name__=='__main__': main()
