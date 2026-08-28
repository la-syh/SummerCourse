"""HTML 内容与链接提取工具。"""

from bs4 import BeautifulSoup
import jieba
import re
from url_normalize import url_normalize
from urllib.parse import urljoin, urldefrag, urlparse

class ExtractHTML:
    def __init__(self, html_doc):
        self.soup = BeautifulSoup(html_doc, 'html5lib')

    def normalize_link(self, href, base_url):
        if not isinstance(href, str):
            return None
        href = href.strip()
        if not href or href.lower().startswith('javascript:'):
            return None

        absolute_url = urljoin(base_url, href)
        absolute_url, _ = urldefrag(absolute_url)
        parsed = urlparse(absolute_url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            return None
        if '%' in parsed.hostname:
            print(f'跳过错误域名: {absolute_url}')
            return None

        try:
            return url_normalize(absolute_url)
        except (UnicodeError, ValueError) as error:
            print(f'跳过无法规范化的链接: {absolute_url}, 原因: {error}')
            return None

    # 提取文档中所有链接
    def extract_links(self, url = ''):
        all_links = set()
        for anchor in self.soup.find_all('a'):
            normalized_url = self.normalize_link(anchor.get('href'), url)
            if normalized_url is not None:
                all_links.add(normalized_url)

        all_links.update(self.extract_redirect_links(url))
        return all_links

    def extract_redirect_links(self, url = ''):
        '''提取 meta refresh 和简单的 JavaScript 字面量跳转。'''
        redirect_links = set()

        for meta in self.soup.find_all('meta'):
            http_equiv = meta.get('http-equiv', '')
            content = meta.get('content', '')
            if (not isinstance(http_equiv, str)
                    or http_equiv.lower() != 'refresh'
                    or not isinstance(content, str)):
                continue
            match = re.search(
                r'''url\s*=\s*(?:"([^"]+)"|'([^']+)'|([^;\s]+))''',
                content,
                flags=re.IGNORECASE,
            )
            if match:
                href = next(group for group in match.groups() if group is not None)
                normalized_url = self.normalize_link(href, url)
                if normalized_url is not None:
                    redirect_links.add(normalized_url)

        assignment_pattern = re.compile(
            r'''(?:window\.)?location\.href\s*=\s*(["'])(.*?)\1''',
            flags=re.IGNORECASE | re.DOTALL,
        )
        replace_pattern = re.compile(
            r'''(?:window\.)?location\.replace\s*\(\s*(["'])(.*?)\1\s*\)''',
            flags=re.IGNORECASE | re.DOTALL,
        )
        for script in self.soup.find_all('script'):
            script_text = script.string or script.get_text()
            if not script_text:
                continue
            for pattern in (assignment_pattern, replace_pattern):
                for match in pattern.finditer(script_text):
                    normalized_url = self.normalize_link(match.group(2), url)
                    if normalized_url is not None:
                        redirect_links.add(normalized_url)

        return redirect_links
    # 抓取标题与正文并分词
    def extract_title_and_body_words(self):
        title = self.soup.title.get_text(strip = True) if self.soup.title else ''
        title_words = jieba.lcut_for_search(title)

        doctitle = [t.get_text(strip = True) for t in self.soup.find_all({'h1', 'h2', 'h3'})]
        doctitle_words = []
        for t in doctitle:
            doctitle_words += [word for word in jieba.lcut_for_search(t) if word.strip()]

        body_text = ' '.join(
            p.get_text(strip = True) for p in self.soup.find_all('p') if p.get_text(strip = True)
        )
        body_words = [word for word in jieba.lcut_for_search(body_text) if word.strip()]

        return title, doctitle, body_text, title_words, doctitle_words, body_words
