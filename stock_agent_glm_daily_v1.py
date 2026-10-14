"""GLM read-only agent for the latest *validated* V5.4 daily research preview.

Commands:
  python stock_agent_glm_daily_v1.py --check
  python stock_agent_glm_daily_v1.py --ask "解释最新组合及风险"
  python stock_agent_glm_daily_v1.py --self-test
No API key is needed for --check/--self-test. No trading or data mutation.
"""
import argparse
import json
import math
import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PREVIEWS = ROOT / 'output' / 'stock_agent_daily_preview'
SHANGHAI = ZoneInfo('Asia/Shanghai')


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _load_validated(directory):
    manifest = _json(directory / 'preview_manifest.json')
    latest = _json(directory / 'latest_preview.json')
    required = {'report_type': 'RESEARCH_PREVIEW_ONLY', 'formal_publication_allowed': False,
                'st_quote_date_verified': False}
    if any(manifest.get(k) != v for k, v in required.items()):
        raise ValueError('Preview manifest safety flags invalid')
    if manifest.get('data_checks_passed') is not True:
        raise ValueError('Preview data check not passed')
    date = manifest.get('asof_date')
    if not isinstance(date, str) or len(date) != 10 or directory.parent.name != date:
        raise ValueError('Preview date/directory mismatch')
    if latest.get('asof_date') != date or latest.get('status') != 'LATEST_DAILY_PREVIEW':
        raise ValueError('Decision date/status mismatch')
    if latest.get('not_live_order') is not True or latest.get('st_filter_applied') is not True:
        raise ValueError('Safety flags missing from decision')
    if latest.get('file_errors'):
        raise ValueError('Stock file errors in decision')
    holdings = latest.get('holdings')
    if not isinstance(holdings, list):
        raise ValueError('Invalid holdings')
    weights = [float(h['target_weight']) for h in holdings]
    cash = float(latest['cash_weight'])
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in weights + [cash]):
        raise ValueError('Invalid weights')
    if not math.isclose(sum(weights) + cash, 1, abs_tol=1e-8):
        raise ValueError('Weights do not sum to 1')
    if len(holdings) != manifest.get('holdings_count'):
        raise ValueError('Holdings count mismatch')
    if not math.isclose(sum(weights), float(manifest.get('equity_weight')), abs_tol=1e-8):
        raise ValueError('Equity weight mismatch')
    if not math.isclose(cash, float(manifest.get('cash_weight')), abs_tol=1e-8):
        raise ValueError('Cash weight mismatch')
    return manifest, latest


def latest_validated_preview(expected_date=None, base=PREVIEWS):
    """Fail closed: only latest dated preview; do not silently fall back to older day."""
    dates = sorted([p for p in base.iterdir() if p.is_dir() and len(p.name) == 10 and
                    p.name[4] == '-' and p.name[7] == '-'], reverse=True) if base.is_dir() else []
    if not dates:
        raise FileNotFoundError('No daily preview found; run daily preview first')
    date_dir = dates[0]
    if expected_date is not None and date_dir.name != expected_date:
        raise RuntimeError(f'Latest preview date {date_dir.name} != expected {expected_date}')
    runs = sorted([p for p in date_dir.iterdir() if p.is_dir() and not p.name.startswith('_')], reverse=True)
    if not runs:
        raise FileNotFoundError(f'No completed run in {date_dir}')
    # Latest run must be valid: never fall back silently to an older run.
    manifest, latest = _load_validated(runs[0])
    return runs[0], manifest, latest


def tool_portfolio(expected_date=None):
    directory, manifest, latest = latest_validated_preview(expected_date)
    return {
        'source_directory': str(directory.relative_to(ROOT)) if directory.is_relative_to(ROOT) else str(directory),
        'asof_date': manifest['asof_date'], 'strategy': latest['strategy'],
        'market': latest.get('market'), 'holdings': latest['holdings'],
        'equity_weight': manifest['equity_weight'], 'cash_weight': manifest['cash_weight'],
        'selection_explanation': latest.get('selection_explanation'),
        'st_excluded_count': latest.get('st_excluded_count'),
        'st_snapshot_retrieved_at': manifest.get('st_snapshot_retrieved_at'),
        'st_quote_date_verified': False, 'formal_publication_allowed': False,
        'research_only': True, 'not_live_order': True,
        'limitations': manifest.get('limitations', []) + latest.get('limitations', []),
    }


def run_glm(question, expected_date=None):
    # Import lazily so offline validation does not require SDK or API key.
    from openai import OpenAI
    from stock_agent_llm_v2 import load_api_key, BASE_URL, MODEL
    data = tool_portfolio(expected_date)
    client = OpenAI(api_key=load_api_key(), base_url=BASE_URL, timeout=90.0, max_retries=1)
    schema = {'type': 'function', 'function': {
        'name': 'get_latest_daily_preview',
        'description': '读取已校验的V5.4最新股票研究预览：日期、市场、策略、持仓、权重和风险限制。只读。',
        'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}}
    messages = [
        {'role': 'system', 'content': (
            '你是中国A股资产配置研究助手。涉及最新市场或组合事实必须调用get_latest_daily_preview。'
            '工具只提供本地已保存的历史交易日研究预览，不是实时行情。'
            '严禁编造数据、股票权重或回测绩效；不能交易或更改配置。'
            '明确说明ST仅按名称识别，快照交易日期未经独立核验；正式发布被阻断。'
            '不构成投资建议。')},
        {'role': 'user', 'content': question},
    ]
    logs = []
    final = None
    for _ in range(4):
        response = client.chat.completions.create(model=MODEL, messages=messages,
                                                   tools=[schema], tool_choice='auto', temperature=0.2)
        msg = response.choices[0].message
        calls = msg.tool_calls or []
        if not calls:
            final = (msg.content or '').strip()
            break
        messages.append(msg.model_dump(exclude_none=True))
        for call in calls:
            if call.function.name != 'get_latest_daily_preview' or json.loads(call.function.arguments or '{}') != {}:
                content = json.dumps({'error': 'Unauthorized tool or arguments'}, ensure_ascii=False)
                logs.append({'tool': call.function.name, 'status': 'FAILED'})
            else:
                content = json.dumps(data, ensure_ascii=False, default=str, allow_nan=False)
                logs.append({'tool': call.function.name, 'status': 'SUCCESS'})
            messages.append({'role': 'tool', 'tool_call_id': call.id, 'content': content})
    if not any(x['status'] == 'SUCCESS' for x in logs):
        raise RuntimeError('GLM did not successfully call the research tool; no verified answer issued')
    if not final:
        raise RuntimeError('GLM did not produce a final answer')
    return {'question': question, 'answer': final, 'tools': logs, 'asof_date': data['asof_date'],
            'model': MODEL, 'research_only': True, 'formal_publication_allowed': False,
            'generated_at_shanghai': datetime.now(SHANGHAI).isoformat()}


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / '2026-10-14' / 'test_run'
        d.mkdir(parents=True)
        manifest = {'report_type': 'RESEARCH_PREVIEW_ONLY', 'formal_publication_allowed': False,
                    'st_quote_date_verified': False, 'data_checks_passed': True,
                    'asof_date': '2026-10-14', 'holdings_count': 1,
                    'equity_weight': 0.3, 'cash_weight': 0.7}
        latest = {'asof_date': '2026-10-14', 'status': 'LATEST_DAILY_PREVIEW',
                  'not_live_order': True, 'st_filter_applied': True, 'file_errors': [],
                  'holdings': [{'symbol': 'sh600000', 'target_weight': 0.3}],
                  'cash_weight': 0.7}
        (d / 'preview_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        (d / 'latest_preview.json').write_text(json.dumps(latest), encoding='utf-8')
        assert latest_validated_preview('2026-10-14', Path(tmp))[0] == d
        latest['cash_weight'] = 0.6
        (d / 'latest_preview.json').write_text(json.dumps(latest), encoding='utf-8')
        try:
            latest_validated_preview('2026-10-14', Path(tmp))
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid weights were accepted')
        print('SELF_TEST_OK: valid snapshot accepted; invalid weights rejected')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true', help='Offline validate and summarize latest preview')
    group.add_argument('--ask', type=str, help='Ask GLM using read-only latest preview tool')
    group.add_argument('--self-test', action='store_true', help='Offline fixture tests')
    parser.add_argument('--expected-date', help='Optional required date YYYY-MM-DD')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.check:
        data = tool_portfolio(args.expected_date)
        print(json.dumps({k: data[k] for k in ('asof_date', 'strategy', 'equity_weight',
                                              'cash_weight', 'st_quote_date_verified',
                                              'formal_publication_allowed')}, ensure_ascii=False, indent=2))
        print('PREVIEW_TOOL_CHECK_OK')
    else:
        result = run_glm(args.ask, args.expected_date)
        out = ROOT / 'output' / 'stock_agent_glm_daily_v1'
        out.mkdir(parents=True, exist_ok=True)
        dest = out / 'last_answer.json'
        temp = out / 'last_answer.json.part'
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, dest)
        print(result['answer'])
        print('TOOLS:', result['tools'])
        print('SAVED:', dest)


if __name__ == '__main__':
    main()
