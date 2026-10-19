"""Read-only audit evidence and output isolation regressions."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'raw_v2'))
import collector as c
import audit
from test_daily_scheduler import create_roster


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / 'accounts.csv'
        create_roster(self.source)
        rows, digest = c.load_accounts(self.source)
        self.out = self.base / 'store'
        self.db = c.connect(self.out / 'collection.sqlite', rows, digest)
        self.addCleanup(self.db.close)

    def test_missing_database_is_unknown_and_never_created(self):
        missing = self.base / 'absent'
        result = audit.audit(missing, self.base / 'missing_report')
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertFalse(missing.exists())

    def test_reports_cannot_overwrite_run_artifacts(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            audit.audit(self.out, self.out / 'runs' / 'existing')
        self.assertFalse((self.out / 'runs').exists())

    def test_terminal_fragment_does_not_verify_whole_history(self):
        with self.db:
            self.db.execute("UPDATE accounts SET backfill_done=1 WHERE account_key='KR_001'")
            self.db.execute("""INSERT INTO history_page_evidence VALUES
                ('fragment','KR_001','missing_parent',NULL,NULL,NULL,?,
                 'api_terminal',?)""", (c.fixed_history_cutoff(self.db,365).isoformat(),c.now()))
        report = self.base / 'report'
        result = audit.audit(self.out, report)
        self.assertEqual(result['status'], 'FAIL')  # also lacks a successful request
        import csv
        with (report / 'account_progress.csv').open(encoding='utf-8-sig',newline='') as fp:
            first = next(csv.DictReader(fp))
        self.assertEqual(first['coverage_verified'], '0')
        self.assertIn('UNVERIFIED_LEGACY_COMPLETION',
                      (report / 'coverage_findings.csv').read_text(encoding='utf-8-sig'))

    def test_undeclared_request_relationship_is_checked_without_mutation(self):
        with self.db:
            self.db.execute("""INSERT INTO request_log
                (run_id,request_id,account_key,phase,status)
                VALUES ('absent_run','orphan','KR_001','front','failed')""")
        before = self.db.execute('SELECT COUNT(*) FROM request_log').fetchone()[0]
        report = self.base / 'report'
        self.assertEqual(audit.audit(self.out, report)['status'], 'FAIL')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM request_log').fetchone()[0], before)
        self.assertIn('REQUEST_WITHOUT_RUN',
                      (report / 'integrity_findings.csv').read_text(encoding='utf-8-sig'))


if __name__ == '__main__':
    unittest.main()
