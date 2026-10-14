"""V5.4 可解释研究快照：最新预览排除当前ST/*ST；历史重建不使用当前ST标签。
只读行情、不联网、不交易；输出到独立V5.4目录。
运行: python stock_agent_current_decision_v54.py
"""
from pathlib import Path
from collections import Counter
from datetime import datetime
import json
import numpy as np
import pandas as pd
import stock_backtest_signals as base

ROOT = Path('data/stocks/mainboard_history_v1')
UNIVERSE = Path('data/stocks/universe.csv')
OUT = Path('output/stock_agent_current_v54')
THRESHOLD = 0.80


def load_current_st_symbols(paired):
    if not UNIVERSE.is_file():
        raise FileNotFoundError(f'缺少当前股票名称快照：{UNIVERSE}')
    df = pd.read_csv(UNIVERSE, encoding='utf-8-sig', dtype=str)
    if not {'symbol', 'name'}.issubset(df.columns):
        raise ValueError('universe.csv 必须包含 symbol、name 字段')
    df['symbol'] = df['symbol'].fillna('').str.strip()
    df['name'] = df['name'].fillna('').str.strip()
    if df['symbol'].duplicated().any() or (df['symbol'] == '').any():
        raise ValueError('股票名称快照存在重复或空股票代码')
    names = df.set_index('symbol')['name']
    missing = sorted(set(paired) - set(names.index))
    blank = sorted(sym for sym in paired if sym in names.index and not names[sym])
    if missing or blank:
        raise RuntimeError(f'股票名称快照不完整：缺失代码{len(missing)}，空名称{len(blank)}；示例：{(missing + blank)[:10]}')
    # 匹配名称中出现的 ST（含 *ST、ST 前后有空格等），不使用正则。
    return {sym for sym in paired if 'ST' in names[sym].upper()}


def run():
    raw = {p.stem: p for p in (ROOT / 'raw').glob('*.csv')}
    qfq = {p.stem: p for p in (ROOT / 'qfq').glob('*.csv')}
    paired = sorted(set(raw) & set(qfq))
    if len(paired) < 3000:
        raise RuntimeError(f'股票配对文件仅{len(paired)}，停止运行，避免误认为全股票池')
    st_symbols = load_current_st_symbols(paired)
    print(f'当前股票名称快照：{len(paired)}只，ST标记{len(st_symbols)}只')

    index = base.load_market()
    index_date = index.index.max()
    if index_date > pd.Timestamp.now().normalize():
        raise RuntimeError('指数日期晚于本机日期，停止运行')
    if (pd.Timestamp.now().normalize() - index_date).days > 10:
        raise RuntimeError(f'指数最后日期{index_date.date()}距今超过10个自然日；请先更新指数')
    previous = index.index[index.index.to_period('M') < index_date.to_period('M')]
    if len(previous) == 0:
        raise RuntimeError('没有可用于历史重建的上一月交易日')
    dates = sorted(set([index_date, previous[-1]]))
    reports = []
    OUT.mkdir(parents=True, exist_ok=True)
    for date in dates:
        latest = date == index_date
        market = base.market_at(index, date)
        factors = []
        counts = Counter()
        failed = []
        st_excluded = []
        for i, sym in enumerate(paired, 1):
            # 仅最新预览使用当前ST名称快照；历史重建不能使用未来ST状态。
            if latest and sym in st_symbols:
                counts['CURRENT_ST_EXCLUDED'] += 1
                st_excluded.append(sym)
            else:
                try:
                    a = base.load_csv(raw[sym])
                    b = base.load_csv(qfq[sym])
                    if not a.index.equals(b.index):
                        counts['RAW_QFQ_DATE_MISMATCH'] += 1
                        continue
                    factor, status = base.stock_factor(sym, a, b, date, index.index)
                    counts[status] += 1
                    if factor is not None:
                        factors.append(factor)
                except Exception as exc:
                    counts['FILE_ERROR'] += 1
                    failed.append({'symbol': sym, 'error': str(exc)})
            if i % 500 == 0:
                print(f'{date.date()} 数据进度 {i}/{len(paired)}', flush=True)
        if not factors:
            raise RuntimeError(f'{date.date()}无合格因子，停止')
        frame = (pd.DataFrame(factors)
                 .sort_values(['avg_amount_20', 'symbol'], ascending=[False, True])
                 .head(base.TOP_CANDIDATES))
        decision = base.select_portfolio(frame, market)
        # 候选解释记录：保留成交额排名、因子、策略筛选及最终入选原因。
        ranked = frame.reset_index(drop=True).copy()
        ranked['liquidity_rank'] = ranked.index + 1
        strategy = decision['strategy']
        if strategy in ('MOMENTUM', 'DEFENSIVE'):
            eligible = ranked[ranked['momentum_60'] > 0].copy()
        else:
            eligible = ranked.copy()
        if strategy == 'MOMENTUM':
            eligible = eligible.sort_values(['score', 'symbol'], ascending=[False, True])
        else:
            eligible = eligible.sort_values(['volatility_20', 'symbol'], ascending=[True, True])
        eligible['strategy_rank'] = range(1, len(eligible) + 1)
        rank_by_symbol = dict(zip(eligible['symbol'], eligible['strategy_rank']))
        preselected = {h['symbol'] for h in decision['holdings']}
        explanations = []
        for item in ranked.to_dict(orient='records'):
            symbol = item['symbol']
            if symbol in preselected:
                reason = 'SELECTED_BY_STRATEGY'
            elif strategy in ('MOMENTUM', 'DEFENSIVE') and item['momentum_60'] <= 0:
                reason = 'NON_POSITIVE_MOMENTUM'
            elif strategy == 'DEFENSIVE' and len(preselected) == 0:
                reason = 'DEFENSIVE_MIN_STOCK_COUNT_NOT_MET'
            else:
                reason = 'BELOW_STRATEGY_TOP_N'
            explanations.append({
                'symbol': symbol,
                'liquidity_rank': int(item['liquidity_rank']),
                'strategy_rank': int(rank_by_symbol[symbol]) if symbol in rank_by_symbol else None,
                'avg_amount_20': float(item['avg_amount_20']),
                'momentum_60': float(item['momentum_60']),
                'volatility_20': float(item['volatility_20']),
                'score': float(item['score']),
                'decision': reason,
            })
        excluded, kept = [], []
        for h in decision['holdings']:
            h = dict(h)
            if decision['strategy'] == 'MOMENTUM' and float(h['volatility_20']) > THRESHOLD:
                excluded.append(h)
            else:
                kept.append(h)
        if latest and any(h['symbol'] in st_symbols for h in kept):
            raise RuntimeError('ST股票意外进入最新持仓，停止输出')
        final_symbols = {h['symbol'] for h in kept}
        for row in explanations:
            if row['symbol'] in final_symbols:
                row['decision'] = 'FINAL_HOLDING'
            elif row['symbol'] in preselected:
                row['decision'] = 'MOMENTUM_VOLATILITY_ABOVE_80_PERCENT'
        equity = sum(float(h['target_weight']) for h in kept)
        cash = 1 - equity
        if not np.isclose(equity + cash, 1, atol=1e-10) or equity > float(decision['target_equity_weight']) + 1e-10:
            raise RuntimeError('权重校验失败')
        status = 'LATEST_DAILY_PREVIEW' if latest else 'PREVIOUS_MONTH_END_RECONSTRUCTION'
        report = {
            'asof_date': str(date.date()), 'status': status, 'is_latest_snapshot': latest,
            'not_live_order': True, 'market': market, 'strategy': decision['strategy'],
            'target_equity_weight_before_filter': float(decision['target_equity_weight']),
            'equity_weight': equity, 'cash_weight': cash, 'holdings': kept,
            'excluded': excluded, 'filtered_count': len(excluded),
            'st_filter_applied': latest,
            'st_filter_source': str(UNIVERSE) if latest else None,
            'st_filter_note': ('使用当前名称快照排除ST，仅用于最新研究预览；名称快照时间未独立核验'
                               if latest else '历史重建未使用当前ST名单，历史ST状态尚未核验'),
            'st_universe_count': len(st_symbols) if latest else None,
            'st_excluded_count': len(st_excluded),
            'st_excluded_symbols': st_excluded,
            'candidate_explanations': explanations,
            'selection_explanation': ('先按过去20日平均成交额选前30只；动量策略按score降序，防御策略要求60日动量为正并按20日波动率升序；最多5只；再执行原有持仓过滤。'),
            'valid_factor_count': len(factors), 'candidate_count': len(frame),
            'paired_universe_count': len(paired), 'factor_status_counts': dict(counts),
            'file_errors': failed, 'generated_at': datetime.now().astimezone().isoformat(),
            'limitations': [
                '脚本只读取本地CSV，不负责下载、定时更新或验证股票池快照日期',
                '最新日为研究预览，非月末正式调仓信号', '不下载数据、不执行交易',
                '当前ST过滤依赖universe.csv名称快照，未核验快照时间与完整风险警示状态',
                '历史重建没有历史ST状态过滤', '停牌及退市事件未独立核验',
                '现存主板样本存在幸存者偏差', '前复权点时可得性和公司行为未独立核验',
                '80%阈值事后选定；历史回测不代表未来收益'
            ]
        }
        reports.append(report)
        path = OUT / ('latest_preview.json' if latest else 'previous_month_end.json')
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        if latest:
            pd.DataFrame(explanations).to_csv(OUT / 'latest_candidate_explanations.csv', index=False, encoding='utf-8-sig')
            pd.DataFrame(kept).to_csv(OUT / 'latest_holdings.csv', index=False, encoding='utf-8-sig')
        print(f"{date.date()} {status} | {decision['strategy']} | 合格股票{len(factors)} | "
              f"ST排除{len(st_excluded)} | 持仓{len(kept)} | 波动率过滤{len(excluded)} | "
              f"股票{equity:.2%} 现金{cash:.2%}")
    (OUT / 'run_summary.json').write_text(json.dumps({
        'reports': [{'date': r['asof_date'], 'status': r['status'],
                     'strategy': r['strategy'], 'equity_weight': r['equity_weight'],
                     'cash_weight': r['cash_weight'], 'st_excluded_count': r['st_excluded_count']}
                    for r in reports]
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print('输出目录:', OUT)


if __name__ == '__main__':
    run()
