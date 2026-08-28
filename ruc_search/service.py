"""统一封装索引加载、结果去重和多样性重排。"""

from collections import Counter
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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

    def get_page_info(self, url: str) -> dict:
        """返回一个 URL 的展示元数据。"""
        return self.page_metadata.get(url, {})

    def search(self, query_text: str, k: int = 20) -> list[str]:
        """检索、去重并返回最多 k 个 URL。"""
        query_text = query_text.strip()
        if not query_text or k <= 0:
            return []

        candidate_count = max(500, k * 25)
        candidates = self.search_engine.query(
            query_text,
            k=candidate_count,
        )

        results = []
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

            if url_key in seen_url_keys:
                return False
            if content_hash and content_hash in seen_hashes:
                return False

            family = get_result_family(url)
            if family is not None and enforce_family_limit:
                if family_counts[family] >= family_limits[family]:
                    return False

            seen_url_keys.add(url_key)
            if content_hash:
                seen_hashes.add(content_hash)
            if family is not None:
                family_counts[family] += 1
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

        return results
