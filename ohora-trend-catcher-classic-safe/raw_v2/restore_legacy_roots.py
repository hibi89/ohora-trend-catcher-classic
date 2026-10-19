#!/usr/bin/env python3
"""Reconstruct missing legacy front roots from verified saved raw. Dry-run by default."""
import argparse, json, sqlite3, shutil, hashlib
from datetime import datetime, timezone
from pathlib import Path
from legacy_root_preflight import TARGETS
from collector import fixed_history_cutoff, history_chain_status, parse_date

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    base=a.output_dir.resolve(); path=base/'collection.sqlite'
    if not path.is_file():raise SystemExit('FAIL: database missing')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) if not a.apply else sqlite3.connect(path)
    db.row_factory=sqlite3.Row
    if not a.apply:db.execute('PRAGMA query_only=ON')
    plans=[];errors=[]
    try:
        for key in TARGETS:
            reasons=[]
            acc=db.execute('SELECT * FROM accounts WHERE account_key=?',(key,)).fetchone()
            if acc is None:errors.append(key+': account missing');continue
            roots=db.execute('SELECT COUNT(*) FROM history_page_evidence WHERE account_key=? AND requested_cursor IS NULL',(key,)).fetchone()[0]
            if roots:reasons.append('existing root')
            logs=list(db.execute("SELECT * FROM request_log WHERE account_key=? AND phase='front' AND status='success'",(key,)))
            if len(logs)!=1:reasons.append('front request count '+str(len(logs)))
            if not acc['backfill_cursor']:reasons.append('missing checkpoint')
            if db.execute('SELECT COUNT(*) FROM history_page_evidence WHERE account_key=?',(key,)).fetchone()[0]:
                reasons.append('existing evidence; manual review')
            if logs:
                log=logs[0]
                if db.execute('SELECT COUNT(*) FROM request_log WHERE request_id=?',(log['request_id'],)).fetchone()[0]!=1:reasons.append('ambiguous request ID')
                fp=base/str(log['raw_response_path'] or '')
                if not fp.is_file() or not fp.resolve().is_relative_to(base/'runs'):
                    reasons.append('raw path missing/outside runs')
                else:
                    try:
                        media=json.loads(fp.read_text(encoding='utf-8'))['business_discovery']['media']
                        posts=media['data']
                        cursors=media.get('paging',{}).get('cursors',{})
                        after=cursors.get('after')
                        dates=[parse_date(item['timestamp']) for item in posts]
                        if not posts or not all(dates):reasons.append('missing timestamps')
                        elif dates!=sorted(dates,reverse=True):reasons.append('unordered timestamps')
                        if after!=acc['backfill_cursor']:reasons.append('cursor mismatch')
                        if db.execute('SELECT COUNT(*) FROM post_observations WHERE request_id=? AND run_id=?',(log['request_id'],log['run_id'])).fetchone()[0]!=len(posts):
                            reasons.append('observations mismatch')
                        if db.execute('SELECT COUNT(*) FROM history_page_evidence WHERE request_id=?',(log['request_id'],)).fetchone()[0]:
                            reasons.append('evidence ID collision')
                    except (OSError,KeyError,ValueError,TypeError,AttributeError) as exc:reasons.append('invalid raw: '+str(exc))
            if reasons:errors.append(key+': '+', '.join(reasons));continue
            plans.append((log['request_id'],key,None,after,min(dates).isoformat(),max(dates).isoformat(),fixed_history_cutoff(db,365).isoformat(),'front_root',log['finished_at']))
        for x in errors:print('FAIL',x)
        print('VALID_CANDIDATES',len(plans),'ERRORS',len(errors),'MODE','APPLY' if a.apply else 'DRY_RUN')
        if errors or len(plans)!=len(TARGETS):return 2
        if not a.apply:
            print('DRY_RUN_PASS: no modifications; --apply requires separate explicit invocation')
            return 0
        # Backup online SQLite (includes WAL state); verify its content before any insert.
        backupdir=base.parent/'OHORA_RAW_v2_backups';backupdir.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        dest=backupdir/('legacy_root_before_'+stamp+'.sqlite')
        copy=sqlite3.connect(dest)
        try:db.backup(copy)
        finally:copy.close()
        check=sqlite3.connect(dest)
        try:
            if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('backup integrity failed')
        finally:check.close()
        print('BACKUP_VERIFIED',dest)
        db.execute('BEGIN IMMEDIATE')
        try:
            for item in plans:
                db.execute('INSERT INTO history_page_evidence VALUES (?,?,?,?,?,?,?,?,?)',item)
            for key in TARGETS:
                status=history_chain_status(db,key)
                if status['reason'] not in ('continuing','verified'):
                    raise RuntimeError(key+': unexpected chain '+status['reason'])
            db.commit()
        except BaseException:
            db.rollback();raise
        print('APPLIED_ROOTS',len(plans),'NOTE: rooted start does not prove history completion')
        return 0
    finally:db.close()

if __name__=='__main__':
    raise SystemExit(main())
