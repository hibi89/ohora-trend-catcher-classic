#!/usr/bin/env python3
"""Read-only OHORA RAW v2 audit: physical integrity, provenance and coverage.

No collector.connect(), API calls, credentials, DB writes or automatic repairs.
The only writes are optional reports to --report-dir (never inside SQLite).
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

from collector import history_chain_status, parse_date


REPORTS=('summary.json','account_progress.csv','integrity_findings.csv',
         'observation_findings.csv','coverage_findings.csv')


def _as_csv(path, rows, fields):
    with path.open('w',encoding='utf-8-sig',newline='') as fp:
        w=csv.DictWriter(fp,fieldnames=fields,extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def audit(folder, report_dir=None):
    folder=Path(folder).resolve()
    dbfile=folder/'collection.sqlite'
    if report_dir:
        dest=Path(report_dir).resolve()
        if dest==folder or dest.is_relative_to(folder):
            raise ValueError('reports must be outside the collection store')
    if not dbfile.is_file():
        summary={'status':'UNKNOWN','db_path':str(dbfile),
                 'ready_for_unattended_collection':False,
                 'note':'collection.sqlite absent; no data integrity or completeness conclusion is possible.'}
        if report_dir:
            dest.mkdir(parents=True,exist_ok=True)
            (dest/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        return summary
    uri=dbfile.as_uri()+'?mode=ro'
    db=sqlite3.connect(uri,uri=True)
    db.row_factory=sqlite3.Row
    integrity=[]
    observation=[]
    coverage=[]
    def add(group,severity,code,detail,account_key=''):
        group.append(dict(severity=severity,code=code,account_key=account_key,detail=str(detail)[:500]))
    def count(sql,params=()):
        return db.execute(sql,params).fetchone()[0]
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        physical=db.execute('PRAGMA integrity_check').fetchone()[0]
        if physical!='ok':add(integrity,'FAIL','SQLITE_INTEGRITY',physical)
        fk=list(db.execute('PRAGMA foreign_key_check'))
        if fk:add(integrity,'FAIL','FOREIGN_KEYS',f'{len(fk)} violations')
        tables={r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required={'config','accounts','posts','post_media','post_observations',
                  'account_observations','runs','request_log','slots','slot_accounts',
                  'field_observations','carousel_status'}
        missing=required-tables
        if missing:
            add(integrity,'FAIL','MISSING_TABLES',','.join(sorted(missing)))
            raise ValueError('Missing essential tables: '+','.join(sorted(missing)))
        total_accounts=count('SELECT COUNT(*) FROM accounts')
        if total_accounts!=294:add(integrity,'FAIL','ROSTER_SIZE',total_accounts)
        sql_checks=[
            ('UNLINKED_POST','SELECT COUNT(*) FROM posts p LEFT JOIN accounts a ON a.account_key=p.account_key WHERE a.account_key IS NULL'),
            ('UNLINKED_MEDIA','SELECT COUNT(*) FROM post_media m LEFT JOIN posts p ON m.post_id=p.post_id WHERE p.post_id IS NULL'),
            ('UNLINKED_POST_OBS','SELECT COUNT(*) FROM post_observations o LEFT JOIN posts p ON o.post_id=p.post_id WHERE p.post_id IS NULL'),
            ('REQUEST_WITHOUT_RUN','SELECT COUNT(*) FROM request_log l LEFT JOIN runs r ON l.run_id=r.run_id WHERE r.run_id IS NULL'),
            ('REQUEST_WITHOUT_ACCOUNT','SELECT COUNT(*) FROM request_log l LEFT JOIN accounts a ON l.account_key=a.account_key WHERE a.account_key IS NULL'),
            ('ACCOUNT_OBS_WITHOUT_ACCOUNT','SELECT COUNT(*) FROM account_observations o LEFT JOIN accounts a ON o.account_key=a.account_key WHERE a.account_key IS NULL'),
            ('MEDIA_WRONG_ACCOUNT','SELECT COUNT(*) FROM post_media m JOIN posts p ON m.post_id=p.post_id WHERE m.account_key!=p.account_key'),
            ('POST_OBS_WITHOUT_REQUEST','SELECT COUNT(*) FROM post_observations o LEFT JOIN request_log l ON o.request_id=l.request_id WHERE l.request_id IS NULL'),
            ('ACCOUNT_OBS_WITHOUT_REQUEST','SELECT COUNT(*) FROM account_observations o LEFT JOIN request_log l ON o.request_id=l.request_id WHERE l.request_id IS NULL'),
            ('FIELD_OBS_WITHOUT_REQUEST','SELECT COUNT(*) FROM field_observations o LEFT JOIN request_log l ON o.request_id=l.request_id WHERE l.request_id IS NULL'),
            ('POST_OBS_WRONG_RUN','SELECT COUNT(*) FROM post_observations o JOIN request_log l ON o.request_id=l.request_id WHERE o.run_id!=l.run_id'),
            ('POST_OBS_WRONG_ACCOUNT','SELECT COUNT(*) FROM post_observations o JOIN request_log l ON o.request_id=l.request_id JOIN posts p ON o.post_id=p.post_id WHERE l.account_key!=p.account_key'),
            ('ACCOUNT_OBS_WRONG_RUN','SELECT COUNT(*) FROM account_observations o JOIN request_log l ON o.request_id=l.request_id WHERE o.run_id!=l.run_id'),
            ('ACCOUNT_OBS_WRONG_ACCOUNT','SELECT COUNT(*) FROM account_observations o JOIN request_log l ON o.request_id=l.request_id WHERE o.account_key!=l.account_key'),
            ('FIELD_OBS_WRONG_RUN','SELECT COUNT(*) FROM field_observations o JOIN request_log l ON o.request_id=l.request_id WHERE o.run_id!=l.run_id'),
            ('FIELD_OBS_WRONG_ACCOUNT','SELECT COUNT(*) FROM field_observations o JOIN request_log l ON o.request_id=l.request_id WHERE o.account_key!=l.account_key'),
            ('SLOT_WITHOUT_REQUEST','SELECT COUNT(*) FROM slot_accounts s LEFT JOIN request_log l ON s.request_id=l.request_id WHERE l.request_id IS NULL'),
            ('SLOT_WRONG_ACCOUNT','SELECT COUNT(*) FROM slot_accounts s JOIN request_log l ON s.request_id=l.request_id WHERE s.account_key!=l.account_key')
        ]
        for name,query in sql_checks:
            amount=count(query)
            if amount:add(integrity,'FAIL',name,amount)
        if 'history_page_evidence' in tables:
            invalid=count("""SELECT COUNT(*) FROM history_page_evidence e
                LEFT JOIN request_log l ON l.request_id=e.request_id
                WHERE l.request_id IS NULL OR l.status!='success'
                   OR l.account_key!=e.account_key OR l.phase NOT IN ('front','history')""")
            if invalid:add(integrity,'FAIL','HISTORY_EVIDENCE_WITHOUT_SUCCESS',invalid)
        for r in db.execute('SELECT run_id,requests,successes,failures FROM runs'):
            measured=db.execute('SELECT COUNT(*),SUM(status="success"),SUM(status!="success") FROM request_log WHERE run_id=?',(r['run_id'],)).fetchone()
            got=(measured[0],measured[1] or 0,measured[2] or 0)
            expected=(r['requests'] or 0,r['successes'] or 0,r['failures'] or 0)
            if got!=expected:
                add(integrity,'FAIL','RUN_LOG_MISMATCH',f'{r["run_id"]}: stored={expected} logged={got}')
        # Different runs may have reused request IDs historically; filesystem shows
        # evidence even when a colliding DB INSERT was rejected by a primary key.
        raw_index={}
        for run_dir in (folder/'runs').glob('*') if (folder/'runs').is_dir() else []:
            raw_dir=run_dir/'raw'
            if not raw_dir.is_dir():continue
            for fp in raw_dir.glob('*.json'):
                stem=fp.stem
                if stem.startswith(('batch_','outer_')):continue
                raw_index[(run_dir.name,stem)]=fp
        by_id={}
        for run_id,request_id in raw_index:
            by_id.setdefault(request_id,[]).append(run_id)
        for req,runids in by_id.items():
            if len(runids)>1:
                add(observation,'WARN','HISTORICAL_REQUEST_ID_REUSE',
                    f'{req}: {len(runids)} raw copies across runs')
        logs=list(db.execute("SELECT run_id,request_id,account_key,phase,status,records_received,raw_response_path FROM request_log"))
        raw_pages={}
        logged={(r['run_id'],r['request_id']):r for r in logs}
        for key,fp in raw_index.items():
            if key not in logged:
                add(observation,'WARN','RAW_WITHOUT_LOG',str(fp.relative_to(folder)))
        for r in logs:
            file=folder/str(r['raw_response_path']) if r['raw_response_path'] else None
            if not file or not file.is_file():
                add(observation,'WARN','LOG_WITHOUT_RAW',f'{r["run_id"]}/{r["request_id"]}',r['account_key'])
                continue
            if r['status']!='success':continue
            try:
                raw=json.loads(file.read_text(encoding='utf-8'))
                page=raw['business_discovery']['media']['data']
                if not isinstance(page,list):raise ValueError('media.data not list')
            except (ValueError,KeyError,TypeError,OSError,json.JSONDecodeError) as exc:
                add(observation,'FAIL','RAW_UNREADABLE',str(exc),r['account_key'])
                continue
            ids=[str(p.get('id')) for p in page if isinstance(p,dict)]
            raw_pages[r['request_id']]=raw
            stored=count('SELECT COUNT(*) FROM post_observations WHERE run_id=? AND request_id=?',(r['run_id'],r['request_id']))
            if stored!=len(ids):
                add(observation,'FAIL','RAW_OBSERVATION_MISMATCH',
                    f'{r["request_id"]}: raw={len(ids)} observations={stored}',r['account_key'])
            if r['records_received']!=len(ids):
                add(observation,'WARN','RAW_LOG_COUNT_MISMATCH',
                    f'{r["request_id"]}: raw={len(ids)}, log={r["records_received"]}',r['account_key'])
            for item in page:
                if not isinstance(item,dict) or not item.get('id'):continue
                obs=db.execute("""SELECT like_count,comments_count FROM post_observations
                                  WHERE post_id=? AND request_id=? AND run_id=?""",
                               (str(item['id']),r['request_id'],r['run_id'])).fetchone()
                if obs and (obs[0]!=item.get('like_count') or obs[1]!=item.get('comments_count')):
                    add(observation,'FAIL','RAW_METRIC_MISMATCH',
                        f'post={item["id"]}, request={r["request_id"]}',r['account_key'])
            profile=raw['business_discovery']
            account_obs=db.execute("""SELECT followers_count,follows_count,media_count
                FROM account_observations WHERE request_id=? AND run_id=? AND account_key=?""",
                (r['request_id'],r['run_id'],r['account_key'])).fetchone()
            expected=tuple(profile.get(f) for f in ('followers_count','follows_count','media_count'))
            if account_obs is None or tuple(account_obs)!=expected:
                add(observation,'FAIL','RAW_ACCOUNT_METRIC_MISMATCH',r['request_id'],r['account_key'])
        invalid_evidence=set()
        if 'history_page_evidence' in tables:
            for e in db.execute('SELECT * FROM history_page_evidence'):
                raw=raw_pages.get(e['request_id'])
                media=raw['business_discovery']['media'] if raw else None
                paging=media.get('paging') if media else None
                cursors=paging.get('cursors') if isinstance(paging,dict) else None
                after=cursors.get('after') if isinstance(cursors,dict) else None
                if raw is None or after!=e['response_cursor']:
                    invalid_evidence.add(e['account_key'])
                    add(coverage,'WARN' if raw is None else 'FAIL','HISTORY_EVIDENCE_RAW_UNVERIFIED',
                        e['request_id'],e['account_key'])
                if raw is not None and e['completion_basis']!='unknown_front_page':
                    dates=[parse_date(p.get('timestamp')) for p in media['data'] if isinstance(p,dict)]
                    valid=len(dates)==len(media['data']) and all(dates)
                    expected=(min(dates),max(dates)) if valid and dates else (None,None)
                    stored=(parse_date(e['oldest_page_ts']),parse_date(e['newest_page_ts']))
                    if stored!=expected:
                        invalid_evidence.add(e['account_key'])
                        add(coverage,'FAIL','HISTORY_EVIDENCE_DATES_MISMATCH',e['request_id'],e['account_key'])
        for r in db.execute("""SELECT post_id,account_key,child_rows,coverage FROM carousel_status
                               WHERE coverage='complete' AND child_rows=0"""):
            add(coverage,'WARN','LEGACY_FALSE_CAROUSEL_COMPLETE',
                r['post_id'],r['account_key'])
        pending_batches=0
        if 'batch_attempts' in tables:
            pending_batches=count("SELECT COUNT(*) FROM batch_attempts WHERE status NOT IN ('complete','aborted_before_send')")
            if pending_batches:add(integrity,'FAIL','UNRESOLVED_API_BATCH',pending_batches)
        accounts=[]
        cols={r['name'] for r in db.execute('PRAGMA table_info(accounts)')}
        if {'backfill_done','backfill_cursor','catchup_cursor','oldest_time'}.issubset(cols):
            evidence='history_page_evidence' in tables
            for a in db.execute('SELECT * FROM accounts ORDER BY ordinal'):
                key=a['account_key']
                posts=count('SELECT COUNT(*) FROM posts WHERE account_key=?',(key,))
                obs=count("""SELECT COUNT(*) FROM post_observations
                             WHERE post_id IN (SELECT post_id FROM posts WHERE account_key=?)""",(key,))
                history_pages=count("SELECT COUNT(*) FROM request_log WHERE account_key=? AND phase='history' AND status='success'",(key,))
                gaps=count("SELECT COUNT(*) FROM catchup_jobs WHERE account_key=?",(key,)) if 'catchup_jobs' in tables else 0
                chain=history_chain_status(db,key) if evidence else {
                    'verified':False,'basis':None,'reason':'no history evidence table'}
                if key in invalid_evidence:
                    chain={**chain,'verified':False,'reason':'history evidence lacks matching raw response'}
                basis=chain.get('basis')
                complete=bool(a['backfill_done'])
                unresolved=bool(a['catchup_cursor']) or bool(gaps)
                if complete and not chain['verified']:
                    add(coverage,'WARN','UNVERIFIED_LEGACY_COMPLETION',
                        'backfill_done=1 without a complete rooted cursor chain; '
                        +chain['reason']+'; cursor_present='+str(bool(a['backfill_cursor'])),key)
                if complete and unresolved:
                    add(coverage,'WARN','COMPLETION_WITH_GAPS',
                        'history flag set but catchup remains; full coverage not verified',key)
                if unresolved and not complete:
                    add(coverage,'WARN','UNRESOLVED_CATCHUP',
                        'active or queued latest-page gap; full coverage not verified',key)
                accounts.append({
                    'ordinal':a['ordinal'],'account_key':key,'country':a['country'],
                    'posts':posts,'observations':obs,'oldest_time':a['oldest_time'] or '',
                    'newest_time':a['newest_time'] or '',
                    'backfill_done_flag':int(complete),'history_pages':history_pages,
                    'history_basis':basis or 'UNKNOWN','history_chain_reason':chain['reason'],
                    'has_backfill_cursor':int(bool(a['backfill_cursor'])),
                    'active_catchup':int(bool(a['catchup_cursor'])),'queued_gaps':gaps,
                    'blocked':a['blocked'],'coverage_verified':int(complete and chain['verified'] and not unresolved)
                })
        else:
            accounts=[]
        if len(accounts)!=294:
            add(integrity,'FAIL','ACCOUNT_PROGRESS_INCOMPLETE',len(accounts))
        summary={'status':'FAIL' if any(f['severity']=='FAIL' for f in integrity+observation+coverage)
                 else 'WARN' if integrity or observation or coverage else 'PASS',
                 'checked_at_utc':datetime.now(timezone.utc).isoformat(),
                 'scope':'read-only local DB + available run raw JSON; API-visible coverage, not Instagram global completeness',
                 'db_path':str(dbfile),'accounts':total_accounts,
                 'posts':count('SELECT COUNT(*) FROM posts'),
                 'post_observations':count('SELECT COUNT(*) FROM post_observations'),
                 'successful_accounts':count('SELECT COUNT(DISTINCT account_key) FROM account_observations'),
                 'unresolved_batches':pending_batches,
                 'findings':{'integrity':len(integrity),'observation':len(observation),'coverage':len(coverage)},
                 'ready_for_unattended_collection':False,
                 'note':'PASS covers measured checks only. Historical coverage requires a rooted cursor chain; Meta visibility remains separate.'}
        db.execute('ROLLBACK')
    finally:
        db.close()
    if report_dir:
        dest=Path(report_dir).resolve()
        if dest==folder or dest.is_relative_to(folder) or dest==dbfile:
            raise ValueError('reports must not overwrite collection store')
        dest.mkdir(parents=True,exist_ok=True)
        (dest/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        _as_csv(dest/'account_progress.csv',accounts,[
            'ordinal','account_key','country','posts','observations','oldest_time',
            'newest_time','backfill_done_flag','history_pages','history_basis','history_chain_reason',
            'has_backfill_cursor','active_catchup','queued_gaps','blocked','coverage_verified'])
        for name,items in [('integrity_findings.csv',integrity),
                           ('observation_findings.csv',observation),
                           ('coverage_findings.csv',coverage)]:
            _as_csv(dest/name,items,['severity','code','account_key','detail'])
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--report-dir',type=Path)
    args=p.parse_args(argv)
    try:
        report=audit(args.output_dir,args.report_dir)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 2 if report['status']=='FAIL' else 0
    except (OSError,ValueError,sqlite3.Error) as exc:
        print('AUDIT FAILED:',str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
