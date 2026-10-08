"""Installed raw evidence, fresh execution identity, and conservative peak budgets."""
import hashlib
import json
import os
from pathlib import Path
import threading
import urllib.request
from core.config import BASE_DIR
from core.resource_coordinator import ResourceDenied
from core.workload_profile import (profile_from_evidence, match_profile, workload_fingerprint,
                                   execution_configuration_fingerprint)
from core.utils import run_args
from clients.docker_client import _get_docker_cmd
from core.phase_profile import phase_profile_from_evidence, match_resident_phase
from clients.comfyui_client import residency_snapshot

_digest_cache = {}
_digest_lock = threading.Lock()


def _root():
    return Path(os.environ.get('GMAE_PROFILE_DIR', str(Path(BASE_DIR) / 'data' / 'profiles')))


def select_profile(workflow):
    """Pin installed evidence at acceptance; HTTP callers cannot provide peaks."""
    digest = workload_fingerprint(workflow)
    profile_key = execution_configuration_fingerprint(workflow)
    manifest_path = _root() / (profile_key + '.json')
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_bytes())
        filename = manifest['raw_file']
        if not isinstance(filename, str) or Path(filename).name != filename or '/' in filename or '\\' in filename:
            raise ValueError('evidence must be a direct local filename')
        payload = (_root() / filename).read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest['raw_sha256']:
            raise ValueError('raw evidence digest mismatch')
        profile = profile_from_evidence(payload, manifest['margin_mb'])
        if profile['execution_configuration_sha256'] != profile_key:
            raise ValueError('workflow evidence mismatch')
        reference = dict(workflow_sha256=digest, profile_key=profile_key, raw_sha256=manifest['raw_sha256'],
                         margin_mb=manifest['margin_mb'])
        if 'resident_raw_file' in manifest:
            resident_payload = _resident_payload(manifest)
            resident = phase_profile_from_evidence(resident_payload, manifest['margin_mb'])
            if (resident['execution_configuration_sha256'] != profile_key or
                    resident['environment'] != profile['environment']):
                raise ValueError('resident profile configuration/environment mismatch')
            reference['resident_raw_sha256'] = manifest['resident_raw_sha256']
        return reference
    except Exception as error:
        raise ResourceDenied('PROFILE_UNVERIFIED', '已安装 Profile 证据无效: ' + str(error)) from error



def _resident_payload(manifest):
    filename = manifest['resident_raw_file']
    if not isinstance(filename, str) or Path(filename).name != filename or '/' in filename or '\\' in filename:
        raise ValueError('resident evidence must be a direct local filename')
    payload = (_root() / filename).read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest['resident_raw_sha256']:
        raise ValueError('resident evidence digest mismatch')
    return payload


def _live_artifact_identity(environment):
    path = '/opt/ComfyUI/models/checkpoints/sd_xl_base_1.0.safetensors'
    script = 'from pathlib import Path;import hashlib,json,sys;p=Path(sys.argv[1]);s=p.stat();print(json.dumps(dict(file_identity=[s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns],path_sha256=hashlib.sha256(str(p.resolve()).encode()).hexdigest())))'
    rc, output = run_args([_get_docker_cmd(), 'exec', 'comfyui', 'python3', '-c', script, path], 10)
    if rc:
        raise ValueError('fresh artifact metadata unavailable')
    return {**json.loads(output), 'model_digest': environment['model_digest']}


def _live_environment(raw):
    """Read identity; rehash model whenever container/file metadata changes.

    Cache assumes ordinary immutable model deployment, not adversarial metadata
    spoofing. Fresh container ID and file inode/ctime/mtime/size fence replacement.
    """
    rc, output = run_args(['nvidia-smi', '--id=0',
        '--query-gpu=name,uuid,driver_version,memory.total', '--format=csv,noheader,nounits'], 10)
    if rc:
        raise ValueError('GPU identity unavailable')
    name, gpu_uuid, driver, total = [part.strip() for part in output.strip().split(',')]
    with urllib.request.urlopen('http://127.0.0.1:8188/system_stats', timeout=10) as response:
        stats = json.load(response)
    system = stats['system']
    backend = {key: system[key] for key in ('comfyui_version', 'python_version', 'pytorch_version')}
    if not isinstance(system.get('argv'), list) or not system['argv']:
        raise ValueError('backend launch identity unavailable')
    backend['launch_args_sha256'] = hashlib.sha256(json.dumps(system['argv'], sort_keys=True).encode()).hexdigest()
    filename = raw['model_artifact']['filename']
    if filename != 'sd_xl_base_1.0.safetensors':
        raise ValueError('artifact verification currently supports SDXL checkpoint only')
    allowed = {'CheckpointLoaderSimple', 'CLIPTextEncode', 'EmptyLatentImage',
               'KSampler', 'VAEDecode', 'SaveImage'}
    loaders = [node for node in raw['workflow'].values() if node.get('class_type') == 'CheckpointLoaderSimple']
    if (any(node.get('class_type') not in allowed for node in raw['workflow'].values()) or
            len(loaders) != 1 or loaders[0].get('inputs', {}).get('ckpt_name') != filename):
        raise ValueError('workflow artifact coverage unsupported')
    path = '/opt/ComfyUI/models/checkpoints/' + filename
    docker = _get_docker_cmd()
    rc, container_id = run_args([docker, 'inspect', '--format', '{{.Id}}', 'comfyui'], 10)
    if rc or not container_id.strip():
        raise ValueError('container identity unavailable')
    script = 'import os,json,sys;s=os.stat(sys.argv[1]);print(json.dumps([s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]))'
    rc, stamp = run_args([docker, 'exec', 'comfyui', 'python3', '-c', script, path], 10)
    if rc:
        raise ValueError('model file identity unavailable')
    identity = (container_id.strip(), path, tuple(json.loads(stamp)))
    with _digest_lock:
        model_digest = _digest_cache.get(identity)
        if model_digest is None:
            rc, output = run_args([docker, 'exec', 'comfyui', 'sha256sum', path], 120)
            if rc:
                raise ValueError('model digest unavailable')
            model_digest = output.split()[0]
            if len(model_digest) != 64 or any(c not in '0123456789abcdef' for c in model_digest):
                raise ValueError('invalid model digest')
            _digest_cache.clear()  # bounded; current supported checkpoint only
            _digest_cache[identity] = model_digest
    return dict(gpu=name + ':' + hashlib.sha256(gpu_uuid.encode()).hexdigest() + ':' + str(int(total)),
                driver=driver, model_digest=model_digest, backend=workload_fingerprint({'backend': backend}))


def measured_budget(workflow, reference):
    """Recompute from pinned raw bytes and check live identity before each budget."""
    try:
        current = select_profile(workflow)
        if current is None or current != reference:
            raise ValueError('accepted evidence changed or disappeared')
        manifest = json.loads((_root() / (current['profile_key'] + '.json')).read_bytes())
        payload = (_root() / manifest['raw_file']).read_bytes()
        if hashlib.sha256(payload).hexdigest() != current['raw_sha256']:
            raise ValueError('evidence changed during read')
        profile = profile_from_evidence(payload, current['margin_mb'])
        environment = _live_environment(json.loads(payload))
        result = match_profile(profile, workflow, environment)
        if not result['ok']:
            raise ValueError(result['reason'])
        if 'resident_raw_sha256' in current:
            resident = phase_profile_from_evidence(_resident_payload(manifest), current['margin_mb'])
            snapshot = residency_snapshot()
            try:
                if not snapshot.get('ok'):
                    raise ValueError('fresh residency unavailable')
                phase = match_resident_phase(resident, snapshot, _live_artifact_identity(environment))
                result = {**result, **phase, 'peak_mb': phase['increment_mb'],
                          'memory_scope': 'measured_resident_increment',
                          'residency_instance': snapshot['backend_instance_id'],
                          'residency_epoch': snapshot['load_epoch']}
            except (ValueError, KeyError, TypeError) as error:
                result = {**result, 'resident_fallback_reason': str(error)}
        return {**result, 'profile_status': 'raw_evidence_and_live_identity_verified',
                'memory_scope': result.get('memory_scope', profile['memory_scope']),
                'limitations': profile['limitations']}
    except Exception as error:
        raise ResourceDenied('PROFILE_UNVERIFIED', '测量预算无法核验: ' + str(error)) from error
