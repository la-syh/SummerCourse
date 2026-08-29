from collections import deque
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, unquote, urlparse

import requests

from info import DocumentRecord, DocumentRegistry

from .extractor import ExtractHTML
from .content_dedup import ContentDeduplicator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
HTML_DIR = DATA_DIR / "downloaded_html"
DOC_ID_FILE = DATA_DIR / "docID.jsonl"
CHECKPOINT_FILE = DATA_DIR / "crawler_checkpoint.json"
FINGERPRINT_FILE = DATA_DIR / "content_fingerprints.jsonl"
DUPLICATE_FILE = DATA_DIR / "duplicate_urls.jsonl"

IGNORED_SUFFIXES = (
    ".zip", ".rar", ".7z", ".tar", ".tar.gz", ".tgz",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".mp3", ".wav", ".mp4", ".avi", ".mov",
)


class Crawler:
    def __init__(
        self,
        start_urls,
        wait_time=1.0,
        max_count=200_000,
        save_interval=1000,
        duplicate_hamming_threshold=7,
        duplicate_minimum_similarity=0.85,
        minimum_content_chars=200,
    ):
        self.start_urls = list(dict.fromkeys(start_urls))
        self.hostnames = list(dict.fromkeys(
            urlparse(url).hostname for url in self.start_urls
        ))
        self.allowed_hostnames = set(self.hostnames)
        self.wait_time = wait_time
        self.max_count = max_count
        self.save_interval = save_interval
        self.headers = {"user-agent": "ruc-search-crawler/1.0"}

        HTML_DIR.mkdir(parents=True, exist_ok=True)
        self.document_registry = DocumentRegistry(PROJECT_ROOT, DOC_ID_FILE)
        saved_records = self.document_registry.records()
        self.saved_urls = set(self.document_registry.urls())
        self.content_deduplicator = ContentDeduplicator(
            FINGERPRINT_FILE,
            DUPLICATE_FILE,
            hamming_threshold=duplicate_hamming_threshold,
            minimum_similarity=duplicate_minimum_similarity,
            minimum_content_chars=minimum_content_chars,
        )
        self.backfill_content_fingerprints(saved_records)
        self.saved_urls.update(self.content_deduplicator.duplicate_urls)
        self.queues, self.all_links, self.last_fetch_time, self.count = \
            self.load_checkpoint()

        for url in self.start_urls:
            if url not in self.all_links:
                self.all_links.add(url)
                self.queues.setdefault(urlparse(url).hostname, deque()).append(url)

    def run(self):
        try:
            while self.queues and self.count < self.max_count:
                for hostname in self.hostnames:
                    if self.count >= self.max_count:
                        break

                    queue = self.queues.get(hostname)
                    if not queue:
                        continue

                    url = queue.popleft()
                    if not queue:
                        del self.queues[hostname]
                    if self.is_ignored_file(url):
                        continue

                    self.count += 1
                    print(
                        f"[{self.count}/{self.max_count}] {url}",
                        flush=True,
                    )
                    self.crawl_url(url)

                    if self.count % self.save_interval == 0:
                        self.save_checkpoint()
        except KeyboardInterrupt:
            print("爬虫已中断")
        finally:
            self.save_checkpoint()

    def crawl_url(self, url):
        self.wait_for_host(url)
        result = self.get_html(url)
        self.last_fetch_time[urlparse(url).hostname] = time.time()
        if result is None:
            return

        html, final_url = result
        if urlparse(final_url).hostname not in self.allowed_hostnames:
            return

        self.all_links.add(final_url)
        try:
            extracted_page = ExtractHTML(html)
        except (TypeError, ValueError) as error:
            print(f"HTML 解析失败: {final_url}: {error}")
            return

        if final_url not in self.saved_urls:
            try:
                content_text = extracted_page.extract_text()
            except (TypeError, ValueError):
                content_text = ""
            signature = self.content_deduplicator.make_signature(
                content_text,
                extracted_page.extract_title(),
            )
            duplicate = self.content_deduplicator.find_duplicate(signature)
            if duplicate is None:
                doc_id = self.save_html(final_url, html)
                self.content_deduplicator.add(
                    doc_id,
                    final_url,
                    signature,
                )
            else:
                self.content_deduplicator.record_duplicate(
                    final_url,
                    duplicate,
                    signature,
                )
                print(
                    "跳过近重复页面: "
                    f"{final_url} -> {duplicate.url} "
                    f"(similarity={duplicate.similarity:.3f})",
                    flush=True,
                )
            self.saved_urls.add(final_url)

        # 即使当前页面因内容重复而不保存，也继续发现其中的链接。
        for new_url in extracted_page.extract_links(final_url):
            hostname = urlparse(new_url).hostname
            if hostname not in self.allowed_hostnames \
                    or new_url in self.all_links \
                    or self.is_ignored_file(new_url):
                continue
            self.all_links.add(new_url)
            self.queues.setdefault(hostname, deque()).append(new_url)

    def get_html(self, url):
        try:
            with requests.get(
                url,
                headers=self.headers,
                timeout=(3, 5),
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").lower()
                if content_type \
                        and "text/html" not in content_type \
                        and "application/xhtml+xml" not in content_type:
                    return None
                return response.content, response.url
        except requests.RequestException as error:
            print(f"访问失败: {url}: {error}")
            return None

    def wait_for_host(self, url):
        hostname = urlparse(url).hostname
        last_fetch = self.last_fetch_time.get(hostname, 0)
        remaining = self.wait_time - (time.time() - last_fetch)
        if remaining > 0:
            time.sleep(remaining)

    @staticmethod
    def is_ignored_file(url):
        parsed = urlparse(url)
        candidates = [unquote(parsed.path).lower()]
        candidates.extend(
            unquote(value).lower()
            for values in parse_qs(parsed.query).values()
            for value in values
        )
        return any(path.endswith(IGNORED_SUFFIXES) for path in candidates)

    def save_html(self, url, html):
        hostname = urlparse(url).hostname
        host_dir = HTML_DIR / hostname
        host_dir.mkdir(exist_ok=True)
        file_path = host_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.html"
        file_path.write_bytes(html)

        record = self.document_registry.add(url, file_path)
        return record.doc_id

    def backfill_content_fingerprints(
        self,
        records: tuple[DocumentRecord, ...],
    ):
        """首次升级时为已有 HTML 补建指纹，后续启动直接复用。"""
        missing = [
            record
            for record in records
            if record.url not in self.content_deduplicator.indexed_urls
        ]
        if not missing:
            return

        print(f"正在为 {len(missing)} 个已有网页补建内容指纹...", flush=True)
        new_records = []
        for position, record in enumerate(missing, start=1):
            try:
                html = record.html_path.read_bytes()
                extracted_page = ExtractHTML(html)
                text = extracted_page.extract_text()
                title = extracted_page.extract_title()
            except (OSError, TypeError, ValueError):
                text = ""
                title = ""
            signature = self.content_deduplicator.make_signature(text, title)
            new_records.append(
                self.content_deduplicator.add(
                    record.doc_id,
                    record.url,
                    signature,
                    persist=False,
                )
            )
            if position % 1000 == 0:
                print(
                    f"内容指纹: {position}/{len(missing)}",
                    flush=True,
                )
        self.content_deduplicator.persist_records(new_records)

    def save_checkpoint(self):
        state = {
            "queues": {
                hostname: list(queue)
                for hostname, queue in self.queues.items()
            },
            "all_links": list(self.all_links),
            "last_fetch_time": self.last_fetch_time,
            "count": self.count,
        }
        CHECKPOINT_FILE.write_text(
            json.dumps(state, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_checkpoint(self):
        if not CHECKPOINT_FILE.exists():
            return {}, set(), {}, 0

        state = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        queues = {
            hostname: deque(urls)
            for hostname, urls in state["queues"].items()
        }
        return (
            queues,
            set(state["all_links"]),
            state["last_fetch_time"],
            state["count"],
        )


if __name__ == "__main__":
    Crawler([
        "http://pd.ruc.edu.cn/",
        "http://sph.ruc.edu.cn/",
        "https://clr.ruc.edu.cn/zwwz/index.htm",
        "http://dis.ruc.edu.cn/",
        "http://dsdj.ruc.edu.cn/",
        "http://scsce.ruc.edu.cn/",
        "http://isbd.ruc.edu.cn/",
        "http://sis.ruc.edu.cn/",
        "http://info.ruc.edu.cn/",
        "http://www.phys.ruc.edu.cn/",
        "http://psy.ruc.edu.cn/",
        "http://guoxue.ruc.edu.cn/",
        "https://envi.ruc.edu.cn/",
        "http://ai.ruc.edu.cn/",
        "https://gsai.ruc.edu.cn/",
    ]).run()
