#!/usr/bin/env python3
"""Read-only OHORA per-account coverage report. No API, credentials or migrations."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
import sys

KST = timezone(timedelta(hours=9))
FIELDS = ('account_key','country','username','unique_posts','oldest_post_at','newest_post_at',
          'last_successful_front_at','front_checked_today_kst','latest_gap_status',
          'pending_catchup_jobs','history_status','history_evidence_status',
          'last_attempt_at','last_error_code','last_error_reason','report_as_of')
REQUIRED = {
    'accounts': {'account_key','country','username','blocked','backfill_done','backfill_cursor','catchup_cursor','last_attempt','last_error'},
    'posts': {'post_id','account_key','timestamp'},
    'request_log': {'account_key','phase','status','http_status','finished_at','started_at','error_code','error_message'},
    'catchup_jobs': {'account_key'},
    'history_page_evidence': {'account_key'},
}

def iso(value):
    if not value: return ''
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None: return ''
        return dt.astimezone(timezone.utc).isoformat(timespec='seconds')
    except (ValueError, TypeError): return ''

def kst(value):
    dt=iso(value)
    return datetime.fromisoformat(dt).astimezone(KST).strftime('%Y-%m-%d %H:%M KST') if dt else '미확인'

def table_columns(db, name):
    return {r[1] for r in db.execute('PRAGMA table_info("'+name+'")')}

def rows_from_db(db, as_of=None):
    from collector import history_chain_status
    as_of=as_of or datetime.now(timezone.utc)
    today=as_of.astimezone(KST).date().isoformat()
    stamp=as_of.isoformat(timespec='seconds')
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, columns in REQUIRED.items():
        if table not in tables or not columns.issubset(table_columns(db,table)):
            raise ValueError(f'incompatible DB schema: {table} missing required columns')
    results=[]
    for a in db.execute('SELECT * FROM accounts ORDER BY ordinal, account_key').fetchall():
        key=a['account_key']
        post=db.execute('SELECT COUNT(*),MIN(timestamp),MAX(timestamp) FROM posts WHERE account_key=?',(key,)).fetchone()
        front=db.execute("""SELECT finished_at FROM request_log
            WHERE account_key=? AND phase='front' AND status='success' AND http_status=200
            AND finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1""",(key,)).fetchone()
        front_at=iso(front[0]) if front else ''
        front_today='yes' if front_at and datetime.fromisoformat(front_at).astimezone(KST).date().isoformat()==today else 'no' if front_at else 'unknown'
        pending=db.execute('SELECT COUNT(*) FROM catchup_jobs WHERE account_key=?',(key,)).fetchone()[0]
        gap='catchup_pending' if a['catchup_cursor'] or pending else 'no_known_gap'
        chain=history_chain_status(db,key)
        chain_state='rooted_chain_verified' if chain['verified'] else 'unverified:'+str(chain['reason'])
        done=bool(a['backfill_done'])
        if a['blocked']: hist='blocked_review'
        elif done and chain['verified'] and gap=='no_known_gap': hist='completion_chain_verified_raw_audit_required'
        elif done: hist='completion_flag_unverified'
        elif a['backfill_cursor'] or db.execute("SELECT 1 FROM request_log WHERE account_key=? AND phase='history' LIMIT 1",(key,)).fetchone(): hist='in_progress'
        else: hist='not_started'
        attempt=db.execute("""SELECT started_at,error_code,error_message FROM request_log
            WHERE account_key=? ORDER BY started_at DESC LIMIT 1""",(key,)).fetchone()
        last_at=iso(attempt[0]) if attempt else iso(a['last_attempt'])
        err_code=str(attempt[1] or '') if attempt and attempt[1] else ''
        err_reason=str(attempt[2] or '') if attempt and attempt[2] else ''
        if not err_reason and a['last_error']: err_reason=str(a['last_error'])
        results.append(dict(zip(FIELDS,(key,a['country'],a['username'],post[0],iso(post[1]),iso(post[2]),
            front_at,front_today,gap,pending,hist,chain_state,last_at,err_code,err_reason,stamp))))
    return results

def generate(db_path, output_root, as_of=None):
    db_path=Path(db_path)
    if not db_path.is_file(): raise FileNotFoundError(f'DB does not exist: {db_path}')
    con=sqlite3.connect(db_path.resolve().as_uri()+'?mode=ro',uri=True)
    con.row_factory=sqlite3.Row
    try:
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
        rows=rows_from_db(con,as_of)
        con.rollback()
    finally: con.close()
    now=as_of or datetime.now(timezone.utc)
    dest=Path(output_root)/('account_status_'+now.astimezone(KST).strftime('%Y%m%d_%H%M%S_%f'))
    dest.mkdir(parents=True,exist_ok=False)
    with (dest/'account_collection_status.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS)
        writer.writeheader();writer.writerows(rows)
    with (dest/'account_collection_status.md').open('w',encoding='utf-8') as f:
        f.write('# OHORA 계정별 수집 현황\n\n')
        f.write(f'보고 기준: {kst(now.isoformat())} | 공식 계정 {len(rows)}개 | 고유 게시물 {sum(r["unique_posts"] for r in rows)}건\n\n')
        f.write('게시일 범위는 저장된 게시물의 최소·최대값일 뿐 연속 확보를 보장하지 않습니다. ')
        f.write('History 완료 근거는 커서 체인 기준이며 원본 JSON 대조는 별도 audit가 필요합니다.\n\n')
        f.write('| 계정 | 국가 | 사용자명 | 게시물 | 최초 게시일(KST) | 최근 게시일(KST) | 마지막 Front(KST) | 오늘 Front | Catchup | History |\n')
        f.write('|---|---|---|---:|---|---|---|---|---|---|\n')
        for r in rows:
            f.write('| '+' | '.join([str(r['account_key']),str(r['country']),str(r['username']).replace('|','\\|'),
                str(r['unique_posts']),kst(r['oldest_post_at']),kst(r['newest_post_at']),kst(r['last_successful_front_at']),
                r['front_checked_today_kst'],r['latest_gap_status']+' ('+str(r['pending_catchup_jobs'])+')',r['history_status']])+' |\n')
        f.write('\n전체 필드·오류·증거 상태는 동봉 CSV를 확인하세요.\n')
    return dest,len(rows)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',required=True,help='Existing RAW store containing collection.sqlite')
    p.add_argument('--report-dir',required=True,help='Output parent folder outside RAW store')
    args=p.parse_args()
    store=Path(args.output_dir).resolve()
    dest=Path(args.report_dir).resolve()
    if dest==store or store in dest.parents: p.error('--report-dir must be outside collection store')
    try:
        output,n=generate(store/'collection.sqlite',dest)
        print(f'REPORT_CREATED {output} ACCOUNTS {n}')
    except (OSError,sqlite3.Error,ValueError) as exc:
        print(f'REPORT_FAILED: {exc}',file=sys.stderr)
        return 1
    return 0
if __name__=='__main__': raise SystemExit(main())
