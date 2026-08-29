"""基于本地 HTML 的字段加权 TF-IDF / BM25 倒排索引。"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from math import log, log10, sqrt
from pathlib import Path

import jieba

from info import DocumentRegistry, PageInfoStore


class LexicalIndex:
    """为精确词项检索提供可持久化的稀疏索引。"""

    INDEX_VERSION = 3

    def __init__(
        self,
        document_registry: DocumentRegistry,
        page_info_store: PageInfoStore,
        index_path: Path,
        stopwords_path: Path | None = None,
    ) -> None:
        self.document_registry = document_registry
        self.page_info_store = page_info_store
        self.index_path = Path(index_path)
        self.stopwords = self._load_stopwords(stopwords_path)

        if self.index_path.exists():
            self._load()
            if self.document_count != len(self.document_registry):
                self._build()
                self._save()
            elif self._needs_save:
                self._save()
        else:
            self._build()
            self._save()

    @staticmethod
    def _load_stopwords(path: Path | None) -> set[str]:
        if path is None or not path.exists():
            return set()
        with path.open(encoding="utf-8") as reader:
            return {
                line.strip().casefold()
                for line in reader
                if line.strip()
            }

    def normalize_words(self, words: list[str]) -> list[str]:
        normalized = []
        for raw_word in words:
            word = raw_word.strip().casefold()
            if word and word not in self.stopwords:
                normalized.append(word)
        return normalized

    @staticmethod
    def _log_tf(value: int) -> float:
        return 0.0 if value <= 0 else 1.0 + log10(value)

    def _build(self) -> None:
        terms: dict[str, dict] = defaultdict(
            lambda: {"df": 0, "postings": []}
        )
        self.document_count = len(self.document_registry)

        for position, document in enumerate(
            self.document_registry,
            start=1,
        ):
            title, headings, body = self.page_info_store.get_index_fields(
                document.url
            )
            title_counts = Counter(
                self.normalize_words(jieba.lcut_for_search(title))
            )
            heading_counts = Counter(
                self.normalize_words(jieba.lcut_for_search(headings))
            )
            body_counts = Counter(
                self.normalize_words(jieba.lcut_for_search(body))
            )

            document_terms = (
                title_counts.keys()
                | heading_counts.keys()
                | body_counts.keys()
            )
            for term in document_terms:
                weighted_tf = (
                    3 * title_counts[term]
                    + 2 * heading_counts[term]
                    + body_counts[term]
                )
                term_data = terms[term]
                term_data["df"] += 1
                term_data["postings"].append(
                    [document.doc_id, weighted_tf]
                )

            if position % 1000 == 0:
                print(
                    f"Lexical index: {position}/{self.document_count}",
                    flush=True,
                )

        self.terms = dict(terms)
        self.doc_lengths = [0.0] * self.document_count
        for term_data in self.terms.values():
            term_data["idf"] = log10(
                self.document_count / term_data["df"]
            )
            idf = term_data["idf"]
            for doc_id, weighted_tf in term_data["postings"]:
                weight = self._log_tf(weighted_tf) * idf
                self.doc_lengths[doc_id] += weight * weight
        self.doc_lengths = [sqrt(value) for value in self.doc_lengths]
        self._prepare_bm25_statistics()

    def _prepare_bm25_statistics(self) -> None:
        """由已有 postings 计算 BM25 文档长度和 IDF。

        旧版 TF-IDF 索引已经保存了每个文档的字段加权词频，因此升级时
        无需重新解析全部 HTML。
        """
        self.bm25_doc_lengths = [0.0] * self.document_count
        for term_data in self.terms.values():
            document_frequency = int(term_data["df"])
            term_data["bm25_idf"] = log(
                1.0
                + (
                    self.document_count
                    - document_frequency
                    + 0.5
                ) / (document_frequency + 0.5)
            )
            for doc_id, weighted_tf in term_data["postings"]:
                self.bm25_doc_lengths[doc_id] += weighted_tf

        self.average_bm25_doc_length = (
            sum(self.bm25_doc_lengths) / self.document_count
            if self.document_count
            else 0.0
        )

    def _save(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.index_path.with_suffix(".json.tmp")
        state = {
            "version": self.INDEX_VERSION,
            "document_count": self.document_count,
            "doc_lengths": self.doc_lengths,
            "bm25_doc_lengths": self.bm25_doc_lengths,
            "average_bm25_doc_length": self.average_bm25_doc_length,
            "terms": self.terms,
        }
        with temporary_path.open("w", encoding="utf-8") as writer:
            json.dump(state, writer, ensure_ascii=False)
        temporary_path.replace(self.index_path)

    def _load(self) -> None:
        with self.index_path.open(encoding="utf-8") as reader:
            state = json.load(reader)
        version = int(state.get("version", 1))
        self.document_count = int(state["document_count"])
        self.doc_lengths = state["doc_lengths"]
        self.terms = state["terms"]
        self._needs_save = version < self.INDEX_VERSION
        if version >= 3:
            self.bm25_doc_lengths = state["bm25_doc_lengths"]
            self.average_bm25_doc_length = float(
                state["average_bm25_doc_length"]
            )
        else:
            self._prepare_bm25_statistics()

    def search_tfidf_with_scores(
        self,
        query: str,
        topk: int = 500,
    ) -> list[tuple[int, float]]:
        """返回 ``(doc_id, cosine_score)``，URL 由 ``info`` 层解析。"""
        if topk <= 0:
            return []

        query_terms = Counter(
            self.normalize_words(jieba.lcut_for_search(query))
        )
        scores: dict[int, float] = defaultdict(float)
        query_length_squared = 0.0

        for term, query_tf in query_terms.items():
            term_data = self.terms.get(term)
            if term_data is None:
                continue
            idf = term_data["idf"]
            query_weight = self._log_tf(query_tf) * idf
            if query_weight == 0:
                continue
            query_length_squared += query_weight * query_weight
            for doc_id, weighted_tf in term_data["postings"]:
                document_weight = self._log_tf(weighted_tf) * idf
                scores[doc_id] += query_weight * document_weight

        query_length = sqrt(query_length_squared)
        if query_length == 0:
            return []

        ranked = []
        for doc_id, dot_product in scores.items():
            document_length = self.doc_lengths[doc_id]
            if document_length == 0:
                continue
            ranked.append(
                (
                    doc_id,
                    dot_product / (document_length * query_length),
                )
            )
        ranked.sort(key=lambda row: row[1], reverse=True)
        return ranked[:topk]

    def search_bm25_with_scores(
        self,
        query: str,
        topk: int = 500,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> list[tuple[int, float]]:
        """返回字段加权 BM25 的 ``(doc_id, score)``。"""
        if topk <= 0:
            return []
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("BM25 参数要求 k1 > 0 且 0 <= b <= 1")
        if self.average_bm25_doc_length <= 0:
            return []

        query_terms = Counter(
            self.normalize_words(jieba.lcut_for_search(query))
        )
        scores: dict[int, float] = defaultdict(float)
        average_length = self.average_bm25_doc_length

        for term, query_tf in query_terms.items():
            term_data = self.terms.get(term)
            if term_data is None:
                continue
            idf = float(term_data["bm25_idf"])
            for doc_id, weighted_tf in term_data["postings"]:
                length_ratio = (
                    self.bm25_doc_lengths[doc_id] / average_length
                )
                denominator = weighted_tf + k1 * (
                    1.0 - b + b * length_ratio
                )
                scores[doc_id] += (
                    query_tf
                    * idf
                    * weighted_tf
                    * (k1 + 1.0)
                    / denominator
                )

        ranked = sorted(
            scores.items(),
            key=lambda row: row[1],
            reverse=True,
        )
        return ranked[:topk]

    def search_with_scores(
        self,
        query: str,
        topk: int = 500,
        method: str = "bm25",
    ) -> list[tuple[int, float]]:
        """按指定词法方法检索，默认使用 BM25。"""
        if method == "bm25":
            return self.search_bm25_with_scores(query, topk=topk)
        if method == "tfidf":
            return self.search_tfidf_with_scores(query, topk=topk)
        raise ValueError("method 必须是 bm25 或 tfidf")
