#!/usr/bin/env python3
"""Signed state-only commits, isolated from the user's checkout and index."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time

REPO = Path(os.environ.get('RSHELPER_REPO', Path(__file__).resolve().parents[1]))
SRC = Path.home()/'.config/rshelper'
DEST = REPO/'data/state'
FILES = ('trades.json','positions.json','watchlist.json','tuning_log.json',
         'volume_baseline.json','signal_cooldowns.json','trader_state.json','alerts.json')
PENDING_REF = 'refs/rshelper/state-sync/pending'
LAST_REF = 'refs/rshelper/state-sync/last-pushed'
SHA = re.compile(r'^[0-9a-f]{40}$')
SNAPSHOT = re.compile(r'^snapshots/(alch|flip|margin|process)-\d{4}-\d{2}-\d{2}\.json$')
ZERO = '0'*40
MAX_SYNC_FILES = 512
MAX_SYNC_BYTES = 64 * 1024 * 1024
MAX_SCAN_ENTRIES = 4096
MAX_GIT_SECONDS = 60
MAX_GIT_OUTPUT = 64 * 1024 * 1024
MAX_GIT_ERROR = 64 * 1024

class SyncError(ValueError):
    pass


def git(repo, *args, index=None, data=None, check=True):
    env = dict(os.environ)
    for key in ('GIT_DIR','GIT_COMMON_DIR','GIT_WORK_TREE','GIT_INDEX_FILE',
                'GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_NAMESPACE'):
        env.pop(key,None)
    env['GIT_TERMINAL_PROMPT']='0'
    env['GIT_OPTIONAL_LOCKS']='0'
    if index is not None: env['GIT_INDEX_FILE'] = str(index)
    command = ['git','-C',str(repo),*args]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    completed = False
    output = {'stdout':bytearray(),'stderr':bytearray()}
    deadline = time.monotonic()+MAX_GIT_SECONDS
    pending = memoryview(data or b'')
    try:
        with selectors.DefaultSelector() as selector:
            for name, stream in (('stdout',proc.stdout),('stderr',proc.stderr)):
                os.set_blocking(stream.fileno(),False)
                selector.register(stream,selectors.EVENT_READ,name)
            if proc.stdin is not None:
                if pending:
                    os.set_blocking(proc.stdin.fileno(),False)
                    selector.register(proc.stdin,selectors.EVENT_WRITE,'stdin')
                else:
                    proc.stdin.close()
            while selector.get_map():
                remaining = deadline-time.monotonic()
                if remaining<=0: raise SyncError('Git command exceeded its absolute deadline')
                for key,_ in selector.select(remaining):
                    if key.data=='stdin':
                        try: count=os.write(key.fd,pending[:65536])
                        except BlockingIOError: continue
                        except BrokenPipeError: pending=pending[len(pending):]
                        else: pending=pending[count:]
                        if not pending:
                            selector.unregister(key.fileobj);key.fileobj.close()
                    else:
                        try: block=os.read(key.fd,65536)
                        except BlockingIOError: continue
                        if not block:
                            selector.unregister(key.fileobj);key.fileobj.close();continue
                        limit=MAX_GIT_OUTPUT if key.data=='stdout' else MAX_GIT_ERROR
                        if len(output[key.data])+len(block)>limit:
                            raise SyncError('Git command exceeded its output budget')
                        output[key.data].extend(block)
        try: code=proc.wait(timeout=max(.001,deadline-time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise SyncError('Git command exceeded its absolute deadline') from exc
        completed=True
        result=subprocess.CompletedProcess(command,code,bytes(output['stdout']),bytes(output['stderr']))
    finally:
        if not completed:
            # The group leader has not been reaped, so its process-group ID
            # cannot belong to another invocation. Also stop inherited-pipe
            # descendants; killing only Git could leave communicate hanging.
            try: os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError: pass
        for stream in (proc.stdin,proc.stdout,proc.stderr):
            if stream is not None and not stream.closed: stream.close()
        if not completed: proc.wait(timeout=2)
    if check and result.returncode: raise SyncError('Git state operation failed: '+args[0])
    return result


def value(repo,*args):
    return git(repo,*args).stdout.decode('utf-8').strip()


def ref(repo, name):
    result=git(repo,'rev-parse','--verify',name,check=False)
    if result.returncode: return None
    revision=result.stdout.decode().strip()
    if not SHA.fullmatch(revision): raise SyncError('Invalid state revision')
    return revision


def head(repo):
    branch=git(repo,'symbolic-ref','--quiet','--short','HEAD',check=False)
    if branch.returncode or branch.stdout.decode().strip()!='main':
        raise SyncError('State sync requires the main checkout; no branch was changed')
    revision=ref(repo,'HEAD')
    if revision is None: raise SyncError('State sync requires an existing initial commit')
    return revision


def sync_status(repo):
    branch=git(repo,'symbolic-ref','--quiet','--short','HEAD',check=False)
    return {'head':ref(repo,'HEAD'),'branch':branch.stdout.decode().strip() or None,
            'pending_revision':ref(repo,PENDING_REF),
            'last_pushed_revision':ref(repo,LAST_REF),'signing':'required by default'}


def allowed_path(path):
    if not path.startswith('data/state/'): return False
    relative=path[len('data/state/'):]
    return relative in FILES or bool(SNAPSHOT.fullmatch(relative))


def state_delta_only(repo, left, right):
    names=value(repo,'diff','--name-only',left,right).splitlines()
    return all(allowed_path(name) for name in names)


def base_revision(repo, current):
    last=ref(repo,LAST_REF)
    if last is None: return current
    if git(repo,'merge-base','--is-ancestor',last,current,check=False).returncode==0:
        return current
    if (git(repo,'merge-base','--is-ancestor',current,last,check=False).returncode==0
            and state_delta_only(repo,current,last)):
        return last
    raise SyncError('State ref and source HEAD diverged; reconcile source without sweeping WIP')


def collect(source):
    # E08 owns these classifications. No new file/profile is selected merely
    # because it appeared on disk. Existing legacy replication is not a demo
    # approval; its private transport cutover remains a separate owner gate.
    candidates=[source/name for name in FILES if (source/name).exists() or (source/name).is_symlink()]
    snapshots=source/'snapshots'
    if snapshots.is_symlink(): raise SyncError('Snapshot directory must not be a symlink')
    if snapshots.is_dir():
        for number,path in enumerate(snapshots.iterdir(),1):
            if number>MAX_SCAN_ENTRIES: raise SyncError('Snapshot directory exceeds entry budget')
            if path.suffix=='.json': candidates.append(path)
            if len(candidates)>MAX_SYNC_FILES: raise SyncError('State selection exceeds file budget')
    if len(candidates)>MAX_SYNC_FILES: raise SyncError('State selection exceeds file budget')
    candidates.sort()
    app_src=REPO/'src'
    package=(app_src/'rshelper').resolve()
    required=('__init__.py','publication.py','backup.py','persistence.py','profile.py','config.py')
    if any(not (package/name).is_file() for name in required):
        raise SyncError('Configured validation source is missing; state selection refused')
    for name,module in tuple(sys.modules.items()):
        if name=='rshelper' or name.startswith('rshelper.'):
            file=getattr(module,'__file__',None)
            if not file or not Path(file).resolve().is_relative_to(package):
                raise SyncError('Loaded validation source differs from configured repository')
    sys.path.insert(0,str(app_src))
    from rshelper.publication import PRIVATE_FILES, KNOWN_FIELDS
    from rshelper.backup import _read_file, _validate_file, CORE_KINDS
    selected={};total=0
    for path in candidates:
        relative=path.relative_to(source).as_posix()
        if relative not in FILES and not SNAPSHOT.fullmatch(relative):
            raise SyncError('Unknown state pathname; publication selection denied')
        if relative in FILES and relative not in PRIVATE_FILES and relative not in KNOWN_FIELDS:
            raise SyncError('State file has no publication classification')
        if any(parent.is_symlink() for parent in (path.parent,*path.parent.parents)):
            raise SyncError('State source parent must not be a symlink')
        raw=_read_file(path);_validate_file(relative,raw)
        payload=json.loads(raw)
        if relative in KNOWN_FIELDS:
            kind=CORE_KINDS[relative]
            if set(payload)-{kind,'schema_version'} or any(set(row)-KNOWN_FIELDS[relative] for row in payload[kind]):
                raise SyncError('Unknown state schema field; publication selection denied')
        selected['data/state/'+relative]=(json.dumps(payload,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
        total+=len(selected['data/state/'+relative])
        if total>MAX_SYNC_BYTES: raise SyncError('State selection exceeds total byte budget')
    return selected


def changed_paths(repo, base, selected):
    changed=[]
    for path,data in selected.items():
        previous=git(repo,'show',base+':'+path,check=False)
        # Canonical comparison makes whitespace/newline-only changes a no-op.
        try: old=(json.dumps(json.loads(previous.stdout),sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
        except (ValueError,UnicodeDecodeError): old=None
        if previous.returncode or old!=data: changed.append(path)
    return changed


@contextmanager
def sync_lock(repo):
    common=Path(value(repo,'rev-parse','--git-common-dir'))
    directory=(common if common.is_absolute() else repo/common).resolve()
    fd=os.open(directory/'rshelper-sync.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid(): raise SyncError('Untrusted sync lock')
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc: raise SyncError('Another state sync owns the lease') from exc
        yield directory
    finally:
        os.close(fd)  # Persistent lock inode is never unlinked.


def push_pending(repo, pending, *, unsigned, expected_head):
    commit=git(repo,'cat-file','commit',pending).stdout
    if not unsigned and b'\ngpgsig ' not in commit:
        raise SyncError('Pending state revision is unsigned; required signing cannot be bypassed')
    if head(repo)!=expected_head:
        raise SyncError('Source HEAD changed before push; pending state revision retained')
    result=git(repo,'push','origin',pending+':refs/heads/main',check=False)
    if result.returncode:
        # A push can reach the remote before the local receipt is recorded.
        # Recover that exact accepted revision even if a later release advanced
        # main; never overwrite that release or manufacture another state commit.
        remote=git(repo,'ls-remote','origin','refs/heads/main',check=False)
        fields=remote.stdout.decode('ascii').split()
        accepted=False
        if (not remote.returncode and len(fields)==2 and SHA.fullmatch(fields[0])
                and fields[1]=='refs/heads/main'):
            fetched=git(repo,'fetch','--no-tags','--no-write-fetch-head','origin',
                        fields[0],check=False)
            accepted=(not fetched.returncode and
                      git(repo,'merge-base','--is-ancestor',pending,fields[0],check=False).returncode==0)
        if not accepted:
            raise SyncError('Push failed; pending state revision retained for retry without a duplicate commit')
    old=ref(repo,LAST_REF)
    git(repo,'update-ref',LAST_REF,pending,old or ZERO)
    git(repo,'update-ref','-d',PENDING_REF,pending)


def run_sync(repo, source, *, unsigned=False, dry_run=False):
    repo=Path(repo);source=Path(source)
    current=head(repo)
    selected=collect(source)
    base=base_revision(repo,current)
    paths=changed_paths(repo,base,selected)
    if dry_run:
        return {'changed':bool(paths),'paths':paths,'revision':base,'pushed':False,
                'pending_revision':ref(repo,PENDING_REF),'signing':'explicit unsigned' if unsigned else 'required'}
    with sync_lock(repo) as directory:
        if head(repo)!=current: raise SyncError('Source HEAD changed before state sync')
        pending=ref(repo,PENDING_REF)
        pushed=False
        if pending:
            if not state_delta_only(repo,current,pending): raise SyncError('Pending revision includes source changes; refusing push')
            push_pending(repo,pending,unsigned=unsigned,expected_head=current);pushed=True
        base=base_revision(repo,current)
        paths=changed_paths(repo,base,selected)
        if not paths: return {'changed':False,'paths':[],'revision':base,'pushed':pushed}
        with tempfile.TemporaryDirectory(dir=directory,prefix='rshelper-index-') as folder:
            index=Path(folder)/'index'
            git(repo,'read-tree',base,index=index)
            for path in paths:
                blob=git(repo,'hash-object','-w','--stdin',data=selected[path]).stdout.decode().strip()
                git(repo,'update-index','--add','--cacheinfo','100644,'+blob+','+path,index=index)
            tree=value_with_index(repo,index,'write-tree')
            # commit-tree does not run source hooks or touch HEAD/real index.
            # Signing is explicit; no exception path creates an unsigned commit.
            result=git(repo,'commit-tree',tree,'-p',base,
                       '--no-gpg-sign' if unsigned else '-S',
                       '-m','state: sync trading history',check=False)
            if result.returncode: raise SyncError('Signed state commit failed; no unsigned fallback or push attempted')
            revision=result.stdout.decode().strip()
            if not SHA.fullmatch(revision): raise SyncError('Invalid state commit receipt')
            if head(repo)!=current: raise SyncError('Source HEAD changed; unreferenced state commit was not pushed')
            git(repo,'update-ref',PENDING_REF,revision,ZERO)
        push_pending(repo,revision,unsigned=unsigned,expected_head=current)
        return {'changed':True,'paths':paths,'revision':revision,'pushed':True}


def value_with_index(repo,index,*args):
    return git(repo,*args,index=index).stdout.decode().strip()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--status',action='store_true')
    parser.add_argument('--unsigned',action='store_true',help='Explicitly permit unsigned synthetic/operator state commits; never automatic')
    args=parser.parse_args(argv)
    try:
        report=sync_status(REPO) if args.status else run_sync(REPO,SRC,unsigned=args.unsigned,dry_run=args.dry_run)
        print(json.dumps(report,sort_keys=True));return 0
    except SyncError as exc:
        print('[sync] '+str(exc)+'; checkout/index preserved; inspect --status',file=sys.stderr)
        return 1
    except (OSError,ValueError,subprocess.TimeoutExpired,ImportError):
        print('[sync] failed; checkout/index preserved, pending revision retained; inspect --status and signing/source readiness',file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
