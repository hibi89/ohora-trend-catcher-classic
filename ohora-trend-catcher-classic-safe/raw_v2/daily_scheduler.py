"""Daily-first OHORA RAW v2 orchestrator (manual foreground, no autonomous Meta calls).

Policy: KST front pages for all eligible official accounts -> catchup gaps ->
historical 365-day cursor traversal. One existing Graph account per slot.
Use --live explicitly; CTRL+C stops the foreground loop.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
import sqlite3
import time

import collector
import audit as integrity_audit
import backup as snapshots

KST = timezone(timedelta(hours=9))  # 2026 Korea Standard Time; no tzdata needed on Windows.
DAILY_LIMIT = 4
BATCH_SIZE = 5
MAX_BATCHES = 30
STOP_USAGE = 85
MAX_FRONT_ATTEMPTS = 2


def today_kst():
    return datetime.now(KST).date().isoformat()


def pending_front_accounts(accounts, states, policy='daily'):
    pending=[]
    for account in accounts:
        if account['blocked']:
            continue
        if policy=='bootstrap-history' and account['latest_id']:
            continue  # Bootstrap does not repeat an already observed head.
        state=states.get(account['account_key'])
        if state and (state['status'] in ('success','needs_review','excluded') or
                      state['attempts']>=MAX_FRONT_ATTEMPTS):
            continue
        pending.append((state['attempts'] if state else 0,account['ordinal'],'front',account))
    return pending


def select_daily_tasks(db, day, max_tasks=294, policy='daily'):
    """Select exactly one stage at a time; do not backfill while front is pending.

    A failed account is retried after yet-unattempted accounts, max twice a day.
    Blocked or exhausted retry accounts are reported as exceptions, never successes.
    """
    accounts=[dict(row) for row in db.execute('SELECT * FROM accounts ORDER BY ordinal')]
    states={row['account_key']:dict(row) for row in db.execute(
        'SELECT * FROM daily_account_state WHERE day_kst=?',(day,))}
    front=pending_front_accounts(accounts,states,policy)
    if front:
        if policy=='history-only':
            return []  # Caller reports unmet daily-front prerequisite; no API request.
        # Strict roster halves for daily; bootstrap prioritizes all never-seen accounts.
        if policy!='bootstrap-history':
            first=[item for item in front if item[1]<=150]
            front=first if first else [item for item in front if item[1]>150]
        front.sort(key=lambda item:(item[0],item[1]))
        return [(phase,account) for _,__,phase,account in front[:max_tasks]]
    if policy=='daily-front':
        return []

    # Avoid an endlessly failing catchup/history account starving all other
    # work. Retry it on the next KST day and keep its cursor unchanged.
    failures={(r['account_key'],r['phase']):r['n'] for r in db.execute(
        """SELECT account_key,phase,COUNT(*) AS n FROM request_log
           WHERE status='failed' AND phase IN ('catchup','history')
             AND date(finished_at,'+9 hours')=?
           GROUP BY account_key,phase""",(day,))}
    catchup=[('catchup',a) for a in accounts if not a['blocked'] and a['catchup_cursor']
             and failures.get((a['account_key'],'catchup'),0)<MAX_FRONT_ATTEMPTS]
    if catchup:
        return catchup[:max_tasks]

    # A legacy done flag, including NULL cursor, is not completion proof.
    # Preserve it and traverse from the saved cursor (or head) to establish evidence.
    history=[a for a in accounts if not a['blocked'] and a['latest_id']
             and (not a['backfill_done'] or not collector.history_completion_verified(db,a['account_key']))
             and not a['catchup_cursor'] and failures.get((a['account_key'],'history'),0)<MAX_FRONT_ATTEMPTS]
    history.sort(key=lambda a:(a['last_history'] or '',a['ordinal']))
    return [('history',a) for a in history[:max_tasks]]



TARGETED_HISTORY_TEN = frozenset(['KR_055','KR_078','US_019','US_022','US_023','US_059','US_072','US_075','JP_055','JP_061'])


def front_pending_guard(db, day):
    accounts=[dict(r) for r in db.execute('SELECT * FROM accounts ORDER BY ordinal')]
    states={r['account_key']:dict(r) for r in db.execute('SELECT * FROM daily_account_state WHERE day_kst=?',(day,))}
    return len(pending_front_accounts(accounts,states,'history-only'))


def targeted_history_tasks(db, day, targets):
    if front_pending_guard(db,day):
        return []
    # Never bypass catchup priority or select a target with unresolved gaps.
    if db.execute('SELECT COUNT(*) FROM accounts WHERE blocked=0 AND catchup_cursor IS NOT NULL').fetchone()[0]:
        return []
    choices=select_daily_tasks(db,day,policy='history-only')
    eligible={a['account_key']:a for phase,a in choices if phase=='history'}
    if any(k not in eligible for k in targets):
        return []
    return [('history',eligible[k]) for k in targets]

def inspect_store(base, source, digest, policy='daily', targets=None):
    """Read scheduler status while holding the same cross-process lock as collector."""
    with collector.process_lock(base):
        db=collector.connect(Path(base)/'collection.sqlite',source,digest)
        try:
            day=today_kst()
            # Adopt verified front observations already made earlier today by the
            # legacy collector; no extra API requests, no old rows updated.
            with db:
                db.execute("""INSERT OR IGNORE INTO daily_account_state(
                    day_kst,account_key,status,attempts,last_request_id,last_error,updated_at)
                    SELECT ?,account_key,'success',1,MAX(request_id),NULL,MAX(finished_at)
                    FROM request_log
                    WHERE phase='front' AND status='success'
                      AND date(finished_at,'+9 hours')=?
                    GROUP BY account_key""",(day,day))
            choices=select_daily_tasks(db,day,policy=policy)
            if targets is not None and not (policy=='history-only' and front_pending_guard(db,day)==0):
                choices=[]
            elif targets is not None:
                choices=targeted_history_tasks(db,day,targets)
            accounts=[dict(row) for row in db.execute('SELECT * FROM accounts ORDER BY ordinal')]
            states={row['account_key']:dict(row) for row in db.execute(
                'SELECT * FROM daily_account_state WHERE day_kst=?',(day,))}
            front_pending=len(pending_front_accounts(accounts,states,policy))
            success=db.execute(
                "SELECT COUNT(*) FROM daily_account_state WHERE day_kst=? AND status='success'",(day,)).fetchone()[0]
            failures=sum(1 for a in accounts if not a['blocked'] and
                (state:=states.get(a['account_key'])) and state['status']!='success' and
                (state['status'] in ('needs_review','excluded') or state['attempts']>=MAX_FRONT_ATTEMPTS))
            blocked=db.execute('SELECT COUNT(*) FROM accounts WHERE blocked=1').fetchone()[0]
            pending_gaps=db.execute("SELECT COUNT(*) FROM accounts WHERE catchup_cursor IS NOT NULL AND blocked=0").fetchone()[0]
            latest=db.execute('SELECT * FROM slots ORDER BY slot_id DESC LIMIT 1').fetchone()
            usage_row=db.execute('SELECT usage_max FROM runs ORDER BY started_at DESC LIMIT 1').fetchone()
            latest_usage=usage_row['usage_max'] if usage_row else None
            ready=collector.slot_ready_at(latest)
            stage=choices[0][0] if choices else 'front_pending' if policy=='history-only' and front_pending else 'done'
            return {'day':day,'tasks':choices,'stage':stage,'front_pending':front_pending,
                    'success':success,'exceptions':failures,'blocked':blocked,'pending_gaps':pending_gaps,
                    'ready':ready,'slot_status':latest['status'] if latest else None,
                    'usage_max':latest_usage}
        finally:
            db.close()


def format_kst(value):
    """Format timezone-aware timestamps for operator-facing KST logs."""
    if value is None:
        return 'unavailable'
    if isinstance(value, str):
        value=datetime.fromisoformat(value.replace('Z','+00:00'))
    if value.tzinfo is None:
        raise ValueError('ready timestamp must include timezone')
    return value.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S KST')


def print_usage_status(snap):
    """Display last persisted Meta X-App-Usage observation, not a live quota."""
    value=snap.get('usage_max')
    shown=f'{value:.1f}%' if isinstance(value,(int,float)) else 'unavailable'
    print(f'META API USAGE (last run observed maximum): {shown}; STOP THRESHOLD: {STOP_USAGE}%')


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--env-file',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--live',action='store_true',help='Opt in to real Meta API calls')
    parser.add_argument('--once',action='store_true',help='Execute at most one collection run, never sleep')
    parser.add_argument('--max-batches',type=int,default=MAX_BATCHES,
                        help='1 for 5-account live pilot; up to 30 for a 150-account slot')
    parser.add_argument('--policy',choices=('daily','bootstrap-history','daily-front','history-only'),
                        default='daily')
    parser.add_argument('--acknowledge-warnings',action='store_true',
                        help='Proceed after inspecting a WARN-only read-only audit; FAIL is always blocked')
    parser.add_argument('--pilot-bypass-cooldown',action='store_true',help='One-time 5-account pilot only; preserve existing slot and cooldown records')
    parser.add_argument('--target-legacy-ten',action='store_true',help='Only the ten fixed unverified legacy history accounts; exactly two batches')
    return parser.parse_args(argv)


def main(argv=None):
    options=parse_args(argv)
    if not 1<=options.max_batches<=30:raise ValueError('--max-batches must be 1..30')
    if options.pilot_bypass_cooldown and not (options.live and options.once and options.max_batches==1 and options.policy=='history-only'):
        raise ValueError('pilot bypass requires --live --once --max-batches 1 --policy history-only')
    if options.target_legacy_ten and (options.policy!='history-only' or not options.once or options.max_batches!=2 or options.pilot_bypass_cooldown):
        raise ValueError('targeted mode requires --policy history-only --once --max-batches 2 and no cooldown bypass')
    rows,digest=collector.load_accounts(options.source)
    if not options.live:
        if options.target_legacy_ten:
            print('TARGETED TEN DRY RUN: fixed account list',sorted(TARGETED_HISTORY_TEN))
            print('Selection requires live DB inspection; dry run does not prove eligibility.')
        print('DRY RUN: policy='+options.policy+'; 294 accounts, 4 posts, batch 5,',
              '150 unique accounts/slot, stop 85%, cooldown=max(finish+63min, start+65min).')
        print('NO database writes, credentials read, or Meta API calls.')
        return 0

    if not options.env_file:
        raise ValueError('--env-file is required for --live')
    # Fail before touching the DB on invalid credentials or unsafe output location.
    collector.load_env(options.env_file)
    base=options.output_dir.resolve()
    if base==collector.ROOT or base.is_relative_to(collector.ROOT/'kq3_294_collection') or base.is_relative_to(collector.ROOT/'experiments'):
        raise ValueError('Output must not overwrite legacy stores')
    base.mkdir(parents=True,exist_ok=True)
    if (base/'collection.sqlite').is_file():
        with collector.process_lock(base):
            path=snapshots.backup_store(base,base.parent/'OHORA_RAW_v2_backups')
        print('Preflight backup verified:',path)
        report=integrity_audit.audit(base)
        print('Read-only preflight audit:',report['status'],report['findings'])
        if report['status']=='FAIL':
            print('COLLECTION REFUSED: integrity FAIL; run raw_v2/audit.py and investigate.')
            return 4
        if report['status']=='WARN' and not options.acknowledge_warnings:
            print('COLLECTION REFUSED: review audit WARN first, then pass --acknowledge-warnings.')
            return 4
    args=argparse.Namespace(
        source=options.source,env_file=options.env_file,output_dir=base,
        live=True,mode='daily',batch_size=BATCH_SIZE,max_batches=options.max_batches,
        limit=DAILY_LIMIT,window_days=7,history_days=365,stop_usage=STOP_USAGE,
        extended_fields=False,cycle_minutes=65,pilot_bypass=options.pilot_bypass_cooldown)
    print('OHORA RAW policy:',options.policy)
    print('Profile: 294 accounts, 4 posts, batch 5, up to 150 per slot, 85% usage, '
          'cooldown=max(finish+63min, start+65min)')
    print('No Windows scheduled task installed. Stop anytime with CTRL+C.')
    try:
        initial_day=today_kst()
        while True:
            if options.policy=='bootstrap-history' and today_kst()!=initial_day:
                print('Bootstrap day ended; exit before the next KST daily-front cycle.')
                return 0
            snap=inspect_store(base,rows,digest,options.policy,TARGETED_HISTORY_TEN if options.target_legacy_ten else None)
            print(f"[{snap['day']}] daily front success={snap['success']}/294, "
                  f"blocked={snap['blocked']}, other exceptions={snap['exceptions']}; stage={snap['stage']}")
            print_usage_status(snap)
            if snap['stage']=='front_pending':
                print(f"HISTORY REFUSED: {snap['front_pending']} daily-front accounts remain unattempted or retryable.")
                print('SCHEDULER_RESULT_JSON '+json.dumps({
                    'policy':options.policy,'run_status':'front_pending','day_kst':snap['day'],
                    'front_success':snap['success'],'front_pending':snap['front_pending'],
                    'blocked':snap['blocked'],'front_exceptions':snap['exceptions'],
                    'next_stage':'daily-front'}))
                return 4
            if snap['stage']=='done':
                print(f"No currently eligible tasks; outstanding catchup gaps={snap['pending_gaps']}. "
                      'Deferred failures are retried on the next KST day. Exiting.')
                print('SCHEDULER_RESULT_JSON '+json.dumps({
                    'policy':options.policy,'run_status':'done','day_kst':snap['day'],
                    'front_success':snap['success'],'blocked':snap['blocked'],
                    'front_exceptions':snap['exceptions'],
                    'next_stage':'done','next_ready_at_utc':snap['ready'].isoformat() if snap['ready'] else None}))
                return 0
            if options.target_legacy_ten and (len(snap['tasks'])!=10 or {a['account_key'] for phase,a in snap['tasks']}!=TARGETED_HISTORY_TEN or any(phase!='history' for phase,a in snap['tasks'])):
                print('TARGETED HISTORY REFUSED: all ten targets must be eligible, with no pending front/catchup.')
                return 4
            ready=snap['ready']
            if ready is not None:
                remaining=(ready-datetime.now(ready.tzinfo)).total_seconds()
                if remaining>0 and options.pilot_bypass_cooldown:
                    print('PILOT BYPASS: local cooldown skipped once; persisted slot record retained')
                elif remaining>0:
                    print(f'Cooling down until {format_kst(ready)}; {int(remaining)+1}s remaining')
                    if options.once:
                        print('SCHEDULER_RESULT_JSON '+json.dumps({
                            'policy':options.policy,'run_status':'cooldown','day_kst':snap['day'],
                            'front_success':snap['success'],'blocked':snap['blocked'],
                            'front_exceptions':snap['exceptions'],
                            'next_stage':snap['stage'],'next_ready_at_utc':ready.isoformat()}))
                        return 0
                    while remaining>0:
                        time.sleep(min(30,max(1,remaining)))
                        remaining=(ready-datetime.now(ready.tzinfo)).total_seconds()
                    continue
            selected_day=snap['day']
            result=collector.run(
                args,task_selector=(lambda db,n:targeted_history_tasks(db,selected_day,TARGETED_HISTORY_TEN)[:n]) if options.target_legacy_ten else (lambda db,n:select_daily_tasks(db,selected_day,n,options.policy)),
                daily_day=selected_day,cooldown_minutes=63)
            after=inspect_store(base,rows,digest,options.policy,TARGETED_HISTORY_TEN if options.target_legacy_ten else None)
            print_usage_status(after)
            print(f"Run finished: status={result}; today's front={after['success']}/294; "
                  f"next stage={after['stage']}")
            print('SCHEDULER_RESULT_JSON '+json.dumps({
                'policy':options.policy,'run_status':result,'day_kst':after['day'],
                'front_success':after['success'],'blocked':after['blocked'],
                'front_exceptions':after['exceptions'],
                'next_stage':after['stage'],
                'next_ready_at_utc':after['ready'].isoformat() if after['ready'] else None}))
            if result==3:
                print('PERMANENT HALT: authentication, identity or usage evidence requires review.')
                return 3
            if options.once:return result
            # A paused slot may be immediately continued. A closed slot is
            # handled by persisted ready_at on the next loop iteration.
    except KeyboardInterrupt:
        print('Stopped by user. Database and checkpoints retained.')
        return 130


if __name__=='__main__':
    raise SystemExit(main())
