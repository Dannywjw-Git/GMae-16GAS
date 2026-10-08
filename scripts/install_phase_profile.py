"""Install reviewed cold and resident traces into a new explicit profile directory."""
import argparse
import hashlib
import json
from pathlib import Path
from measure_comfy_workload import APP
from core.workload_profile import profile_from_evidence
from core.phase_profile import phase_profile_from_evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cold-raw', required=True)
    parser.add_argument('--resident-raw', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--margin-mb', type=int, default=512)
    args = parser.parse_args()
    cold_bytes, resident_bytes = Path(args.cold_raw).read_bytes(), Path(args.resident_raw).read_bytes()
    cold, resident = profile_from_evidence(cold_bytes,args.margin_mb), phase_profile_from_evidence(resident_bytes,args.margin_mb)
    if cold['environment'] != resident['environment'] or cold['execution_configuration_sha256'] != resident['execution_configuration_sha256']:
        raise ValueError('cold and resident configurations must match')
    root = Path(args.destination)
    root.mkdir(parents=True,exist_ok=True)
    manifest = dict(margin_mb=args.margin_mb)
    for label, payload in (('raw',cold_bytes),('resident_raw',resident_bytes)):
        digest = hashlib.sha256(payload).hexdigest()
        filename = digest + '-raw.json'
        target=root/filename
        if target.exists():
            if target.read_bytes()!=payload: raise ValueError('existing evidence differs')
        else:
            with target.open('xb') as output: output.write(payload)
        manifest[label+'_file']=filename
        manifest[label+'_sha256']=digest
    with (root/(cold['execution_configuration_sha256']+'.json')).open('x',encoding='utf-8') as output:
        json.dump(manifest,output)
    print(json.dumps(dict(installed=True,profile_key=cold['execution_configuration_sha256'],increment_mb=resident['increment_mb'],resident_model_mb=resident['resident_model_mb'])))


if __name__=='__main__': main()
