"""Conservative incremental scheduler for the existing V5.5 stock updater.

Default: local-only plan, no network and no writes. --apply delegates selected
lagging raw/qfq pairs to the original validated V5.5 updater.
This is a request-saving filter, NOT a guarantee of detecting corporate-action
revisions in already-current qfq history. Schedule occasional full audits.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / 'data/stocks/mainboard_history_v1'
UPDATER = ROOT / 'stock_mainboard_incremental_update_v55.py'
REPORT_DIR = ROOT / 'output/stock_mainboard_smart_update_v1'
SHANGHAI = ZoneInfo('Asia/Shanghai')


def last_date(path):
    dates = pd.read_csv(path, usecols=['date'])['date']
    if dates.empty:
        raise ValueError(f'Empty history: {path}')
    parsed = pd.to_datetime(dates, errors='raise')
    if parsed.isna().any() or parsed.duplicated().any() or not parsed.is_monotonic_increasing:
        raise ValueError(f'Invalid/unsorted/duplicated dates: {path}')
    return parsed.iloc[-1].date()


def expected_trade_date():
    now = datetime.now(SHANGHAI)
    calendar = ak.tool_trade_date_hist_sina()
    if 'trade_date' not in calendar.columns or calendar.empty:
        raise RuntimeError('Trade calendar unavailable')
    days = pd.to_datetime(calendar['trade_date'], errors='raise').dt.date
    cutoff = now.date() if now.time() >= clock_time(16, 0) else (now.date() - pd.Timedelta(days=1))
    valid = days[days <= cutoff]
    if valid.empty:
        raise RuntimeError('No completed trade date in calendar')
    return valid.max().isoformat(), now


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true', help='Run original V5.5 on lagging pairs; may write validated data')
    p.add_argument('--limit', type=int, default=None, help='Max selected lagging stocks; testing only')
    p.add_argument('--sleep', type=float, default=0.5, help='Delay after each V5.5 network request')
    p.add_argument('--retries', type=int, default=2)
    p.add_argument('--run-id', help='V5.5 checkpoint ID; use the same ID when resuming')
    p.add_argument('--resume', action='store_true', help='Resume V5.5 checkpoint; requires --apply and --run-id')
    args = p.parse_args()
    if args.limit is not None and args.limit < 1:
        p.error('--limit must be positive')
    if args.sleep < 0 or args.retries < 0:
        p.error('Invalid numeric argument')
    if args.resume and (not args.apply or not args.run_id):
        p.error('--resume requires --apply and --run-id')
    if not UPDATER.is_file():
        p.error(f'Original V5.5 not found: {UPDATER}')
    expected, now = expected_trade_date()
    raw_dir, qfq_dir = HISTORY / 'raw', HISTORY / 'qfq'
    raw = {f.stem for f in raw_dir.glob('*.csv')}
    qfq = {f.stem for f in qfq_dir.glob('*.csv')}
    if not raw or raw != qfq:
        raise RuntimeError(f'Unpaired files: raw={len(raw)}, qfq={len(qfq)}, raw_only={len(raw-qfq)}, qfq_only={len(qfq-raw)}')
    lagging = []
    errors = []
    current = 0
    for symbol in sorted(raw):
        try:
            rd = last_date(raw_dir / (symbol + '.csv'))
            qd = last_date(qfq_dir / (symbol + '.csv'))
            if rd != qd:
                raise ValueError(f'raw/qfq end mismatch: {rd} vs {qd}')
            if rd > pd.Timestamp(expected).date():
                raise ValueError(f'future data {rd} beyond expected {expected}')
            if rd == pd.Timestamp(expected).date():
                current += 1
            else:
                lagging.append(symbol)
        except Exception as exc:
            errors.append(f'{symbol}: {exc}')
    if errors:
        print(json.dumps({'status':'BLOCKED_INVALID_LOCAL_DATA','errors':errors[:20], 'error_count':len(errors)},ensure_ascii=False,indent=2))
        return 1
    selected = lagging[:args.limit] if args.limit is not None else lagging
    plan = {'mode':'APPLY' if args.apply else 'PLAN_ONLY','expected_trade_date':expected,
            'generated_at_shanghai':now.isoformat(),'paired_count':len(raw),
            'already_on_expected_date':current,'lagging_count':len(lagging),
            'selected_count':len(selected),'selected_symbols':selected[:30],
            'limitations':['Already-current stocks are not redownloaded; historical qfq revisions may be missed',
                           'Lagging stocks may be suspended; no dates are padded',
                           'Original V5.5 performs validation, backups and checkpointing']}
    print(json.dumps(plan,ensure_ascii=False,indent=2),flush=True)
    if not args.apply:
        print('PLAN_ONLY_NO_FILES_CHANGED')
        return 0
    if not selected:
        print('NO_LAGGING_STOCKS_NO_UPDATE_NEEDED')
        return 0
    REPORT_DIR.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stock_smart_') as tmp:
        selection = Path(tmp)/'symbols.txt'
        selection.write_text('\n'.join(selected)+'\n',encoding='utf-8')
        cmd=[sys.executable,str(UPDATER),'--symbols-file',str(selection),'--apply',
             '--sleep',str(args.sleep),'--retries',str(args.retries)]
        if args.run_id: cmd += ['--run-id',args.run_id]
        if args.resume: cmd += ['--resume']
        print('DELEGATING_TO_ORIGINAL_V55',flush=True)
        result=subprocess.run(cmd,cwd=ROOT)
    print(f'ORIGINAL_V55_EXIT={result.returncode}',flush=True)
    return result.returncode

if __name__=='__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'SMART_UPDATE_FAILED: {type(exc).__name__}: {exc}',file=sys.stderr)
        sys.exit(1)
