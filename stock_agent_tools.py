
"""
stock_agent_tools.py

股票Agent V2的只读工具层。

读取已有研究结果，不联网，不重新计算策略，
不执行交易，不允许大模型修改组合权重。
"""

import json
from pathlib import Path

import pandas as pd


BASE = Path("output")

MARKET_FILE = (
    BASE / "stock_market_state" / "market_state.json"
)

DECISION_FILE = (
    BASE / "stock_multi_strategy" / "decision_report.json"
)

PORTFOLIO_FILE = (
    BASE / "stock_multi_strategy" / "portfolio.csv"
)

FACTOR_AUDIT_FILE = (
    BASE / "stock_factor_audit" / "audit_report.json"
)

FAILURE_FILE = (
    BASE / "stock_factor_audit" / "audit_failures.csv"
)


def read_json(path):
    if not path.exists():
        raise FileNotFoundError(
            f"缺少文件：{path}。请先运行对应的Python模块。"
        )

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_market_state():
    """读取沪深300市场状态。"""

    market = read_json(MARKET_FILE)

    fields = [
        "latest_date",
        "index_name",
        "return_20",
        "return_60",
        "volatility_20",
        "trend",
        "volatility_regime",
        "rules",
        "limitations",
    ]

    return {
        key: market.get(key)
        for key in fields
    }


def get_portfolio_decision():
    """
    读取动态配置结果，并进行基本一致性检查。
    """

    report = read_json(DECISION_FILE)

    if not PORTFOLIO_FILE.exists():
        raise FileNotFoundError(
            f"缺少组合文件：{PORTFOLIO_FILE}"
        )

    portfolio = pd.read_csv(
        PORTFOLIO_FILE,
        dtype={"code": str, "symbol": str}
    )

    required = [
        "symbol", "name", "target_weight"
    ]

    missing = [
        x for x in required
        if x not in portfolio.columns
    ]

    if missing:
        raise ValueError(
            f"组合文件缺少字段：{missing}"
        )

    weights = pd.to_numeric(
        portfolio["target_weight"],
        errors="raise"
    )

    if weights.isna().any():
        raise ValueError("组合权重存在缺失值")

    if (weights < 0).any():
        raise ValueError("组合存在负权重")

    if portfolio["symbol"].duplicated().any():
        raise ValueError("组合存在重复股票")

    equity = float(weights.sum())
    cash = float(report["cash_weight"])

    if abs(equity + cash - 1.0) > 1e-8:
        raise ValueError(
            "组合股票权重与现金权重之和不等于1"
        )

    if abs(
        equity - float(report["actual_equity_weight"])
    ) > 1e-8:
        raise ValueError(
            "CSV股票权重与JSON报告不一致"
        )

    if (
        equity
        > float(report["target_equity_weight"]) + 1e-8
    ):
        raise ValueError("股票仓位超过策略上限")

    if len(portfolio) != int(
        report["selected_stock_count"]
    ):
        raise ValueError("组合股票数量与报告不一致")

    market = read_json(MARKET_FILE)

    if (
        str(report["decision_date"])
        != str(market["latest_date"])
    ):
        raise ValueError(
            "市场状态与组合决策日期不一致，"
            "请重新运行数据与策略模块"
        )

    report_market = report.get("market_state", {})

    for key in ["trend", "volatility_regime"]:
        if report_market.get(key) != market.get(key):
            raise ValueError(
                f"组合与当前市场状态不一致：{key}"
            )

    return {
        "decision_date": report["decision_date"],
        "strategy": report["strategy"],
        "strategy_name": report["strategy_name"],
        "selection_rule": report["selection_rule"],
        "decision_reason": report["decision_reason"],
        "factor_stock_count": report["factor_stock_count"],
        "target_equity_weight": report[
            "target_equity_weight"
        ],
        "actual_equity_weight": equity,
        "cash_weight": cash,
        "holdings": report["holdings"],
        "risk_controls": report["risk_controls"],
        "data_governance": report["data_governance"],
        "limitations": report["limitations"],
        "report_generated_at": report.get("generated_at"),
    }


def get_data_audit():
    """读取复权因子审计摘要和失败记录。"""

    report = read_json(FACTOR_AUDIT_FILE)

    failures = []

    if FAILURE_FILE.exists():
        df = pd.read_csv(
            FAILURE_FILE,
            dtype=str
        ).fillna("")

        failures = df.to_dict(
            orient="records"
        )

    return {
        "candidate_count": report.get("candidate_count"),
        "audited_count": report.get("audited_count"),
        "failed_count": report.get("failed_count"),
        "total_return_difference_events": report.get(
            "total_return_difference_events"
        ),
        "max_abs_momentum_diff": report.get(
            "max_abs_momentum_diff"
        ),
        "max_abs_volatility_diff": report.get(
            "max_abs_volatility_diff"
        ),
        "rank_changed_count": report.get(
            "rank_changed_count"
        ),
        "top5_overlap": report.get("top5_overlap"),
        "top5_changed": report.get("top5_changed"),
        "failures": failures,
        "independent_corporate_action_verified": report.get(
            "independent_corporate_action_verified"
        ),
        "point_in_time_verified": report.get(
            "point_in_time_verified"
        ),
        "approved_for_backtesting": report.get(
            "approved_for_backtesting"
        ),
    }


# 只允许调用以下三个工具
TOOL_FUNCTIONS = {
    "get_market_state": get_market_state,
    "get_portfolio_decision": get_portfolio_decision,
    "get_data_audit": get_data_audit,
}


def call_stock_tool(name):
    if name not in TOOL_FUNCTIONS:
        raise ValueError(
            f"不允许调用的工具：{name}"
        )

    return TOOL_FUNCTIONS[name]()


def main():
    print("=" * 60)
    print("股票Agent V2 - 工具层测试")
    print("=" * 60)

    for name in TOOL_FUNCTIONS:
        print(f"\n测试工具：{name}")

        try:
            result = call_stock_tool(name)
            print(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    indent=2
                )[:1800]
            )
            print("状态：SUCCESS")
        except Exception as e:
            print(
                "状态：FAILED",
                type(e).__name__,
                str(e)
            )


if __name__ == "__main__":
    main()
