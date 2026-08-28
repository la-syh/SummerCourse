"""原检索（MRR@20）评测接口。"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
project_root_string = str(PROJECT_ROOT)
if project_root_string not in sys.path:
    sys.path.insert(0, project_root_string)

from ruc_search.service import SearchService


search_service = SearchService(PROJECT_ROOT)


def evaluate(query: str) -> list[str]:
    """检索一条查询，并返回前 20 个去重 URL。"""
    return search_service.search(query, k=20)
