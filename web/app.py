"""RUC Search 的 Flask Web 入口。"""

from flask import Flask, render_template, request
from markupsafe import Markup, escape
from pathlib import Path
import re

from ruc_search.offline_model import load_embedding_model
from ruc_search.search_engine import SearchEngine
from info import DocumentRegistry, PageInfoStore
from students_evaluation.rag.search_engine import (
    configure_services,
    rag_answer,
)

project_root = Path(__file__).resolve().parents[1]
doc_id_path = project_root / 'data' / 'docID.jsonl'
chunk_path = project_root / 'data' / 'chunks.jsonl'
embedding_path = project_root / 'data' / 'chunk_embeddings.npy'
model = load_embedding_model()
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
configure_services(search_service, page_info_store)
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


@app.route('/rag', methods=['POST'])
def rag_query():
    question = str(request.form.get('key') or '').strip()
    if not question:
        return render_template(
            'rag.html',
            key='',
            answer='',
            sources=[],
            error='请先输入一个问题。',
        ), 400

    try:
        answer, sources = rag_answer(question)
        error = ''
    except Exception as exc:
        app.logger.exception("RAG 问答失败")
        answer = ''
        sources = []
        if isinstance(exc, RuntimeError) and str(exc).strip():
            # RuntimeError 由本项目主动抛出，只包含缺少 Key、连续空响应等
            # 可安全展示的诊断信息，不应再用笼统提示掩盖真正原因。
            error = f"RAG 生成失败：{str(exc).strip()}"
        else:
            error = (
                f"RAG 生成失败（{type(exc).__name__}）。"
                "请检查模型配置和网络连接，并查看服务端日志。"
            )

    return render_template(
        'rag.html',
        key=question,
        answer=answer,
        sources=sources,
        error=error,
    )

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=12345, debug=True)
