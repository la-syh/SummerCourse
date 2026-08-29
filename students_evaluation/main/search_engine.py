"""原检索（MRR@20）评测接口。"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT_TEXT = str(PROJECT_ROOT)
if PROJECT_ROOT_TEXT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_TEXT)

from ruc_search.offline_model import load_embedding_model
from ruc_search.search_engine import SearchEngine
from info import DocumentRegistry, PageInfoStore


doc_id_path = PROJECT_ROOT / "data" / "docID.jsonl"
chunk_path = PROJECT_ROOT / "data" / "chunks.jsonl"
embedding_path = PROJECT_ROOT / "data" / "chunk_embeddings.npy"
model = load_embedding_model()
document_registry = DocumentRegistry(PROJECT_ROOT, doc_id_path)
page_info_store = PageInfoStore(document_registry)

chunk_tokens = 384
overlap_tokens = 64
search_service = SearchEngine(
    PROJECT_ROOT,
    document_registry,
    page_info_store,
    chunk_path,
    embedding_path,
    model,
)


def evaluate(query: str) -> list[str]:
    """检索一条查询，并返回前 20 个去重 URL。"""
    return search_service.search(query, topk=20)
