"""``docID``、URL 和本地 HTML 路径的唯一映射入口。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class DocumentRecord:
    """一篇已保存网页的稳定标识与本地位置。"""

    doc_id: int
    url: str
    html_path: Path


class DocumentRegistry:
    """加载并维护 ``data/docID.jsonl`` 中的文档映射。"""

    def __init__(self, project_root: Path, mapping_path: Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.mapping_path = Path(mapping_path)
        if not self.mapping_path.is_absolute():
            self.mapping_path = self.project_root / self.mapping_path

        self._records: list[DocumentRecord] = []
        self._by_doc_id: dict[int, DocumentRecord] = {}
        self._by_url: dict[str, DocumentRecord] = {}
        self._load()

    def _resolve_html_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        return path if path.is_absolute() else self.project_root / path

    def _load(self) -> None:
        if not self.mapping_path.exists():
            return

        with self.mapping_path.open(encoding="utf-8") as reader:
            for line_number, line in enumerate(reader, start=1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    record = DocumentRecord(
                        doc_id=int(raw["docID"]),
                        url=str(raw["url"]),
                        html_path=self._resolve_html_path(raw["file"]),
                    )
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError(
                        f"{self.mapping_path}:{line_number} 不是有效文档记录"
                    ) from error

                self._records.append(record)
                self._by_doc_id[record.doc_id] = record
                self._by_url[record.url] = record

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[DocumentRecord]:
        return iter(self._records)

    @property
    def next_doc_id(self) -> int:
        return len(self._records)

    def records(self) -> tuple[DocumentRecord, ...]:
        return tuple(self._records)

    def urls(self) -> list[str]:
        return [record.url for record in self._records]

    def get_by_doc_id(self, doc_id: int) -> DocumentRecord | None:
        return self._by_doc_id.get(int(doc_id))

    def get_by_url(self, url: str) -> DocumentRecord | None:
        return self._by_url.get(str(url))

    def get_url(self, doc_id: int) -> str | None:
        record = self.get_by_doc_id(doc_id)
        return record.url if record else None

    def get_html_path_by_doc_id(self, doc_id: int) -> Path | None:
        record = self.get_by_doc_id(doc_id)
        return record.html_path if record else None

    def get_html_path_by_url(self, url: str) -> Path | None:
        record = self.get_by_url(url)
        return record.html_path if record else None

    def add(self, url: str, html_path: Path) -> DocumentRecord:
        """持久化新映射；已存在的 URL 直接返回原记录。"""
        url = str(url)
        existing = self._by_url.get(url)
        if existing is not None:
            return existing

        resolved_path = self._resolve_html_path(html_path)
        try:
            stored_path = resolved_path.relative_to(self.project_root).as_posix()
        except ValueError:
            stored_path = resolved_path.as_posix()

        record = DocumentRecord(
            doc_id=self.next_doc_id,
            url=url,
            html_path=resolved_path,
        )
        raw = {
            "docID": record.doc_id,
            "url": record.url,
            "file": stored_path,
        }
        self.mapping_path.parent.mkdir(parents=True, exist_ok=True)
        with self.mapping_path.open("a", encoding="utf-8") as writer:
            writer.write(json.dumps(raw, ensure_ascii=False) + "\n")

        self._records.append(record)
        self._by_doc_id[record.doc_id] = record
        self._by_url[record.url] = record
        return record
