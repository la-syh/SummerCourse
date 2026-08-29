"""本地网页映射与内容信息的统一数据访问层。"""

from .document_registry import DocumentRecord, DocumentRegistry
from .page_info import PageInfo, PageInfoStore

__all__ = [
    "DocumentRecord",
    "DocumentRegistry",
    "PageInfo",
    "PageInfoStore",
]
