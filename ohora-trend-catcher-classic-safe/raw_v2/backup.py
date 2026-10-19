#!/usr/bin/env python3
"""Create a consistent SQLite backup without changing the live OHORA RAW database."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib
from itertools import zip_longest
from pathlib import Path
import sqlite3


def assert_same_snapshot(source, copied):
    """Compare schema and every stored value, including cursors and run state."""
    schema="SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
    if [tuple(r) for r in source.execute(schema)]!=[tuple(r) for r in copied.execute(schema)]:
        raise ValueError('Backup is not a current snapshot: schema')
    sentinel=object()
    for (name,) in source.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        quoted='"'+name.replace('"','""')+'"'
        columns=len(source.execute('SELECT * FROM '+quoted+' LIMIT 0').description)
        query='SELECT * FROM '+quoted+' ORDER BY '+','.join(str(i) for i in range(1,columns+1))
        for left,right in zip_longest(source.execute(query),copied.execute(query),fillvalue=sentinel):
            if left is sentinel or right is sentinel or tuple(left)!=tuple(right):
                raise ValueError('Backup is not a current snapshot: '+name)


def backup_store(output_dir,backup_dir):
    source=Path(output_dir).resolve()/'collection.sqlite'
    if not source.is_file():raise ValueError('Existing collection.sqlite not found')
    destination=Path(backup_dir).resolve()
    if destination==source.parent or destination.is_relative_to(source.parent):
        raise ValueError('Save backups OUTSIDE the live output directory')
    destination.mkdir(parents=True,exist_ok=True)
    timestamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target=destination/('collection_'+timestamp+'.sqlite')
    if target.exists():raise ValueError('Backup already exists; no overwrite')
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src:
            # Keep the backup and its validation on one consistent read snapshot.
            src.execute('BEGIN')
            src.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()
            with closing(sqlite3.connect(target)) as out:
                src.backup(out,pages=128)
                if out.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise ValueError('Backup failed integrity_check')
                assert_same_snapshot(src,out)
                copied_count=out.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    print('BACKUP_CREATED',target)
    print('SHA256',digest)
    print('POSTS',copied_count)
    print('Important: retain original runs/raw JSON separately; the SQLite snapshot does not include it.')
    return target


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--backup-dir',type=Path,required=True)
    a=p.parse_args()
    try:backup_store(a.output_dir,a.backup_dir);return 0
    except (OSError,ValueError,sqlite3.Error) as e:
        print('BACKUP_FAILED',str(e));return 1


if __name__=='__main__':
    raise SystemExit(main())
