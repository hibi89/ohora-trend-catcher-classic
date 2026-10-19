#!/usr/bin/env python3
"""Read-only preflight for legacy missing front-root evidence. No API, no DB writes."""
import argparse
import json
import sqlite3
from pathlib import Path
from datetime import datetime

TARGETS=('KR_055','KR_078','US_019','US_022','US_023','US_059','US_072','US_075','JP_055','JP_061')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,required=True)
    a=p.parse_args()
    base=a.output_dir.resolve()
    dbfile=base/'collection.sqlite'
    if not dbfile.is_file():
        print('FAIL: DB missing');return 2
    db=sqlite3.connect(dbfile.as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    failed=0
    try:
        for key in TARGETS:
            reasons=[]
            account=db.execute('SELECT * FROM accounts WHERE account_key=?',(key,)).fetchone()
            if account is None:
                print(key,'FAIL account missing');failed+=1;continue
            roots=db.execute('SELECT COUNT(*) FROM history_page_evidence WHERE account_key=? AND requested_cursor IS NULL',(key,)).fetchone()[0]
            if roots:reasons.append('root already exists')
            if not account['backfill_cursor']:reasons.append('no saved cursor')
            logs=list(db.execute("""SELECT * FROM request_log WHERE account_key=? AND phase='front' AND status='success' ORDER BY finished_at""",(key,)))
            if len(logs)!=1:reasons.append('expected exactly one successful front, found '+str(len(logs)))
            if logs:
                log=logs[0]
                fp=base/str(log['raw_response_path'])
                if not fp.is_file():reasons.append('raw file missing')
                else:
                    try:
                        raw=json.loads(fp.read_text(encoding='utf-8'))
                        media=raw['business_discovery']['media']
                        data=media['data']
                        cursors=media.get('paging',{}).get('cursors',{})
                        after=cursors.get('after')
                        if after!=account['backfill_cursor']:reasons.append('cursor mismatch')
                        if not isinstance(data,list) or not data:reasons.append('missing posts')
                        else:
                            dates=[datetime.fromisoformat(x['timestamp'].replace('Z','+00:00')) for x in data]
                            if dates!=sorted(dates,reverse=True):reasons.append('timestamps not descending')
                            observed=db.execute('SELECT COUNT(*) FROM post_observations WHERE request_id=? AND run_id=?',(log['request_id'],log['run_id'])).fetchone()[0]
                            if observed!=len(data):reasons.append('observation count mismatch')
                        if db.execute('SELECT COUNT(*) FROM history_page_evidence WHERE request_id=?',(log['request_id'],)).fetchone()[0]:
                            reasons.append('request evidence already present')
                        if db.execute('SELECT COUNT(*) FROM request_log WHERE request_id=?',(log['request_id'],)).fetchone()[0]!=1:
                            reasons.append('ambiguous request ID')
                    except (OSError,KeyError,TypeError,ValueError) as exc:reasons.append('raw parse: '+str(exc))
            if db.execute('SELECT COUNT(*) FROM history_page_evidence WHERE account_key=? AND requested_cursor IS NOT NULL',(key,)).fetchone()[0]:
                reasons.append('existing non-root evidence requires manual review')
            print(key,'PASS: candidate only (not restored)' if not reasons else 'REVIEW: '+ '; '.join(reasons))
            failed+=bool(reasons)
    finally:
        db.execute('ROLLBACK')
        db.close()
    print('RESULT:', 'PASS candidate review only; zero modifications' if not failed else f'REVIEW {failed} account(s); zero modifications')
    return 0 if not failed else 2

if __name__=='__main__':
    raise SystemExit(main())
