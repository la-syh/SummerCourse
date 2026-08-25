from day1.day1 import ExtractHTML
from bs4 import BeautifulSoup
from collections import deque
import os
import json
import time
import requests
from urllib.parse import urlparse, unquote, parse_qs

class Crawler:
    def __init__(self, url, max_count=1_000_000, wait_time=5.,
                 checkpointfile='crawler_checkpoint.json', save_interval=1000):
        self.headers = {'user-agent': 'my-app/0.0.1'}
        self.checkpointfile, self.save_interval = checkpointfile, save_interval
        self.ignored_suffixes = (
            ".zip", ".rar", ".7z", ".tar", ".tar.gz", ".tgz",
            ".pdf", ".doc", ".docx", ".xls", ".xlsx",
            ".ppt", ".pptx",
            ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
            ".mp3", ".wav", ".mp4", ".avi", ".mov",
        )
        q, self.all_links, count = self.load_checkpoint(url)

        try:
            while len(q) > 0 and count < max_count:
                u, count = q.popleft(), count + 1
                print(f"[{count}/{max_count}] 正在访问：{u}", flush=True)
                html = self.get_html(u, headers=self.headers, timeout=(3, 5))
                if html is not None:
                    links = ExtractHTML(html).extract_links(u)
                    for new_url in links:
                        if self.is_ignored_file(new_url):
                            print(f'跳过文件：{new_url}')
                            continue
                        if new_url not in self.all_links:
                            self.all_links.add(new_url)
                            q.append(new_url)
                if count % save_interval == 0:
                    self.save_checkpoint(q, count)
                    print(f'已保存断点：完成 {count} 个页面，剩余 {len(q)} 个页面')
                if wait_time > 0:
                    time.sleep(wait_time)
        except KeyboardInterrupt:
            print('\n程序被中断，保存断点中...')
        finally:
            self.save_checkpoint(q, count)

        # if not q or count >= max_count:
        #     self.remove_checkpoint()

    def is_ignored_file(self, url):
        parsed = urlparse(url)

        candidates = [
            unquote(parsed.path).lower(),
        ]

        query_parameters = parse_qs(parsed.query)

        for values in query_parameters.values():
            for value in values:
                candidates.append(unquote(value).lower())

        return any(
            candidate.endswith(self.ignored_suffixes)
            for candidate in candidates
        )
    def get_html(self, uri, headers=None, timeout=None):
        if headers == None:
            headers = {}
        try:
            r = requests.get(uri, headers=headers, timeout=timeout)
            r.raise_for_status()
            r.encoding = 'utf-8'
            return r.text
        except requests.RequestException as error:
            print(f'访问失败： {uri}，原因： {error}')
            return None
        
    def save_checkpoint(self, queue, count):
        state = {
            'queue': list(queue),
            'all_links': list(self.all_links),
            'count': count
        }
        temp_file = self.checkpointfile + '.tmp'
        with open(temp_file, 'w', encoding='utf-8') as file:
            json.dump(state, file, ensure_ascii=False)
        os.replace(temp_file, self.checkpointfile)

    def load_checkpoint(self, start_url):
        if os.path.exists(self.checkpointfile):
            try:
                with open(self.checkpointfile, "r", encoding='utf-8') as file:
                    state = json.load(file)
                print(f'从断点恢复，已完成 {state["count"]} 个页面')
                return (deque(state['queue']), set(state['all_links']), state['count'])
            except:
                print(f'断点恢复失败，重新开始')
        return deque([start_url]), set({start_url}), 0

    def remove_checkpoint(self):
        if os.path.exists(self.checkpointfile):
            os.remove(self.checkpointfile)
    
    def __str__(self):
        return '\n'.join(sorted(self.all_links))

if __name__ == "__main__":
    # 测试
    crawl_tester = Crawler('https://news.ruc.edu.cn/', wait_time=1)
    with open('crawled_links', 'w', encoding='utf-8') as file:
        file.write(crawl_tester.__str__())