from day1.day1 import ExtractHTML
from bs4 import BeautifulSoup
from collections import deque
import time
import requests
class Crawler:
    def get_html(self, uri, headers={}, timeout=None):
        try:
            r = requests.get(uri, headers=headers, timeout=timeout)
            r.raise_for_status()
            r.encoding = 'utf-8'
            return r.text
        except:
            return None
    def __init__(self, url, max_count = 500000, wait_time = 5):
        self.headers = {'user-agent': 'my-app/0.0.1'}
        q, self.all_links, count = deque([url]), set({url}), 0
        while len(q) > 0 and count < max_count:
            u, count = q.popleft(), count + 1
            html = self.get_html(u, headers=self.headers, timeout=10)
            if html == None:
                continue
            links = ExtractHTML(html).extract_links(u)
            for new_url in links:
                if new_url not in self.all_links:
                    self.all_links.add(new_url)
                    q.append(new_url)
            if wait_time > 0:
                time.sleep(wait_time)
    def __str__(self):
        return '\n'.join(sorted(self.all_links))

if __name__ == "__main__":
    # 测试
    crawl_tester = Crawler('https://www.ruc.edu.cn/', max_count=10, wait_time=1)
    print(crawl_tester)