"""最小化的大模型调用封装。

本文件使用 OpenAI 兼容接口，因此可连接 OpenAI、DeepSeek 或课程指定的
兼容服务。
"""

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
import os
import time


BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-v4-flash"

def call_model(
    user_prompt: str,
    system_prompt: str = "你是一个严谨的问答助手。",
    timeout: float = 60.0,
    max_tokens: int = 8192,
    attempts: int = 2,
) -> str:
    """调用一次大模型并返回纯文本答案。"""
    if not 1 <= attempts <= 3:
        raise ValueError("attempts 必须在 1 到 3 之间")
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("请先设置环境变量 DEEPSEEK_API_KEY")

    # 按尝试次数分配总预算。RAG 使用 attempts=1，因此在 60 秒评测
    # 限制内可给思考模型约 55 秒，而不是旧实现固定最多 25 秒。
    per_attempt_timeout = max(
        5.0,
        min(55.0, timeout / attempts - 1.0),
    )
    client = OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
        timeout=per_attempt_timeout,
        max_retries=0,
    )

    transient_errors = (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )
    for attempt in range(attempts):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=max_tokens,
                # 为复杂的跨页面事实整合保留思考过程；8192 token 同时
                # 容纳 reasoning_content 和最终可见答案。
                reasoning_effort="low",
                extra_body={"thinking": {"type": "enabled"}},
                stream=False,
            )
            if not response.choices:
                content = ""
                finish_reason = "no_choices"
            else:
                choice = response.choices[0]
                content = choice.message.content or ""
                finish_reason = choice.finish_reason or "unknown"
            if not content.strip():
                if attempt < attempts - 1:
                    time.sleep(0.2)
                    continue
                raise RuntimeError(
                    "大模型连续返回空答案"
                    f"（finish_reason={finish_reason}, max_tokens={max_tokens}）"
                )
            return content.strip()
        except transient_errors:
            if attempt == attempts - 1:
                raise
            time.sleep(1.0)

    raise RuntimeError("大模型调用失败")
