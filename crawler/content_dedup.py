"""网页正文精确与近重复检测。"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from math import log2
from pathlib import Path
import re
import unicodedata

import jieba
import numpy as np


FINGERPRINT_VERSION = 4
SKETCH_SIZE = 64
CONTENT_CHARACTERS = re.compile(r"[0-9a-z\u4e00-\u9fff]+")


def normalize_content(text: str) -> str:
    """消除大小写、全半角、空白和标点差异。"""
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(CONTENT_CHARACTERS.findall(normalized))


def tokenize_content(text: str) -> list[str]:
    return [
        word
        for word in jieba.lcut(text, cut_all=False)
        if CONTENT_CHARACTERS.fullmatch(word)
    ]


def simhash64_from_words(words: list[str]) -> int:
    """根据正文词频生成可持久化的 64 位 SimHash。"""
    counts = Counter(words)
    if not counts:
        return 0

    hashes = np.fromiter(
        (
            int.from_bytes(
                hashlib.blake2b(
                    word.encode("utf-8"),
                    digest_size=8,
                ).digest(),
                "little",
            )
            for word in counts
        ),
        dtype=np.uint64,
        count=len(counts),
    )
    weights = np.fromiter(
        (1.0 + log2(count) for count in counts.values()),
        dtype=np.float64,
        count=len(counts),
    )
    bit_positions = np.arange(64, dtype=np.uint64)
    bits = ((hashes[:, None] >> bit_positions) & 1).astype(np.int8)
    votes = (bits * 2 - 1).T @ weights

    fingerprint = 0
    for bit, vote in enumerate(votes):
        if vote >= 0:
            fingerprint |= 1 << bit
    return fingerprint


def simhash64(text: str) -> int:
    return simhash64_from_words(tokenize_content(text))


def content_sketch(words: list[str]) -> tuple[int, ...]:
    """生成三词 shingle 的协调 bottom-k 草图，用于估计 Jaccard。"""
    if len(words) >= 3:
        features = (
            "\x1f".join(words[position:position + 3])
            for position in range(len(words) - 2)
        )
    else:
        features = iter(words)

    hashes = {
        int.from_bytes(
            hashlib.blake2b(
                feature.encode("utf-8"),
                digest_size=8,
            ).digest(),
            "little",
        )
        for feature in features
    }
    return tuple(sorted(hashes)[:SKETCH_SIZE])


def sketch_similarity(
    left: tuple[int, ...],
    right: tuple[int, ...],
) -> float:
    """用两个协调 bottom-k 草图估计原始 shingle 集合的 Jaccard。"""
    if not left or not right:
        return 0.0
    left_set = set(left)
    right_set = set(right)
    union_sample = sorted(left_set | right_set)[:SKETCH_SIZE]
    if not union_sample:
        return 0.0
    shared = left_set & right_set
    return sum(value in shared for value in union_sample) / len(union_sample)


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


@dataclass(frozen=True)
class ContentSignature:
    exact_hash: str
    simhash: int | None
    sketch: tuple[int, ...] | None
    char_count: int
    title_key: str


@dataclass(frozen=True)
class DuplicateMatch:
    url: str
    distance: int
    exact: bool
    content_similarity: float

    @property
    def similarity(self) -> float:
        return 1.0 if self.exact else self.content_similarity


class ContentDeduplicator:
    """维护正文指纹、LSH 分桶和重复 URL 持久化记录。"""

    BAND_COUNT = 8
    BAND_BITS = 8
    BAND_MASK = (1 << BAND_BITS) - 1

    def __init__(
        self,
        fingerprint_path: Path,
        duplicate_path: Path,
        hamming_threshold: int = 7,
        minimum_similarity: float = 0.85,
        minimum_content_chars: int = 200,
    ) -> None:
        if not 0 <= hamming_threshold < self.BAND_COUNT:
            raise ValueError(
                f"hamming_threshold 必须在 0 到 {self.BAND_COUNT - 1} 之间"
            )
        self.fingerprint_path = Path(fingerprint_path)
        self.duplicate_path = Path(duplicate_path)
        self.hamming_threshold = hamming_threshold
        if not 0.0 <= minimum_similarity <= 1.0:
            raise ValueError("minimum_similarity 必须在 0 到 1 之间")
        self.minimum_similarity = minimum_similarity
        self.minimum_content_chars = minimum_content_chars

        self.indexed_urls: set[str] = set()
        self.duplicate_urls: set[str] = set()
        self.exact_hash_to_url: dict[str, str] = {}
        self.url_to_simhash: dict[str, int] = {}
        self.url_to_sketch: dict[str, tuple[int, ...]] = {}
        self.url_to_doc_id: dict[str, int] = {}
        self.url_to_char_count: dict[str, int] = {}
        self.url_to_title_key: dict[str, str] = {}
        self.buckets: dict[tuple[int, int], list[str]] = defaultdict(list)

        self._load_fingerprints()
        self._load_duplicates()
        jieba.initialize()

    def make_signature(
        self,
        text: str,
        title: str = "",
    ) -> ContentSignature:
        normalized_source = unicodedata.normalize(
            "NFKC",
            str(text or ""),
        ).casefold()
        compact_content = normalize_content(normalized_source)
        title_key = normalize_content(title)
        if not compact_content:
            return ContentSignature("", None, None, 0, title_key)

        exact_hash = hashlib.sha256(
            compact_content.encode("utf-8")
        ).hexdigest()
        fingerprint = None
        sketch = None
        if len(compact_content) >= self.minimum_content_chars:
            words = tokenize_content(normalized_source)
            fingerprint = simhash64_from_words(words)
            sketch = content_sketch(words)
        return ContentSignature(
            exact_hash=exact_hash,
            simhash=fingerprint,
            sketch=sketch,
            char_count=len(compact_content),
            title_key=title_key,
        )

    def _bucket_keys(self, fingerprint: int):
        for band in range(self.BAND_COUNT):
            shift = band * self.BAND_BITS
            yield band, (fingerprint >> shift) & self.BAND_MASK

    def find_duplicate(
        self,
        signature: ContentSignature,
    ) -> DuplicateMatch | None:
        if not signature.exact_hash:
            return None

        exact_url = self.exact_hash_to_url.get(signature.exact_hash)
        if exact_url is not None:
            return DuplicateMatch(
                exact_url,
                distance=0,
                exact=True,
                content_similarity=1.0,
            )

        if signature.simhash is None or not signature.sketch:
            return None

        candidate_urls = set()
        for key in self._bucket_keys(signature.simhash):
            candidate_urls.update(self.buckets.get(key, ()))

        best_key = None
        for candidate_url in candidate_urls:
            if not self._titles_equivalent(
                signature.title_key,
                self.url_to_title_key[candidate_url],
            ):
                continue
            distance = hamming_distance(
                signature.simhash,
                self.url_to_simhash[candidate_url],
            )
            similarity = sketch_similarity(
                signature.sketch,
                self.url_to_sketch[candidate_url],
            )
            shorter_content = min(
                signature.char_count,
                self.url_to_char_count[candidate_url],
            )
            required_similarity = max(
                self.minimum_similarity,
                0.95 if shorter_content < 1000 else self.minimum_similarity,
            )
            if similarity < required_similarity:
                continue
            candidate_key = (
                -similarity,
                distance,
                self.url_to_doc_id[candidate_url],
                candidate_url,
            )
            if best_key is None or candidate_key < best_key:
                best_key = candidate_key

        if best_key is None or best_key[1] > self.hamming_threshold:
            return None
        return DuplicateMatch(
            best_key[3],
            distance=best_key[1],
            exact=False,
            content_similarity=-best_key[0],
        )

    def add(
        self,
        doc_id: int,
        url: str,
        signature: ContentSignature,
        persist: bool = True,
    ) -> dict:
        record = {
            "version": FINGERPRINT_VERSION,
            "docID": int(doc_id),
            "url": url,
            "exact_hash": signature.exact_hash,
            "simhash": (
                f"{signature.simhash:016x}"
                if signature.simhash is not None
                else None
            ),
            "sketch": (
                [f"{value:016x}" for value in signature.sketch]
                if signature.sketch is not None
                else None
            ),
            "char_count": signature.char_count,
            "title_key": signature.title_key,
        }
        self._index_record(record)
        if persist:
            self._append_jsonl(self.fingerprint_path, [record])
        return record

    def record_duplicate(
        self,
        url: str,
        match: DuplicateMatch,
        signature: ContentSignature,
    ) -> None:
        record = {
            "url": url,
            "duplicate_of": match.url,
            "exact": match.exact,
            "hamming_distance": match.distance,
            "similarity": round(match.similarity, 6),
            "exact_hash": signature.exact_hash,
        }
        self._append_jsonl(self.duplicate_path, [record])
        self.duplicate_urls.add(url)

    def persist_records(self, records: list[dict]) -> None:
        self._append_jsonl(self.fingerprint_path, records)

    def _index_record(self, record: dict) -> None:
        url = record["url"]
        self.indexed_urls.add(url)
        self.url_to_doc_id[url] = int(record["docID"])
        self.url_to_char_count[url] = int(record.get("char_count", 0))
        self.url_to_title_key[url] = str(record.get("title_key") or "")

        exact_hash = record.get("exact_hash") or ""
        if exact_hash:
            self.exact_hash_to_url.setdefault(exact_hash, url)

        simhash_text = record.get("simhash")
        sketch_values = record.get("sketch")
        if not simhash_text or not sketch_values:
            return
        fingerprint = int(simhash_text, 16)
        self.url_to_simhash[url] = fingerprint
        self.url_to_sketch[url] = tuple(
            int(value, 16) for value in sketch_values
        )
        for key in self._bucket_keys(fingerprint):
            self.buckets[key].append(url)

    @staticmethod
    def _titles_equivalent(left: str, right: str) -> bool:
        if not left or not right:
            return False
        if left == right:
            return True
        shorter, longer = sorted((left, right), key=len)
        return (
            len(shorter) >= 8
            and shorter in longer
            and len(shorter) / len(longer) >= 0.65
        )

    def _load_fingerprints(self) -> None:
        if not self.fingerprint_path.exists():
            return
        with self.fingerprint_path.open(encoding="utf-8") as reader:
            for line in reader:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("version") == FINGERPRINT_VERSION:
                    self._index_record(record)

    def _load_duplicates(self) -> None:
        if not self.duplicate_path.exists():
            return
        with self.duplicate_path.open(encoding="utf-8") as reader:
            for line in reader:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                url = record.get("url")
                if isinstance(url, str):
                    self.duplicate_urls.add(url)

    @staticmethod
    def _append_jsonl(path: Path, records: list[dict]) -> None:
        if not records:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as writer:
            for record in records:
                writer.write(json.dumps(record, ensure_ascii=False) + "\n")
