# -*- coding: utf-8 -*-
"""Stock research daily pipeline V3. Default read-only check; no live orders.

python stock_agent_daily_automation_v3.py
python stock_agent_daily_automation_v3.py --daily-update --confirm-daily-update

Run from asset_agent root. The full mode writes validated market-data caches.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output' / 'stock_agent_daily_automation_v3'
PREFLIGHT = ROOT / 'output' / 'stock_agent_daily_pipeline_v2' / 'last_preflight.json'
TZ = ZoneInfo('Asia/Shanghai')

def sh_now():
    return datetime.now(TZ)

def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.part')
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

def terminate_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        # /T terminates nested V5.5 spawned by the smart updater.
        try:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            proc.kill()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

def execute(label, argv, logs, timeout_seconds, allowed=(0,)):
    print(f'[{label}] START', flush=True)
    stdout = logs / f'{label}.stdout.txt'
    stderr = logs / f'{label}.stderr.txt'
    started = time.monotonic()
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    with stdout.open('w', encoding='utf-8') as so, stderr.open('w', encoding='utf-8') as se:
        proc = subprocess.Popen([sys.executable, *map(str, argv)], cwd=ROOT,
                                stdout=so, stderr=se, creationflags=flags,
                                start_new_session=(os.name != 'nt'))
        try:
            code = proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            terminate_tree(proc)
            raise RuntimeError(f'{label} timed out after {timeout_seconds}s; process tree stopped; logs: {logs}') from exc
        except BaseException:
            terminate_tree(proc)
            raise
    print(f'[{label}] EXIT={code}; duration={time.monotonic()-started:.1f}s', flush=True)
    if code not in allowed:
        raise RuntimeError(f'{label} failed (exit={code}); inspect {stdout} and {stderr}')
    return code

def verify_preflight(logs, timeout):
    PREFLIGHT.unlink(missing_ok=True)
    code = execute('preflight', ['stock_agent_daily_pipeline_v2.py'], logs, timeout, allowed=(0, 1))
    if not PREFLIGHT.is_file():
        raise RuntimeError('Preflight did not create a fresh report')
    data = json.loads(PREFLIGHT.read_text(encoding='utf-8-sig'))
    atomic_json(logs / 'preflight.json', data)
    checks = data.get('checks') or {}
    if data.get('data_checks_passed') is not True:
        raise RuntimeError(f"Data integrity failed: {data.get('errors')}")
    if data.get('publication_allowed') is not False or data.get('passed') is not False:
        raise RuntimeError('Unexpected publication status; fail closed')
    if checks.get('universe_quote_date_verified') is not False or code != 1:
        raise RuntimeError('ST-date publication block absent; fail closed')
    expected = checks.get('expected_trade_date')
    if not expected or checks.get('index_end') != expected:
        raise RuntimeError('Index end does not match expected trade date')
    return expected

def acquire_lock():
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / '.running.lock'
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(f'Run lock exists. Inspect before manual removal: {lock}') from exc
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump({'pid': os.getpid(), 'started_at_shanghai': sh_now().isoformat()}, f)
    return lock

def resolve_date():
    from stock_mainboard_smart_update_v1 import expected_trade_date
    expected, _ = expected_trade_date()
    return expected

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--daily-update', action='store_true', help='Run real market-data updates and research preview')
    p.add_argument('--confirm-daily-update', action='store_true', help='Explicitly authorize data-cache writes')
    p.add_argument('--sleep', type=float, default=0.5)
    p.add_argument('--retries', type=int, default=2)
    p.add_argument('--timeout', type=int, default=21600, help='Per-step timeout in seconds')
    args = p.parse_args()
    if args.daily_update != args.confirm_daily_update:
        p.error('Use --daily-update and --confirm-daily-update together')
    if args.sleep < 0 or args.retries < 0 or args.timeout < 60:
        p.error('Invalid numeric options')
    mode = 'DAILY_UPDATE' if args.daily_update else 'CHECK_ONLY'
    started = sh_now()
    if args.daily_update and started.time() < clock_time(16, 0):
        p.error('Write mode requires at least 16:00 Shanghai time')
    summary = {'mode': mode, 'started_at_shanghai': started.isoformat(), 'status': 'STARTED',
               'formal_publication_allowed': False, 'st_quote_date_verified': False,
               'steps': [], 'expected_trade_date': None, 'error': None}
    lock = None
    logs = None
    try:
        lock = acquire_lock()
        run_id = started.strftime('%Y%m%d_%H%M%S_%f')
        logs = OUT / run_id
        logs.mkdir(parents=True, exist_ok=False)
        summary['run_id'] = run_id
        if mode == 'CHECK_ONLY':
            summary['expected_trade_date'] = verify_preflight(logs, args.timeout)
            summary['steps'].append('PREFLIGHT_PASSED')
            summary['status'] = 'CHECK_OK_PUBLICATION_BLOCKED'
        else:
            target = resolve_date()
            summary['expected_trade_date'] = target
            summary['steps'].append('TRADE_DATE_RESOLVED')
            marker = OUT / 'completed_dates' / f'{target}.json'
            if marker.exists():
                prior = json.loads(marker.read_text(encoding='utf-8'))
                summary['status'] = 'ALREADY_COMPLETED_NO_CHANGES'
                summary['prior_run_id'] = prior.get('run_id')
            else:
                execute('smart_stock_update', ['stock_mainboard_smart_update_v1.py', '--apply',
                        '--sleep', str(args.sleep), '--retries', str(args.retries)], logs, args.timeout)
                summary['steps'].append('SMART_STOCK_UPDATE_OK')
                if resolve_date() != target:
                    raise RuntimeError('Trade date changed after stock update; stop')
                index_code = ('import stock_market_state as s; '
                              'r=s.get_stock_market_state(force_refresh=True); '
                              'print("INDEX_DATE:",r["latest_date"],"SOURCE:",r["cache_status"])')
                execute('index_update', ['-c', index_code], logs, args.timeout)
                summary['steps'].append('INDEX_REFRESH_OK')
                execute('st_snapshot_update', ['stock_universe_daily_update_v1.py', '--apply'], logs, args.timeout)
                summary['steps'].append('ST_SNAPSHOT_UPDATED_DATE_UNVERIFIED')
                checked = verify_preflight(logs, args.timeout)
                if checked != target or resolve_date() != target:
                    raise RuntimeError(f'Trade date changed during pipeline: {target} -> {checked}; stop')
                summary['steps'].append('FINAL_PREFLIGHT_PASSED')
                execute('research_preview', ['stock_agent_daily_preview_v1.py'], logs, args.timeout)
                summary['steps'].append('RESEARCH_PREVIEW_CREATED')
                if resolve_date() != target:
                    raise RuntimeError('Trade date changed after preview; completion not marked')
                summary['status'] = 'RESEARCH_PREVIEW_CREATED_PUBLICATION_BLOCKED'
                atomic_json(marker, {'run_id': run_id, 'expected_trade_date': target,
                                     'status': summary['status'], 'completed_at_shanghai': sh_now().isoformat(),
                                     'formal_publication_allowed': False})
    except Exception as exc:
        summary['status'] = 'FAILED'
        summary['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        summary['finished_at_shanghai'] = sh_now().isoformat()
        if logs is not None:
            atomic_json(logs / 'run_summary.json', summary)
            print('RUN_REPORT:', logs / 'run_summary.json', flush=True)
        if lock is not None:
            lock.unlink(missing_ok=True)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 1 if summary['status'] == 'FAILED' else 0

if __name__ == '__main__':
    sys.exit(main())
