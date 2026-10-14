"""Stock Agent daily preflight V2. Read-only for market data; writes only audit JSON.

Run from project root: python stock_agent_daily_pipeline_v2.py
Requires: pandas, akshare. No updater, trading, or V5.4 publication is invoked.
"""
import argparse
import json
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'stocks'
HIST = DATA / 'mainboard_history_v1'
INDEX = DATA / 'market' / 'sh000300.csv'
UNIVERSE = DATA / 'universe.csv'
META = DATA / 'universe_metadata.json'
OUT = ROOT / 'output' / 'stock_agent_daily_pipeline_v2'
TZ = ZoneInfo('Asia/Shanghai')


def last_date(path):
    df = pd.read_csv(path, usecols=['date'])
    d = pd.to_datetime(df['date'], errors='coerce')
    if d.empty or d.isna().any() or d.duplicated().any() or not d.is_monotonic_increasing:
        raise ValueError(f'Invalid, duplicate, or unsorted dates: {path}')
    if (d > pd.Timestamp(datetime.now(TZ).date())).any():
        raise ValueError(f'Future dated bars: {path}')
    return d.iloc[-1].date().isoformat()


def expected_trade_date(now):
    import akshare as ak
    cal = ak.tool_trade_date_hist_sina()
    if 'trade_date' not in cal.columns:
        raise ValueError('Trading calendar missing trade_date')
    parsed = pd.to_datetime(cal['trade_date'], errors='coerce')
    if parsed.empty or parsed.isna().any() or parsed.duplicated().any():
        raise ValueError('Trading calendar empty, malformed, or duplicated')
    dates = parsed.dt.date
    if not dates.is_monotonic_increasing:
        raise ValueError('Trading calendar is not sorted')
    cutoff = now.date() if now.time() >= time(16, 0) else now.date() - timedelta(days=1)
    eligible = dates[dates <= cutoff]
    if eligible.empty:
        raise ValueError('No completed trade date found in calendar')
    result = eligible.max()
    # Fail closed if provider calendar appears outdated.
    if (cutoff - result).days > 10:
        raise ValueError(f'Calendar may be outdated: last eligible={result}, cutoff={cutoff}')
    return result.isoformat(), cutoff.isoformat(), dates.max().isoformat(), len(dates)


def run(args):
    now = datetime.now(TZ)
    report = {
        'generated_at_shanghai': now.isoformat(),
        'mode': 'READ_ONLY_PREFLIGHT',
        'data_checks_passed': False,
        'publication_allowed': False,
        'passed': False,
        'checks': {}, 'warnings': [], 'errors': [],
    }
    c = report['checks']
    try:
        expected, cutoff, calendar_end, n_dates = expected_trade_date(now)
        c.update(expected_trade_date=expected, cutoff_date=cutoff,
                 calendar_last_date=calendar_end, calendar_rows=n_dates,
                 calendar_source='AKShare tool_trade_date_hist_sina')
        if args.expected_date and args.expected_date != expected:
            raise ValueError(f'Manual expected date {args.expected_date} differs from calendar {expected}')

        index_end = last_date(INDEX)
        c['index_end'] = index_end
        if index_end != expected:
            raise ValueError(f'Index end {index_end} != expected trade date {expected}')

        raw = {p.stem: p for p in (HIST / 'raw').glob('*.csv')}
        qfq = {p.stem: p for p in (HIST / 'qfq').glob('*.csv')}
        raw_only, qfq_only = sorted(set(raw) - set(qfq)), sorted(set(qfq) - set(raw))
        paired = sorted(set(raw) & set(qfq))
        c.update(paired_count=len(paired), raw_only_count=len(raw_only),
                 qfq_only_count=len(qfq_only))
        if raw_only or qfq_only:
            raise ValueError(f'Unpaired histories: raw_only={len(raw_only)}, qfq_only={len(qfq_only)}')
        if len(paired) < args.min_paired:
            raise ValueError(f'Only {len(paired)} paired stocks, minimum {args.min_paired}')

        names = pd.read_csv(UNIVERSE, dtype=str, encoding='utf-8-sig')
        if not {'symbol', 'name'}.issubset(names.columns):
            raise ValueError('universe.csv missing symbol/name')
        names['symbol'] = names['symbol'].fillna('').str.strip()
        names['name'] = names['name'].fillna('').str.strip()
        if (names['symbol'] == '').any() or names['symbol'].duplicated().any() or (names['name'] == '').any():
            raise ValueError('Blank/duplicate universe symbols or blank names')
        name_map = dict(zip(names['symbol'], names['name']))
        missing_names = sorted(set(paired) - set(name_map))
        no_history = sorted(set(name_map) - set(paired))
        c.update(universe_count=len(names), universe_missing_history_count=len(no_history),
                 history_missing_universe_count=len(missing_names),
                 st_count=sum('ST' in name_map[s].upper() for s in paired if s in name_map))
        if missing_names or no_history:
            raise ValueError(f'Universe/history membership mismatch: history_missing_names={len(missing_names)}, universe_missing_histories={len(no_history)}')

        if not META.is_file():
            raise FileNotFoundError(f'Missing universe metadata: {META}')
        meta = json.loads(META.read_text(encoding='utf-8-sig'))
        c['universe_retrieved_at'] = meta.get('retrieved_at')
        c['universe_quote_date_verified'] = meta.get('quote_date_verified') is True
        if meta.get('count') != len(names):
            raise ValueError(f'Metadata count {meta.get("count")} != universe {len(names)}')
        if meta.get('quote_date_verified') is not True:
            report['warnings'].append('ST/name snapshot quote date is not independently verified')

        current, lagging, mismatched, file_errors, ahead = 0, [], [], [], []
        for symbol in paired:
            try:
                a, b = last_date(raw[symbol]), last_date(qfq[symbol])
                if a != b:
                    mismatched.append({'symbol': symbol, 'raw': a, 'qfq': b})
                elif a == expected:
                    current += 1
                elif a > expected:
                    ahead.append({'symbol': symbol, 'last_date': a})
                else:
                    lagging.append({'symbol': symbol, 'last_date': a})
            except Exception as exc:
                file_errors.append({'symbol': symbol, 'error': str(exc)})
        ratio = current / len(paired)
        c.update(same_day_pair_count=current, same_day_ratio=round(ratio, 6),
                 lagging_count=len(lagging), raw_qfq_end_mismatch_count=len(mismatched),
                 future_vs_expected_count=len(ahead), file_error_count=len(file_errors),
                 lagging_sample=lagging[:10], mismatch_sample=mismatched[:10],
                 ahead_sample=ahead[:10], error_sample=file_errors[:10])
        if mismatched or file_errors or ahead:
            raise ValueError('Raw/qfq mismatches, invalid files, or data ahead of expected date')
        if ratio < args.min_current_ratio:
            raise ValueError(f'Same-day coverage {ratio:.2%} < required {args.min_current_ratio:.2%}')
        if lagging:
            report['warnings'].append(f'{len(lagging)} stocks lag expected trade date; not padded')
        report['data_checks_passed'] = True
        if meta.get('quote_date_verified') is not True:
            report['errors'].append('Publication blocked: ST/name quote date not independently verified')
        else:
            # Metadata flag alone does not establish its verification method or as-of date.
            report['errors'].append('Publication blocked: V2 does not verify independent ST snapshot evidence or its as-of date')
    except Exception as exc:
        report['errors'].append(f'{type(exc).__name__}: {exc}')
    report['passed'] = report['data_checks_passed'] and report['publication_allowed']
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--expected-date', help='Optional YYYY-MM-DD cross-check; never overrides calendar')
    ap.add_argument('--min-paired', type=int, default=3000)
    ap.add_argument('--min-current-ratio', type=float, default=0.97)
    args = ap.parse_args()
    if not 0 < args.min_current_ratio <= 1 or args.min_paired < 1:
        ap.error('Invalid thresholds')
    if args.expected_date:
        try:
            datetime.strptime(args.expected_date, '%Y-%m-%d')
        except ValueError:
            ap.error('--expected-date must be YYYY-MM-DD')
    report = run(args)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'last_preflight.json'
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('Report:', path)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
