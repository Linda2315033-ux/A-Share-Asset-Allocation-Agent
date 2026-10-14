
"""
stock_agent_llm_v2.py

股票研究Agent V2
GLM + 只读工具调用 + 可追溯研究报告

模型负责：
- 理解自然语言问题
- 选择工具
- 解释工具结果
- 指出数据局限

模型不负责：
- 修改组合权重
- 执行交易
- 编造行情
- 宣称未验证的历史收益
"""

import json
import os
import tomllib
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from stock_agent_tools import call_stock_tool


BASE_URL = (
    "https://open.bigmodel.cn/api/paas/v4/"
)

MODEL = os.getenv(
    "ZHIPU_MODEL",
    "glm-5.3-flash"
)

OUTPUT_DIR = Path(
    "output/stock_agent_llm_v2"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

MAX_TOOL_ROUNDS = 6


def load_api_key():
    """
    优先读取环境变量。
    其次读取Streamlit secrets.toml。
    """

    for env_name in [
        "ZHIPU_API_KEY",
        "ZHIPUAI_API_KEY",
    ]:
        value = os.getenv(env_name)

        if value:
            return value

    secrets_file = Path(
        ".streamlit/secrets.toml"
    )

    if secrets_file.exists():

        with open(secrets_file, "rb") as f:
            secrets = tomllib.load(f)

        for key in [
            "ZHIPU_API_KEY",
            "ZHIPUAI_API_KEY",
            "API_KEY",
        ]:
            value = secrets.get(key)

            if value:
                return value

        # 兼容部分用户使用的分组结构
        for section in [
            "zhipu", "llm"
        ]:
            group = secrets.get(section, {})

            if isinstance(group, dict):
                for key in [
                    "api_key", "API_KEY"
                ]:
                    if group.get(key):
                        return group[key]

    raise RuntimeError(
        "未找到智谱API Key。"
        "请设置ZHIPU_API_KEY环境变量，"
        "或检查.streamlit/secrets.toml。"
    )


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_market_state",
            "description": (
                "读取沪深300市场状态，包括20日和60日"
                "收益率、波动率、趋势及数据日期。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_decision",
            "description": (
                "读取已经由规则系统计算好的动态股票"
                "组合，包括股票名单、权重、现金比例、"
                "策略理由和风险限制。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_data_audit",
            "description": (
                "读取前复权与未复权数据口径审计结果，"
                "包括差异事件、排名变化、失败股票和"
                "尚未完成的数据验证。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]


SYSTEM_PROMPT = """
你是沪深主板股票资产配置研究智能体。

你必须遵守：

1. 对市场数据、股票名单、权重、审计结果，
   必须调用工具获取，不能编造。
2. 用户要求解释当前配置时，调用市场状态和
   组合工具；涉及数据可靠性时调用审计工具。
3. 组合由确定性Python规则计算。
   你不得擅自修改股票名单或目标权重。
4. 明确区分历史观测、规则判断和未来预测。
5. 不得声称策略已经回测验证。
6. 不得声称已经完成独立公司行为核验。
7. 不得声称这是实盘交易系统。
8. 解释为什么选择当前策略，以及现金仓位
   的风险管理含义。
9. 回答使用中文，表达清楚、专业但易懂。
10. 如果数据不足，明确说明，不要猜测。
11. 这是研究原型，不构成个性化投资建议。
"""


def run_agent(question):

    api_key = load_api_key()

    client = OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
        timeout=90.0,
        max_retries=1,
    )

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": question,
        },
    ]

    tool_log = []
    final_answer = None

    for round_no in range(
        1, MAX_TOOL_ROUNDS + 1
    ):

        print(
            f"\nAgent推理轮次：{round_no}"
        )

        response = (
            client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.2,
            )
        )

        message = response.choices[0].message

        tool_calls = message.tool_calls or []

        if not tool_calls:
            final_answer = (
                message.content or ""
            ).strip()
            break

        messages.append(
            message.model_dump(
                exclude_none=True
            )
        )

        for tool_call in tool_calls:

            name = tool_call.function.name

            print(
                "模型调用工具：",
                name
            )

            try:
                arguments = json.loads(
                    tool_call.function.arguments or "{}"
                )

                if arguments != {}:
                    raise ValueError(
                        "当前工具不接受参数"
                    )

                result = call_stock_tool(
                    name
                )

                tool_log.append({
                    "round": round_no,
                    "tool": name,
                    "status": "SUCCESS",
                    "result": result,
                })

                content = json.dumps(
                    result,
                    ensure_ascii=False,
                    default=str
                )

            except Exception as e:

                error_text = (
                    f"{type(e).__name__}: {e}"
                )

                tool_log.append({
                    "round": round_no,
                    "tool": name,
                    "status": "FAILED",
                    "error": error_text,
                })

                content = json.dumps({
                    "error": error_text
                }, ensure_ascii=False)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": content,
            })

    if final_answer is None:
        final_answer = (
            "已达到工具调用轮次上限，"
            "本次未生成完整分析。"
            "请缩小问题范围后重试。"
        )

    # 对没有实际工具证据的回答进行明确标记
    if not tool_log:
        final_answer = (
            "【提示：本轮模型未调用研究数据工具，"
            "以下内容不能视为已核验的当前配置报告】\n\n"
            + final_answer
        )

    result = {
        "model": MODEL,
        "question": question,
        "answer": final_answer,
        "tool_log": tool_log,
        "generated_at": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
        "research_only": True,
        "approved_for_trading": False,
    }

    report_path = (
        OUTPUT_DIR / "agent_report.json"
    )

    report_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str
        ),
        encoding="utf-8"
    )

    return result


def main():

    print("=" * 66)
    print("沪深主板股票研究Agent V2")
    print("=" * 66)

    question = (
        "请分析当前沪深主板股票组合。"
        "先说明沪深300市场状态，"
        "再解释为什么选择当前策略、"
        "五只股票的权重和现金比例。"
        "最后结合数据审计结果说明"
        "该配置的主要风险和研究局限。"
    )

    print("\n用户问题：")
    print(question)

    result = run_agent(question)

    print("\n" + "=" * 66)
    print("Agent最终回答")
    print("=" * 66)

    print(result["answer"])

    print("\n工具调用记录：")

    for item in result["tool_log"]:
        print(
            item["tool"],
            item["status"]
        )

    print(
        "\n报告已保存：",
        OUTPUT_DIR / "agent_report.json"
    )


if __name__ == "__main__":
    main()
