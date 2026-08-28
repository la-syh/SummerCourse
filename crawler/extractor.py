import re
from urllib.parse import urldefrag, urljoin, urlparse

from resiliparse.parse.encoding import detect_encoding
from resiliparse.parse.html import HTMLTree
from url_normalize import url_normalize


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
        encoding = detect_encoding(html) or "utf-8"
        self.document = HTMLTree.parse_from_bytes(
            html,
            encoding=encoding,
        ).document

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
