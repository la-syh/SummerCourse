import re
from urllib.parse import urldefrag, urljoin, urlparse

from url_normalize import url_normalize

from info.page_info import extract_text, extract_title, parse_html_bytes


META_REFRESH = re.compile(
    r'''url\s*=\s*(?:"([^"]+)"|'([^']+)'|([^;\s]+))''',
    re.IGNORECASE,
)
SCRIPT_REDIRECT = re.compile(
    r'''(?:(?:window\.)?location\.href\s*=|'''
    r'''(?:window\.)?location\.replace\s*\()\s*(["'])(.*?)\1''',
    re.IGNORECASE | re.DOTALL,
)


class ExtractHTML:
    def __init__(self, html):
        self.tree = parse_html_bytes(html)
        self.document = self.tree.document

    def extract_title(self):
        return extract_title(self.tree)

    def extract_text(self):
        """提取用于内容指纹的正文，主内容过短时退回全部可见文字。"""
        return extract_text(
            self.tree,
            main_content=True,
            fallback_to_all=True,
        )

    @staticmethod
    def normalize_link(href, base_url):
        url = url_normalize(urldefrag(urljoin(base_url, href))[0])
        if urlparse(url).scheme in {"http", "https"}:
            return url

    def extract_links(self, base_url):
        links = {
            self.normalize_link(anchor["href"], base_url)
            for anchor in self.document.query_selector_all("a[href]")
        }
        links.discard(None)
        return links | self.extract_redirect_links(base_url)

    def extract_redirect_links(self, base_url):
        links = set()

        for meta in self.document.query_selector_all(
            'meta[http-equiv="refresh"][content]'
        ):
            match = META_REFRESH.search(meta["content"])
            if match:
                href = next(value for value in match.groups() if value)
                links.add(self.normalize_link(href, base_url))

        for script in self.document.query_selector_all("script"):
            for match in SCRIPT_REDIRECT.finditer(script.text or ""):
                links.add(self.normalize_link(match.group(2), base_url))

        links.discard(None)
        return links
