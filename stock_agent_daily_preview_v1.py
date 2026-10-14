"""Safe, research-only daily preview runner for Stock Agent V5.4.
Run from project root: python stock_agent_daily_preview_v1.py
Does not update market data, trade, or authorize formal publication.
"""
import contextlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PREFLIGHT = ROOT / 'stock_agent_daily_pipeline_v2.py'
DECISION = ROOT / 'stock_agent_current_decision_v54.py'
BASE = ROOT / 'output' / 'stock_agent_daily_preview'
TZ = ZoneInfo('Asia/Shanghai')
REQUIRED = ('latest_preview.json', 'previous_month_end.json',
            'latest_candidate_explanations.csv', 'latest_holdings.csv', 'run_summary.json')


def main():
    now = datetime.now(TZ)
    run_id = now.strftime('%Y%m%d_%H%M%S_%f')
    stage = BASE / '_staging' / run_id
    stage.mkdir(parents=True, exist_ok=False)
    log_path = stage / 'runner.log'
    try:
        if not PREFLIGHT.is_file() or not DECISION.is_file():
            raise FileNotFoundError('Missing V2 preflight or V5.4 decision script in project root')
        check = subprocess.run([sys.executable, str(PREFLIGHT)], cwd=ROOT,
                               capture_output=True, text=True, errors='replace')
        (stage / 'preflight_stdout.txt').write_text(check.stdout, encoding='utf-8')
        (stage / 'preflight_stderr.txt').write_text(check.stderr, encoding='utf-8')
        source_report = ROOT / 'output' / 'stock_agent_daily_pipeline_v2' / 'last_preflight.json'
        if not source_report.is_file():
            raise RuntimeError('Preflight report missing')
        # Guard against accidentally reading a stale report from an earlier invocation.
        if source_report.stat().st_mtime < now.timestamp() - 30:
            raise RuntimeError('Preflight report appears stale')
        report = json.loads(source_report.read_text(encoding='utf-8'))
        (stage / 'preflight.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if check.returncode not in (0, 1):
            raise RuntimeError(f'Preflight process crashed: exit={check.returncode}')
        if report.get('data_checks_passed') is not True:
            raise RuntimeError('Data preflight did not pass; no preview generated')
        if report.get('checks', {}).get('universe_quote_date_verified') is not False:
            raise RuntimeError('This preview runner expects an explicitly unverified ST snapshot')
        expected = report['checks']['expected_trade_date']
        if report['checks'].get('index_end') != expected:
            raise RuntimeError('Index does not match expected trading date')
        if report.get('publication_allowed') is True:
            raise RuntimeError('Unexpected publication authorization: fail closed')
        if check.returncode != 1:
            raise RuntimeError('Preflight exit status and blocked publication disagree')

        # Load V5.4 from its original file, redirect only its output directory.
        # The original V5.4 source and its existing reports remain unchanged.
        spec = importlib.util.spec_from_file_location('daily_preview_v54', DECISION)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ROOT = ROOT / 'data' / 'stocks' / 'mainboard_history_v1'
        module.UNIVERSE = ROOT / 'data' / 'stocks' / 'universe.csv'
        module.OUT = stage
        with log_path.open('w', encoding='utf-8') as log, contextlib.redirect_stdout(log):
            old_cwd = Path.cwd()
            try:
                os.chdir(ROOT)  # stock_backtest_signals uses project-relative paths
                module.run()
            finally:
                os.chdir(old_cwd)
        for filename in REQUIRED:
            if not (stage / filename).is_file():
                raise RuntimeError(f'V5.4 missing output: {filename}')
        latest = json.loads((stage / 'latest_preview.json').read_text(encoding='utf-8'))
        if latest.get('asof_date') != expected or latest.get('status') != 'LATEST_DAILY_PREVIEW':
            raise RuntimeError('Latest V5.4 decision date/status mismatch')
        if latest.get('st_filter_applied') is not True or latest.get('not_live_order') is not True:
            raise RuntimeError('ST filter or no-trade declaration missing')
        if latest.get('file_errors'):
            raise RuntimeError(f"V5.4 encountered {len(latest['file_errors'])} stock file errors")
        holdings = latest.get('holdings', [])
        equity = sum(float(h['target_weight']) for h in holdings)
        cash = float(latest['cash_weight'])
        if not all(math.isfinite(x) for x in (equity, cash)) or not math.isclose(equity + cash, 1.0, abs_tol=1e-8):
            raise RuntimeError('Invalid portfolio weight sum')
        if not (0 <= cash <= 1) or not (0 <= equity <= 1):
            raise RuntimeError('Portfolio weight out of range')
        manifest = {
            'asof_date': expected,
            'generated_at_shanghai': datetime.now(TZ).isoformat(),
            'run_id': run_id,
            'report_type': 'RESEARCH_PREVIEW_ONLY',
            'formal_publication_allowed': False,
            'st_quote_date_verified': False,
            'st_snapshot_retrieved_at': report['checks'].get('universe_retrieved_at'),
            'data_checks_passed': True,
            'strategy': latest.get('strategy'),
            'holdings_count': len(holdings),
            'equity_weight': equity,
            'cash_weight': cash,
            'limitations': [
                'ST/name quote date not independently verified; ST exclusion is name-based only',
                'Research preview, not an order, recommendation, or formal publication',
                'Existing-universe survivorship bias and historical point-in-time limitations remain',
                'No data downloads or historical CSV updates performed by this runner',
            ],
        }
        (stage / 'preview_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        destination = BASE / expected / run_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(destination)  # Publish only after all validation succeeds.
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        print('PREVIEW_SAVED:', destination)
        return 0
    except Exception as exc:
        (stage / 'FAILED.txt').write_text(f'{type(exc).__name__}: {exc}\n', encoding='utf-8')
        print(f'PREVIEW_NOT_PUBLISHED: {type(exc).__name__}: {exc}', file=sys.stderr)
        print('Failure artifacts:', stage, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
