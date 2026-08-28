from day4.Inverted_index import Inverted_index
from flask import Flask, render_template, request
from markupsafe import Markup, escape
from collections import Counter
from pathlib import Path
import json
import re
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit,
)

def get_result_family(url: str) -> str | None:
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

    # 去掉默认端口
    port = parts.port
    if port is None:
        netloc = hostname
    elif (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    ):
        netloc = hostname
    else:
        netloc = f"{hostname}:{port}"

    # 合并连续斜杠
    path = re.sub(r"/+", "/", parts.path or "/")

    # /foo/index.html 与 /foo 视为同一地址
    if path.endswith("/index.html"):
        path = path.removesuffix("/index.html")

    # /foo/ 与 /foo 视为同一地址
    if path != "/":
        path = path.rstrip("/")

    query_params = []

    for name, value in parse_qsl(
        parts.query,
        keep_blank_values=True,
    ):
        # 只针对高瓴视频分类页删除显示参数
        is_video_category = (
            hostname == "gsai.ruc.edu.cn"
            and path.endswith("/addons/video/video/cate.html")
        )

        if is_video_category:
            # cate_name 只影响页面显示，不表示不同分类
            if name == "cate_name":
                continue

            # 第一页和未指定页码视为同一页
            if name == "page" and value == "1":
                continue

        query_params.append((name, value))

    # 参数顺序不同也应视为相同 URL
    query_params.sort()
    normalized_query = urlencode(query_params, doseq=True)

    # 丢弃 #fragment
    return urlunsplit(
        (
            scheme,
            netloc,
            path,
            normalized_query,
            "",
        )
    )

PROJECT_ROOT = Path(__file__).resolve().parents[1]
METADATA_PATH = PROJECT_ROOT / "inverted_index" / "page_metadata.jsonl"

def load_page_metadata(path: Path) -> dict[str, dict]:
    metadata = {}

    with path.open("r", encoding="utf-8") as reader:
        for line in reader:
            record = json.loads(line)
            metadata[record["url"]] = record

    return metadata


page_metadata = load_page_metadata(METADATA_PATH)

app = Flask(__name__)


@app.template_filter("highlight")
def highlight_query(text: str, query_text: str) -> Markup:
    """安全地高亮文本中与查询词匹配的部分。"""
    source = str(text or "")
    query_text = str(query_text or "").strip()

    if not query_text:
        return Markup(escape(source))

    terms = sorted(
        {
            term
            for term in re.split(r"\s+", query_text)
            if term
        },
        key=len,
        reverse=True,
    )
    if not terms:
        return Markup(escape(source))

    pattern = re.compile(
        "|".join(re.escape(term) for term in terms),
        flags=re.IGNORECASE,
    )
    highlighted_parts = []
    previous_end = 0

    for match in pattern.finditer(source):
        highlighted_parts.append(
            escape(source[previous_end:match.start()])
        )
        highlighted_parts.append(
            Markup('<mark class="query-highlight">')
            + escape(match.group(0))
            + Markup("</mark>")
        )
        previous_end = match.end()

    highlighted_parts.append(escape(source[previous_end:]))
    return Markup("").join(highlighted_parts)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/query', methods = ['GET'])
def query():
    key = request.args.get('key')

    # Implement your search engine here.
    # Generate a list of search results.
    urls = search(key) if key else []

    results = []
    for url in urls:
        page_info = page_metadata.get(url, {})

        results.append(
            {
                "title": page_info.get("title") or url,
                "url": url,
                "abstract": page_info.get("abstract") or "暂无摘要",
            }
        )

    return render_template('res.html', key=key, results=results)

def title_contains_query(url: str, query_text: str) -> bool:
    title = page_metadata.get(url, {}).get("title", "")
    return query_text.casefold() in title.casefold()

def search(query_text: str, k: int = 20) -> list[str]:
    query_text = query_text.strip()
    if not query_text:
        return []

    candidates = search_engine.query(query_text, k=200)
    # candidates.sort(
    #     key=lambda url: title_contains_query(url, query_text),
    #     reverse=True,
    # )

    results = []
    seen_hashes = set()
    seen_url_keys = set()
    family_counts = Counter()

    family_limits = {
        "gsai-video-play": 2,
        "gsai-video-category": 1,
    }

    for url in candidates:
        page_info = page_metadata.get(url, {})
        content_hash = page_info.get("content_hash")
        url_key = canonicalize_url(url)

        if url_key in seen_url_keys:
            continue
        if content_hash and content_hash in seen_hashes:
            continue
        family = get_result_family(url)
        if family is not None:
            limit = family_limits[family]

            if family_counts[family] >= limit:
                continue

        seen_url_keys.add(url_key)
        if content_hash:
            seen_hashes.add(content_hash)
        if family is not None:
            family_counts[family] += 1

        results.append(url)
        if len(results) == k:
            break

    return results

if __name__ == "__main__":
    docID_path = PROJECT_ROOT / "downloaded_html" / "docID.jsonl"
    index_path = PROJECT_ROOT / "inverted_index" / "inverted_index.json"
    stopwords_path = PROJECT_ROOT / "stopwords.txt"

    search_engine = Inverted_index(
        str(docID_path),
        str(index_path),
        str(stopwords_path),
    )
    app.run(host='0.0.0.0', port=12345, debug=True)
