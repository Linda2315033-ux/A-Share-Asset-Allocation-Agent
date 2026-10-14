
"""
stock_market_state.py

沪深主板股票Agent - 市场状态识别 V1

数据：
    新浪沪深300指数日线（AKShare）

功能：
    1. 下载并缓存指数历史行情
    2. 检查数据质量和日期
    3. 计算20日、60日收益率
    4. 计算20日年化波动率
    5. 根据透明规则识别市场状态
    6. 保存JSON结果

注意：
    仅用于探索性研究。
    尚未进行参数优化和历史回测。
"""

import json
import os
from datetime import datetime
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd


# ==============================
# 一、配置
# ==============================

INDEX_SYMBOL = "sh000300"
INDEX_NAME = "沪深300指数"

DATA_DIR = Path("data/stocks/market")
OUTPUT_DIR = Path("output/stock_market_state")

DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CACHE_FILE = DATA_DIR / "sh000300.csv"
REPORT_FILE = OUTPUT_DIR / "market_state.json"

CACHE_HOURS = 12
MAX_STALE_CALENDAR_DAYS = 10

MOMENTUM_SHORT = 20
MOMENTUM_LONG = 60
VOL_WINDOW = 20

UP_THRESHOLD = 0.05
DOWN_THRESHOLD = -0.05
HIGH_VOL_THRESHOLD = 0.25


# ==============================
# 二、清洗指数行情
# ==============================

def normalize_index_data(raw):

    if raw is None or raw.empty:
        raise ValueError("指数行情为空")

    df = raw.copy()

    required = [
        "date", "open", "high",
        "low", "close", "volume"
    ]

    missing = [
        col for col in required
        if col not in df.columns
    ]

    if missing:
        raise ValueError(
            f"指数行情缺少字段：{missing}"
        )

    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce"
    )

    numeric_cols = [
        "open", "high", "low",
        "close", "volume"
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    if df[required].isna().any().any():
        raise ValueError(
            "指数行情存在缺失值或无效数据"
        )

    if df["date"].duplicated().any():
        raise ValueError(
            "指数行情存在重复日期"
        )

    prices = df[
        ["open", "high", "low", "close"]
    ]

    if (prices <= 0).any().any():
        raise ValueError(
            "指数价格存在非正值"
        )

    if (df["volume"] < 0).any():
        raise ValueError(
            "指数成交量存在负值"
        )

    if not np.isfinite(
        df[numeric_cols].to_numpy(dtype=float)
    ).all():
        raise ValueError(
            "指数行情存在无穷大数据"
        )

    # 检查OHLC价格逻辑
    invalid_ohlc = (
        (df["high"] < df["low"])
        | (df["high"] < df["open"])
        | (df["high"] < df["close"])
        | (df["low"] > df["open"])
        | (df["low"] > df["close"])
    )

    if invalid_ohlc.any():
        raise ValueError(
            "指数行情存在OHLC价格逻辑错误"
        )

    df = (
        df[required]
        .sort_values("date")
        .reset_index(drop=True)
    )

    # 只保留研究期间数据
    df = df[
        df["date"] >= pd.Timestamp("2016-01-04")
    ].reset_index(drop=True)

    if len(df) < 90:
        raise ValueError(
            "指数行情不足90个交易日"
        )

    return df


# ==============================
# 三、指数缓存
# ==============================

def load_index_data(force_refresh=False):

    cached = None

    if CACHE_FILE.exists():

        try:
            cached = normalize_index_data(
                pd.read_csv(CACHE_FILE)
            )
        except Exception as e:
            print("指数缓存无效：", e)

    cache_fresh = False

    if cached is not None:

        age_hours = (
            datetime.now().timestamp()
            - CACHE_FILE.stat().st_mtime
        ) / 3600

        cache_fresh = (
            0 <= age_hours <= CACHE_HOURS
        )

    if (
        cached is not None
        and cache_fresh
        and not force_refresh
    ):
        return cached, "CACHE_HIT"

    print(
        f"正在下载指数行情："
        f"{INDEX_SYMBOL} {INDEX_NAME}"
    )

    try:

        raw = ak.stock_zh_index_daily(
            symbol=INDEX_SYMBOL
        )

        df = normalize_index_data(raw)

        # 防止用旧下载结果覆盖更新的缓存
        if cached is not None:

            cached_last = cached["date"].iloc[-1]
            new_last = df["date"].iloc[-1]

            if new_last < cached_last:
                raise ValueError(
                    "新下载数据比现有缓存更旧"
                )

        tmp_path = CACHE_FILE.with_name(
            CACHE_FILE.name + ".tmp"
        )

        try:

            df.to_csv(
                tmp_path,
                index=False,
                encoding="utf-8-sig",
                date_format="%Y-%m-%d"
            )

            os.replace(
                tmp_path,
                CACHE_FILE
            )

        finally:

            if tmp_path.exists():
                tmp_path.unlink()

        return df, "DOWNLOADED"

    except Exception as e:

        # 有缓存也不能假装刷新成功
        raise RuntimeError(
            "指数数据刷新失败；"
            "为避免旧数据影响新决策，"
            f"本次停止分析。原因：{e}"
        ) from e


# ==============================
# 四、计算市场指标
# ==============================

def calculate_market_metrics(df):

    close = df["close"].astype(float)

    returns = close.pct_change(
        fill_method=None
    )

    ret20 = (
        close.iloc[-1]
        / close.iloc[-21]
        - 1
    )

    ret60 = (
        close.iloc[-1]
        / close.iloc[-61]
        - 1
    )

    vol20 = (
        returns.tail(VOL_WINDOW).std()
        * np.sqrt(252)
    )

    values = [ret20, ret60, vol20]

    if not all(
        np.isfinite(x) for x in values
    ):
        raise ValueError(
            "市场指标出现无效结果"
        )

    return {
        "return_20": float(ret20),
        "return_60": float(ret60),
        "volatility_20": float(vol20),
    }


# ==============================
# 五、识别市场状态
# ==============================

def classify_market(metrics):

    ret20 = metrics["return_20"]
    ret60 = metrics["return_60"]
    vol20 = metrics["volatility_20"]

    if (
        ret60 > UP_THRESHOLD
        and ret20 > 0
    ):
        trend = "UPTREND"

    elif (
        ret60 < DOWN_THRESHOLD
        and ret20 < 0
    ):
        trend = "DOWNTREND"

    else:
        trend = "SIDEWAYS"

    if vol20 > HIGH_VOL_THRESHOLD:
        volatility_regime = (
            "HIGH_VOLATILITY"
        )
    else:
        volatility_regime = (
            "NORMAL_VOLATILITY"
        )

    return trend, volatility_regime


# ==============================
# 六、生成市场状态报告
# ==============================

def get_stock_market_state(
    force_refresh=False
):

    df, cache_status = load_index_data(
        force_refresh=force_refresh
    )

    latest_date = df["date"].iloc[-1].date()

    stale_days = (
        datetime.now().date()
        - latest_date
    ).days

    if (
        stale_days < 0
        or stale_days > MAX_STALE_CALENDAR_DAYS
    ):
        raise ValueError(
            "指数行情日期不符合新鲜度要求："
            f"{latest_date}"
        )

    metrics = calculate_market_metrics(df)

    trend, volatility_regime = (
        classify_market(metrics)
    )

    report = {
        "module": "stock_market_state_v1",
        "index_symbol": INDEX_SYMBOL,
        "index_name": INDEX_NAME,
        "source": "AKShare / Sina",
        "latest_date": str(latest_date),
        "history_rows": len(df),
        "cache_status": cache_status,

        **metrics,

        "trend": trend,
        "volatility_regime": volatility_regime,

        "rules": {
            "up_threshold": UP_THRESHOLD,
            "down_threshold": DOWN_THRESHOLD,
            "high_vol_threshold": HIGH_VOL_THRESHOLD,
            "momentum_short_days": MOMENTUM_SHORT,
            "momentum_long_days": MOMENTUM_LONG,
            "volatility_days": VOL_WINDOW,
        },

        "limitations": [
            "仅使用沪深300指数代表大盘",
            "市场分类阈值尚未经过回测验证",
            "尚未使用A股交易日历验证最新交易日",
            "指数历史行情尚未完成独立来源核验",
            "本模块不直接生成买卖指令",
        ],

        "approved_for_production": False,

        "generated_at": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
    }

    return report


def main():

    print("=" * 65)
    print("沪深主板股票Agent - 市场状态识别 V1")
    print("=" * 65)

    report = get_stock_market_state()

    REPORT_FILE.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        "\n指数：",
        report["index_name"]
    )

    print(
        "数据日期：",
        report["latest_date"]
    )

    print(
        "历史交易日：",
        report["history_rows"]
    )

    print(
        "缓存状态：",
        report["cache_status"]
    )

    print(
        "\n20日收益率：",
        f"{report['return_20']:.2%}"
    )

    print(
        "60日收益率：",
        f"{report['return_60']:.2%}"
    )

    print(
        "20日年化波动率：",
        f"{report['volatility_20']:.2%}"
    )

    print(
        "\n市场趋势：",
        report["trend"]
    )

    print(
        "波动率状态：",
        report["volatility_regime"]
    )

    print(
        "\n输出文件：",
        REPORT_FILE
    )

    print(
        "\n注意：市场状态规则尚未经过"
        "历史回测验证。"
    )


if __name__ == "__main__":
    main()
