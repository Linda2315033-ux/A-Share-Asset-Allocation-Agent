
"""
stock_backtest_policy.py

股票历史回测 - 策略规则模块 V1

目标：
1. 根据历史市场指标判断市场状态
2. 根据市场状态切换投资策略
3. 根据历史股票因子选择持仓
4. 输出目标股票权重和现金权重

不下载行情，不调用GLM，不执行交易。

注意：
这是固定股票池回测的规则模块。
历史股票池、交易执行、复权与公司行为
由后续模块负责。

在正式回测前，应与现有
stock_multi_strategy.py 的规则逐项对照。
"""

import math
import numpy as np
import pandas as pd


TOP_N = 5

MAX_SINGLE_WEIGHT = 0.16

MIN_DEFENSIVE_STOCKS = 3


STRATEGY_EQUITY = {
    "MOMENTUM": 0.80,
    "LOW_VOLATILITY": 0.60,
    "DEFENSIVE": 0.30,
    "RISK_REDUCTION": 0.40,
}


def classify_market(
    return_20,
    return_60,
    volatility_20
):
    """
    输入：
        return_20: 20交易日收益率
        return_60: 60交易日收益率
        volatility_20: 20日年化波动率

    输入数值均为小数：
        -5% 写成 -0.05
        25% 写成 0.25
    """

    values = [
        return_20,
        return_60,
        volatility_20
    ]

    if not all(
        math.isfinite(float(x))
        for x in values
    ):
        raise ValueError(
            "市场指标存在无效数值"
        )

    if volatility_20 < 0:
        raise ValueError(
            "波动率不能小于0"
        )

    if (
        return_60 > 0.05
        and return_20 > 0
    ):
        trend = "UPTREND"

    elif (
        return_60 < -0.05
        and return_20 < 0
    ):
        trend = "DOWNTREND"

    else:
        trend = "SIDEWAYS"

    if volatility_20 > 0.25:
        volatility_regime = (
            "HIGH_VOLATILITY"
        )
    else:
        volatility_regime = (
            "NORMAL_VOLATILITY"
        )

    return {
        "trend": trend,
        "volatility_regime": (
            volatility_regime
        ),
        "return_20": float(return_20),
        "return_60": float(return_60),
        "volatility_20": (
            float(volatility_20)
        ),
    }


def choose_strategy(market_state):

    trend = market_state["trend"]

    volatility_regime = market_state[
        "volatility_regime"
    ]

    # 高波动优先于趋势判断
    if (
        volatility_regime
        == "HIGH_VOLATILITY"
    ):
        return "RISK_REDUCTION"

    if trend == "UPTREND":
        return "MOMENTUM"

    if trend == "DOWNTREND":
        return "DEFENSIVE"

    return "LOW_VOLATILITY"


def select_portfolio(
    factor_df,
    market_state
):
    """
    factor_df 必须只包含决策日已知的数据。

    必需字段：
        symbol
        momentum_60
        volatility_20
        score

    返回：
        strategy
        holdings
        equity_weight
        cash_weight
    """

    required = {
        "symbol",
        "momentum_60",
        "volatility_20",
        "score",
    }

    missing = required - set(
        factor_df.columns
    )

    if missing:
        raise ValueError(
            f"因子数据缺少字段：{missing}"
        )

    strategy = choose_strategy(
        market_state
    )

    df = factor_df.copy()

    df["symbol"] = (
        df["symbol"].astype(str)
    )

    if df["symbol"].duplicated().any():
        raise ValueError(
            "因子表存在重复股票代码"
        )

    for col in [
        "momentum_60",
        "volatility_20",
        "score"
    ]:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    
    numeric_cols = [
        "momentum_60",
        "volatility_20",
        "score",
    ]

    invalid = (
        df[numeric_cols].isna().any(axis=1)
        | ~np.isfinite(
            df[numeric_cols]
        ).all(axis=1)
        | (df["volatility_20"] <= 0)
    )

    if invalid.any():
        raise ValueError(
            f"发现{int(invalid.sum())}条无效因子，"
            "回测拒绝静默删除股票"
        )

    if df.empty:
        raise ValueError(
            "因子表为空"
        )


    if strategy == "MOMENTUM":

        df = df[
            df["momentum_60"] > 0
        ]

        df = df.sort_values(
            ["score", "symbol"],
            ascending=[False, True]
        )

    elif strategy == "DEFENSIVE":

        df = df[
            df["momentum_60"] > 0
        ]

        df = df.sort_values(
            ["volatility_20", "symbol"],
            ascending=[True, True]
        )

    else:

        df = df.sort_values(
            ["volatility_20", "symbol"],
            ascending=[True, True]
        )

    selected = df.head(
        TOP_N
    ).copy()

    # 下跌趋势中，如果正动量股票
    # 不足3只，全部持有现金。
    if (
        strategy == "DEFENSIVE"
        and len(selected)
        < MIN_DEFENSIVE_STOCKS
    ):
        selected = selected.iloc[0:0]

    target_equity = (
        STRATEGY_EQUITY[strategy]
    )

    if selected.empty:
        target_equity = 0.0

    # 如果可用股票较少，
    # 不允许单票超过16%。
    if not selected.empty:

        per_stock = min(
            target_equity / len(selected),
            MAX_SINGLE_WEIGHT
        )

        selected["target_weight"] = (
            per_stock
        )

        actual_equity = (
            per_stock * len(selected)
        )

    else:

        selected["target_weight"] = (
            pd.Series(dtype=float)
        )

        actual_equity = 0.0

    cash_weight = (
        1.0 - actual_equity
    )

    holdings = selected[
        [
            "symbol",
            "momentum_60",
            "volatility_20",
            "score",
            "target_weight",
        ]
    ].to_dict(
        orient="records"
    )

    return {
        "strategy": strategy,
        "target_equity_weight": (
            target_equity
        ),
        "actual_equity_weight": (
            round(actual_equity, 10)
        ),
        "cash_weight": (
            round(cash_weight, 10)
        ),
        "selected_stock_count": (
            len(holdings)
        ),
        "holdings": holdings,
    }


def run_self_tests():

    print("=" * 60)
    print("股票回测策略规则 - 自检")
    print("=" * 60)

    scenarios = [
        (
            "上涨市场",
            0.03,
            0.10,
            0.15,
            "MOMENTUM",
        ),
        (
            "下跌市场",
            -0.04,
            -0.10,
            0.15,
            "DEFENSIVE",
        ),
        (
            "震荡市场",
            0.01,
            0.02,
            0.15,
            "LOW_VOLATILITY",
        ),
        (
            "高波动市场",
            -0.04,
            -0.10,
            0.30,
            "RISK_REDUCTION",
        ),
    ]

    for (
        name,
        ret20,
        ret60,
        vol20,
        expected
    ) in scenarios:

        market = classify_market(
            ret20,
            ret60,
            vol20
        )

        actual = choose_strategy(
            market
        )

        assert actual == expected, (
            name,
            actual,
            expected
        )

        print(
            f"[PASS] {name}: {actual}"
        )

    factors = pd.DataFrame({
        "symbol": [
            "600001",
            "600002",
            "600003",
            "600004",
            "600005",
            "600006",
        ],
        "momentum_60": [
            0.10,
            0.15,
            0.20,
            0.08,
            0.12,
            -0.03,
        ],
        "volatility_20": [
            0.20,
            0.25,
            0.30,
            0.18,
            0.22,
            0.15,
        ],
        "score": [
            0.50,
            0.60,
            0.67,
            0.44,
            0.55,
            -0.20,
        ],
    })

    expected_equity = {
        "MOMENTUM": 0.80,
        "DEFENSIVE": 0.30,
        "LOW_VOLATILITY": 0.60,
        "RISK_REDUCTION": 0.40,
    }

    for (
        name,
        ret20,
        ret60,
        vol20,
        expected
    ) in scenarios:

        market = classify_market(
            ret20,
            ret60,
            vol20
        )

        result = select_portfolio(
            factors,
            market
        )

        assert result["strategy"] == expected

        assert abs(
            result["actual_equity_weight"]
            - expected_equity[expected]
        ) < 1e-9

        assert abs(
            result["actual_equity_weight"]
            + result["cash_weight"]
            - 1.0
        ) < 1e-9

        assert all(
            h["target_weight"]
            <= MAX_SINGLE_WEIGHT + 1e-9
            for h in result["holdings"]
        )

        print(
            f"[PASS] {expected}: "
            f"股票{result['actual_equity_weight']:.0%} "
            f"现金{result['cash_weight']:.0%}"
        )

    # 防御策略：正动量股票不足3只
    # 应返回100%现金。
    weak_factors = factors.copy()

    weak_factors["momentum_60"] = [
        0.10,
        0.05,
        -0.01,
        -0.02,
        -0.03,
        -0.04,
    ]

    down_market = classify_market(
        -0.04,
        -0.10,
        0.15
    )

    result = select_portfolio(
        weak_factors,
        down_market
    )

    assert result["selected_stock_count"] == 0

    assert result["cash_weight"] == 1.0

    print(
        "[PASS] 防御策略候选不足：100%现金"
    )

    print("\n全部自检通过。")


if __name__ == "__main__":
    run_self_tests()
