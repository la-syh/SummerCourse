"""融合字段加权词法检索与 chunk embedding 的搜索引擎。"""

from __future__ import annotations

from bisect import bisect_left
from math import log2
from pathlib import Path
import re

import jieba
import numpy as np

from info import DocumentRegistry, PageInfoStore

from .embedding_builder import Embeddings
from .lexical_index import LexicalIndex
from .offline_model import SentenceTransformer


def compact_search_text(text: str) -> str:
    """保留适合中文、英文和数字子串匹配的字符。"""
    return re.sub(
        r"[^0-9a-z\u4e00-\u9fff]+",
        "",
        str(text or "").casefold(),
    )


def extract_full_dates(text: str) -> set[str]:
    """将常见完整日期统一为 YYYYMMDD，用于日期精确匹配。"""
    dates = set()
    pattern = re.compile(
        r"(?<!\d)(\d{4})\s*[年./-]\s*(\d{1,2})\s*[月./-]"
        r"\s*(\d{1,2})\s*日?"
    )
    for year, month, day in pattern.findall(str(text or "")):
        dates.add(f"{int(year):04d}{int(month):02d}{int(day):02d}")
    return dates


class SearchEngine:
    """以词法精排为主、向量召回为辅的文档级混合检索。"""

    QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
    CANDIDATE_COUNT = 500
    SEMANTIC_WEIGHT = 0.06

    def __init__(
        self,
        project_root: Path,
        document_registry: DocumentRegistry,
        page_info_store: PageInfoStore,
        chunk_path: Path,
        embedding_path: Path,
        model: SentenceTransformer,
        chunk_tokens: int = 384,
        overlap_tokens: int = 64,
    ) -> None:
        self.project_root = Path(project_root)
        self.document_registry = document_registry
        self.page_info_store = page_info_store
        self.chunk_path = Path(chunk_path)
        self.embedding_path = Path(embedding_path)
        self.model = model
        self.chunk_tokens = chunk_tokens
        self.overlap_tokens = overlap_tokens

        self.data = Embeddings(
            self.document_registry,
            self.page_info_store,
            self.chunk_path,
            self.embedding_path,
            self.model,
            self.chunk_tokens,
            self.overlap_tokens,
            remake=False,
        )
        self.page_info_store.prime_from_chunks(self.data.all_chunks)
        self.lexical_index = LexicalIndex(
            document_registry=self.document_registry,
            page_info_store=self.page_info_store,
            index_path=self.project_root / "data" / "lexical_index.json",
            stopwords_path=self.project_root / "stopwords.txt",
        )

        self.chunk_doc_ids = np.fromiter(
            (int(chunk["doc_id"]) for chunk in self.data.all_chunks),
            dtype=np.int32,
            count=len(self.data.all_chunks),
        )
        self.document_count = self.lexical_index.document_count

        # 分词词典的首次加载可能需要约 200ms，不应计入第一条查询。
        jieba.initialize()

    @staticmethod
    def _posting_contains(postings: list[list[int]], doc_id: int) -> bool:
        position = bisect_left(
            postings,
            doc_id,
            key=lambda posting: posting[0],
        )
        return (
            position < len(postings)
            and postings[position][0] == doc_id
        )

    def _query_terms(self, text: str) -> list[tuple[str, float, list]]:
        terms = []
        seen = set()
        for term in self.lexical_index.normalize_words(
            jieba.lcut_for_search(text)
        ):
            compact_term = compact_search_text(term)
            term_data = self.lexical_index.terms.get(term)
            if (
                len(compact_term) < 2
                or term in seen
                or term_data is None
            ):
                continue
            seen.add(term)
            terms.append(
                (
                    compact_term,
                    float(term_data["idf"]),
                    term_data["postings"],
                )
            )
        return terms

    def _dense_document_scores(self, text: str) -> np.ndarray:
        query_embedding = self.model.encode(
            self.QUERY_PREFIX + text,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        chunk_scores = self.data.embeddings @ query_embedding
        document_scores = np.full(
            self.document_count,
            -np.inf,
            dtype=np.float32,
        )
        np.maximum.at(document_scores, self.chunk_doc_ids, chunk_scores)
        return document_scores

    def _lexical_ranking(
        self,
        text: str,
        method: str,
    ) -> list[str]:
        rows = self.lexical_index.search_with_scores(
            text,
            topk=self.CANDIDATE_COUNT,
            method=method,
        )
        return [
            url
            for doc_id, _ in rows
            if (url := self.document_registry.get_url(doc_id)) is not None
        ]

    def _embedding_ranking(self, text: str) -> list[str]:
        dense_scores = self._dense_document_scores(text)
        doc_ids = np.argsort(-dense_scores)
        return [
            url
            for doc_id in doc_ids
            if np.isfinite(dense_scores[int(doc_id)])
            and (
                url := self.document_registry.get_url(int(doc_id))
            ) is not None
        ]

    def _hybrid_ranking(
        self,
        text: str,
        lexical_method: str = "bm25",
    ) -> list[str]:
        lexical_rows = self.lexical_index.search_with_scores(
            text,
            topk=self.CANDIDATE_COUNT,
            method=lexical_method,
        )
        lexical_rank = {
            doc_id: rank
            for rank, (doc_id, _) in enumerate(lexical_rows, start=1)
        }

        dense_scores = self._dense_document_scores(text)
        dense_doc_ids = np.argsort(-dense_scores)[: self.CANDIDATE_COUNT]
        dense_rank = {
            int(doc_id): rank
            for rank, doc_id in enumerate(dense_doc_ids, start=1)
            if np.isfinite(dense_scores[int(doc_id)])
        }

        candidate_doc_ids = list(lexical_rank)
        candidate_doc_ids.extend(
            doc_id
            for doc_id in dense_rank
            if doc_id not in lexical_rank
        )
        if not lexical_rows:
            return [
                url
                for doc_id in candidate_doc_ids
                if (url := self.document_registry.get_url(doc_id)) is not None
            ]

        query_terms = self._query_terms(text)
        total_term_weight = sum(weight for _, weight, _ in query_terms)
        compact_query = compact_search_text(text)
        query_dates = extract_full_dates(text)

        finite_dense_scores = dense_scores[dense_doc_ids]
        finite_dense_scores = finite_dense_scores[
            np.isfinite(finite_dense_scores)
        ]
        dense_ceiling = (
            float(finite_dense_scores[0])
            if len(finite_dense_scores)
            else 0.0
        )
        dense_floor = (
            float(finite_dense_scores[-1])
            if len(finite_dense_scores)
            else dense_ceiling
        )
        dense_range = max(dense_ceiling - dense_floor, 1e-9)

        ranked = []
        for doc_id in candidate_doc_ids:
            url = self.document_registry.get_url(doc_id)
            if url is None:
                continue
            page_info = self.page_info_store.get_search_fields(url)
            title = compact_search_text(page_info.get("title", ""))
            first_chunk = compact_search_text(
                page_info.get("first_chunk", "")
            )

            if total_term_weight > 0:
                title_coverage = sum(
                    weight
                    for term, weight, _ in query_terms
                    if term in title
                ) / total_term_weight
                chunk_coverage = sum(
                    weight
                    for term, weight, _ in query_terms
                    if term in first_chunk
                ) / total_term_weight
                document_coverage = sum(
                    weight
                    for _, weight, postings in query_terms
                    if self._posting_contains(postings, doc_id)
                ) / total_term_weight
            else:
                title_coverage = 0.0
                chunk_coverage = 0.0
                document_coverage = 0.0

            original_rank = lexical_rank.get(doc_id)
            lexical_position_score = (
                1.0 / log2(original_rank + 1)
                if original_rank is not None
                else 0.0
            )
            semantic_score = max(
                0.0,
                (float(dense_scores[doc_id]) - dense_floor) / dense_range,
            )
            exact_title_bonus = (
                0.25
                if compact_query and compact_query in title
                else 0.0
            )
            exact_chunk_bonus = (
                0.10
                if compact_query and compact_query in first_chunk
                else 0.0
            )
            exact_date_bonus = (
                0.45
                if query_dates
                and query_dates.intersection(
                    extract_full_dates(
                        str(page_info.get("title", ""))
                        + " "
                        + str(page_info.get("first_chunk", ""))
                    )
                )
                else 0.0
            )

            score = (
                lexical_position_score
                + 1.25 * title_coverage
                + 0.5 * chunk_coverage
                + document_coverage
                + exact_title_bonus
                + exact_chunk_bonus
                + exact_date_bonus
                + self.SEMANTIC_WEIGHT * semantic_score
            )
            ranked.append((score, -lexical_rank.get(doc_id, 10**9), url))

        ranked.sort(reverse=True)
        urls = [url for _, _, url in ranked]

        # 保护词法检索最强的三个候选，最多只允许各下降两位。
        protected_urls = [
            url
            for doc_id, _ in lexical_rows[:3]
            if (url := self.document_registry.get_url(doc_id)) is not None
        ]
        for original_rank, url in reversed(
            list(enumerate(protected_urls, start=1))
        ):
            current_index = urls.index(url)
            maximum_index = original_rank + 1
            if current_index > maximum_index:
                urls.pop(current_index)
                urls.insert(maximum_index, url)

        return urls

    def search(
        self,
        text: str | None,
        topk: int = 20,
        mode: str = "bm25_hybrid",
    ) -> list[str]:
        if topk <= 0:
            return []

        normalized_text = str(text or "").strip().casefold()
        if normalized_text:
            if mode == "tfidf":
                candidates = self._lexical_ranking(
                    normalized_text,
                    method="tfidf",
                )
            elif mode == "bm25":
                candidates = self._lexical_ranking(
                    normalized_text,
                    method="bm25",
                )
            elif mode == "embedding":
                candidates = self._embedding_ranking(normalized_text)
            elif mode == "tfidf_hybrid":
                candidates = self._hybrid_ranking(
                    normalized_text,
                    lexical_method="tfidf",
                )
            elif mode == "bm25_hybrid":
                candidates = self._hybrid_ranking(
                    normalized_text,
                    lexical_method="bm25",
                )
            else:
                raise ValueError(
                    "mode 必须是 tfidf、bm25、embedding、"
                    "tfidf_hybrid 或 bm25_hybrid"
                )
        else:
            candidates = self.document_registry.urls()

        urls = []
        seen_urls = set()
        for url in candidates:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            urls.append(url)
            if len(urls) == topk:
                return urls

        # 任意查询都必须返回恰好 topk 个不同 URL。
        for url in self.document_registry.urls():
            if url in seen_urls:
                continue
            seen_urls.add(url)
            urls.append(url)
            if len(urls) == topk:
                break
        return urls
