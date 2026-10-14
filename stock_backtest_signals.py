
"""
stock_backtest_signals.py

股票Agent历史回测 - 历史决策信号生成 V1

研究窗口：2019-01-01 ~ 2025-12-31
股票池：本地32只股票，固定样本演示
决策：每月最后一个指数交易日收盘后
执行：本模块不执行交易

不联网、不调用GLM、不修改原始数据。
"""

from pathlib import Path
import json
import math

import numpy as np
import pandas as pd

from stock_backtest_policy import (
    classify_market,
    select_portfolio,
)

ROOT = Path("data/stocks")
RAW_DIR = ROOT / "history"
QFQ_DIR = ROOT / "research_qfq"
INDEX_FILE = ROOT / "market" / "sh000300.csv"

OUT = Path("output/stock_backtest")
OUT.mkdir(parents=True, exist_ok=True)

START = pd.Timestamp("2019-01-01")
END = pd.Timestamp("2025-12-31")

TOP_CANDIDATES = 30
MOMENTUM_DAYS = 60
VOL_DAYS = 20
AMOUNT_DAYS = 20


def load_csv(path):
    df = pd.read_csv(path, dtype=str)
    df.columns = [
        str(c).strip().lower()
        for c in df.columns
    ]

    date_col = next(
        (
            c for c in ["date", "trade_date", "datetime"]
            if c in df.columns
        ),
        None
    )

    if date_col is None:
        raise ValueError(f"{path}: 缺少日期字段")

    df["date"] = pd.to_datetime(
        df[date_col], errors="coerce"
    )

    if df["date"].isna().any():
        raise ValueError(f"{path}: 日期无效")

    if df["date"].duplicated().any():
        raise ValueError(f"{path}: 日期重复")

    for col in [
        "open", "high", "low", "close",
        "volume", "amount", "turnover"
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col], errors="coerce"
            )

    return (
        df.sort_values("date")
        .set_index("date")
    )


def load_market():
    index = load_csv(INDEX_FILE)

    if "close" not in index.columns:
        raise ValueError("指数缺少close")

    if (
        index["close"].isna().any()
        or (index["close"] <= 0).any()
    ):
        raise ValueError("指数收盘价无效")

    return index


def month_end_dates(index):
    calendar = index.loc[
        (index.index >= START)
        & (index.index <= END)
    ].index

    dates = (
        pd.Series(calendar, index=calendar)
        .groupby(calendar.to_period("M"))
        .last()
        .tolist()
    )

    return dates


def market_at(index, date):
    history = index.loc[:date, "close"]

    # 60日收益需要61个收盘价
    if len(history) < 61:
        raise ValueError("指数历史长度不足61日")

    close = history.iloc[-1]
    ret20 = close / history.iloc[-21] - 1
    ret60 = close / history.iloc[-61] - 1

    daily_returns = history.pct_change().dropna()

    vol20 = (
        daily_returns.tail(20).std()
        * math.sqrt(252)
    )

    return classify_market(
        float(ret20),
        float(ret60),
        float(vol20),
    )


def stock_factor(symbol, raw, qfq, date, calendar):
    """
    只使用决策日及之前的数据。

    必须在决策日有行情。
    需要足够的历史观测值。
    最近60个指数交易日需有完整股票行情。

    返回因子及历史成交额指标。
    """

    if date not in raw.index:
        return None, "RAW_MISSING_ON_DATE"

    if date not in qfq.index:
        return None, "QFQ_MISSING_ON_DATE"

    recent_calendar = calendar[
        calendar <= date
    ][-61:]

    if len(recent_calendar) < 61:
        return None, "CALENDAR_TOO_SHORT"

    raw_recent = raw.reindex(recent_calendar)
    qfq_recent = qfq.reindex(recent_calendar)

    if (
        raw_recent["close"].isna().any()
        or qfq_recent["close"].isna().any()
    ):
        return None, "MISSING_RECENT_TRADING_DAY"

    close = qfq_recent["close"]

    if (close <= 0).any():
        return None, "INVALID_QFQ_CLOSE"

    returns = close.pct_change().dropna()

    momentum = (
        close.iloc[-1] / close.iloc[-61] - 1
    )

    volatility = (
        returns.tail(VOL_DAYS).std()
        * math.sqrt(252)
    )

    if (
        not np.isfinite(momentum)
        or not np.isfinite(volatility)
        or volatility <= 0
    ):
        return None, "INVALID_FACTOR"

    # 必须使用历史成交额，不使用当前行情排名。
    amount_col = next(
        (
            c for c in ["amount", "turnover"]
            if c in raw_recent.columns
        ),
        None
    )

    if amount_col is None:
        return None, "MISSING_AMOUNT_COLUMN"

    amounts = raw_recent[
        amount_col
    ].tail(AMOUNT_DAYS)

    if (
        amounts.isna().any()
        or (amounts < 0).any()
    ):
        return None, "INVALID_AMOUNT"

    avg_amount = float(amounts.mean())

    if avg_amount <= 0:
        return None, "ZERO_AMOUNT"

    return {
        "symbol": symbol,
        "momentum_60": float(momentum),
        "volatility_20": float(volatility),
        "score": float(momentum / volatility),
        "avg_amount_20": avg_amount,
    }, "PASS"


def load_stocks():
    raw_files = {
        p.stem: p
        for p in RAW_DIR.glob("*.csv")
    }

    qfq_files = {
        p.stem: p
        for p in QFQ_DIR.glob("*.csv")
    }

    symbols = sorted(
        set(raw_files) & set(qfq_files)
    )

    if not symbols:
        raise RuntimeError("没有匹配的股票文件")

    stocks = {}

    for symbol in symbols:
        raw = load_csv(raw_files[symbol])
        qfq = load_csv(qfq_files[symbol])

        if not raw.index.equals(qfq.index):
            raise ValueError(
                f"{symbol}: 两种价格口径日期不一致"
            )

        if (
            "close" not in raw.columns
            or "close" not in qfq.columns
        ):
            raise ValueError(
                f"{symbol}: 缺少收盘价"
            )

        stocks[symbol] = (raw, qfq)

    return stocks


def main():
    print("=" * 66)
    print("股票Agent历史决策信号生成 V1")
    print("=" * 66)

    index = load_market()
    dates = month_end_dates(index)
    stocks = load_stocks()

    calendar = index.index

    print("股票样本数：", len(stocks))
    print("计划决策月份：", len(dates))

    decisions = []
    holdings = []
    audit_rows = []

    for date in dates:
        date_str = date.strftime("%Y-%m-%d")

        market = market_at(index, date)

        factors = []

        for symbol, (raw, qfq) in stocks.items():
            factor, status = stock_factor(
                symbol, raw, qfq,
                date, calendar
            )

            audit_rows.append({
                "decision_date": date_str,
                "symbol": symbol,
                "status": status,
            })

            if factor is not None:
                factors.append(factor)

        factor_df = pd.DataFrame(factors)

        if factor_df.empty:
            # 无有效候选时，研究组合持有现金
            decision = {
                "strategy": "NO_DATA_CASH",
                "target_equity_weight": 0.0,
                "actual_equity_weight": 0.0,
                "cash_weight": 1.0,
                "selected_stock_count": 0,
                "holdings": [],
            }
            candidate_count = 0

        else:
            # 在固定32只样本中，按历史成交额筛选
            factor_df = factor_df.sort_values(
                ["avg_amount_20", "symbol"],
                ascending=[False, True]
            ).head(TOP_CANDIDATES)

            candidate_count = len(factor_df)

            decision = select_portfolio(
                factor_df, market
            )

        decisions.append({
            "decision_date": date_str,
            "trend": market["trend"],
            "volatility_regime": (
                market["volatility_regime"]
            ),
            "return_20": market["return_20"],
            "return_60": market["return_60"],
            "market_volatility_20": (
                market["volatility_20"]
            ),
            "valid_candidate_count": candidate_count,
            "strategy": decision["strategy"],
            "target_equity_weight": (
                decision["target_equity_weight"]
            ),
            "actual_equity_weight": (
                decision["actual_equity_weight"]
            ),
            "cash_weight": (
                decision["cash_weight"]
            ),
            "selected_stock_count": (
                decision["selected_stock_count"]
            ),
        })

        for holding in decision["holdings"]:
            holdings.append({
                "decision_date": date_str,
                **holding,
            })

        print(
            f"{date_str} | "
            f"{decision['strategy']:<16} | "
            f"候选{candidate_count:2d}只 | "
            f"持仓{decision['selected_stock_count']}只 | "
            f"股票{decision['actual_equity_weight']:.0%}"
        )

    decision_file = OUT / "historical_decisions.csv"
    holdings_file = OUT / "historical_holdings.csv"
    audit_file = OUT / "historical_factor_audit.csv"

    pd.DataFrame(decisions).to_csv(
        decision_file,
        index=False,
        encoding="utf-8-sig"
    )

    pd.DataFrame(
        holdings,
        columns=[
            "decision_date",
            "symbol",
            "momentum_60",
            "volatility_20",
            "score",
            "target_weight",
        ]
    ).to_csv(
        holdings_file,
        index=False,
        encoding="utf-8-sig"
    )

    pd.DataFrame(audit_rows).to_csv(
        audit_file,
        index=False,
        encoding="utf-8-sig"
    )

    strategy_counts = (
        pd.DataFrame(decisions)["strategy"]
        .value_counts()
        .to_dict()
    )

    report = {
        "module": "stock_backtest_signals_v1",
        "sample_type": "FIXED_CURRENT_SAMPLE",
        "historical_universe_verified": False,
        "historical_membership_verified": False,
        "survivorship_bias_resolved": False,
        "corporate_actions_verified": False,
        "backtest_executed": False,
        "decision_count": len(decisions),
        "sample_stock_count": len(stocks),
        "strategy_counts": strategy_counts,
        "limitations": [
            "仅使用本地固定股票样本",
            "历史成交额排名仅在固定样本内计算",
            "未覆盖历史退市股票和完整主板股票池",
            "不包含交易执行、手续费或净值计算",
            "前复权数据尚未独立核验公司行为",
            "未验证历史可交易性和价格限制",
            "尚未证明研究结果不存在样本选择偏差"
        ],
    }

    report_file = OUT / "historical_signals_report.json"

    report_file.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("\n策略触发次数：")
    for name, count in strategy_counts.items():
        print(f"  {name}: {count}")

    print("\n输出文件：")
    print(decision_file)
    print(holdings_file)
    print(audit_file)
    print(report_file)

    print(
        "\n完成：历史决策信号已生成，"
        "尚未执行历史收益回测。"
    )


if __name__ == "__main__":
    main()
