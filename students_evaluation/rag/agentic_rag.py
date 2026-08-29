"""最多三轮的迭代检索控制器。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, TypedDict


class SearchResult(TypedDict, total=False):
    url: str
    title: str
    snippet: str
    content: str
    matched_query: str


class AgentDecision(TypedDict):
    action: str
    value: str


SearchFunction = Callable[..., list[SearchResult]]
IntegrateFunction = Callable[..., str]
ModelFunction = Callable[..., str]


ANSWER_RULES = """回答要求：
1. 只回答事实本身，不要输出分析过程；
2. 涉及计数、实体或日期时给出明确结果；
3. 先识别问题要求的答案类型和输出对象。排序问题要区分被排序的对象和排序依据，输出问题明确要求的对象；
4. 问题要求共同项或交集时，分别读取每个对象的材料，再求交集；
5. 问题涉及报道中的人物及其主页时，将报道和主页材料关联起来；
6. 证据可能分散在不同资料中，必须综合所有资料；
7. 同一对象出现多条记录时，依据年份、活动名称、系列和其他限定条件消歧；
8. 只有必需实体确实没有任何证据时才回答“材料不足”，不得使用材料之外的知识猜测；
9. 无论材料是否充分都必须返回非空字符串。"""


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", str(query or "")).strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """从纯 JSON 或 Markdown 代码围栏中读取一个对象。"""
    cleaned = str(text or "").strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced:
        cleaned = fenced.group(1).strip()

    try:
        value = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(cleaned[start:end + 1])
        except (json.JSONDecodeError, TypeError):
            return None

    return value if isinstance(value, dict) else None


def _parse_decision(text: str) -> AgentDecision | None:
    value = _extract_json_object(text)
    if value is None:
        return None

    action = str(value.get("action") or "").strip().casefold()
    if action == "search":
        query = _normalize_query(value.get("query", ""))
        if query:
            return AgentDecision(action="search", value=query[:160])
    elif action == "answer":
        answer = str(value.get("answer") or "").strip()
        if answer:
            return AgentDecision(action="answer", value=answer)
    return None


def _interleave_rounds(
    result_rounds: list[list[SearchResult]],
) -> list[SearchResult]:
    """让各轮结果交错出现，避免第一轮占满上下文。"""
    if not result_rounds:
        return []

    ordered = []
    seen_urls = set()
    maximum_length = max(map(len, result_rounds), default=0)
    for index in range(maximum_length):
        for results in reversed(result_rounds):
            if index >= len(results):
                continue
            result = results[index]
            url = str(result.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            ordered.append(result)
    return ordered


def _decision_prompt(
    question: str,
    current_query: str,
    searched_queries: list[str],
    context: str,
) -> str:
    queries = "\n".join(f"- {item}" for item in searched_queries)
    return f"""你在控制一个本地网页搜索引擎。请判断当前证据能否回答原问题。

原问题：{question}
本轮检索词：{current_query}
已经使用的检索词：
{queries}

检索材料：
{context or "（本轮没有获得有效材料）"}

如果证据已经充分，只输出：
{{"action":"answer","answer":"最终答案"}}

如果证据不充分，只输出：
{{"action":"search","query":"下一条简短、具体的检索词"}}

下一条检索词必须服务于原问题，一次只补充一个缺失的实体、年份或关系；保留原问题中的活动系列、年份等消歧条件，并且不得重复已经使用的检索词。不要输出 Markdown 或其他文字。

{ANSWER_RULES}"""


def _answer_prompt(question: str, context: str) -> str:
    return f"""请仅依据检索材料回答原问题。

原问题：{question}

检索材料：
{context or "（没有获得有效材料）"}

{ANSWER_RULES}

直接输出最终答案，不要输出 JSON、分析过程或检索建议。"""


def run_agentic_rag(
    question: str,
    search_fn: SearchFunction,
    integrate_fn: IntegrateFunction,
    model_fn: ModelFunction,
    *,
    top_k: int = 5,
    strategy: str = "custom",
    max_rounds: int = 3,
) -> tuple[str, list[SearchResult]]:
    """迭代检索并回答；每轮至多调用一次模型。"""
    question = _normalize_query(question)
    if not question:
        return "请提供问题", []
    if not 1 <= max_rounds <= 3:
        raise ValueError("max_rounds 必须在 1 到 3 之间")

    result_rounds: list[list[SearchResult]] = []
    searched_queries: list[str] = []
    searched_query_keys = set()
    current_query = question
    force_answer = max_rounds == 1
    per_call_timeout = max(10.0, 54.0 / max_rounds)

    for round_index in range(max_rounds):
        query_key = current_query.casefold()
        if query_key not in searched_query_keys:
            searched_query_keys.add(query_key)
            searched_queries.append(current_query)
            result_rounds.append(search_fn(current_query, top_k=top_k))

        ordered_results = _interleave_rounds(result_rounds)
        context = integrate_fn(
            ordered_results,
            strategy=strategy,
            query=question,
        )

        is_last_round = round_index == max_rounds - 1
        if force_answer or is_last_round:
            if not context:
                return "材料不足", ordered_results[:10]
            raw_answer = model_fn(
                user_prompt=_answer_prompt(question, context),
                system_prompt="你是一个只能依据检索材料回答问题的 RAG 助手。",
                timeout=per_call_timeout,
                max_tokens=2048,
            ).strip()
            decision = _parse_decision(raw_answer)
            if decision and decision["action"] == "answer":
                raw_answer = decision["value"]
            return raw_answer or "材料不足", ordered_results[:10]

        try:
            raw_decision = model_fn(
                user_prompt=_decision_prompt(
                    question,
                    current_query,
                    searched_queries,
                    context,
                ),
                system_prompt="你是一个严格输出 JSON 的迭代检索控制器。",
                timeout=per_call_timeout,
                # 推理模型可能先消耗一部分输出 token，256 容易没有最终内容。
                max_tokens=1024,
            ).strip()
        except RuntimeError as exc:
            if "空答案" not in str(exc):
                raise
            # 控制器没有给出决策时，下一轮直接使用现有证据回答。
            force_answer = True
            continue
        decision = _parse_decision(raw_decision)

        # 某些模型会忽略 JSON 要求而直接给出答案，此时接受非空自然语言。
        if decision is None:
            if raw_decision and not raw_decision.lstrip().startswith("{"):
                return raw_decision, ordered_results[:10]
            force_answer = True
            continue

        if decision["action"] == "answer":
            return decision["value"], ordered_results[:10]

        next_query = decision["value"]
        if next_query.casefold() in searched_query_keys:
            force_answer = True
        else:
            current_query = next_query

    return "材料不足", _interleave_rounds(result_rounds)[:10]
