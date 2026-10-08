import json
from pathlib import Path
import sys
repo=Path(__file__).resolve().parents[1]/'GMae-16GAS'
sys.path.insert(0,str(repo/'scripts'))
from measure_comfy_workload import APP,prepare_unloaded_condition,validate_trial_preflight
from core.process_ownership import ProcessOwnership
from core.task_store import TaskStore
from core.operation_journal import OperationJournal
from engine.coordinator import restore_resource_operations
owner=ProcessOwnership(APP/'data/tasks.sqlite3').acquire()
store=TaskStore(APP/'data/tasks.sqlite3');journal=OperationJournal(store.path)
restore_resource_operations();validate_trial_preflight(store,journal)
evidence=prepare_unloaded_condition(12800)
validate_trial_preflight(store,journal)
with Path(__file__).with_name('mixed-final-unload-20261008.json').open('x',encoding='utf-8',newline='\n') as file:
    json.dump(evidence,file,indent=2)
print(json.dumps({'condition':evidence['condition'],'free_mb':evidence['readings'][-1]['gpu']['free_mb']}))
