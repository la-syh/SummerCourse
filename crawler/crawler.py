from collections import deque
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, unquote, urlparse

import requests

from .extractor import ExtractHTML


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
HTML_DIR = DATA_DIR / "downloaded_html"
DOC_ID_FILE = DATA_DIR / "docID.jsonl"
CHECKPOINT_FILE = DATA_DIR / "crawler_checkpoint.json"

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
        self.saved_urls, self.next_doc_id = self.load_saved_urls()
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
        if final_url not in self.saved_urls:
            self.save_html(final_url, html)
            self.saved_urls.add(final_url)

        for new_url in ExtractHTML(html).extract_links(final_url):
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

        record = {
            "docID": self.next_doc_id,
            "url": url,
            "file": file_path.relative_to(PROJECT_ROOT).as_posix(),
        }
        with DOC_ID_FILE.open("a", encoding="utf-8") as writer:
            writer.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.next_doc_id += 1

    @staticmethod
    def load_saved_urls():
        if not DOC_ID_FILE.exists():
            return set(), 0

        with DOC_ID_FILE.open(encoding="utf-8") as reader:
            records = [json.loads(line) for line in reader]
        saved_urls = {record["url"] for record in records}
        return saved_urls, records[-1]["docID"] + 1

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
