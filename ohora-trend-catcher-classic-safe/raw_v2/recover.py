#!/usr/bin/env python3
"""Offline archived-batch recovery; dry-run by default, never calls the API.

Apply only to an explicitly selected copy after a separately verified backup.
Unknown remote outcomes and legacy journals without replay semantics require
manual reconciliation, never an automatic API retry.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys

import collector as col
from backup import assert_same_snapshot


EXPORTS=('input_accounts.csv','accounts.csv','posts.csv','post_media.csv',
         'collection_log.csv','like_missing_audit.csv','field_support.csv','run_manifest.json')
STATE_KEYS=('latest_id','backfill_cursor','backfill_done','catchup_cursor','catchup_anchor')


def archive_path(base,entry):
    run=entry['run_id'];number=entry['batch_no']
    if not isinstance(run,str) or not run or Path(run).name!=run or run in ('.','..') or '\\' in run:
        raise ValueError('Unsafe recovery run identifier')
    if not isinstance(number,int) or number<0:raise ValueError('Invalid recovery batch number')
    archive=base/'runs'/run/'raw'/f'batch_{number:04}.json'
    if not archive.resolve().is_relative_to(base):raise ValueError('Archive escapes output directory')
    return archive


def examine(base):
    base=Path(base).resolve();target=base/'collection.sqlite'
    if not target.is_file():raise ValueError('Existing database not found')
    with closing(sqlite3.connect(target.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='batch_attempts'").fetchone():return []
        rows=[]
        for b in db.execute("SELECT * FROM batch_attempts WHERE status NOT IN ('complete','aborted_before_send') ORDER BY started_at,run_id,batch_no"):
            row=dict(b);archive=archive_path(base,row)
            row['archive_exists']=archive.is_file()
            row['resolution']='MANUAL_REVIEW_REQUIRED' if row['status']=='requires_review' else 'ARCHIVE_PRESENT_UNVALIDATED' if row['archive_exists'] else 'UNKNOWN_REMOTE_OUTCOME'
            rows.append(row)
        return rows


def validate_batches(db,base,entries):
    """Validate every journal and existing artifact before any recovery writes."""
    prepared=[]
    for entry in entries:
        run=entry['run_id'];slot=entry['slot_id'];archive=archive_path(base,entry)
        if entry['status'] not in ('prepared','response_saved'):
            raise ValueError('Unsupported unresolved batch state; manual review required')
        if entry['response_path'] and entry['response_path']!=str(archive.relative_to(base)):
            raise ValueError('Archived response path disagrees with journal')
        body=json.loads(archive.read_text(encoding='utf-8'));plans=json.loads(entry['request_json'])
        if not isinstance(plans,list) or not plans or len(plans)>10 or not isinstance(body,list) or len(body)!=len(plans):
            raise ValueError('Archived batch and plans disagree; manual review required')
        oldrun=db.execute('SELECT * FROM runs WHERE run_id=?',(run,)).fetchone()
        if not oldrun:
            raise ValueError('Batch run record absent; cannot safely replay')
        totals=db.execute("SELECT COUNT(*),COALESCE(SUM(status='success'),0),COALESCE(SUM(status!='success'),0) FROM request_log WHERE run_id=?",(run,)).fetchone()
        if tuple(totals)!=(oldrun['requests'],oldrun['successes'],oldrun['failures']):
            raise ValueError('Recovery run counters disagree with committed requests')
        slot_row=db.execute('SELECT * FROM slots WHERE slot_id=?',(slot,)).fetchone()
        if not slot_row:
            raise ValueError('Batch slot record absent; cannot safely replay')
        if slot_row['status'] not in ('active','cooldown') or not col.parse_date(slot_row['started_at']) or not col.parse_date(entry['started_at']):
            raise ValueError('Invalid recovery slot/batch state or timestamp')
        if any((base/'runs'/run/name).exists() for name in EXPORTS):
            raise ValueError('Prior run export exists: avoid overwriting immutable evidence')
        seen=set()
        for i,(plan,part) in enumerate(zip(plans,body)):
            if not isinstance(plan,dict) or plan.get('phase') not in ('front','catchup','history'):
                raise ValueError('Invalid archived request plan')
            key=plan.get('account_key');phase=plan['phase']
            a=db.execute('SELECT * FROM accounts WHERE account_key=?',(key,)).fetchone()
            if not a or a['ordinal']!=plan.get('ordinal') or key in seen:
                raise ValueError('Recovery account roster mismatch or duplicate account')
            seen.add(key)
            options=plan.get('options');state=plan.get('state')
            if (not isinstance(options,dict) or options.get('limit') not in (4,5)
                    or options.get('history_days') not in (365,730)
                    or type(options.get('window_days')) is not int or not 1<=options['window_days']<=31
                    or type(options.get('extended_fields')) is not bool
                    or not isinstance(state,dict) or any(k not in state for k in STATE_KEYS)
                    or 'daily_day' not in plan or 'requested_cursor' not in plan
                    or type(plan.get('cooldown_minutes')) is not int or plan['cooldown_minutes']<63
                    or type(plan.get('cycle_minutes')) is not int or plan['cycle_minutes']<0):
                raise ValueError('Archived request options/state absent or invalid; manual reconciliation required')
            day=plan['daily_day']
            if day is not None:
                try:valid_day=isinstance(day,str) and date.fromisoformat(day).isoformat()==day
                except ValueError:valid_day=False
                if not valid_day:raise ValueError('Invalid journaled daily day')
            req=f'{run}_{entry["batch_no"]:04}_{i:02}_{a["ordinal"]:03}_{phase}'
            if plan.get('request_id')!=req:
                raise ValueError('Archived request identifier disagrees with journal')
            existing=db.execute('SELECT * FROM request_log WHERE request_id=?',(req,)).fetchone()
            if existing:
                occupied=db.execute('SELECT request_id FROM slot_accounts WHERE slot_id=? AND account_key=?',(slot,key)).fetchone()
                if (existing['run_id'],existing['account_key'],existing['phase'])!=(run,key,phase) or not occupied or occupied[0]!=req:
                    raise ValueError('Committed recovery request and slot disagree')
                if existing['status'] not in ('success','failed'):
                    raise ValueError('Committed recovery request has invalid status')
            else:
                cursor=state['catchup_cursor'] if phase=='catchup' else state['backfill_cursor'] if phase=='history' else None
                if plan.get('requested_cursor')!=cursor or any(a[k]!=state[k] for k in STATE_KEYS):
                    raise ValueError('Recovery account cursor/state differs from archived request')
                if db.execute('SELECT 1 FROM slot_accounts WHERE slot_id=? AND account_key=?',(slot,key)).fetchone():
                    raise ValueError('Recovery account already consumed this slot')
            if not isinstance(part,dict):raise ValueError('Invalid archived subresponse')
            try:
                payload=json.loads(part.get('body') or '{}');int(part.get('code') or 0)
            except (ValueError,TypeError) as exc:raise ValueError('Invalid archived JSON/status') from exc
            if not isinstance(payload,dict):raise ValueError('Invalid archived payload object')
            raw=base/'runs'/run/'raw'/(req+'.json')
            if raw.exists() and json.loads(raw.read_text(encoding='utf-8'))!=payload:
                raise ValueError('Existing raw response disagrees with archived batch; preserve both for manual review')
            if existing and (not raw.is_file() or existing['raw_response_path']!=str(raw.relative_to(base))):
                raise ValueError('Committed recovery request raw evidence is missing or mismatched')
        occupied=db.execute('SELECT COUNT(*) FROM slot_accounts WHERE slot_id=?',(slot,)).fetchone()[0]
        pending=sum(not db.execute('SELECT 1 FROM request_log WHERE request_id=?',(p['request_id'],)).fetchone() for p in plans)
        if occupied+pending>col.SLOT_ACCOUNT_LIMIT:
            raise ValueError('Recovery would exceed slot account budget')
        prepared.append((entry,plans,body))
    return prepared


def replay_batches(db,base,source,prepared,write_files):
    count=0
    for entry,plans,body in prepared:
        run=entry['run_id'];number=entry['batch_no'];slot=entry['slot_id']
        requires_review=False
        for i,(plan,part) in enumerate(zip(plans,body)):
            key=plan['account_key'];phase=plan['phase'];options=plan['options']
            a=db.execute('SELECT * FROM accounts WHERE account_key=?',(key,)).fetchone()
            req=f'{run}_{number:04}_{i:02}_{a["ordinal"]:03}_{phase}'
            payload=json.loads(part.get('body') or '{}');http=int(part.get('code') or 0)
            error=payload.get('error') if isinstance(payload.get('error'),dict) else {}
            error_code=str(error.get('code','')) if error else ''
            if http in (401,403) or error_code in ('10','102','104','190','200'):
                requires_review=True
            if db.execute('SELECT 1 FROM request_log WHERE request_id=?',(req,)).fetchone():continue
            ts=entry['started_at']  # Preserve original observation time.
            raw=base/'runs'/run/'raw'/(req+'.json')
            if write_files and not raw.exists():col.persist_response(base,run,req,payload,'')
            def log_account(status,items,more):
                if status!='success':
                    db.execute("""UPDATE accounts SET attempts=attempts+1,last_attempt=?,last_error=?,
                        blocked=CASE WHEN ?='110' THEN 1 ELSE blocked END WHERE account_key=?""",
                        (ts,error_code,error_code,key))
                db.execute("""INSERT INTO request_log(
                    run_id,request_id,account_key,phase,started_at,finished_at,http_status,status,
                    records_received,has_next_page,stop_reason,error_code,error_subcode,error_message,
                    raw_response_path,requested_fields,usage_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (run,req,key,phase,ts,ts,http,status,items,
                     'true' if more else 'false' if status=='success' else 'unknown',
                     'recovered_archived_response',error_code,str(error.get('error_subcode','')),
                     str(error.get('message',''))[:300],str(raw.relative_to(base)),
                     col.BASE_PROFILE+(','+col.EXTRA_PROFILE if options['extended_fields'] else '')+','+col.MEDIA_FIELDS,
                     json.dumps({'recovered_from_batch':number,'requested_post_limit':options['limit']})))
                db.execute('UPDATE runs SET requests=requests+1,successes=successes+?,failures=failures+? WHERE run_id=?',
                           (int(status=='success'),int(status!='success'),run))
                db.execute('INSERT INTO slot_accounts(slot_id,account_key,request_id) VALUES (?,?,?)',(slot,key,req))
                if plan['daily_day'] and phase=='front':
                    daily_status='success' if status=='success' else 'needs_review' if error_code=='110' else 'retry_pending'
                    db.execute("""INSERT INTO daily_account_state
                        (day_kst,account_key,status,attempts,last_request_id,last_error,updated_at)
                        VALUES (?,?,?,?,?,?,?) ON CONFLICT(day_kst,account_key) DO UPDATE SET
                        status=excluded.status,attempts=daily_account_state.attempts+1,
                        last_request_id=excluded.last_request_id,last_error=excluded.last_error,updated_at=excluded.updated_at""",
                        (plan['daily_day'],key,daily_status,1,req,error_code or None,ts))
            if http==200 and not error:
                try:
                    col.insert_success(db,dict(a),phase,payload,run,req,ts,options['history_days'],
                                       extended=options['extended_fields'],window_days=options['window_days'],limit=options['limit'],
                                       commit_hook=lambda new,items,more:log_account('success',items,more))
                except ValueError as exc:
                    raise ValueError('Archived response is invalid; manual reconciliation required: '+str(exc)) from exc
            else:
                with db:log_account('failed',0,False)
            count+=1
        # Resolve the uncertainty only after the conservative wait is durable.
        # An export failure must never leave a replayed slot immediately reusable.
        active=db.execute('SELECT status FROM slots WHERE slot_id=?',(slot,)).fetchone()
        if write_files and active and active[0]=='active':
            col.close_slot(db,slot,'recovered_batch_conservative_cooldown',
                           max(p['cooldown_minutes'] for p in plans),max(p['cycle_minutes'] for p in plans))
        with db:
            db.execute('UPDATE batch_attempts SET status=? WHERE run_id=? AND batch_no=?',
                       ('requires_review' if requires_review else 'complete',run,number))
            if requires_review:
                db.execute("UPDATE runs SET finished_at=COALESCE(finished_at,?),status='requires_review' WHERE run_id=?",(col.now(),run))
        rest=db.execute("SELECT COUNT(*) FROM batch_attempts WHERE run_id=? AND status NOT IN ('complete','aborted_before_send')",(run,)).fetchone()[0]
        if rest==0:
            with db:db.execute("UPDATE runs SET finished_at=COALESCE(finished_at,?),status='recovered' WHERE run_id=?",(col.now(),run))
            if write_files:col.export_run(db,base,run,source)
    return count


def recover(base,source,backup,apply=False):
    base=Path(base).resolve()
    if not apply:
        return {'mode':'READ_ONLY_PREVIEW','batches':[
            {k:b[k] for k in ('run_id','batch_no','status','resolution')} for b in examine(base)]}
    with col.process_lock(base):
        entries=examine(base)
        summary=[{k:b[k] for k in ('run_id','batch_no','status','resolution')} for b in entries]
        if not entries:return {'mode':'APPLY','batches':[],'replayed':0}
        if any(not b['archive_exists'] for b in entries):
            raise ValueError('Unknown remote outcome; no automatic retry. Resolve missing batch archives manually.')
        backup=Path(backup).resolve() if backup else None;target=base/'collection.sqlite'
        if backup is None or not backup.is_file() or backup.is_relative_to(base) or backup.samefile(target):
            raise ValueError('A separately located, verified --backup-file outside output directory is mandatory for --apply')
        accounts,digest=col.load_accounts(source)
        with closing(sqlite3.connect(target.as_uri()+'?mode=ro',uri=True)) as live, \
                closing(sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True)) as check:
            live.row_factory=sqlite3.Row
            live.execute('BEGIN');check.execute('BEGIN')
            if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup failed integrity check')
            assert_same_snapshot(live,check)
            if live.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Recovery database has foreign key violations')
            cfg=dict(live.execute('SELECT k,v FROM config'))
            if cfg.get('source_sha')!=digest or cfg.get('schema')!=col.SCHEMA_VERSION:
                raise ValueError('Source hash or schema changed; recovery cannot change source identity')
            stored=[tuple(r) for r in live.execute('SELECT account_key,ordinal,input_username,country,input_profile_url FROM accounts ORDER BY ordinal')]
            expected=[(a['key'],a['ordinal'],a['input_username'],a['country'],a['input_profile_url']) for a in accounts]
            if stored!=expected:raise ValueError('Recovery account roster mismatch')
            prepared=validate_batches(live,base,entries)
            # Validate payloads and commit hooks on a disposable DB. A later bad
            # part must not leave earlier recovery rows or raw files committed.
            with closing(sqlite3.connect(':memory:')) as trial:
                live.backup(trial);trial.row_factory=sqlite3.Row
                trial.execute('PRAGMA foreign_keys=ON')
                replay_batches(trial,base,source,prepared,False)
        with closing(sqlite3.connect(target)) as db:
            db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
            count=replay_batches(db,base,source,prepared,True)
            reviews=db.execute("SELECT COUNT(*) FROM batch_attempts WHERE status='requires_review'").fetchone()[0]
        return {'mode':'APPLY','batches':summary,'replayed':count,'requires_review':reviews}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--backup-file',type=Path)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    if args.apply and (not args.source or not args.backup_file):parser.error('--apply requires --source and --backup-file')
    try:
        result=recover(args.output_dir,args.source,args.backup_file,args.apply)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 2 if result.get('requires_review') else 0
    except (ValueError,OSError,sqlite3.Error,json.JSONDecodeError) as exc:
        print('RECOVERY_BLOCKED',str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
