"""Offline regressions for RAW completeness blockers. No real Meta API."""
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from argparse import Namespace
from contextlib import closing
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'raw_v2'))
import collector as col
import audit as aud
from test_daily_scheduler import create_roster,make_page


class CompletenessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.source=self.base/'account_list.csv'
        create_roster(self.source)
        self.roster,self.digest=col.load_accounts(self.source)
        self.out=self.base/'store'
        self.db=col.connect(self.out/'collection.sqlite',self.roster,self.digest)
        self.addCleanup(self.db.close)

    def account(self,key='KR_001'):
        return dict(self.db.execute('SELECT * FROM accounts WHERE account_key=?',(key,)).fetchone())

    def test_ancient_front_post_must_not_end_history(self):
        p=make_page([1,2,3,4],after='MORE_HISTORY')
        p['business_discovery']['media']['data'][-1]['timestamp']='2020-01-01T00:00:00+00:00'
        col.insert_success(self.db,self.account(),'front',p,'R1','r1',col.now(),365,limit=4)
        row=self.account()
        self.assertEqual(row['backfill_done'],0)
        self.assertEqual(row['backfill_cursor'],'MORE_HISTORY')

    def test_history_evidence_crosses_cutoff_only_on_actual_history(self):
        p=make_page([1,2,3,4],after='NEXT')
        col.insert_success(self.db,self.account(),'front',p,'R1','r1',col.now(),365,limit=4)
        old=make_page([5,6,7,8],after='OLDER')
        old['business_discovery']['media']['data'][-1]['timestamp']='2020-01-01T00:00:00+00:00'
        col.insert_success(self.db,self.account(),'history',old,'R2','r2',col.now(),365,limit=4)
        row=self.db.execute('SELECT completion_basis FROM history_page_evidence WHERE request_id=?',('r2',)).fetchone()
        self.assertEqual(row[0],'cutoff_crossed')
        self.assertEqual(self.account()['backfill_done'],1)

    def test_history_unsorted_rejected_without_mutation(self):
        p=make_page([1,2,3,4],after='OLDER')
        items=p['business_discovery']['media']['data']
        items[0]['timestamp']='2025-01-01T00:00:00+00:00'
        items[1]['timestamp']='2026-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'not descending'):
            col.insert_success(self.db,self.account(),'history',p,'R','bad',col.now(),365,limit=4)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],0)

    def test_nonadjacent_history_cursor_cycle_refused(self):
        col.insert_success(self.db,self.account(),'front',make_page([1],after='CUR1'),
                           'R1','r1',col.now(),365,limit=4)
        col.insert_success(self.db,self.account(),'history',make_page([2],after='CUR2'),
                           'R2','r2',col.now(),365,limit=4)
        with self.assertRaisesRegex(ValueError,'cursor cycle'):
            col.insert_success(self.db,self.account(),'history',make_page([3],after='CUR1'),
                               'R3','r3',col.now(),365,limit=4)
        self.assertEqual(self.account()['backfill_cursor'],'CUR2')

    def test_cross_page_history_newer_timestamp_refused(self):
        col.insert_success(self.db,self.account(),'front',make_page([1],after='CUR1'),
                           'R1','r1',col.now(),365,limit=4)
        first=make_page([2],after='CUR2')
        first['business_discovery']['media']['data'][0]['timestamp']='2025-12-01T00:00:00+00:00'
        col.insert_success(self.db,self.account(),'history',first,'R2','r2',col.now(),365,limit=4)
        newer=make_page([3],after='CUR3')
        newer['business_discovery']['media']['data'][0]['timestamp']='2026-10-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'chronology unverified'):
            col.insert_success(self.db,self.account(),'history',newer,'R3','r3',col.now(),365,limit=4)
        self.assertEqual(self.account()['backfill_cursor'],'CUR2')

    def test_first_history_page_must_follow_front_chronology(self):
        front=make_page([1],after='CUR1')
        front['business_discovery']['media']['data'][0]['timestamp']='2026-01-01T00:00:00+00:00'
        col.insert_success(self.db,self.account(),'front',front,'R1','r1',col.now(),365,limit=4)
        with self.assertRaisesRegex(ValueError,'chronology unverified'):
            col.insert_success(self.db,self.account(),'history',make_page([2],after=None),
                               'R2','r2',col.now(),365,limit=4)
        self.assertEqual(self.account()['backfill_done'],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],1)

    def test_completion_requires_every_edge_from_head_to_boundary(self):
        col.insert_success(self.db,self.account(),'front',make_page([1],after='CUR1'),
                           'R1','root',col.now(),365,limit=4)
        col.insert_success(self.db,self.account(),'history',make_page([2],after='CUR2'),
                           'R2','middle',col.now(),365,limit=4)
        col.insert_success(self.db,self.account(),'history',make_page([3],after=None),
                           'R3','terminal',col.now(),365,limit=4)
        self.assertTrue(col.history_completion_verified(self.db,'KR_001'))
        with self.db:self.db.execute("DELETE FROM history_page_evidence WHERE request_id='middle'")
        result=col.history_chain_status(self.db,'KR_001')
        self.assertFalse(result['verified'])
        self.assertEqual(result['reason'],'disconnected_cursor')
        # Keep the historical flag and checkpoint intact; verification is separate.
        self.assertEqual((self.account()['backfill_done'],self.account()['backfill_cursor']),(1,None))

    def test_isolated_terminal_evidence_does_not_prove_completion(self):
        with self.db:
            self.db.execute("UPDATE accounts SET latest_id='123',backfill_done=1 WHERE account_key='KR_001'")
            self.db.execute('INSERT INTO history_page_evidence VALUES (?,?,?,?,?,?,?,?,?)',
                ('orphan','KR_001','MISSING_ROOT',None,None,None,'2025-10-19T00:00:00+00:00','api_terminal',col.now()))
        self.assertEqual(col.history_chain_status(self.db,'KR_001')['reason'],'no_root')
        tasks=col.select_tasks(self.db,'history',294)
        phase,selected=next((p,a) for p,a in tasks if a['account_key']=='KR_001')
        self.assertEqual((phase,selected['backfill_cursor']),('history',None))

    def test_legacy_done_null_cursor_remains_eligible_without_reset(self):
        with self.db:
            self.db.execute("UPDATE accounts SET latest_id='123',last_front=?,backfill_done=1 WHERE account_key='KR_001'",(col.now(),))
        before=self.account()
        for mode in ('history','balanced'):
            choices=col.select_tasks(self.db,mode,294)
            phase,selected=next((p,a) for p,a in choices if a['account_key']=='KR_001')
            self.assertEqual(phase,'history')
            self.assertIsNone(selected['backfill_cursor'])
        self.assertEqual(self.account(),before)

    def test_one_page_or_empty_head_has_terminal_proof(self):
        for ids in ([1],[]):
            with self.subTest(ids=ids):
                req='single' if ids else 'empty'
                col.insert_success(self.db,self.account(),'front' if ids else 'history',make_page(ids,after=None),
                                   'R1',req,col.now(),365,limit=4)
                self.assertTrue(col.history_completion_verified(self.db,'KR_001'))

    def test_front_terminal_without_timestamp_is_unknown(self):
        page=make_page([1],after=None)
        del page['business_discovery']['media']['data'][0]['timestamp']
        col.insert_success(self.db,self.account(),'front',page,'R1','root',col.now(),365,limit=4)
        self.assertFalse(col.history_completion_verified(self.db,'KR_001'))

    def test_malformed_paging_cannot_become_terminal_proof(self):
        before=self.account()
        malformed=([], 'invalid', {'cursors':[]}, {'cursors':'invalid'},
                   {'cursors':{'after':123}}, {'cursors':{'after':''}},
                   {'next':'https://example.invalid/older'}, {'next':[]})
        for phase in ('front','history'):
            for n,paging in enumerate(malformed):
                with self.subTest(phase=phase,paging=paging):
                    page=make_page([1],after=None)
                    page['business_discovery']['media']['paging']=paging
                    with self.assertRaisesRegex(ValueError,'paging|cursor|next page'):
                        col.insert_success(self.db,self.account(),phase,page,'R',f'{phase}{n}',col.now(),365,limit=4)
                    self.assertEqual(self.account(),before)
                    self.assertFalse(col.history_completion_verified(self.db,'KR_001'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM history_page_evidence').fetchone()[0],0)

    def test_new_null_cursor_proof_can_revisit_legacy_cursors(self):
        with self.db:
            self.db.execute("UPDATE accounts SET latest_id='123',backfill_done=1 WHERE account_key='KR_001'")
            self.db.execute('INSERT INTO history_page_evidence VALUES (?,?,?,?,?,?,?,?,?)',
                ('legacy','KR_001','CUR1',None,None,None,'2025-10-19T00:00:00+00:00','api_terminal',col.now()))
        col.insert_success(self.db,self.account(),'history',make_page([1],after='CUR1'),
                           'R1','new_root',col.now(),365,limit=4)
        col.insert_success(self.db,self.account(),'history',make_page([2],after=None),
                           'R2','new_terminal',col.now(),365,limit=4)
        self.assertTrue(col.history_completion_verified(self.db,'KR_001'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM history_page_evidence').fetchone()[0],3)

    def test_nonadjacent_catchup_cursor_cycle_is_atomic(self):
        col.insert_success(self.db,self.account(),'front',make_page([1],after='HISTORY'),
                           'R1','front1',col.now(),365,limit=4)
        col.insert_success(self.db,self.account(),'front',make_page([2],after='GAP1'),
                           'R2','front2',col.now(),365,limit=4)
        col.insert_success(self.db,self.account(),'catchup',make_page([3],after='GAP2'),
                           'R3','catch1',col.now(),365,limit=4)
        with self.assertRaisesRegex(ValueError,'catchup pagination cursor cycle'):
            col.insert_success(self.db,self.account(),'catchup',make_page([4],after='GAP1'),
                               'R4','catch2',col.now(),365,limit=4)
        self.assertEqual(self.account()['catchup_cursor'],'GAP2')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],3)

    def test_365_day_proof_does_not_claim_730_days(self):
        with self.db:self.db.execute("UPDATE config SET v='2026-10-19T00:00:00+00:00' WHERE k='backfill_anchor_utc'")
        col.insert_success(self.db,self.account(),'front',make_page([1],after='CUR1'),
                           'R1','root',col.now(),365,limit=4)
        page=make_page([2],after='CUR2')
        page['business_discovery']['media']['data'][0]['timestamp']='2025-01-01T00:00:00+00:00'
        col.insert_success(self.db,self.account(),'history',page,'R2','boundary',col.now(),365,limit=4)
        self.assertTrue(col.history_completion_verified(self.db,'KR_001',365))
        self.assertFalse(col.history_completion_verified(self.db,'KR_001',730))

    def test_missing_empty_children_partial_and_later_repair(self):
        p=make_page([1],after=None)
        entry=p['business_discovery']['media']['data'][0]
        entry['media_type']='CAROUSEL_ALBUM'
        col.insert_success(self.db,self.account(),'front',p,'R1','r1',col.now(),365,limit=4)
        self.assertEqual(tuple(self.db.execute('SELECT child_rows,coverage FROM carousel_status').fetchone()),(0,'partial'))
        p2=make_page([1],after=None)
        q=p2['business_discovery']['media']['data'][0]
        q['media_type']='CAROUSEL_ALBUM'
        q['children']={'data':[{'id':str(10**18+9),'media_type':'IMAGE'}]}
        col.insert_success(self.db,self.account(),'front',p2,'R2','r2',col.now(),365,limit=4)
        self.assertEqual(tuple(self.db.execute('SELECT child_rows,coverage FROM carousel_status').fetchone()),(1,'complete'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM post_media').fetchone()[0],1)

    def test_account_mismatch_blocks_all_mutations(self):
        wrong=make_page([1],after=None)
        wrong['business_discovery']['username']='different_account'
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            col.insert_success(self.db,self.account(),'front',wrong,'R','bad',col.now(),365,limit=4)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],0)
        col.insert_success(self.db,self.account(),'front',make_page([1],after=None),'R1','good',col.now(),365,limit=4)
        mismatched=make_page([1],after=None)
        mismatched['business_discovery']['id']='123987'
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            col.insert_success(self.db,self.account(),'front',mismatched,'R2','bad',col.now(),365,limit=4)

    def test_stable_discovery_id_allows_username_rename(self):
        col.insert_success(self.db,self.account(),'front',make_page([1],after=None),'R1','first',col.now(),365,limit=4)
        original=self.account()['input_username']
        renamed=make_page([1],after=None)
        renamed['business_discovery']['username']='renamed_account'
        col.insert_success(self.db,self.account(),'front',renamed,'R2','renamed',col.now(),365,limit=4)
        self.assertEqual(self.account()['username'],'renamed_account')
        self.assertEqual(self.account()['input_username'],original)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM post_observations').fetchone()[0],2)

    def test_malformed_or_duplicate_children_preserve_post_metrics_as_partial(self):
        child={'id':str(10**18+9),'media_type':'IMAGE'}
        for n,children in enumerate((None,{'data':'bad'},{'data':[None]}, {'data':[child,child]}),1):
            with self.subTest(children=children):
                page=make_page([n],after=None)
                post=page['business_discovery']['media']['data'][0]
                post.update(media_type='CAROUSEL_ALBUM',children=children)
                col.insert_success(self.db,self.account(),'history',page,'R',f'partial{n}',col.now(),365,limit=4)
                row=self.db.execute('SELECT coverage FROM carousel_status WHERE post_id=?',(post['id'],)).fetchone()
                self.assertEqual(row[0],'partial')
                self.assertEqual(self.db.execute('SELECT like_count FROM post_observations WHERE request_id=?',(f'partial{n}',)).fetchone()[0],2)

    def test_common_slot_wait_uses_finish63_start65_and_saved_ready(self):
        slot=dict(status='cooldown',started_at='2026-10-19T00:00:00+00:00',
                  finished_at='2026-10-19T00:01:00+00:00',ready_at=None)
        self.assertEqual(col.slot_ready_at(slot).isoformat(),'2026-10-19T01:05:00+00:00')
        slot['finished_at']='2026-10-19T00:10:00+00:00'
        self.assertEqual(col.slot_ready_at(slot).isoformat(),'2026-10-19T01:13:00+00:00')
        slot['ready_at']='2026-10-19T02:00:00+00:00'
        self.assertEqual(col.slot_ready_at(slot).isoformat(),slot['ready_at'])
        self.assertEqual(slot['ready_at'],'2026-10-19T02:00:00+00:00')

    def test_nonfinite_or_negative_usage_is_not_valid_headroom(self):
        for body in ('{"total_time":NaN}','{"total_time":Infinity}','{"total_time":-1}'):
            self.assertIsNone(col.usage({'X-App-Usage':body}))
        self.assertEqual(col.usage({'X-App-Usage':'{"total_time":NaN,"call_count":85}'}),85)

    def test_reference_conflict_stops_before_next_batch(self):
        col.insert_success(self.db,self.account(),'front',make_page([1],after=None),
                           'R1','existing',col.now(),365,limit=4)
        self.db.close()
        env=self.base/'synthetic.env'
        env.write_text('META_ACCESS_TOKEN=SECRET\nMETA_IG_USER_ID=12345',encoding='utf-8')
        args=Namespace(source=self.source,env_file=env,output_dir=self.out,live=True,
                       mode='front',batch_size=1,max_batches=2,limit=4,window_days=7,
                       history_days=365,stop_usage=85,extended_fields=False,cycle_minutes=65)
        calls=[]
        def fake(*_):
            calls.append(1)
            page=make_page([1],after=None)
            page['business_discovery']['username']='kr_test_2'
            return 200,[{'code':200,'body':json.dumps(page)}],{'X-App-Usage':'{"total_time":3}'}
        def choose(db,n):
            return [('front',dict(r)) for r in db.execute('SELECT * FROM accounts WHERE ordinal IN (2,3) ORDER BY ordinal')]
        self.assertEqual(col.run(args,fake,task_selector=choose),3)
        self.assertEqual(len(calls),1)
        with closing(sqlite3.connect(self.out/'collection.sqlite')) as saved:
            self.assertEqual(saved.execute('SELECT COUNT(*) FROM posts').fetchone()[0],1)
            self.assertEqual(saved.execute("SELECT COUNT(*) FROM account_observations WHERE account_key='KR_002'").fetchone()[0],0)

    def test_halted_batch_cannot_commit_complete_without_cooldown(self):
        self.db.close()
        env=self.base/'synthetic.env'
        env.write_text('META_ACCESS_TOKEN=SECRET\nMETA_IG_USER_ID=12345',encoding='utf-8')
        args=Namespace(source=self.source,env_file=env,output_dir=self.out,live=True,
                       mode='front',batch_size=1,max_batches=2,limit=4,window_days=7,
                       history_days=365,stop_usage=85,extended_fields=False,cycle_minutes=65)
        calls=[]
        def fake(*_):
            calls.append(1)
            return 200,[{'code':400,'body':json.dumps({'error':{'code':4}})}],{'X-App-Usage':'{"total_time":85}'}
        with patch.object(col,'close_slot',side_effect=RuntimeError('simulated shutdown')):
            with self.assertRaisesRegex(RuntimeError,'simulated shutdown'):
                col.run(args,fake)
        with closing(sqlite3.connect(self.out/'collection.sqlite')) as saved:
            self.assertEqual(saved.execute('SELECT status FROM batch_attempts').fetchone()[0],'response_saved')
        with self.assertRaisesRegex(ValueError,'unresolved prior batch'):
            col.run(args,fake)
        self.assertEqual(len(calls),1)

    def test_readonly_audit_warns_on_unverified_completion(self):
        with self.db:
            self.db.execute("UPDATE accounts SET backfill_done=1,backfill_cursor='OLDER' WHERE account_key='KR_001'")
        report_dir=self.base/'audit_report'
        result=aud.audit(self.out,report_dir)
        self.assertEqual(result['status'],'WARN')
        self.assertFalse(result['ready_for_unattended_collection'])
        self.assertTrue((report_dir/'summary.json').exists())
        report=(report_dir/'coverage_findings.csv').read_text(encoding='utf-8-sig')
        self.assertIn('UNVERIFIED_LEGACY_COMPLETION',report)
        self.assertFalse((self.out/'collection.sqlite').stat().st_size==0)

    def test_batch_journal_prevents_unobserved_retry(self):
        self.db.close()
        env=self.base/'env.local'
        env.write_text('META_ACCESS_TOKEN=SECRET\nMETA_IG_USER_ID=12345',encoding='utf-8')
        args=Namespace(source=self.source,env_file=env,output_dir=self.out,
                       live=True,mode='front',batch_size=1,max_batches=1,
                       limit=4,window_days=7,history_days=365,stop_usage=85,
                       extended_fields=False,cycle_minutes=65)
        def network_timeout(*_):
            with closing(sqlite3.connect(self.out/'collection.sqlite')) as journal:
                journal.row_factory=sqlite3.Row
                plan=json.loads(journal.execute('SELECT request_json FROM batch_attempts').fetchone()[0])[0]
                saved=dict(journal.execute("SELECT * FROM accounts WHERE account_key='KR_001'").fetchone())
            self.assertTrue(plan['request_id'].endswith('_0000_00_001_front'))
            self.assertEqual(plan['options'],dict(limit=4,window_days=7,history_days=365,extended_fields=False))
            self.assertEqual(plan['state'],{k:saved[k] for k in
                ('latest_id','backfill_cursor','backfill_done','catchup_cursor','catchup_anchor')})
            self.assertIsNone(plan['daily_day'])
            self.assertEqual((plan['cooldown_minutes'],plan['cycle_minutes']),(63,65))
            raise TimeoutError('unknown outcome')
        self.assertEqual(col.run(args,network_timeout),2)
        with self.assertRaisesRegex(ValueError,'unresolved prior batch'):
            col.run(args,network_timeout)
        report=aud.audit(self.out)
        self.assertEqual(report['status'],'FAIL')
        self.assertEqual(report['unresolved_batches'],1)


if __name__=='__main__':
    unittest.main()
