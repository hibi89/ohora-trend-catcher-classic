#!/usr/bin/env python3
"""Offline re-open and integrity audit of OHORA RAW v2 results (no API/credentials)."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing


def verify(folder,run_id=None):
    root=Path(folder).resolve()
    runs=root/'runs'
    options=sorted(x for x in runs.iterdir() if x.is_dir()) if runs.is_dir() else []
    if not options:raise ValueError('No run folders')
    folder=(runs/run_id if run_id else options[-1])
    data=json.loads((folder/'run_manifest.json').read_text(encoding='utf-8'))
    if data['schema']!='raw-v2.1':raise ValueError('Unexpected schema')
    files=data.get('file_sha256',{})
    if not files:raise ValueError('No file hashes')
    for rel,expected in files.items():
        path=folder/rel
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('File missing or SHA mismatch: '+rel)
    for name,expected in data['row_count'].items():
        with (folder/name).open(encoding='utf-8-sig',newline='') as fp:
            count=sum(1 for _ in csv.DictReader(fp))
        if count!=expected:raise ValueError('Row count mismatch: '+name)
    with closing(sqlite3.connect(f'file:{(root/"collection.sqlite").as_posix()}?mode=ro',uri=True)) as db:
        orphan=db.execute('SELECT COUNT(*) FROM post_media m LEFT JOIN posts p ON p.post_id=m.post_id WHERE p.post_id IS NULL').fetchone()[0]
        duplicates=db.execute('SELECT COUNT(*)-COUNT(DISTINCT post_id) FROM posts').fetchone()[0]
        cross=db.execute('SELECT COUNT(*) FROM post_observations o LEFT JOIN posts p ON p.post_id=o.post_id WHERE p.post_id IS NULL').fetchone()[0]
        if orphan or duplicates or cross:raise ValueError(f'SQLite integrity failed: orphan={orphan},duplicates={duplicates},unlinked_obs={cross}')
        rows=db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
        if rows!=294:raise ValueError('Account roster size differs from 294')
        problems=db.execute("PRAGMA integrity_check").fetchone()[0]
        if problems!='ok':raise ValueError('SQLite integrity check failed')
        posts=db.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
        observations=db.execute('SELECT COUNT(*) FROM post_observations').fetchone()[0]
        missing=db.execute('SELECT COUNT(*) FROM post_observations WHERE like_present=0').fetchone()[0]
    return {'verified_run':data['run_id'],'checks':'PASS','sha_files':len(files),'rows':data['row_count'],
            'cumulative_posts':posts,'observations':observations,'like_missing_or_null_observations':missing}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',required=True)
    p.add_argument('--run-id')
    args=p.parse_args()
    try:
        print(json.dumps(verify(args.output_dir,args.run_id),indent=2));return 0
    except (OSError,ValueError,sqlite3.Error,json.JSONDecodeError) as e:
        print('FAIL:',str(e));return 1

if __name__=='__main__':raise SystemExit(main())
