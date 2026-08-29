"""从本地 HTML 读取标题、正文和摘要。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from resiliparse.extract.html2text import extract_plain_text
from resiliparse.parse.encoding import detect_encoding
from resiliparse.parse.html import HTMLTree

from .document_registry import DocumentRecord, DocumentRegistry


TEXT_OPTIONS = {
    "preserve_formatting": True,
    "links": False,
    "alt_texts": False,
    "form_fields": False,
    "noscript": False,
    "list_bullets": False,
}


def get_attribute(node, name: str) -> str:
    if node is None:
        return ""
    try:
        return str(node[name]).strip()
    except (KeyError, TypeError, ValueError):
        return ""


def parse_html_bytes(html: bytes) -> HTMLTree:
    encoding = detect_encoding(html) or "utf-8"
    return HTMLTree.parse_from_bytes(html, encoding=encoding)


def extract_title(tree: HTMLTree) -> str:
    for selector in (
        'meta[name="citation_title"]',
        'meta[name="ArticleTitle"]',
        'meta[property="og:title"]',
        'meta[name="title"]',
    ):
        node = tree.document.query_selector(selector)
        title = get_attribute(node, "content")
        if title:
            return title

    heading = tree.document.query_selector("h1")
    if heading is not None and (heading.text or "").strip():
        return heading.text.strip()
    return (tree.title or "").strip()


def clean_text(text: str) -> str:
    """清理行内多余空格，保留段落换行。"""
    lines = []
    for line in str(text or "").splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def extract_text(
    tree: HTMLTree,
    *,
    main_content: bool = False,
    fallback_to_all: bool = False,
) -> str:
    text = extract_plain_text(
        tree,
        main_content=main_content,
        **TEXT_OPTIONS,
    ) or ""
    if fallback_to_all and len(text.strip()) < 100:
        text = extract_plain_text(
            tree,
            main_content=False,
            **TEXT_OPTIONS,
        ) or text
    return clean_text(text)


def extract_headings(tree: HTMLTree) -> str:
    return " ".join(
        (node.text or "").strip()
        for selector in ("h1", "h2", "h3")
        for node in tree.document.query_selector_all(selector)
        if (node.text or "").strip()
    )


def extract_paragraphs(tree: HTMLTree, fallback: str) -> str:
    paragraphs = " ".join(
        (node.text or "").strip()
        for node in tree.document.query_selector_all("p")
        if (node.text or "").strip()
    )
    return paragraphs or re.sub(r"\s+", " ", fallback).strip()


def make_abstract(content: str, max_chars: int = 220) -> str:
    return re.sub(r"\s+", " ", str(content or "")).strip()[:max_chars]


@dataclass(frozen=True)
class PageInfo:
    doc_id: int
    url: str
    html_path: Path
    title: str
    content: str
    abstract: str
    html_title: str
    headings: str
    body: str

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "url": self.url,
            "html_path": str(self.html_path),
            "title": self.title,
            "content": self.content,
            "abstract": self.abstract,
            "snippet": self.abstract,
        }


class PageInfoStore:
    """通过 URL 查询本地网页信息，并缓存已解析页面。"""

    def __init__(self, registry: DocumentRegistry) -> None:
        self.registry = registry
        self._page_cache: dict[str, PageInfo] = {}
        self._search_fields: dict[str, dict] = {}

    def prime_from_chunks(self, chunks: Iterable[dict]) -> None:
        """从已有 chunk 注入轻量搜索字段，避免排序时重读 HTML。"""
        for chunk in chunks:
            url = str(chunk["url"])
            if url in self._search_fields:
                continue
            text = str(chunk.get("text", ""))
            abstract = make_abstract(text)
            self._search_fields[url] = {
                "doc_id": int(chunk["doc_id"]),
                "url": url,
                "title": str(chunk.get("title", "")) or url,
                "abstract": abstract,
                "snippet": abstract,
                "first_chunk": text,
            }

    def _parse_record(self, record: DocumentRecord) -> PageInfo:
        try:
            html = record.html_path.read_bytes()
            tree = parse_html_bytes(html)
            content = extract_text(tree, main_content=False)
            title = extract_title(tree)
            html_title = (tree.title or "").strip()
            headings = extract_headings(tree)
            body = extract_paragraphs(tree, content)
        except (OSError, TypeError, ValueError):
            content = ""
            title = ""
            html_title = ""
            headings = ""
            body = ""

        hint = self._search_fields.get(record.url, {})
        title = title or str(hint.get("title", "")) or record.url
        abstract = make_abstract(content) or str(hint.get("abstract", ""))
        return PageInfo(
            doc_id=record.doc_id,
            url=record.url,
            html_path=record.html_path,
            title=title,
            content=content,
            abstract=abstract,
            html_title=html_title,
            headings=headings,
            body=body,
        )

    def get(self, url: str, *, cache: bool = True) -> PageInfo | None:
        url = str(url)
        cached = self._page_cache.get(url)
        if cached is not None:
            return cached
        record = self.registry.get_by_url(url)
        if record is None:
            return None
        page = self._parse_record(record)
        if cache:
            self._page_cache[url] = page
        return page

    def get_by_doc_id(self, doc_id: int) -> PageInfo | None:
        url = self.registry.get_url(doc_id)
        return self.get(url) if url is not None else None

    def get_page_info(self, url: str) -> dict:
        page = self.get(url)
        return page.to_dict() if page else {}

    def get_title(self, url: str) -> str:
        page = self.get(url)
        return page.title if page else ""

    def get_content(self, url: str) -> str:
        page = self.get(url)
        return page.content if page else ""

    def get_abstract(self, url: str) -> str:
        page = self.get(url)
        return page.abstract if page else ""

    def get_search_fields(self, url: str) -> dict:
        fields = self._search_fields.get(str(url))
        if fields is not None:
            return dict(fields)
        page = self.get(url)
        if page is None:
            return {}
        fields = page.to_dict()
        fields["first_chunk"] = page.content
        return fields

    def get_index_fields(self, url: str) -> tuple[str, str, str]:
        page = self.get(url, cache=False)
        if page is None:
            return "", "", ""
        return page.html_title, page.headings, page.body
