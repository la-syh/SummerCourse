"""RUC Search 的 Flask Web 入口。"""

from flask import Flask, render_template, request
from sentence_transformers import SentenceTransformer
from markupsafe import Markup, escape
from pathlib import Path
import re

from ruc_search.search_engine import SearchEngine
from info import DocumentRegistry, PageInfoStore

project_root = Path(__file__).resolve().parents[1]
doc_id_path = project_root / 'data' / 'docID.jsonl'
chunk_path = project_root / 'data' / 'chunks.jsonl'
embedding_path = project_root / 'data' / 'chunk_embeddings.npy'
MODEL_NAME = "BAAI/bge-small-zh-v1.5"
model = SentenceTransformer(MODEL_NAME, local_files_only=True)
document_registry = DocumentRegistry(project_root, doc_id_path)
page_info_store = PageInfoStore(document_registry)

chunk_tokens = 384
overlap_tokens = 64
search_service = SearchEngine(
    project_root,
    document_registry,
    page_info_store,
    chunk_path,
    embedding_path,
    model,
)
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

    urls = search_service.search(key)

    results = []
    for url in urls:
        page_info = page_info_store.get_search_fields(url)

        results.append(
            {
                "title": page_info.get("title") or url,
                "url": url,
                "abstract": page_info.get("abstract") or "暂无摘要",
            }
        )

    return render_template('res.html', key=key, results=results)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=12345, debug=True)
