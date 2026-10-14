"""V5.4 resilient stock history updater; run from asset_agent project root.
Dry run by default. --apply writes validated CSVs with retained backups.
--symbols-file selects symbols; --resume skips successful entries in this run's checkpoint.
"""
import argparse
import sys
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
import akshare as ak
import pandas as pd

ROOT = Path('data/stocks/mainboard_history_v1')
REPORT = Path('output/stock_mainboard_incremental_update_v54')
FIELDS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']

def normalize(frame):
    if frame is None or frame.empty or not set(FIELDS).issubset(frame.columns):
        raise ValueError('empty data or missing columns')
    d = frame[FIELDS].copy()
    d['date'] = pd.to_datetime(d['date'], errors='coerce').dt.normalize()
    for field in FIELDS[1:]:
        d[field] = pd.to_numeric(d[field], errors='coerce')
    if d.isna().any().any() or d.date.duplicated().any():
        raise ValueError('missing values or duplicated dates')
    if (d[['open', 'high', 'low', 'close']] <= 0).any().any():
        raise ValueError('invalid prices')
    if (d[['volume', 'amount']] < 0).any().any():
        raise ValueError('negative trading values')
    return d.sort_values('date').reset_index(drop=True)


def validate_pair(old, new, kind, symbol):
    if new.date.min() > old.date.min():
        raise ValueError(f'{symbol} {kind}: downloaded history starts later than cache')
    if new.date.max() < old.date.max():
        raise ValueError(f'{symbol} {kind}: downloaded history is older than cache')
    missing = old.loc[~old.date.isin(new.date), 'date']
    if len(missing):
        raise ValueError(f'{symbol} {kind}: {len(missing)} old dates disappeared')
    if kind == 'raw':
        common = old.merge(new, on='date', suffixes=('_old', '_new')).tail(20)
        if len(common) < min(5, len(old)):
            raise ValueError(f'{symbol}: insufficient overlapping raw dates')
        for field in ['open', 'high', 'low', 'close']:
            delta = (common[field+'_old'] - common[field+'_new']).abs()
            if (delta > 0.011).any():
                raise ValueError(f'{symbol}: raw {field} changed on overlap; manual review needed')
    else:
        common = old.merge(new, on='date', suffixes=('_old', '_new')).tail(20)
        if len(common) < min(5, len(old)):
            raise ValueError(f'{symbol}: insufficient overlapping qfq dates')
        ratio = common.close_new / common.close_old
        if (ratio <= 0).any() or (ratio.max() / ratio.min() > 1.02):
            raise ValueError(f'{symbol}: qfq overlap changed non-uniformly; manual review needed')


def atomic_write(df, path):
    tmp = path.with_name(path.name + '.v54.part')
    try:
        df.to_csv(tmp, index=False, encoding='utf-8-sig', date_format='%Y-%m-%d')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


NETWORK_MARKERS = (
    'ProxyError', 'SSLError', 'ConnectionError', 'ConnectTimeout', 'ReadTimeout',
    'TimeoutError', 'NameResolutionError', 'ConnectionResetError',
    'RemoteDisconnected', 'NewConnectionError', 'getaddrinfo failed',
    'Max retries exceeded', 'Connection aborted', 'Network is unreachable',
)


def is_network_error(exc):
    description = f'{type(exc).__name__}: {exc}'
    return any(marker.lower() in description.lower() for marker in NETWORK_MARKERS)


def fetch(symbol, adjust, retries, wait):
    for attempt in range(retries + 1):
        try:
            return normalize(ak.stock_zh_a_daily(symbol=symbol, adjust=adjust))
        except Exception as exc:
            if not is_network_error(exc) or attempt == retries:
                raise
            pause = wait * (2 ** attempt)
            print(f'  Network error {symbol} ({adjust or "raw"}); '
                  f'retry {attempt + 1}/{retries} after {pause:.1f}s', flush=True)
            time.sleep(pause)


def write_json_atomic(path, data):
    temp = path.with_name(path.name + '.part')
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=None, help='Optional max symbols; default processes all selected symbols')
    parser.add_argument('--symbols-file', type=Path, help='UTF-8 text, one symbol per line')
    parser.add_argument('--apply', action='store_true', help='Write validated data')
    parser.add_argument('--sleep', type=float, default=1.5, help='Pause after each request')
    parser.add_argument('--retries', type=int, default=2, help='Network retries per request')
    parser.add_argument('--retry-wait', type=float, default=5.0, help='Initial retry wait seconds')
    parser.add_argument('--max-consecutive-network-failures', type=int, default=5)
    parser.add_argument('--run-id', type=str, help='Stable checkpoint name for --resume')
    parser.add_argument('--resume', action='store_true', help='Skip successful checkpoint records')
    args = parser.parse_args()
    if ((args.limit is not None and args.limit < 1) or args.sleep < 0 or args.retries < 0 or args.retry_wait < 0
            or args.max_consecutive_network_failures < 1):
        parser.error('Invalid numeric argument')
    if args.resume and not args.apply:
        parser.error('--resume requires --apply; dry-run results are not checkpointed')
    if args.resume and not args.run_id:
        parser.error('--resume requires --run-id')
    if args.run_id and (not args.run_id.replace('_', '').replace('-', '').isalnum()):
        parser.error('--run-id must contain only letters, digits, underscore, hyphen')

    raw_paths = sorted((ROOT / 'raw').glob('*.csv'))
    symbols = [p.stem for p in raw_paths if (ROOT / 'qfq' / p.name).exists()]
    available = set(symbols)
    if not symbols:
        parser.error(f'No paired raw/qfq files in {ROOT}')
    if args.symbols_file:
        if not args.symbols_file.is_file():
            parser.error(f'Symbols file not found: {args.symbols_file}')
        requested = [line.strip() for line in args.symbols_file.read_text(encoding='utf-8-sig').splitlines()
                     if line.strip() and not line.lstrip().startswith('#')]
        chosen = list(dict.fromkeys(requested))
        unknown = [s for s in chosen if s not in available]
        if unknown:
            parser.error(f'Unknown or unpaired symbols ({len(unknown)}): {unknown[:10]}')
    else:
        chosen = symbols
    if args.limit is not None:
        chosen = chosen[:args.limit]
    if not chosen:
        parser.error('No symbols selected')

    run_id = args.run_id or datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    REPORT.mkdir(parents=True, exist_ok=True) if args.apply else None
    checkpoint = REPORT / f'checkpoint_{run_id}.json'
    results = {}
    if args.resume and checkpoint.exists():
        previous = json.loads(checkpoint.read_text(encoding='utf-8'))
        if not isinstance(previous, dict):
            parser.error('Checkpoint is not a dictionary')
        results = {s: v for s, v in previous.items() if s in chosen}
    elif args.resume:
        parser.error(f'Checkpoint not found: {checkpoint}')
    elif args.apply and checkpoint.exists():
        parser.error(f'Checkpoint exists: {checkpoint}; use --resume')

    print(f'Mode: {"APPLY" if args.apply else "DRY RUN"}; '
          f'selected: {len(chosen)} / {len(symbols)}; run-id: {run_id}', flush=True)
    consecutive_network_failures = 0
    stopped = False
    try:
        for i, symbol in enumerate(chosen, 1):
            if args.resume and results.get(symbol, {}).get('status') in ('UPDATED', 'ALREADY_CURRENT', 'VALIDATED'):
                print(f'[{i}/{len(chosen)}] {symbol}: SKIPPED_CHECKPOINT', flush=True)
                continue
            paths = {kind: ROOT / kind / f'{symbol}.csv' for kind in ('raw', 'qfq')}
            try:
                old = {kind: normalize(pd.read_csv(path)) for kind, path in paths.items()}
                new = {}
                for kind, adjust in (('raw', ''), ('qfq', 'qfq')):
                    new[kind] = fetch(symbol, adjust, args.retries, args.retry_wait)
                    validate_pair(old[kind], new[kind], kind, symbol)
                    time.sleep(args.sleep)
                if new['raw'].date.max() != new['qfq'].date.max():
                    raise ValueError('raw and qfq downloaded end dates disagree')
                old_end = max(d.date.max() for d in old.values()).date().isoformat()
                new_end = new['raw'].date.max().date().isoformat()
                state = 'ALREADY_CURRENT' if all(new[k].equals(old[k]) for k in paths) else 'VALIDATED'
                if args.apply and state != 'ALREADY_CURRENT':
                    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                    backup = REPORT / 'backups' / stamp / symbol
                    backup.mkdir(parents=True, exist_ok=False)
                    for kind, path in paths.items():
                        shutil.copy2(path, backup / f'{kind}.csv')
                    try:
                        for kind, path in paths.items():
                            atomic_write(new[kind], path)
                    except Exception:
                        for kind, path in paths.items():
                            shutil.copy2(backup / f'{kind}.csv', path)
                        raise
                    state = 'UPDATED'
                result = {'symbol': symbol, 'status': state, 'old_end': old_end, 'new_end': new_end}
                consecutive_network_failures = 0
            except Exception as exc:
                network = is_network_error(exc)
                result = {'symbol': symbol, 'status': 'FAILED',
                          'error': f'{type(exc).__name__}: {exc}', 'network_error': network}
                consecutive_network_failures = consecutive_network_failures + 1 if network else 0
            results[symbol] = result
            print(f'[{i}/{len(chosen)}] {result}', flush=True)
            if args.apply:
                write_json_atomic(checkpoint, results)
            if consecutive_network_failures >= args.max_consecutive_network_failures:
                print('STOP: repeated network failures; check connection and resume later.', flush=True)
                stopped = True
                break
    except KeyboardInterrupt:
        stopped = True
        print('Interrupted by user; checkpoint retained.', flush=True)
    finally:
        if args.apply:
            write_json_atomic(checkpoint, results)
            print(f'Checkpoint: {checkpoint}', flush=True)
        passed = sum(v['status'] != 'FAILED' for v in results.values())
        failed = sum(v['status'] == 'FAILED' for v in results.values())
        not_processed = len(chosen) - len(results)
        print(f'Summary: {passed} passed, {failed} failed; '
              f'{not_processed} not processed; stopped={stopped}', flush=True)
        if failed or not_processed or stopped:
            sys.exit(1)


if __name__ == '__main__':
    main()
