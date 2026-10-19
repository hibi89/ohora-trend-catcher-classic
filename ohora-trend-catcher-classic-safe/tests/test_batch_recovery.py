"""No-network archived-batch reconciliation and backup acceptance tests."""
import json
from datetime import timedelta
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'raw_v2'))
import collector as c
import backup as bak
import recover
from test_daily_scheduler import create_roster,make_page


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        network=patch.object(c,'urlopen',side_effect=AssertionError('Offline recovery test attempted network'))
        network.start();self.addCleanup(network.stop)
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.src=self.base/'accounts.csv';create_roster(self.src)
        rows,sha=c.load_accounts(self.src)
        self.out=self.base/'store'
        self.db=c.connect(self.out/'collection.sqlite',rows,sha)
        self.addCleanup(self.db.close)
        self.run_id='recovery_run'
        self.slot=c.active_slot(self.db)
        with self.db:
            self.db.execute("""INSERT INTO runs(run_id,started_at,api_version,mode,status)
                VALUES (?,?,?,?,?)""",(self.run_id,c.now(),'v26.0','daily','started'))

    def plan(self,key='KR_001',phase='front',daily_day=None,**options):
        account=self.db.execute('SELECT * FROM accounts WHERE account_key=?',(key,)).fetchone()
        defaults={'limit':4,'history_days':365,'window_days':7,'extended_fields':False}
        defaults.update(options)
        return {'account_key':key,'ordinal':account['ordinal'],'phase':phase,
                'request_id':f'{self.run_id}_0000_00_{account["ordinal"]:03}_{phase}',
                'requested_cursor':account['catchup_cursor'] if phase=='catchup' else account['backfill_cursor'] if phase=='history' else None,
                'state':{k:account[k] for k in recover.STATE_KEYS},'options':defaults,'daily_day':daily_day,
                'cooldown_minutes':63,'cycle_minutes':65}

    def planned_batch(self, archived=True, plans=None, body=None):
        plans=plans or [self.plan()]
        for i,plan in enumerate(plans):
            plan['request_id']=f'{self.run_id}_0000_{i:02}_{plan["ordinal"]:03}_{plan["phase"]}'
        with self.db:
            self.db.execute("""INSERT INTO batch_attempts
                (run_id,batch_no,slot_id,request_json,started_at,status)
                VALUES (?,?,?,?,?,?)""",
                (self.run_id,0,self.slot,json.dumps(plans),
                    c.now(),'response_saved' if archived else 'prepared'))
        if archived:
            body=body or [{'code':200,'body':json.dumps(make_page([1],after='MORE'))}]
            raw=self.out/'runs'/self.run_id/'raw'/'batch_0000.json'
            raw.parent.mkdir(parents=True,exist_ok=True)
            raw.write_text(json.dumps(body),encoding='utf-8')

    def state(self):
        return '\n'.join(self.db.iterdump())

    def backup(self):
        return bak.backup_store(self.out,self.base/'backups')

    def test_backup_and_replay_with_no_api(self):
        self.planned_batch()
        before=recover.recover(self.out,None,None,False)
        self.assertEqual(before['batches'][0]['resolution'],'ARCHIVE_PRESENT_UNVALIDATED')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],0)
        backup=bak.backup_store(self.out,self.base/'backups')
        self.db.close()
        result=recover.recover(self.out,self.src,backup,True)
        self.assertEqual(result['replayed'],1)
        with sqlite3.connect(self.out/'collection.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM post_observations').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM request_log').fetchone()[0],1)
            self.assertEqual(db.execute("SELECT status FROM batch_attempts").fetchone()[0],'complete')
            self.assertEqual(db.execute("SELECT status FROM slots").fetchone()[0],'cooldown')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM daily_account_state').fetchone()[0],0)
        db.close()
        self.assertEqual(recover.recover(self.out,None,None,False)['batches'],[])

    def test_unknown_remote_outcome_never_retried(self):
        self.planned_batch(archived=False)
        cases=recover.recover(self.out,None,None,False)['batches']
        self.assertEqual(cases[0]['resolution'],'UNKNOWN_REMOTE_OUTCOME')
        backup=bak.backup_store(self.out,self.base/'backup')
        self.db.close()
        with self.assertRaisesRegex(ValueError,'Unknown remote outcome'):
            recover.recover(self.out,self.src,backup,True)
        with sqlite3.connect(self.out/'collection.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM request_log').fetchone()[0],0)
        db.close()

    def test_backup_rejects_same_counts_with_changed_cursor(self):
        self.planned_batch();backup=self.backup()
        with self.db:self.db.execute("UPDATE accounts SET backfill_cursor='CHANGED' WHERE account_key='KR_001'")
        before=self.state()
        with self.assertRaisesRegex(ValueError,'current snapshot: accounts'):
            recover.recover(self.out,self.src,backup,True)
        self.assertEqual(self.state(),before)

    def test_recovery_rejects_cursor_state_changed_after_request(self):
        self.planned_batch()
        with self.db:self.db.execute("UPDATE accounts SET backfill_cursor='CHANGED' WHERE account_key='KR_001'")
        backup=self.backup();before=self.state()
        with self.assertRaisesRegex(ValueError,'cursor/state differs'):
            recover.recover(self.out,self.src,backup,True)
        self.assertEqual(self.state(),before)

    def test_legacy_plan_does_not_guess_request_options(self):
        plan=self.plan();del plan['options']
        self.planned_batch(plans=[plan]);backup=self.backup();before=self.state()
        with self.assertRaisesRegex(ValueError,'options/state absent'):
            recover.recover(self.out,self.src,backup,True)
        self.assertEqual(self.state(),before)

    def test_source_mismatch_does_not_initialize_or_migrate_db(self):
        self.planned_batch()
        with self.db:
            self.db.execute("DELETE FROM config WHERE k='backfill_anchor_utc'")
            self.db.execute('DROP TABLE catchup_page_evidence')
        backup=self.backup();before=self.state()
        wrong=self.base/'wrong_accounts.csv'
        wrong.write_text(self.src.read_text(encoding='utf-8').replace('kr_test_1,','different_name,'),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Source hash'):
            recover.recover(self.out,wrong,backup,True)
        self.assertEqual(self.state(),before)

    def test_existing_raw_is_not_overwritten(self):
        self.planned_batch()
        raw=self.out/'runs'/self.run_id/'raw'/f'{self.run_id}_0000_00_001_front.json'
        raw.write_text('{"prior":"evidence"}',encoding='utf-8')
        backup=self.backup();before=self.state()
        with self.assertRaisesRegex(ValueError,'Existing raw response disagrees'):
            recover.recover(self.out,self.src,backup,True)
        self.assertEqual(raw.read_text(encoding='utf-8'),'{"prior":"evidence"}')
        self.assertEqual(self.state(),before)

    def test_existing_export_without_manifest_is_preserved(self):
        self.planned_batch();export=self.out/'runs'/self.run_id/'posts.csv'
        export.write_text('prior export',encoding='utf-8')
        backup=self.backup();before=self.state()
        with self.assertRaisesRegex(ValueError,'Prior run export exists'):
            recover.recover(self.out,self.src,backup,True)
        self.assertEqual(export.read_text(encoding='utf-8'),'prior export')
        self.assertEqual(self.state(),before)

    def test_all_parts_validated_before_any_rows_or_raw_are_written(self):
        body=[{'code':200,'body':json.dumps(make_page([1],after='MORE'))},
              {'code':200,'body':json.dumps(make_page([2],after='MORE'))}]
        # The second response belongs to KR_001, not the requested KR_002.
        self.planned_batch(plans=[self.plan(),self.plan('KR_002')],body=body)
        backup=self.backup();before=self.state()
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            recover.recover(self.out,self.src,backup,True)
        self.assertEqual(self.state(),before)
        self.assertEqual(len(list((self.out/'runs'/self.run_id/'raw').glob('*.json'))),1)

    def test_exact_limit_and_daily_day_replayed(self):
        day='2026-10-19'
        self.planned_batch(plans=[self.plan(daily_day=day,limit=5,window_days=14,history_days=730)],
                           body=[{'code':200,'body':json.dumps(make_page([1,2,3,4,5],after='MORE'))}])
        result=recover.recover(self.out,self.src,self.backup(),True)
        self.assertEqual(result['replayed'],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],5)
        self.assertEqual(tuple(self.db.execute('SELECT day_kst,status FROM daily_account_state').fetchone()),(day,'success'))
        usage=json.loads(self.db.execute('SELECT usage_json FROM request_log').fetchone()[0])
        self.assertEqual(usage['requested_post_limit'],5)

    def test_failed_replay_uses_scheduler_retry_status(self):
        self.planned_batch(plans=[self.plan(daily_day='2026-10-19')],
                           body=[{'code':400,'body':json.dumps({'error':{'code':4,'message':'synthetic'}})}])
        recover.recover(self.out,self.src,self.backup(),True)
        self.assertEqual(self.db.execute('SELECT status FROM daily_account_state').fetchone()[0],'retry_pending')
        self.assertEqual(self.db.execute('SELECT failures FROM runs').fetchone()[0],1)

    def test_already_committed_part_is_not_counted_or_observed_twice(self):
        first=make_page([1],after='MORE')
        second=make_page([2],after='MORE');second['business_discovery']['username']='kr_test_2'
        plans=[self.plan(),self.plan('KR_002')]
        self.planned_batch(plans=plans,body=[{'code':200,'body':json.dumps(first)},
                                            {'code':200,'body':json.dumps(second)}])
        req=plans[0]['request_id'];ts=c.now()
        raw=self.out/'runs'/self.run_id/'raw'/(req+'.json')
        original=json.dumps(first,indent=4);raw.write_text(original,encoding='utf-8')
        def committed(new,items,more):
            self.db.execute("""INSERT INTO request_log
                (run_id,request_id,account_key,phase,started_at,finished_at,status,records_received,raw_response_path)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (self.run_id,req,'KR_001','front',ts,ts,'success',items,str(raw.relative_to(self.out))))
            self.db.execute('INSERT INTO slot_accounts VALUES (?,?,?)',(self.slot,'KR_001',req))
            self.db.execute('UPDATE runs SET requests=1,successes=1 WHERE run_id=?',(self.run_id,))
        account=dict(self.db.execute("SELECT * FROM accounts WHERE account_key='KR_001'").fetchone())
        c.insert_success(self.db,account,'front',first,self.run_id,req,ts,365,limit=4,commit_hook=committed)
        result=recover.recover(self.out,self.src,self.backup(),True)
        self.assertEqual(result['replayed'],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM post_observations').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM request_log').fetchone()[0],2)
        self.assertEqual(tuple(self.db.execute('SELECT requests,successes,failures FROM runs').fetchone()),(2,2,0))
        self.assertEqual(self.db.execute("SELECT attempts FROM accounts WHERE account_key='KR_001'").fetchone()[0],1)
        self.assertEqual(raw.read_text(encoding='utf-8'),original)

    def test_backup_failure_closes_handles_before_cleanup(self):
        with patch.object(bak,'assert_same_snapshot',side_effect=ValueError('synthetic validation failure')):
            with self.assertRaisesRegex(ValueError,'synthetic validation failure'):
                self.backup()
        self.assertEqual(list((self.base/'backups').glob('*.sqlite')),[])

    def test_export_failure_keeps_recovered_slot_in_cooldown(self):
        self.planned_batch();backup=self.backup()
        with patch.object(c,'export_run',side_effect=OSError('synthetic export failure')):
            with self.assertRaisesRegex(OSError,'synthetic export failure'):
                recover.recover(self.out,self.src,backup,True)
        slot=dict(self.db.execute('SELECT * FROM slots').fetchone())
        self.assertEqual(slot['status'],'cooldown')
        self.assertGreaterEqual(c.parse_date(slot['ready_at']),c.parse_date(slot['finished_at'])+timedelta(minutes=63))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM request_log').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT status FROM batch_attempts').fetchone()[0],'complete')

    def test_archived_auth_error_preserves_successes_and_blocks_resume(self):
        self.planned_batch(plans=[self.plan(),self.plan('KR_002')],body=[
            {'code':200,'body':json.dumps(make_page([1],after='MORE'))},
            {'code':400,'body':json.dumps({'error':{'code':190,'message':'synthetic auth failure'}})}])
        result=recover.recover(self.out,self.src,self.backup(),True)
        self.assertEqual(result['replayed'],2)
        self.assertEqual(result['requires_review'],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],1)
        self.assertEqual(tuple(self.db.execute('SELECT requests,successes,failures FROM runs').fetchone()),(2,1,1))
        self.assertEqual(self.db.execute('SELECT status FROM batch_attempts').fetchone()[0],'requires_review')
        self.assertEqual(self.db.execute('SELECT status FROM slots').fetchone()[0],'cooldown')
        self.assertEqual(recover.recover(self.out,None,None,False)['batches'][0]['resolution'],'MANUAL_REVIEW_REQUIRED')
        with self.assertRaisesRegex(ValueError,'Unsupported unresolved batch state'):
            recover.recover(self.out,self.src,self.backup(),True)

    def test_backup_handle_released_after_success(self):
        backup=self.backup();backup.unlink()
        self.assertFalse(backup.exists())


if __name__=='__main__':
    unittest.main()
