"""统一封装索引加载、结果去重和多样性重排。"""

from bisect import bisect_left
from collections import Counter
import json
from math import log2
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from bs4 import BeautifulSoup
import jieba

from .index import Inverted_index

def get_result_family(url: str) -> str | None:
    """返回需要限制数量的结果族。"""
    parts = urlsplit(url)
    path = parts.path

    if (
        parts.hostname == "gsai.ruc.edu.cn"
        and path.endswith("/addons/video/video/play.html")
    ):
        return "gsai-video-play"

    if (
        parts.hostname == "gsai.ruc.edu.cn"
        and path.endswith("/addons/video/video/cate.html")
    ):
        return "gsai-video-category"

    return None


def canonicalize_url(url: str) -> str:
    """生成仅用于结果去重的规范 URL。"""
    parts = urlsplit(url)
    scheme = parts.scheme.casefold()
    hostname = (parts.hostname or "").casefold()

    port = parts.port
    if port is None:
        netloc = hostname
    elif (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    ):
        netloc = hostname
    else:
        netloc = f"{hostname}:{port}"

    path = re.sub(r"/+", "/", parts.path or "/")
    if path.endswith("/index.html"):
        path = path.removesuffix("/index.html")
    if path != "/":
        path = path.rstrip("/")

    query_params = []
    for name, value in parse_qsl(
        parts.query,
        keep_blank_values=True,
    ):
        is_video_category = (
            hostname == "gsai.ruc.edu.cn"
            and path.endswith("/addons/video/video/cate.html")
        )
        if is_video_category:
            if name == "cate_name":
                continue
            if name == "page" and value == "1":
                continue
        query_params.append((name, value))

    query_params.sort()
    normalized_query = urlencode(query_params, doseq=True)
    return urlunsplit(
        (scheme, netloc, path, normalized_query, "")
    )


def load_page_metadata(path: Path) -> dict[str, dict]:
    """将 JSONL 页面元数据加载为 URL 到记录的映射。"""
    metadata = {}
    with path.open("r", encoding="utf-8") as reader:
        for line in reader:
            record = json.loads(line)
            metadata[record["url"]] = record
    return metadata


def compact_search_text(text: str) -> str:
    """保留适合做子串匹配的中文、英文和数字。"""
    return re.sub(
        r"[^0-9a-z\u4e00-\u9fff]+",
        "",
        str(text or "").casefold(),
    )


class SearchService:
    """供 Web UI 和自动评测共同调用的搜索服务。"""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.page_metadata = load_page_metadata(
            self.project_root
            / "inverted_index"
            / "page_metadata.jsonl"
        )
        self.search_engine = Inverted_index(
            str(
                self.project_root
                / "downloaded_html"
                / "docID.jsonl"
            ),
            str(
                self.project_root
                / "inverted_index"
                / "inverted_index.json"
            ),
            str(self.project_root / "stopwords.txt"),
        )
        self.url_to_doc_id = {
            url: int(doc_id)
            for doc_id, url in self.search_engine.docID2url.items()
        }
        self.url_to_html_path = {}
        doc_id_path = (
            self.project_root
            / "downloaded_html"
            / "docID.jsonl"
        )
        with doc_id_path.open("r", encoding="utf-8") as reader:
            for line in reader:
                record = json.loads(line)

                url = record["url"]
                html_path = Path(record["file"])

                if not html_path.is_absolute():
                    html_path = self.project_root / html_path

                self.url_to_html_path[url] = html_path

    def get_page_info(self, url: str) -> dict:
        """返回一个 URL 的展示元数据。"""
        return self.page_metadata.get(url, {})
    def get_page_content(
        self,
        url: str,
        max_chars: int | None = None,
    ) -> str:
        """读取本地 HTML，返回清洗后的正文。"""
        html_path = self.url_to_html_path.get(url)

        if html_path is None or not html_path.exists():
            return ""

        try:
            html = html_path.read_bytes()
        except OSError:
            return ""

        soup = BeautifulSoup(html, "html.parser")

        # 删除不会作为正文使用的内容
        for node in soup.find_all(
            [
                "script",
                "style",
                "noscript",
                "template",
                "svg",
                "nav",
                "footer",
            ]
        ):
            node.decompose()

        # 优先寻找常见正文容器
        selectors = [
            "article",
            "main",
            ".article-content",
            ".article_content",
            ".detail",
            ".content",
            ".v_news_content",
            ".TRS_Editor",
            ".zi",
        ]

        content_nodes = []

        for selector in selectors:
            content_nodes.extend(soup.select(selector))

        if content_nodes:
            # 选择文字最多的容器，避免选到小型侧边栏
            content_root = max(
                content_nodes,
                key=lambda node: len(
                    node.get_text(" ", strip=True)
                ),
            )
        else:
            content_root = soup.body or soup

        content = content_root.get_text(" ", strip=True)

        # 合并换行、制表符和连续空格
        content = re.sub(r"\s+", " ", content).strip()

        if max_chars is not None:
            content = content[:max_chars]

        return content

    def rerank_candidates(
        self,
        query_text: str,
        candidates: list[str],
    ) -> list[str]:
        """根据标题和摘要中的稀有查询词覆盖率重排候选。"""
        if not query_text or not candidates:
            return candidates

        query_terms = []
        seen_terms = set()
        for term in self.search_engine.normalize_words(
            jieba.lcut_for_search(query_text)
        ):
            compact_term = compact_search_text(term)
            if (
                len(compact_term) < 2
                or term in seen_terms
                or term not in self.search_engine.terms
            ):
                continue
            seen_terms.add(term)
            term_data = self.search_engine.terms[term]
            query_terms.append(
                (
                    compact_term,
                    term_data["idf"],
                    term_data["postings"],
                )
            )

        total_weight = sum(weight for _, weight, _ in query_terms)
        if total_weight <= 0:
            return candidates

        ranked_candidates = []
        for original_rank, url in enumerate(candidates, start=1):
            page_info = self.get_page_info(url)
            title = compact_search_text(
                str(page_info.get("title", ""))
                + " "
                + str(page_info.get("published_date", ""))
            )
            abstract = compact_search_text(page_info.get("abstract", ""))

            title_coverage = sum(
                weight
                for term, weight, _ in query_terms
                if term in title
            ) / total_weight
            abstract_coverage = sum(
                weight
                for term, weight, _ in query_terms
                if term in abstract
            ) / total_weight
            doc_id = self.url_to_doc_id[url]
            document_coverage = sum(
                weight
                for _, weight, postings in query_terms
                if self._posting_contains(postings, doc_id)
            ) / total_weight

            # 保留原始 TF-IDF 次序作为基础信号，同时优先展示标题和
            # 摘要更完整地覆盖查询中稀有词项的页面。
            score = (
                1.0 / log2(original_rank + 1)
                + 1.25 * title_coverage
                + 0.5 * abstract_coverage
                + 1.0 * document_coverage
            )
            ranked_candidates.append((score, -original_rank, url))

        ranked_candidates.sort(reverse=True)
        reranked = [url for _, _, url in ranked_candidates]

        # 页面元数据可能缺失或只有通用站点标题。保护原始前三名，
        # 使其最多下降两位，避免重排因信息不完整而误伤强候选。
        for original_rank, url in reversed(
            list(enumerate(candidates[:3], start=1))
        ):
            current_index = reranked.index(url)
            maximum_index = original_rank + 1
            if current_index > maximum_index:
                reranked.pop(current_index)
                reranked.insert(maximum_index, url)

        return reranked

    @staticmethod
    def _posting_contains(postings: list[dict], doc_id: int) -> bool:
        """利用 postings 的 docID 升序性质执行二分成员检查。"""
        position = bisect_left(
            postings,
            doc_id,
            key=lambda posting: posting["docID"],
        )
        return (
            position < len(postings)
            and postings[position]["docID"] == doc_id
        )

    def search(self, query_text: str | None, k: int = 20) -> list[str]:
        """检索并为任意查询补足 k 个不同 URL。"""
        query_text = str(query_text or "").strip()
        if k <= 0:
            return []

        candidate_count = max(500, k * 25)
        candidates = (
            self.search_engine.query(query_text, k=candidate_count)
            if query_text
            else []
        )
        candidates = self.rerank_candidates(query_text, candidates)

        results = []
        seen_urls = set()
        seen_hashes = set()
        seen_url_keys = set()
        family_counts = Counter()
        family_limits = {
            "gsai-video-play": 2,
            "gsai-video-category": 1,
        }

        def add_candidate(
            url: str,
            enforce_family_limit: bool,
        ) -> bool:
            page_info = self.get_page_info(url)
            content_hash = page_info.get("content_hash")
            url_key = canonicalize_url(url)

            if url in seen_urls:
                return False
            if url_key in seen_url_keys:
                return False
            if content_hash and content_hash in seen_hashes:
                return False

            family = get_result_family(url)
            if family is not None and enforce_family_limit:
                if family_counts[family] >= family_limits[family]:
                    return False

            seen_urls.add(url)
            seen_url_keys.add(url_key)
            if content_hash:
                seen_hashes.add(content_hash)
            if family is not None:
                family_counts[family] += 1
            results.append(url)
            return True

        def add_unique_url(url: str) -> bool:
            """补足阶段只保证 URL 字符串不重复。"""
            if not isinstance(url, str) or url in seen_urls:
                return False
            seen_urls.add(url)
            results.append(url)
            return True

        deferred_candidates = []
        for url in candidates:
            if not add_candidate(url, enforce_family_limit=True):
                deferred_candidates.append(url)
            if len(results) >= k:
                break

        if len(results) < k:
            for url in deferred_candidates:
                add_candidate(url, enforce_family_limit=False)
                if len(results) >= k:
                    break

        # 相关候选经严格去重后仍不足时，允许内容相同但 URL 不同的
        # 候选补位，避免自动评测收到少于 k 条结果。
        if len(results) < k:
            for url in candidates:
                add_unique_url(url)
                if len(results) >= k:
                    break

        # 查询命中文档本身不足 k 条时，从已索引语料中补充其他 URL。
        if len(results) < k:
            for url in self.search_engine.docID2url.values():
                add_unique_url(url)
                if len(results) >= k:
                    break

        return results[:k]
