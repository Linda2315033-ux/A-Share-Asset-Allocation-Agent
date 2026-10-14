# -*- coding: utf-8 -*-
"""Safe current-name/ST snapshot updater for a FIXED research universe.

Default DRY RUN: fetch and validate, but do not change local files.
Apply: python stock_universe_daily_update_v1.py --apply
This does NOT certify the market quote's trading date or PIT ST history.
"""
import argparse
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent
STOCKS = ROOT / 'data' / 'stocks'
CSV_PATH = STOCKS / 'universe.csv'
META_PATH = STOCKS / 'universe_metadata.json'
BACKUP_ROOT = STOCKS / 'universe_backups'
REPORT_DIR = ROOT / 'output' / 'stock_universe_daily_update_v1'
TZ = ZoneInfo('Asia/Shanghai')


def atomic_bytes(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with open(tmp, 'wb') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def main():
    ap = argparse.ArgumentParser(description='Fixed-universe stock names and ST snapshot updater')
    ap.add_argument('--apply', action='store_true', help='Backup and update universe.csv and metadata')
    args = ap.parse_args()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(TZ).strftime('%Y%m%d_%H%M%S_%f')
    report_path = REPORT_DIR / 'last_run.json'
    report = {'run_id': run_id, 'mode': 'APPLY' if args.apply else 'DRY_RUN',
              'retrieved_at': None, 'passed': False, 'written': False,
              'quote_date_verified': False, 'errors': [], 'warnings': [
                  'Sina spot timestamp has no independently verified trading date',
                  'Name-based ST status is not an exchange-verified complete risk-status feed',
              ]}
    try:
        if not CSV_PATH.is_file() or not META_PATH.is_file():
            raise FileNotFoundError('Existing universe.csv and universe_metadata.json are required')
        old = pd.read_csv(CSV_PATH, dtype=str, encoding='utf-8-sig', keep_default_na=False)
        if not {'symbol', 'name', 'code', 'exchange'}.issubset(old.columns):
            raise ValueError('Existing universe missing symbol/name/code/exchange')
        old['symbol'] = old['symbol'].str.strip().str.lower()
        if old['symbol'].eq('').any() or old['symbol'].duplicated().any():
            raise ValueError('Existing universe has empty/duplicate symbols')
        with open(META_PATH, encoding='utf-8-sig') as f:
            old_meta = json.load(f)
        import akshare as ak
        live = ak.stock_zh_a_spot()
        if live is None or live.empty:
            raise ValueError('Sina spot response empty')
        # Require named columns rather than positional assumptions.
        required = {'代码', '名称', '最新价', '成交额', '时间戳'}
        if not required.issubset(live.columns):
            raise ValueError(f'Sina response missing columns: {sorted(required - set(live.columns))}')
        live = live.copy()
        live['symbol'] = live['代码'].astype(str).str.strip().str.lower()
        if live['symbol'].eq('').any() or live['symbol'].duplicated().any():
            raise ValueError('Sina spot response has empty/duplicate symbols')
        old_symbols = set(old['symbol'])
        live_symbols = set(live['symbol'])
        missing = sorted(old_symbols - live_symbols)
        if missing:
            raise ValueError(f'{len(missing)} historical symbols absent from spot response; sample: {missing[:10]}')
        latest = live.set_index('symbol').loc[old['symbol']]
        names = latest['名称'].astype(str).str.strip()
        if names.eq('').any() or names.str.lower().isin(['nan', 'none', 'null']).any():
            raise ValueError('Latest stock names include empty/invalid values')
        old_names = old.set_index('symbol')['name'].astype(str)
        new_names = pd.Series(names.to_numpy(), index=old['symbol'].to_numpy())
        old_st = {s for s, n in old_names.items() if 'ST' in n.upper()}
        new_st = {s for s, n in new_names.items() if 'ST' in n.upper()}
        added_st = sorted(new_st - old_st)
        removed_st = sorted(old_st - new_st)
        changed = sorted(s for s in old_symbols if old_names[s] != new_names[s])
        report.update({'retrieved_at': datetime.now(TZ).isoformat(),
                       'old_count': len(old), 'live_count': len(live),
                       'matched_count': len(old_symbols), 'missing_count': 0,
                       'old_st_count': len(old_st), 'new_st_count': len(new_st),
                       'new_st_symbols': added_st, 'removed_st_symbols': removed_st,
                       'name_changed_count': len(changed), 'name_changed_sample': changed[:30]})
        # Preserve original membership and columns; only refresh names and available quote fields.
        updated = old.copy()
        updated['name'] = names.to_numpy()
        for dest, source in [('price', '最新价'), ('amount', '成交额'), ('quote_time', '时间戳')]:
            if dest in updated.columns:
                updated[dest] = latest[source].astype(str).to_numpy()
        # Name update is allowed even if quote price is missing; preserve old numeric quote fields instead.
        for dest in ('price', 'amount'):
            if dest in updated.columns:
                numeric = pd.to_numeric(updated[dest], errors='coerce')
                valid = numeric.gt(0) if dest == 'price' else numeric.ge(0)
                updated.loc[~valid, dest] = old.loc[~valid, dest].to_numpy()
        metadata = dict(old_meta)
        metadata.update({'source': 'AKShare stock_zh_a_spot / Sina',
                         'retrieved_at': report['retrieved_at'],
                         'count': len(updated),
                         'sh_count': int(updated['exchange'].eq('SH').sum()),
                         'sz_count': int(updated['exchange'].eq('SZ').sum()),
                         'universe_type': 'current_mainboard_quote_candidates',
                         'exchange_membership_verified': False,
                         'quote_date_verified': False,
                         'historical_universe': False,
                         'st_name_count': len(new_st),
                         'name_snapshot_run_id': run_id,
                         'name_snapshot_date_verified': False})
        report['passed'] = True
        if args.apply:
            backup_dir = BACKUP_ROOT / run_id
            backup_dir.mkdir(parents=True, exist_ok=False)
            shutil.copy2(CSV_PATH, backup_dir / CSV_PATH.name)
            shutil.copy2(META_PATH, backup_dir / META_PATH.name)
            report['backup_dir'] = str(backup_dir)
            csv_bytes = updated.to_csv(index=False).encode('utf-8-sig')
            meta_bytes = json.dumps(metadata, ensure_ascii=False, indent=2).encode('utf-8')
            try:
                atomic_bytes(CSV_PATH, csv_bytes)
                atomic_bytes(META_PATH, meta_bytes)
            except Exception:
                # Restore both from verified backups if either replacement fails.
                atomic_bytes(CSV_PATH, (backup_dir / CSV_PATH.name).read_bytes())
                atomic_bytes(META_PATH, (backup_dir / META_PATH.name).read_bytes())
                raise
            report['written'] = True
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        report['passed'] = False
        report['errors'].append(f'{type(exc).__name__}: {exc}')
        print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    finally:
        atomic_bytes(report_path, json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8'))
        print('Report:', report_path)


if __name__ == '__main__':
    sys.exit(main())
