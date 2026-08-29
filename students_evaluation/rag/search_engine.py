"""独立的学生 RAG 检索与问答接口。"""

from typing import TypedDict

import jieba

if __package__:
    from .agentic_rag import run_agentic_rag
    from .call_model import call_model
else:
    from agentic_rag import run_agentic_rag
    from call_model import call_model

from pathlib import Path
import sys, re


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT_TEXT = str(PROJECT_ROOT)
if PROJECT_ROOT_TEXT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_TEXT)

from ruc_search.offline_model import load_embedding_model
from ruc_search.search_engine import SearchEngine
from info import DocumentRegistry, PageInfoStore


search_service: SearchEngine | None = None
page_info_store: PageInfoStore | None = None


def configure_services(
    service: SearchEngine,
    pages: PageInfoStore,
) -> None:
    """注入已有检索服务，避免 Web 重复加载模型与索引。"""
    global search_service, page_info_store
    search_service = service
    page_info_store = pages


def get_services() -> tuple[SearchEngine, PageInfoStore]:
    """返回已注入的服务；独立评测时才延迟创建默认实例。"""
    global search_service, page_info_store
    if search_service is None or page_info_store is None:
        doc_id_path = PROJECT_ROOT / "data" / "docID.jsonl"
        chunk_path = PROJECT_ROOT / "data" / "chunks.jsonl"
        embedding_path = PROJECT_ROOT / "data" / "chunk_embeddings.npy"
        model = load_embedding_model()
        document_registry = DocumentRegistry(PROJECT_ROOT, doc_id_path)
        page_info_store = PageInfoStore(document_registry)
        search_service = SearchEngine(
            PROJECT_ROOT,
            document_registry,
            page_info_store,
            chunk_path,
            embedding_path,
            model,
        )
    return search_service, page_info_store


class SearchResult(TypedDict, total=False):
    """一条检索结果。url 必填，其余字段可按自己的搜索引擎能力提供。"""

    url: str
    title: str
    snippet: str
    content: str
    matched_query: str


def search(query: str, top_k: int = 20) -> list[SearchResult]:
    """检索接口：请替换为自己的搜索引擎。

    返回值按相关性从高到低排列。RAG 推荐至少提供 ``snippet``；如果已经
    保存了网页正文，也可以提供 ``content``。

    示例：
        return [{
            "url": "https://example.com/a",
            "title": "页面标题",
            "snippet": "与查询有关的网页摘要",
            "content": "可选的网页正文",
        }]
    """
    service, pages = get_services()
    urls = service.search(query, topk=top_k)
    results = []
    for url in urls:
        page_info = pages.get_page_info(url)

        results.append(SearchResult(
            {
                "title": page_info.get("title") or url,
                "url": url,
                "snippet": page_info.get("abstract") or "暂无摘要",
                "content": page_info.get("content", ""),
            })
        )
    return results


def extract_query_terms(query: str, limit: int = 12) -> list[str]:
    """选出适合正文片段匹配的高信息量查询词。"""
    service, _ = get_services()
    weighted_terms = []
    seen = set()
    for term in service.lexical_index.normalize_words(
        jieba.lcut_for_search(query)
    ):
        normalized = term.strip().casefold()
        if (
            len(normalized) < 2
            or normalized in seen
            or normalized not in service.lexical_index.terms
        ):
            continue
        seen.add(normalized)
        idf = service.lexical_index.terms[normalized]["idf"]
        weighted_terms.append((idf, normalized))

    weighted_terms.sort(reverse=True)
    return [term for _, term in weighted_terms[:limit]]


def build_search_queries(query: str) -> list[str]:
    """将多条件问题拆成实体、栏目、年份或公司的短查询。"""
    query = clean_content(query)
    queries = []

    quoted = re.findall(r'[“"]([^”"]+)[”"]', query)
    teachers = []
    for name in re.findall(r"([\u4e00-\u9fff]{2,3})老师", query):
        if len(name) == 3 and name[0] in "和与及同":
            name = name[1:]
        if name not in teachers:
            teachers.append(name)

    course_anchor = "教授课程" if "教授课程" in query else "课程"
    for teacher in teachers:
        parts = [teacher, *quoted]
        if course_anchor not in parts:
            parts.append(course_anchor)
        queries.append(" ".join(parts))

    years = list(dict.fromkeys(re.findall(r"(?:19|20)\d{2}", query)))
    rare_terms = extract_query_terms(query, limit=10)

    # 多年份问题必须逐年召回，避免一条混合 query 只命中其中某一年。
    if len(years) >= 2:
        year_anchors = [
            term
            for term in rare_terms
            if term not in years
            and term not in {"比较", "分别", "年份", "年度", "排序"}
        ][:4]
        for year in years:
            queries.append(" ".join([year, *year_anchors]))

    if "夏令营" in query:
        for year in years:
            queries.append(f"{year} 高瓴人工智能学院 夏令营")

    if "参访" in query:
        # 列举多个公司的问法通常只在最后一个名称后写“公司”。直接截取
        # “公司”前的字符会把“快手和腾讯”误识别为一个实体，因此利用
        # 高 IDF 查询词为每个候选实体分别召回。
        generic_terms = {
            "按照", "参访", "企业", "活动", "公司", "排序", "顺序",
            "站次", "第几站", "进行", "分别", "高瓴", "人工智能学院",
        }
        entity_terms = [
            term
            for term in rare_terms
            if term not in generic_terms
            and term not in years
            and not term.isdigit()
            and 2 <= len(term) <= 8
        ][:5]
        for entity in entity_terms:
            queries.append(f"{entity} 公司 企业参访")

    if "科技新星" in query:
        queries.append("高瓴人工智能学院 2024 北京市科技新星计划 入选教师")

    if rare_terms:
        queries.append(" ".join(rare_terms[:8]))
    queries.append(query)
    return list(dict.fromkeys(item for item in queries if item))[:8]


def multi_search(query: str, top_k: int = 5) -> list[SearchResult]:
    """执行多个短查询，按查询轮流合并并去除重复 URL。"""
    search_queries = build_search_queries(query)
    result_groups = []
    for search_query in search_queries:
        group = []
        for result in search(search_query, top_k=top_k):
            group.append(
                SearchResult({**result, "matched_query": search_query})
            )
        result_groups.append(group)

    results = []
    seen_urls = set()
    result_limit = max(10, top_k * 4)
    maximum_length = max(map(len, result_groups), default=0)
    for rank in range(maximum_length):
        for group in result_groups:
            if rank >= len(group):
                continue
            result = group[rank]
            url = result.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(result)
            if len(results) >= result_limit:
                break
        if len(results) >= result_limit:
            break

    # 二跳检索：先从指定年份的入选报道标题识别教师，再检索主页课程。
    if "个人主页" in query and "入选" in query:
        target_years = set(re.findall(r"(?:19|20)\d{2}", query))
        discovered_names = []
        for result in results:
            title = clean_content(result.get("title", ""))
            if target_years and not any(year in title for year in target_years):
                continue
            match = re.search(
                r"(?:我院)?([\u4e00-\u9fff]{2,3})(?:老师|副教授)?入选",
                title,
            )
            if match and match.group(1) not in discovered_names:
                discovered_names.append(match.group(1))

        second_hop_results = []
        for name in discovered_names:
            for result in search(f"{name} 教授课程", top_k=top_k):
                url = result.get('url', '')
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                second_hop_results.append(result)

        if second_hop_results:
            results = results[:5] + second_hop_results + results[5:]

    return results[:result_limit]


def snippet_merge(
    results: list[SearchResult],
    max_chars: int = 12_000,
) -> str:
    """snippet 整合接口：清洗、去重并组织搜索摘要。

    TODO: 读取 ``title``、``snippet``，去重后组织为上下文字符串。
    当前空实现便于同学逐步补充，不会影响未完成代码的调试启动。
    """
    del results, max_chars
    return ""

def clean_content(text: str) -> str:
    """清理正文中的连续空白。"""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def deduplicate_sentences(text: str) -> str:
    """按句子去除页面中重复的导航或正文。"""
    sentences = re.split(
        r"(?<=[。！？!?；;])\s*",
        text,
    )

    result = []
    seen = set()

    for sentence in sentences:
        sentence = clean_content(sentence)

        if not sentence:
            continue

        key = re.sub(
            r"\s+",
            "",
            sentence.casefold(),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(sentence)

    return "\n".join(result)

def full_merge(
    results: list[SearchResult],
    max_chars: int = 12_000,
) -> str:
    """full 整合接口：读取网页或本地文档正文后组织上下文。

    TODO: 自行实现正文读取、HTML 清洗、分块、截断和异常处理。
    """
    """合并多个页面的正文，并控制总字符数。"""
    if not results or max_chars <= 0:
        return ""

    pages = []
    seen_urls = set()
    seen_contents = set()

    for result in results:
        url = clean_content(result.get("url", ""))

        if not url or url in seen_urls:
            continue

        seen_urls.add(url)

        title = clean_content(
            result.get("title", "")
        )
        matched_query = clean_content(
            result.get("matched_query", "")
        )

        content = clean_content(
            result.get("content", "")
        )

        # 正文不存在时退回摘要
        if not content:
            content = clean_content(
                result.get("snippet", "")
            )

        if not content:
            continue

        content = deduplicate_sentences(content)

        # 防止内容相同的不同 URL 重复进入上下文
        content_key = re.sub(
            r"\s+",
            "",
            content.casefold(),
        )

        if content_key in seen_contents:
            continue

        seen_contents.add(content_key)

        pages.append({
            "url": url,
            "title": title or url,
            "matched_query": matched_query,
            "content": content,
        })

    if not pages:
        return ""

    merged_parts = []
    used_chars = 0

    for index, page in enumerate(pages, start=1):
        remaining_chars = max_chars - used_chars
        remaining_pages = len(pages) - index + 1

        if remaining_chars <= 0:
            break

        header = (
            f"[资料{index}]\n"
            f"标题：{page['title']}\n"
            f"URL：{page['url']}\n"
        )
        if page["matched_query"]:
            header += f"命中检索词：{page['matched_query']}\n"
        header += "正文："

        # 给后面的页面预留空间，防止第一篇占满上下文
        page_budget = (
            remaining_chars // remaining_pages
            - len(header)
            - 2
        )

        if page_budget <= 0:
            continue

        content = page["content"][:page_budget]

        part = header + content
        merged_parts.append(part)
        used_chars += len(part) + 2

    context = "\n\n".join(merged_parts)
    return context[:max_chars]

def custom_integrator(
    results: list[SearchResult],
    query: str = "",
    max_chars: int = 12_000,
) -> str:
    """按查询词覆盖率选择正文片段，再合并多个页面。"""
    if not results or max_chars <= 0:
        return ""

    selected_results = results[:10]
    terms = extract_query_terms(query)
    per_page_budget = max(700, max_chars // len(selected_results) - 180)
    prepared = []

    for result in selected_results:
        content = clean_content(
            result.get("content", "") or result.get("snippet", "")
        )
        if not content:
            continue

        chunk_size = 650
        step = 500
        chunks = [
            content[start:start + chunk_size]
            for start in range(0, len(content), step)
        ]
        scored_chunks = []
        for index, chunk in enumerate(chunks):
            score = sum(
                (len(term) + 1) * chunk.casefold().count(term)
                for term in terms
            )
            scored_chunks.append((score, -index, chunk))

        scored_chunks.sort(reverse=True)
        chosen = []
        used = 0
        for _, _, chunk in scored_chunks:
            if used >= per_page_budget:
                break
            remaining = per_page_budget - used
            chosen.append(chunk[:remaining])
            used += min(len(chunk), remaining)

        prepared.append(
            SearchResult(
                {
                    **result,
                    "content": "\n".join(chosen),
                }
            )
        )

    return full_merge(prepared, max_chars=max_chars)


def integrate_information(
    results: list[SearchResult],
    strategy: str = "snippet",
    query: str = "",
    max_chars: int = 12_000,
) -> str:
    """只负责按 strategy 分发到三种信息整合接口。"""
    if strategy == "snippet":
        return snippet_merge(results, max_chars=max_chars)
    if strategy == "full":
        return full_merge(results, max_chars=max_chars)
    if strategy == "custom":
        return custom_integrator(
            results,
            query=query,
            max_chars=max_chars,
        )
    raise ValueError("strategy 必须是 snippet、full 或 custom")


def rag_answer(
    query: str,
    top_k: int = 5,
    strategy: str = "custom",
    max_rounds: int = 3,
) -> tuple[str, list[SearchResult]]:
    """最多执行三轮迭代检索，并返回答案及实际使用的候选来源。"""
    answer, sources = run_agentic_rag(
        query,
        multi_search,
        integrate_information,
        call_model,
        top_k=top_k,
        strategy=strategy,
        max_rounds=max_rounds,
    )
    return answer, sources


def rag_evaluate(
    query: str,
    top_k: int = 5,
    strategy: str = "custom",
    max_rounds: int = 3,
) -> str:
    """评测接口：对一条查询只返回答案字符串。"""
    answer, _ = rag_answer(
        query,
        top_k=top_k,
        strategy=strategy,
        max_rounds=max_rounds,
    )
    return answer
