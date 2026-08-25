from bs4 import BeautifulSoup
import jieba
from url_normalize import url_normalize
from urllib.parse import urljoin, urldefrag, urlparse

class ExtractHTML:
    def __init__(self, html_doc):
        self.soup = BeautifulSoup(html_doc, 'html5lib')
    # 提取文档中所有链接
    def extract_links(self, url = ''):
        all_links = set()
        for anchor in self.soup.find_all('a'):
            href = anchor.get('href')
            if not isinstance(href, str):
                continue
            href = href.strip()
            if not href or href.lower().startswith('javascript:'):
                continue
            absolute_url = urljoin(url, href)
            absolute_url, _ = urldefrag(absolute_url)
            parsed = urlparse(absolute_url)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
                continue
            if '%' in parsed.hostname:
                print(f'跳过错误域名: {absolute_url}')
                continue
            try:
                normalized_url = url_normalize(absolute_url)
            except (UnicodeError, ValueError) as error:
                print(f'跳过无法规范化的链接: {absolute_url}, 原因: {error}')
                continue
            all_links.add(url_normalize(normalized_url))
        return all_links
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

if __name__ == "__main__":
    # 测试
    with open('day1/index.html', 'r', encoding = 'utf-8') as file:
        html_doc = file.read()

    test_extract = ExtractHTML(html_doc)
    print(f'文档中链接: {test_extract.extract_links()}')
    title, doctitle, body_text, title_words, doctitle_words, body_words = test_extract.extract_title_and_body_words()
    print(f'文档标题: {title}\nhx标题: {doctitle}\n文档内容: {body_text}')
    print(f'标题分词: {title_words}\nhx标题分词: {doctitle_words}\n内容分词: {body_words}')