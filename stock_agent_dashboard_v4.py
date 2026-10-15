"""Read-only Streamlit dashboard for validated stock Agent V5.4 daily research previews.
Run: python -m streamlit run stock_agent_dashboard_v3.py
"""
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from stock_agent_glm_daily_v2 import tool_portfolio, run_glm

ROOT = Path(__file__).resolve().parent
ANSWER = ROOT / 'output' / 'stock_agent_glm_daily_v1' / 'last_answer.json'
DEFAULT_QUESTION = '请调用最新研究预览工具，解释当前市场状态、为何选择此策略、各只股票的目标权重以及主要风险。'

st.set_page_config(page_title='A股资产配置研究Agent', page_icon='📊', layout='wide')
st.title('A股资产配置研究 Agent')
st.caption('V5.4 研究预览 · GLM 只读工具调用 · 不提供交易指令')

try:
    data = tool_portfolio()
except Exception as exc:
    st.error(f'无法读取通过校验的最新研究预览：{exc}')
    st.info('请先运行 stock_agent_daily_preview_v1.py，并确认预览校验通过。不会自动回退到较早日期的报告。')
    st.stop()

asof = data['asof_date']
st.warning(f'研究数据截至 {asof}，并非实时行情。ST名称快照日期未经独立核验；正式发布被阻断。')

c1, c2, c3, c4 = st.columns(4)
c1.metric('研究日期', asof)
c2.metric('策略', str(data['strategy']))
c3.metric('股票仓位', f"{float(data['equity_weight']):.1%}")
c4.metric('现金比例', f"{float(data['cash_weight']):.1%}")

st.subheader('市场状态')
market = data.get('market') or {}
if isinstance(market, dict):
    keys = [('trend', '市场趋势'), ('volatility_regime', '波动率状态'),
            ('return_20', '20日收益率'), ('return_60', '60日收益率'),
            ('volatility_20', '20日年化波动率')]
    cols = st.columns(5)
    for col, (key, label) in zip(cols, keys):
        value = market.get(key)
        if value is None:
            shown = '未提供'
        elif key.startswith('return_') or key.startswith('volatility_'):
            try:
                shown = f'{float(value):.2%}'
            except (ValueError, TypeError):
                shown = str(value)
        else:
            shown = str(value)
        col.metric(label, shown)
    with st.expander('市场原始数据'):
        st.json(market)
else:
    st.info('研究快照没有提供可解析的市场状态。')

st.subheader('目标组合')
holdings = data.get('holdings', [])
if holdings:
    df = pd.DataFrame(holdings)
    display = df.copy()
    if 'target_weight' in display:
        display['target_weight'] = pd.to_numeric(display['target_weight'], errors='coerce')
    st.dataframe(display, use_container_width=True, hide_index=True)
    chart = pd.DataFrame([
        {'资产': str(h.get('symbol', '未知')), '权重': float(h['target_weight'])}
        for h in holdings
    ] + [{'资产': '现金', '权重': float(data['cash_weight'])}]).set_index('资产')
    st.bar_chart(chart, y='权重', horizontal=True)
else:
    st.info('该研究日期没有入选股票，组合可能全部持有现金。')

def chinese_selection_explanation(info):
    """使用已知策略规则生成中文说明，不将英文原文直接展示在网页。"""
    strategy = str(info.get('strategy', '')).upper()
    intro = (
        '系统首先根据历史成交额筛选流动性较好的候选股票，'
        '再结合市场趋势、价格动量和波动率决定股票配置。'
    )
    if strategy == 'DEFENSIVE':
        details = (
            '当前为防御型策略：先按过去20个交易日的平均成交额筛选前30只候选股票；'
            '优先考虑过去60个交易日动量为正的股票，按过去20个交易日波动率从低到高排序；'
            '最多选择5只，并根据可用性和风险过滤结果确定最终持仓。'
        )
    else:
        details = (
            '当前策略为“' + strategy + '”。具体筛选阈值应以当日保存的研究快照和策略代码为准；'
            '此处不推测未验证的策略细节。'
        )
    return intro + details + '当前股票总仓位为{:.1%}，现金比例为{:.1%}。'.format(
        float(info['equity_weight']), float(info['cash_weight'])
    )


def chinese_research_limitations(info):
    """将当前研究快照中已知的英文风险标签转换为中文。"""
    raw = [str(x) for x in (info.get('limitations') or [])]
    catalog = [
        ('ST名称识别与日期核验', ('st', 'name', 'quote date'),
         'ST股票仅根据名称识别，名称快照对应的交易日期尚未经过独立核验，可能遗漏或误判。'),
        ('股票池幸存者偏差', ('survivorship', 'existing-universe'),
         '股票池以当前存续股票为基础，历史研究可能存在幸存者偏差。'),
        ('历史时点信息', ('point-in-time', 'historical st', 'lookahead', 'look-ahead'),
         '历史ST状态与其他历史时点信息未完成独立核验，存在潜在前视偏差。'),
        ('停牌与退市', ('suspend', 'delist'),
         '停牌、复牌和退市等事件尚未完成独立核验。'),
        ('复权与公司行为', ('adjust', 'corporate action', 'qfq'),
         '复权价格修订及分红、拆股等公司行为尚未完成独立核验。'),
        ('研究预览与交易限制', ('research preview', 'not an order', 'formal publication', 'not live'),
         '本结果仅为研究预览，不是交易指令、投资建议或正式发布结果。'),
        ('本地数据读取', ('no data downloads', 'csv', 'not update'),
         '本页面读取本地研究数据，不负责联网更新历史行情。'),
        ('交易可执行性', ('execution', 'limit-up', 'limit-down', 'transaction cost'),
         '历史成交、涨跌停约束及交易成本等可执行性因素可能未得到充分验证。'),
        ('未来收益不确定性', ('future return', 'past performance', 'not guarantee'),
         '历史回测表现不代表未来收益。'),
    ]
    result = []
    for line in raw:
        lowered = line.lower()
        matched = [cn for _, keywords, cn in catalog if any(k in lowered for k in keywords)]
        if matched:
            result.extend(matched)
        elif any('\u4e00' <= c <= '\u9fff' for c in line):
            result.append(line)
        else:
            result.append('研究快照包含一项尚未完成中文释义的附加限制，请以原始研究报告核查其具体含义。')
    result.extend([
        'ST名称快照日期未经独立核验，正式发布权限保持关闭。',
        '现有股票池可能存在幸存者偏差，历史结果不代表未来表现。',
    ])
    return list(dict.fromkeys(result))


with st.expander('选股规则与研究限制', expanded=True):
    st.markdown('**一、选股规则**')
    st.write(chinese_selection_explanation(data))
    st.write(f"按名称识别并排除的ST股票数量：{data.get('st_excluded_count', '未提供')}")
    st.write(f"ST名称快照获取时间：{data.get('st_snapshot_retrieved_at') or '未提供'}")
    st.markdown('**二、研究限制与风险**')
    for limitation in chinese_research_limitations(data):
        st.write('• ' + limitation)
    st.caption('上述说明仅供研究参考。策略规则以Python实现为准；英文原始字段不在此区域直接显示。')



# 历史回测：使用已保存的历史逐期决策，不重新拟合或使用当日股票回填过去。
st.subheader('当前策略的历史回测表现')
st.caption('展示历史动态策略回测，并提取历史上与今日策略同名的决策期。仅供研究，非今日4只股票的历史回测。')

@st.cache_data(show_spinner=False)
def load_historical_backtest(root_string):
    root = Path(root_string)
    def find_one(filename):
        direct = [root / filename, root / 'output' / filename]
        for p in direct:
            if p.is_file():
                return p
        matches = sorted((root / 'output').rglob(filename)) if (root / 'output').exists() else []
        return matches[-1] if matches else None
    decisions_path = find_one('historical_decisions.csv')
    nav_path = find_one('backtest_v31_nav.csv')
    if not nav_path:
        nav_path = find_one('baseline_nav.csv')
    if not decisions_path or not nav_path:
        return None, None, decisions_path, nav_path
    d = pd.read_csv(decisions_path, encoding='utf-8-sig')
    n = pd.read_csv(nav_path, encoding='utf-8-sig')
    if not {'decision_date', 'strategy'}.issubset(d.columns):
        raise ValueError('historical_decisions.csv缺少决策日期或策略列')
    if not {'date', 'nav_normalized', 'benchmark_normalized'}.issubset(n.columns):
        raise ValueError('回测净值文件缺少日期或净值列')
    d['decision_date'] = pd.to_datetime(d['decision_date'], errors='raise')
    n['date'] = pd.to_datetime(n['date'], errors='raise')
    d = d.sort_values('decision_date').drop_duplicates('decision_date', keep='last')
    n = n.sort_values('date').drop_duplicates('date', keep='last')
    for c in ['nav_normalized', 'benchmark_normalized']:
        n[c] = pd.to_numeric(n[c], errors='coerce')
    n = n.dropna(subset=['nav_normalized', 'benchmark_normalized'])
    n = n[(n['nav_normalized'] > 0) & (n['benchmark_normalized'] > 0)]
    return d, n, decisions_path, nav_path

try:
    decisions, hist_nav, decisions_file, nav_file = load_historical_backtest(str(ROOT))
    if decisions is None or hist_nav is None:
        st.info('尚未找到历史回测文件。请将 historical_decisions.csv 和 backtest_v31_nav.csv 放到项目根目录或 output 子目录；不使用模拟数据填充。')
    elif len(hist_nav) < 3:
        st.warning('历史净值数据不足，无法计算回测指标。')
    else:
        start = hist_nav['date'].iloc[0].date()
        end = hist_nav['date'].iloc[-1].date()
        st.write(f'**历史回测区间：** {start} 至 {end} ｜ **当前研究策略：** {data["strategy"]}')
        st.caption(f'数据来源：{nav_file.name} + {decisions_file.name}。历史策略由当时的市场状态逐期决定，可能与今日策略不同。')
        series = hist_nav.set_index('date')[['nav_normalized', 'benchmark_normalized']].rename(columns={
            'nav_normalized': 'Dynamic Agent Portfolio',
            'benchmark_normalized': 'CSI 300 Benchmark',
        })
        st.line_chart(series, x_label='Date', y_label='Normalized NAV')
        def metrics(nav):
            nav = nav.astype(float)
            ret = nav.pct_change(fill_method=None).dropna()
            if len(ret) < 2:
                return None
            total = nav.iloc[-1] / nav.iloc[0] - 1
            annual = (nav.iloc[-1] / nav.iloc[0]) ** (252 / len(ret)) - 1
            vol = ret.std() * (252 ** 0.5)
            sharpe = (ret.mean() * 252 / vol) if vol > 0 else float('nan')
            dd = nav / nav.cummax() - 1
            return total, annual, vol, sharpe, dd.min(), dd
        p = metrics(hist_nav['nav_normalized'])
        b = metrics(hist_nav['benchmark_normalized'])
        if p and b:
            comparison = pd.DataFrame({
                '指标': ['累计收益率', '年化收益率', '年化波动率', '夏普比率（无风险利率0）', '最大回撤'],
                '动态Agent组合': [f'{p[0]:.2%}', f'{p[1]:.2%}', f'{p[2]:.2%}', f'{p[3]:.3f}', f'{p[4]:.2%}'],
                '沪深300基准': [f'{b[0]:.2%}', f'{b[1]:.2%}', f'{b[2]:.2%}', f'{b[3]:.3f}', f'{b[4]:.2%}'],
            })
            st.dataframe(comparison, hide_index=True, use_container_width=True)
            drawdowns = pd.DataFrame({
                'Agent Drawdown': p[5].to_numpy(),
                'Benchmark Drawdown': b[5].to_numpy(),
            }, index=hist_nav['date'])
            st.line_chart(drawdowns, x_label='Date', y_label='Drawdown')
        st.markdown('**历史上与今日策略相同的决策期**')
        chosen = decisions[decisions['strategy'].astype(str).str.upper() == str(data['strategy']).upper()].copy()
        if chosen.empty:
            st.info('历史决策记录中没有出现当前策略，无法给出该策略的历史分段表现。')
        else:
            # A signal observed at close on the decision day applies to subsequent sessions,
            # not the decision day itself. Match each NAV day to the last prior decision.
            daily = hist_nav[['date', 'nav_normalized', 'benchmark_normalized']].copy()
            daily['portfolio_return'] = daily['nav_normalized'].pct_change(fill_method=None)
            daily['benchmark_return'] = daily['benchmark_normalized'].pct_change(fill_method=None)
            assigned = pd.merge_asof(daily.sort_values('date'),
                decisions[['decision_date', 'strategy']].sort_values('decision_date'),
                left_on='date', right_on='decision_date', direction='backward', allow_exact_matches=False)
            matching = assigned[assigned['strategy'].astype(str).str.upper() == str(data['strategy']).upper()].dropna(subset=['portfolio_return', 'benchmark_return'])
            st.metric('历史同策略决策次数', f'{len(chosen)} 次')
            if matching.empty:
                st.info('该策略没有可匹配的后续交易日净值，暂不能计算历史分段收益。')
            else:
                # Cumulative returns are compounded only over matching strategy days;
                # noncontiguous segments are deliberately not presented as a tradable NAV.
                strat_total = (1 + matching['portfolio_return']).prod() - 1
                bench_total = (1 + matching['benchmark_return']).prod() - 1
                col_a, col_b, col_c = st.columns(3)
                col_a.metric('同策略后续交易日', f'{len(matching)} 天')
                col_b.metric('这些交易日组合复合收益', f'{strat_total:.2%}')
                col_c.metric('相同交易日基准复合收益', f'{bench_total:.2%}')
                st.caption('以上为历史动态组合在同名策略期间的条件表现：各段不连续，复合收益不是独立运行该策略的完整回测，也不能直接年化。')
            with st.expander('查看同策略历史决策日期'):
                cols = [c for c in ['decision_date', 'trend', 'volatility_regime', 'strategy', 'target_equity_weight', 'actual_equity_weight', 'selected_stock_count'] if c in chosen.columns]
                st.dataframe(chosen[cols].sort_values('decision_date', ascending=False), hide_index=True, use_container_width=True)
        st.warning('回测研究局限：当前存续股票池可能存在幸存者偏差；历史ST、停复牌、涨跌停、复权和交易可执行性未完成独立核验。历史表现不代表未来收益。')
except Exception as exc:
    st.error(f'历史回测展示失败：{exc}。原有当日研究预览与GLM功能不受影响。')

st.subheader('GLM研究解读')
st.caption('点击后才调用在线模型。模型仅能读取经过校验的本地研究预览，不会修改配置或下单。')
question = st.text_area('研究问题', value=DEFAULT_QUESTION, height=90)
if st.button('调用GLM解释最新研究预览', type='primary'):
    if not question.strip():
        st.error('请输入研究问题。')
    else:
        with st.spinner('GLM正在调用只读研究工具并生成解释……'):
            try:
                result = run_glm(question.strip(), expected_date=asof)
                if result.get('asof_date') != asof or not any(
                    x.get('tool') == 'get_latest_daily_preview' and x.get('status') == 'SUCCESS'
                    for x in result.get('tools', [])
                ):
                    raise ValueError('GLM未成功调用本日期的研究工具')
                st.session_state['stock_glm_result'] = result
            except Exception as exc:
                st.error(f'GLM调用失败：{exc}')

result = st.session_state.get('stock_glm_result')
if result and result.get('asof_date') == asof:
    st.markdown(result.get('answer', ''))
    st.caption(f"本次会话回答 · 模型：{result.get('model', '未提供')} · 已成功调用研究工具")
elif ANSWER.is_file():
    try:
        saved = json.loads(ANSWER.read_text(encoding='utf-8'))
        valid = (saved.get('asof_date') == asof and saved.get('formal_publication_allowed') is False
                 and any(t.get('tool') == 'get_latest_daily_preview' and t.get('status') == 'SUCCESS'
                         for t in saved.get('tools', [])))
        if valid:
            with st.expander('查看此前保存的GLM解读（非本次实时调用）'):
                st.markdown(saved.get('answer', ''))
        else:
            st.info('已有GLM回答与当前研究日期或安全标记不匹配，未显示旧回答。')
    except (ValueError, OSError, TypeError) as exc:
        st.caption(f'旧GLM回答文件无法读取：{exc}')

st.divider()
st.caption('仅供研究、教学和软件演示；非实时行情、投资建议、正式发布或交易系统。')
