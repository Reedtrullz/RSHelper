import hashlib
import math
import time
import tomllib
from datetime import datetime,timezone
from pathlib import Path

from rshelper import backup,config,persistence,profile as profiles,state_identity,state_transaction,tuning

MAX_CONFIG_BYTES=65536

def _parse(candidate):
    if type(candidate) is not str or len(candidate.encode('utf-8'))>MAX_CONFIG_BYTES:
        raise ValueError('configuration must be bounded TOML text')
    return config.effective_config_dict(config.validate_config(config._config_from_toml(tomllib.loads(candidate))))

def _hash(raw):
    return hashlib.sha256(raw).hexdigest()

def _snapshot(profile):
    path=profiles.resolve_config_path('config.toml',profile)
    try:
        raw=backup._read_file(path,MAX_CONFIG_BYTES)
        exists=True
    except FileNotFoundError:
        raw=config.DEFAULT_CONFIG_TOML.encode()
        exists=False
    current=_parse(raw.decode('utf-8'))
    log=tuning._load_log(profile)
    number=log.get('config_revision',0)
    revision=str(number)+':'+_hash((b'present\0' if exists else b'missing\0')+raw)
    return path,raw,current,log,revision

def _diff(current,candidate):
    return [{'field':section+'.'+field,'before':value,'after':candidate[section][field]}
            for section,values in current.items() for field,value in values.items()
            if value!=candidate[section][field]]

def preview_config(profile,candidate=None):
    root=profiles.resolve_config_path('config.toml',profile).parent
    with state_transaction.profile_transaction(profile or 'default',root):
        _,raw,current,_,revision=_snapshot(profile)
        effective=_parse(raw.decode() if candidate is None else candidate)
        diff=_diff(current,effective)
        return {'revision':revision,'current':current,'effective':effective,
                'document':raw.decode(),'profile_values':tomllib.loads(raw.decode()),
                'defaults':config.effective_config_dict(config.Config()),'diff':diff,
                'config_id':tuning.config_id(effective),'restart_required':bool(diff),
                'guidance':'Running processes retain their configuration until explicitly restarted; paper bankroll is unchanged.'}

def apply_config(profile,candidate,*,expected_revision,operation_id,backup_path,now=None,_restore=None):
    effective=_parse(candidate)
    persistence.canonical_uuid(operation_id)
    if type(expected_revision) is not str or len(expected_revision)>100:
        raise ValueError('expected configuration revision required')
    now=time.time() if now is None else now
    if type(now) not in (int,float) or not math.isfinite(now) or now<0:
        raise ValueError('invalid configuration effective time')
    instant=datetime.fromtimestamp(now,timezone.utc).isoformat()
    destination=Path(backup_path).absolute()
    request_hash=state_identity.request_hash({'candidate_sha256':_hash(candidate.encode()),
                  'expected_revision':expected_revision,'backup_path':str(destination),'restore_operation':_restore})
    root=profiles.resolve_config_path('config.toml',profile).parent
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        state_identity.require_financial_authority(state_identity.activation_manifest(root/'identity-activation.json'))
        path,raw,current,log,revision=_snapshot(profile)
        operations=log.setdefault('config_operations',{})
        previous=operations.get(operation_id)
        if previous is not None:
            if previous['request_sha256']!=request_hash:
                raise ValueError('configuration operation reused with different request')
            return {**previous,'retry':True,'current_revision':revision}
        if revision!=expected_revision:raise ValueError('configuration revision changed; preview again')
        for entry in log['entries']:
            try:prior=tuning._instant(entry['ts'])
            except (ValueError,TypeError,AttributeError):continue
            if prior>=tuning._instant(instant):raise ValueError('configuration effective time must advance')
        diff=_diff(current,effective)
        backup.export_profile(profile,destination)
        number=log.get('config_revision',0)+1
        next_revision=str(number)+':'+_hash(b'present\0'+candidate.encode())
        receipt={'request_sha256':request_hash,'operation_revision':number,'revision':next_revision,
                 'before_toml':raw.decode(),'candidate_sha256':_hash(candidate.encode()),
                 'effective_at':instant,'effective_config_id':tuning.config_id(effective),
                 'backup_path':str(destination),'restart_required':bool(diff)}
        operations[operation_id]=receipt
        log['config_revision']=number
        if diff:
            log['entries'].append({'ts':instant,'params':effective,'config_id':tuning.config_id(effective),
                  'operation_id':operation_id,'note':'owner configuration rollback' if _restore else 'owner configuration apply'})
        tuning.validate_log(log)
        txn.stage_bytes('config.toml',candidate.encode())
        txn.stage('tuning_log.json',log)
        txn.commit(operation_id=operation_id)
        return {**receipt,'retry':False,'current_revision':next_revision}

def rollback_config(profile,restore_operation,*,expected_revision,operation_id,backup_path,now=None):
    persistence.canonical_uuid(restore_operation)
    root=profiles.resolve_config_path('config.toml',profile).parent
    with state_transaction.profile_transaction(profile or 'default',root):
        _,_,_,log,_=_snapshot(profile)
        receipt=log.get('config_operations',{}).get(restore_operation)
        if receipt is None:raise ValueError('configuration operation not found')
        return apply_config(profile,receipt['before_toml'],expected_revision=expected_revision,
                    operation_id=operation_id,backup_path=backup_path,now=now,_restore=restore_operation)
