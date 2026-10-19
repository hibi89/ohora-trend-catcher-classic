"""Synthetic offline tests for read-only per-account status reporting."""
import sys
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'raw_v2'))
from account_collection_status import generate, rows_from_db

class AccountStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=self.root/'collection.sqlite'
        self.c=sqlite3.connect(self.db)
        self.c.row_factory=sqlite3.Row
        self.c.executescript("""
          CREATE TABLE config(k TEXT PRIMARY KEY,v TEXT);
          CREATE TABLE accounts(account_key TEXT,country TEXT,username TEXT,ordinal INTEGER,blocked INTEGER,backfill_done INTEGER,backfill_cursor TEXT,catchup_cursor TEXT,last_attempt TEXT,last_error TEXT);
          CREATE TABLE posts(post_id TEXT PRIMARY KEY,account_key TEXT,timestamp TEXT);
          CREATE TABLE post_observations(post_id TEXT,observed_at TEXT);
          CREATE TABLE request_log(account_key TEXT,phase TEXT,status TEXT,http_status INTEGER,finished_at TEXT,started_at TEXT,error_code TEXT,error_message TEXT);
          CREATE TABLE catchup_jobs(account_key TEXT);
          CREATE TABLE history_page_evidence(account_key TEXT,request_id TEXT,requested_cursor TEXT,response_cursor TEXT,oldest_page_ts TEXT,newest_page_ts TEXT,cutoff_ts TEXT,completion_basis TEXT,observed_at TEXT);
        """)
        for i in range(1,7):
            self.c.execute('INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?,?)',(f'KR_{i:03}','KR',f'user{i}',i,1 if i==3 else 0,1 if i==4 else 0,None,None,None,None))
        self.c.executemany('INSERT INTO posts VALUES (?,?,?)',[
            ('p1','KR_001','2025-03-01T00:00:00+00:00'),('p2','KR_001','2026-10-18T00:00:00+00:00'),
            ('p3','KR_005','2026-10-18T00:00:00+00:00')])
        self.c.executemany('INSERT INTO request_log VALUES (?,?,?,?,?,?,?,?)',[
            ('KR_001','front','success',200,'2026-10-18T16:01:00+00:00','2026-10-18T16:00:00+00:00',None,None),
            ('KR_002','front','success',200,'2026-10-18T15:01:00+00:00','2026-10-18T15:00:00+00:00',None,None),
            ('KR_003','front','failed',400,'2026-10-18T15:02:00+00:00','2026-10-18T15:00:00+00:00','110','unavailable'),
            ('KR_005','history','success',200,'2026-10-18T16:03:00+00:00','2026-10-18T16:00:00+00:00',None,None),
            ('KR_006','front','success',200,'2026-10-18T15:03:00+00:00','2026-10-18T15:00:00+00:00',None,None),
        ])
        self.c.execute('INSERT INTO catchup_jobs VALUES (?)',('KR_006',))
        self.c.executemany('INSERT INTO post_observations VALUES (?,?)', [('p1','2026-10-17'),('p1','2026-10-18')])
        self.c.commit()
        self.now=datetime(2026,10,19,1,0,tzinfo=timezone.utc)
    def tearDown(self): self.c.close()
    def test_all_accounts_zero_post_and_kst_boundary(self):
        rows=rows_from_db(self.c,self.now)
        self.assertEqual(len(rows),6)
        self.assertEqual(rows[1]['unique_posts'],0)
        self.assertEqual(rows[1]['front_checked_today_kst'],'yes')
        self.assertEqual(rows[0]['front_checked_today_kst'],'yes')
        self.assertEqual(rows[0]['oldest_post_at'],'2025-03-01T00:00:00+00:00')
        self.assertEqual(rows[0]['unique_posts'],2) # two observations of p1 must not increase unique post count
    def test_history_not_front_catchup_unverified_and_errors(self):
        rows=rows_from_db(self.c,self.now)
        self.assertEqual(rows[4]['front_checked_today_kst'],'unknown')
        self.assertEqual(rows[5]['latest_gap_status'],'catchup_pending')
        self.assertEqual(rows[5]['pending_catchup_jobs'],1)
        self.assertEqual(rows[3]['history_status'],'completion_flag_unverified')
        self.assertEqual(rows[2]['last_error_code'],'110')
    def test_read_only_and_output(self):
        before=self.db.read_bytes()
        self.c.close()
        dest,count=generate(self.db,self.root/'reports',self.now)
        self.assertEqual(count,6)
        self.assertTrue((dest/'account_collection_status.csv').is_file())
        self.assertTrue((dest/'account_collection_status.md').is_file())
        self.assertEqual(before,self.db.read_bytes())
        self.c=sqlite3.connect(self.db)
        self.c.row_factory=sqlite3.Row
    def test_output_failure_keeps_db_unchanged(self):
        before=self.db.read_bytes()
        self.c.close()
        blocked=self.root/'not_a_directory'
        blocked.write_text('x')
        with self.assertRaises(OSError): generate(self.db,blocked,self.now)
        self.assertEqual(before,self.db.read_bytes())
        self.c=sqlite3.connect(self.db)
        self.c.row_factory=sqlite3.Row
    def test_missing_db_and_schema(self):
        with self.assertRaises(FileNotFoundError): generate(self.root/'missing.sqlite',self.root/'reports',self.now)
        self.c.execute('DROP TABLE catchup_jobs');self.c.commit()
        with self.assertRaisesRegex(ValueError,'incompatible'): rows_from_db(self.c,self.now)

if __name__=='__main__': unittest.main()
