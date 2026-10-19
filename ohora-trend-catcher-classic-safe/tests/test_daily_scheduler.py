"""Offline tests for daily-first RAW v2 scheduling and data safety."""
import json
import sqlite3
import sys
from argparse import Namespace
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'raw_v2'))
import collector as c
import daily_scheduler as sched


def create_roster(path):
    import csv
    with path.open('w',newline='',encoding='utf-8') as fp:
        wr=csv.writer(fp);wr.writerow(['account_key','username','country','profile_url'])
        for country,count in [('KR',100),('US',101),('JP',93)]:
            for n in range(1,count+1):
                wr.writerow([f'{country}_{n:03}',f'{country.lower()}_test_{n}',country,''])


def make_page(ids,after='NEXT',likes=2):
    return {'business_discovery':{
        'id':'987654321','username':'kr_test_1','followers_count':100,'media_count':500,
        'media':{'data':[{
            'id':str(10**17+n),'username':'kr_test_1','timestamp':'2026-10-18T01:00:00+0000',
            'media_type':'IMAGE','comments_count':1,'like_count':likes,
            'permalink':'https://example.invalid/post'
        } for n in ids], 'paging':{'cursors':{'after':after}} if after else {}}
    }}


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.source=self.base/'accounts.csv'
        create_roster(self.source)
        self.accounts,self.digest=c.load_accounts(self.source)
        self.db=c.connect(self.base/'store'/'collection.sqlite',self.accounts,self.digest)
        self.addCleanup(self.db.close)

    def account(self,key='KR_001'):
        return dict(self.db.execute('SELECT * FROM accounts WHERE account_key=?',(key,)).fetchone())

    def mark_fronts_complete(self,day='2026-10-19'):
        with self.db:
            self.db.executemany(
                "INSERT INTO daily_account_state(day_kst,account_key,status,attempts,updated_at) VALUES (?,?,?,?,?)",
                [(day,a['account_key'],'success',1,c.now())
                 for a in self.db.execute('SELECT account_key FROM accounts')])

    def test_daily_front_order_and_retry_priority(self):
        tasks=sched.select_daily_tasks(self.db,'2026-10-19')
        self.assertEqual(len(tasks),150)
        self.assertEqual([a['ordinal'] for _,a in tasks[:3]],[1,2,3])
        with self.db:
            self.db.execute("""INSERT INTO daily_account_state
                (day_kst,account_key,status,attempts,updated_at) VALUES (?,?,?,?,?)""",
                ('2026-10-19','KR_001','success',1,c.now()))
            self.db.execute("""INSERT INTO daily_account_state
                (day_kst,account_key,status,attempts,updated_at) VALUES (?,?,?,?,?)""",
                ('2026-10-19','KR_002','retry_pending',1,c.now()))
            self.db.execute("UPDATE accounts SET blocked=1 WHERE account_key='KR_003'")
        tasks=sched.select_daily_tasks(self.db,'2026-10-19')
        self.assertEqual(tasks[0][1]['account_key'],'KR_004')
        self.assertEqual(tasks[-1][1]['account_key'],'KR_002')
        self.assertNotIn('KR_001',[a['account_key'] for _,a in tasks])
        self.assertNotIn('KR_003',[a['account_key'] for _,a in tasks])
        self.assertTrue(all(a['ordinal']<=150 for _,a in tasks))
        # A new KST day is an independent front cycle.
        self.assertEqual(sched.select_daily_tasks(self.db,'2026-10-20')[0][1]['account_key'],'KR_001')

    def test_second_roster_cohort_only_after_first_completed(self):
        with self.db:
            self.db.executemany(
                'INSERT INTO daily_account_state(day_kst,account_key,status,attempts,updated_at) VALUES (?,?,?,?,?)',
                [('2026-10-19',a['account_key'],'success',1,c.now())
                 for a in self.db.execute('SELECT account_key FROM accounts WHERE ordinal<=150')])
        tasks=sched.select_daily_tasks(self.db,'2026-10-19')
        self.assertEqual(len(tasks),144)
        self.assertEqual((tasks[0][1]['ordinal'],tasks[-1][1]['ordinal']),(151,294))

    def test_bootstrap_existing_front_observation_without_api(self):
        day=sched.today_kst()
        with self.db:
            self.db.execute("""INSERT INTO request_log(run_id,request_id,account_key,phase,status,finished_at)
                               VALUES (?,?,?,?,?,?)""",
                            ('legacy','legacy_1','KR_001','front','success',c.now()))
            self.db.execute("""INSERT INTO request_log(run_id,request_id,account_key,phase,status,finished_at)
                               VALUES (?,?,?,?,?,?)""",
                            ('legacy','legacy_2','KR_002','history','success',c.now()))
        snap=sched.inspect_store(self.base/'store',self.accounts,self.digest)
        self.assertEqual(snap['day'],day)
        self.assertEqual(snap['success'],1)
        self.assertEqual(sched.select_daily_tasks(self.db,day)[0][1]['account_key'],'KR_002')

    def test_stage_order_no_history_while_front_pending(self):
        a=self.account()
        c.insert_success(self.db,a,'front',make_page(range(1,5)),'R1','req1',c.now(),365,limit=4)
        self.assertTrue(all(phase=='front' for phase,a in sched.select_daily_tasks(self.db,'2026-10-19')))
        with self.db:
            self.db.executemany("INSERT INTO daily_account_state(day_kst,account_key,status,attempts,updated_at) VALUES (?,?,?,?,?)",
                 [('2026-10-19',a['account_key'],'success',1,c.now()) for a in self.db.execute('SELECT account_key FROM accounts')])
        tasks=sched.select_daily_tasks(self.db,'2026-10-19')
        self.assertEqual(tasks[0][0],'history')
        with self.db:
            self.db.execute("UPDATE accounts SET catchup_cursor='GAP',catchup_anchor='ANCHOR' WHERE account_key='KR_001'")
        self.assertEqual(sched.select_daily_tasks(self.db,'2026-10-19')[0][0],'catchup')

    def test_queued_gap_preserved_by_further_daily_front(self):
        t=c.now()
        c.insert_success(self.db,self.account(),'front',make_page(range(1,5),after='BASE'),'R1','r1',t,365,limit=4)
        c.insert_success(self.db,self.account(),'front',make_page(range(5,9),after='GAP1'),'R2','r2',t,365,limit=4)
        first=self.account()
        self.assertEqual((first['catchup_cursor'],first['catchup_anchor']),('GAP1',str(10**17+1)))
        c.insert_success(self.db,self.account(),'front',make_page(range(9,13),after='GAP2'),'R3','r3',t,365,limit=4)
        second=self.account()
        self.assertEqual((second['catchup_cursor'],second['catchup_anchor']),('GAP1',str(10**17+1)))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catchup_jobs').fetchone()[0],1)
        c.insert_success(self.db,self.account(),'catchup',make_page(range(1,5),after='PAGE2'),'R4','r4',t,365,limit=4)
        third=self.account()
        self.assertEqual((third['catchup_cursor'],third['catchup_anchor']),('GAP2',str(10**17+5)))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catchup_jobs').fetchone()[0],0)
        self.assertEqual(third['last_front'],second['last_front'])
        c.insert_success(self.db,self.account(),'catchup',make_page(range(5,9),after='PAGE3'),'R5','r5',t,365,limit=4)
        self.assertIsNone(self.account()['catchup_cursor'])

    def test_deferred_catchup_never_becomes_history_for_same_account(self):
        day='2026-10-19'
        with self.db:
            self.db.executemany(
                "INSERT INTO daily_account_state(day_kst,account_key,status,attempts,updated_at) VALUES (?,?,?,?,?)",
                [(day,r['account_key'],'success',1,c.now()) for r in self.db.execute('SELECT account_key FROM accounts')])
            self.db.execute("UPDATE accounts SET catchup_cursor='OLD_GAP',catchup_anchor='ANCHOR',latest_id='123',backfill_cursor='OLDER' WHERE account_key='KR_001'")
            for n in (1,2):
                self.db.execute(
                    "INSERT INTO request_log(run_id,request_id,account_key,phase,status,finished_at) VALUES (?,?,?,?,?,?)",
                    ('R',f'failed_catchup_{n}','KR_001','catchup','failed','2026-10-18T16:10:00+00:00'))
        tasks=sched.select_daily_tasks(self.db,day)
        self.assertNotIn('KR_001',[a['account_key'] for _,a in tasks])
        self.assertIsNone(self.account()['last_history'])

    def test_insert_hook_rolls_back_all_post_updates(self):
        def fail(*_):raise ValueError('simulate logging failure')
        with self.assertRaisesRegex(ValueError,'logging failure'):
            c.insert_success(self.db,self.account(),'front',make_page([1],after=None),
                             'R','req',c.now(),365,limit=4,commit_hook=fail)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM post_observations').fetchone()[0],0)
        self.assertIsNone(self.account()['latest_id'])

    def test_usage_checks_all_available_counters(self):
        self.assertEqual(c.usage({'X-App-Usage':'{"call_count":84,"total_time":30,"total_cputime":87}'}),87)
        self.assertIsNone(c.usage({}))
        self.assertEqual(c.usage({'X-App-Usage':'{"total_time":70}'}),70)

    def test_two_runs_same_post_two_days_unique_request_ids(self):
        env=self.base/'secret.env'
        env.write_text('META_ACCESS_TOKEN=SECRET\nMETA_IG_USER_ID=12345',encoding='utf-8')
        out=self.base/'out'
        args=Namespace(source=self.source,env_file=env,output_dir=out,live=True,mode='front',
                       batch_size=1,max_batches=1,limit=4,window_days=7,history_days=365,
                       stop_usage=85,extended_fields=False,cycle_minutes=63)
        called=[0]
        def fake(version,token,ops):
            called[0]+=1
            body=make_page([1],after=None,likes=100+called[0])
            return 200,[{'code':200,'body':json.dumps(body),'headers':[]}],{'X-App-Usage':'{"total_time":3}'}
        def chooser(db,n):
            return [('front',dict(db.execute("SELECT * FROM accounts WHERE account_key='KR_001'").fetchone()))]
        with patch.object(c,'datetime',wraps=c.datetime) as clock:
            clock.now.return_value=c.parse_date('2026-10-19T01:00:00+00:00')
            self.assertEqual(c.run(args,fake,chooser,'2026-10-19'),0)
        with closing(sqlite3.connect(out/'collection.sqlite')) as db:
            db.execute("UPDATE slots SET ready_at='2000-01-01T00:00:00+00:00'");db.commit()
        with patch.object(c,'datetime',wraps=c.datetime) as clock:
            clock.now.return_value=c.parse_date('2026-10-20T01:00:00+00:00')
            self.assertEqual(c.run(args,fake,chooser,'2026-10-20'),0)
        with closing(sqlite3.connect(out/'collection.sqlite')) as db:
            reqs=[row[0] for row in db.execute('SELECT request_id FROM request_log')]
            self.assertEqual(len(reqs),2)
            self.assertEqual(len(set(reqs)),2)
            self.assertEqual([row[0] for row in db.execute('SELECT like_count FROM post_observations ORDER BY id')],[101,102])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM daily_account_state WHERE status='success'").fetchone()[0],2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],1)
        self.assertEqual(called[0],2)

    def test_bootstrap_only_fills_missing_head_then_history(self):
        c.insert_success(self.db,self.account(),'front',make_page([1],after='OLDER'),
                         'R1','r1',c.now(),365,limit=4)
        tasks=sched.select_daily_tasks(self.db,'2026-10-19',policy='bootstrap-history')
        self.assertEqual(tasks[0][1]['account_key'],'KR_002')
        self.assertTrue(all(phase=='front' and not a['latest_id'] for phase,a in tasks))

    def test_history_only_waits_for_daily_front_without_requesting_latest(self):
        c.insert_success(self.db,self.account(),'front',make_page([1],after='OLDER'),
                         'R1','r1',c.now(),365,limit=4)
        tasks=sched.select_daily_tasks(self.db,'2026-10-19',policy='history-only')
        self.assertEqual(tasks,[])
        self.mark_fronts_complete()
        tasks=sched.select_daily_tasks(self.db,'2026-10-19',policy='history-only')
        self.assertEqual(tasks[0][0],'history')
        self.assertEqual(tasks[0][1]['account_key'],'KR_001')
        self.assertEqual(sched.select_daily_tasks(self.db,'2026-10-20',policy='history-only'),[])

    def test_history_only_allows_front_exceptions_but_not_retryable_fronts(self):
        self.mark_fronts_complete()
        c.insert_success(self.db,self.account(),'front',make_page([1],after='OLDER'),
                         'R1','r1',c.now(),365,limit=4)
        with self.db:
            self.db.execute("UPDATE daily_account_state SET status='retry_pending',attempts=1 WHERE account_key='KR_002'")
            self.db.execute("UPDATE accounts SET catchup_cursor='GAP',catchup_anchor='ANCHOR' WHERE account_key='KR_001'")
        self.assertEqual(sched.select_daily_tasks(self.db,'2026-10-19',policy='history-only'),[])
        with self.db:
            self.db.execute("UPDATE daily_account_state SET attempts=2 WHERE account_key='KR_002'")
            self.db.execute("UPDATE accounts SET blocked=1 WHERE account_key='KR_003'")
        self.assertEqual(sched.select_daily_tasks(self.db,'2026-10-19',policy='history-only')[0][0],'catchup')

    def test_inspect_history_only_distinguishes_pending_front_and_exhausted_exception(self):
        self.mark_fronts_complete()
        with self.db:
            self.db.execute("UPDATE daily_account_state SET status='retry_pending',attempts=1 WHERE account_key='KR_002'")
            self.db.execute("UPDATE accounts SET blocked=1 WHERE account_key='KR_003'")
        with patch.object(sched,'today_kst',return_value='2026-10-19'):
            snap=sched.inspect_store(self.base/'store',self.accounts,self.digest,'history-only')
        self.assertEqual((snap['stage'],snap['front_pending'],snap['exceptions'],snap['blocked']),
                         ('front_pending',1,0,1))
        with self.db:
            self.db.execute("UPDATE daily_account_state SET attempts=2 WHERE account_key='KR_002'")
        with patch.object(sched,'today_kst',return_value='2026-10-19'):
            snap=sched.inspect_store(self.base/'store',self.accounts,self.digest,'history-only')
        self.assertEqual((snap['stage'],snap['front_pending'],snap['exceptions']),('done',0,1))

    def test_history_only_reports_pending_front_and_never_calls_collector(self):
        options=['--source',str(self.source),'--output-dir',str(self.base/'live_empty'),
                 '--env-file',str(self.base/'unused.env'),'--live','--once','--policy','history-only']
        snapshot={'day':'2026-10-19','stage':'front_pending','front_pending':294,
                  'success':0,'exceptions':0,'blocked':0,'pending_gaps':0,'ready':None}
        with patch.object(c,'load_env'),patch.object(sched,'inspect_store',return_value=snapshot), \
             patch.object(c,'run') as run:
            self.assertEqual(sched.main(options),4)
            run.assert_not_called()

    def test_history_only_rechecks_date_after_each_completed_batch(self):
        options=['--source',str(self.source),'--output-dir',str(self.base/'live_empty'),
                 '--env-file',str(self.base/'unused.env'),'--live','--once','--policy','history-only']
        snapshot={'day':'2026-10-19','stage':'history','front_pending':0,
                  'success':294,'exceptions':0,'blocked':0,'pending_gaps':0,'ready':None}
        with patch.object(c,'load_env'),patch.object(sched,'inspect_store',return_value=snapshot), \
             patch.object(c,'run',return_value=0) as run:
            self.assertEqual(sched.main(options),0)
            self.assertEqual(run.call_args.kwargs['daily_day'],'2026-10-19')
            self.assertEqual(run.call_args.kwargs['cooldown_minutes'],63)
            self.assertEqual(run.call_args.args[0].cycle_minutes,65)

    def test_daily_front_policy_never_enters_history(self):
        c.insert_success(self.db,self.account(),'front',make_page([1],after='OLDER'),
                         'R1','r1',c.now(),365,limit=4)
        with self.db:
            self.db.executemany(
                "INSERT INTO daily_account_state(day_kst,account_key,status,attempts,updated_at) VALUES (?,?,?,?,?)",
                [('2026-10-19',a['account_key'],'success',1,c.now())
                 for a in self.db.execute('SELECT account_key FROM accounts')])
        self.assertEqual(sched.select_daily_tasks(self.db,'2026-10-19',policy='daily-front'),[])
        self.assertEqual(sched.select_daily_tasks(self.db,'2026-10-19',policy='daily')[0][0],'history')

    def test_legacy_done_flag_with_cursor_remains_history_eligible(self):
        c.insert_success(self.db,self.account(),'front',make_page([1],after='OLDER'),
                         'R1','r1',c.now(),365,limit=4)
        with self.db:
            self.db.execute("UPDATE accounts SET backfill_done=1 WHERE account_key='KR_001'")
        self.mark_fronts_complete()
        tasks=sched.select_daily_tasks(self.db,'2026-10-19',policy='history-only')
        self.assertEqual(tasks[0][1]['account_key'],'KR_001')
        self.assertEqual(self.account()['backfill_done'],1)  # old data not cleared

    def test_legacy_done_flag_without_cursor_restarts_proof_without_erasing_flag(self):
        with self.db:
            self.db.execute("UPDATE accounts SET latest_id='123',backfill_done=1,backfill_cursor=NULL WHERE account_key='KR_001'")
        self.mark_fronts_complete()
        tasks=sched.select_daily_tasks(self.db,'2026-10-19',policy='history-only')
        self.assertEqual([(p,a['account_key']) for p,a in tasks],[('history','KR_001')])
        self.assertIsNone(tasks[0][1]['backfill_cursor'])
        self.assertEqual(self.account()['backfill_done'],1)

    def test_verified_terminal_front_does_not_restart_history(self):
        c.insert_success(self.db,self.account(),'front',make_page([1],after=None),
                         'R1','r1',c.now(),365,limit=4)
        self.mark_fronts_complete()
        self.assertEqual(sched.select_daily_tasks(self.db,'2026-10-19',policy='history-only'),[])

    def test_daily_dryrun_does_not_touch_db(self):
        result=sched.main(['--source',str(self.source),'--output-dir',str(self.base/'missing')])
        self.assertEqual(result,0)
        self.assertFalse((self.base/'missing').exists())


if __name__=='__main__':
    unittest.main()
