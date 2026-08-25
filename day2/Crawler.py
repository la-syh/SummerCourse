from day1.ExtractHTML import ExtractHTML
import requests
import heapq
import time
from urllib.parse import urlparse, unquote, parse_qs
import json
import os
import hashlib

class Crawler:
    def __init__(self, start_urls, wait_time=5., max_count = 200_000, 
                 checkpoint_file='crawler_checkpoint.json',
                 save_interval=1000,
                 html_dir = 'downloaded_html'):
        self.start_urls = start_urls
        if isinstance(self.start_urls, str):
            self.start_urls = [self.start_urls]
        self.wait_time = wait_time
        self.max_count = max_count
        self.save_interval = save_interval
        self.html_dir = html_dir
        self.url_index_file = os.path.join(
            self.html_dir,
            "url_index.jsonl",
        )
        self.headers = {'user-agent': 'my-app/0.0.1'}
        self.checkpoint_file = checkpoint_file
        self.sequence = 0   # 优先队列历史元素数
        self.ignored_suffixes = (
        ".zip", ".rar", ".7z", ".tar", ".tar.gz", ".tgz",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", 
        ".pptx", ".jpg", ".jpeg", ".png", ".gif", ".webp", 
        ".svg", ".mp3", ".wav", ".mp4", ".avi", ".mov",
        )
        frontier, self.all_links, self.last_fetch_time, count = self.load_checkpoint(self.start_urls)

        hostnames = set()
        for url in self.start_urls:
            hostnames.add(urlparse(url).hostname)

        try:
            while frontier and count < self.max_count:
                _, _, url = heapq.heappop(frontier)
                if self.is_ignored_file(url):
                    print(f'跳过文件 {url}')
                    continue
                count += 1
                print(f'[{count} / {self.max_count}] '
                    f'正在访问 {url}', flush=True)
                self.wait_for_host(url)
                html = self.get_html(url, headers=self.headers, timeout=(3, 5))
                self.record_host_fetch(url)
                if html is not None:
                    self.save_html(url, html)
                    links = ExtractHTML(html).extract_links(url)
                    for new_url in links:
                        if self.is_ignored_file(new_url):
                            print(f'跳过文件 {new_url}')
                            continue
                        if new_url in self.all_links or urlparse(new_url).hostname not in hostnames:
                            continue
                        self.all_links.add(new_url)
                        self.push_url(frontier, new_url, self.calc_priority(new_url, url))
                if count % self.save_interval == 0:
                    self.save_checkpoint(frontier, count)
                    print(f'已保存断点, 共 {count} 个页面, 剩余 {len(frontier)} 个页面')
        except KeyboardInterrupt:
            print(f'程序被中断, 断点已保存')
        finally:
            self.save_checkpoint(frontier, count)

    def get_html(self, uri, headers=None, timeout=None):
        '''从给定的 url 中获取 html 文档'''
        if headers is None:
            headers = {}
        try:
            with requests.get(uri, headers=headers, timeout=timeout, stream=True) as response:
                response.raise_for_status()
                content_type = response.headers.get('Content-Type', '').lower()
                if (content_type
                        and 'text/html' not in content_type
                        and 'application/xhtml+xml' not in content_type):
                    print(f'跳过非 HTML 内容：{uri} ({content_type})')
                    return None
                return response.content
        except requests.RequestException as error:
            print(f'访问失败: {uri}, 原因: {error}')
            return None
        
    def calc_priority(self, url, parent_url=None):
        score = 0
        parsed = urlparse(url)
        if parsed.scheme == 'https':
            score += 1  # https 加一分
        if not parsed.query:
            score += 1  # 没有 ?id=... 类似的询问参数加一分
        path_depth = len([part for part in parsed.path.split("/") if part])
        score -= path_depth # 按照路径深度减分
        if parsed.path == '/' or not parsed.path:
            score += 2  # 网站首页加两分
        if parent_url != None and parsed.hostname == urlparse(parent_url).hostname:
            score += 2  # 来源一致加两分
        return score

    def push_url(self, frontier, url, priority):
        self.sequence += 1
        heapq.heappush(frontier, (-priority, self.sequence, url))

    def wait_for_host(self, url):
        hostname = urlparse(url).hostname
        if not hostname:
            return
        last_fetch = self.last_fetch_time.get(hostname)
        if last_fetch == None:
            return
        remaining_time = self.wait_time - (time.time() - last_fetch)
        if remaining_time > 0:
            print(f'等待 {hostname} {remaining_time:.2f} 秒')
            time.sleep(remaining_time)

    def record_host_fetch(self, url):
        hostname = urlparse(url).hostname
        if hostname:
            self.last_fetch_time[hostname] = time.time()

    def is_ignored_file(self, url): 
        parsed = urlparse(url)
        candidates = [unquote(parsed.path).lower(),]
        query_parameters = parse_qs(parsed.query)
        for values in query_parameters.values():
            for value in values:
                candidates.append(unquote(value).lower())
        return any(candidate.endswith(self.ignored_suffixes) for candidate in candidates)

    def save_html(self, url, html):
        hostname = urlparse(url).hostname or 'unknown-host'
        host_dir = os.path.join(self.html_dir, hostname)
        os.makedirs(host_dir, exist_ok=True)
        url_hash = hashlib.sha256(
            url.encode('utf-8')
        ).hexdigest()
        file_path = os.path.join(
            host_dir,
            f'{url_hash}.html',
        )
        temp_file = file_path + '.tmp'
        with open(temp_file, 'wb') as file:
            file.write(html)
        os.replace(temp_file, file_path)

        relative_path = os.path.relpath(
            file_path,
            self.html_dir,
        )
        record = {
            "url": url,
            "file": relative_path,
        }

        with open(self.url_index_file, 'a', encoding='utf-8') as index_file:
            index_file.write(json.dumps(record, ensure_ascii=False) + '\n')
        print(f"已保存 HTML: {file_path}")

    def save_checkpoint(self, frontier, count):
        '''存档'''
        state = {
            'frontier': list(frontier),
            'all_links': list(self.all_links),
            'last_fetch_time': self.last_fetch_time,
            'count': count,
            'sequence':self.sequence
        }
        temp_file = self.checkpoint_file + '.tmp'
        with open(temp_file, 'w', encoding='utf-8') as file:
            json.dump(state, file, ensure_ascii=False)
        os.replace(temp_file, self.checkpoint_file)

    def load_checkpoint(self, start_urls):
        '''读档'''
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, 'r', encoding='utf-8') as file:
                    state = json.load(file)
                frontier = [tuple(item) for item in state.get('frontier', [])]
                heapq.heapify(frontier)
                all_links = set(state.get('all_links', []))
                last_fetch_time = state.get('last_fetch_time', dict())
                count = state.get('count', 0)
                self.sequence = state.get('sequence', 0)
                return frontier, all_links, last_fetch_time, count
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
                print(f'断点恢复失败, 重新开始 {error}')

        frontier = []
        if isinstance(start_urls, str):
            start_urls = [start_urls]
        
        start_urls = list(dict.fromkeys(start_urls))
        for url in start_urls:
            self.push_url(frontier, url, self.calc_priority(url))
        return frontier, set(start_urls), dict(), 0

if __name__ == "__main__":
    start_urls = [
        'http://pd.ruc.edu.cn/',
        'http://sph.ruc.edu.cn/',
        'https://clr.ruc.edu.cn/',
        'http://dis.ruc.edu.cn/',
        'http://dsdj.ruc.edu.cn/',
        'http://scsce.ruc.edu.cn/',
        'http://isbd.ruc.edu.cn/',
        'http://sis.ruc.edu.cn/',
        'http://info.ruc.edu.cn/',
        'http://www.phys.ruc.edu.cn/',
        'http://psy.ruc.edu.cn/',
        'http://guoxue.ruc.edu.cn/',
        'https://envi.ruc.edu.cn/',
        'http://ai.ruc.edu.cn/', 
        'https://gsai.ruc.edu.cn'
    ]
    crawl_tester = Crawler(start_urls=start_urls, wait_time=1,
                           max_count=200000)