from .extractor import ExtractHTML
import requests
import heapq
import time
from urllib.parse import urlparse, unquote, parse_qs
import json
import os
import hashlib
from collections import deque
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

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
        self.saved_urls = self.load_saved_urls()
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
        hostnames = {urlparse(url).hostname for url in self.start_urls}

        self.recover_saved_redirects(frontier, hostnames)

        for start_url in self.start_urls:
            if start_url in self.all_links:
                continue
            self.all_links.add(start_url)
            self.sequence += 1
            item = (
                -self.calc_priority(start_url),
                self.sequence,
                start_url,
            )
            heapq.heappush(frontier, item)  # 修正 https://clr.ruc.edu.cn/zwwz/index.htm

        host_frontiers, host_rotation, scheduled_hosts = {}, deque(), set()
        for item in sorted(frontier):
            self.add_host_item(host_frontiers, host_rotation, scheduled_hosts, item)

        try:
            while host_rotation and count < self.max_count:
                _, _, url = self.pop_host_url(host_frontiers, host_rotation, scheduled_hosts)
                if self.is_ignored_file(url):
                    print(f'跳过文件 {url}')
                    continue
                count += 1
                print(f'[{count} / {self.max_count}] '
                    f'正在访问 {url}', flush=True)
                self.wait_for_host(url)
                result = self.get_html(url, headers=self.headers, timeout=(3, 5))
                self.record_host_fetch(url)
                if result is not None:
                    html, final_url = result
                    if urlparse(final_url).hostname not in hostnames:
                        print(f'跳过重定向到站外的页面: {final_url}')
                    else:
                        self.all_links.add(final_url)
                        if final_url not in self.saved_urls:
                            self.save_html(final_url, html)
                            self.saved_urls.add(final_url)
                            links = ExtractHTML(html).extract_links(final_url)
                            
                            for new_url in links:
                                if self.is_ignored_file(new_url):
                                    print(f'跳过文件 {new_url}')
                                    continue
                                if new_url in self.all_links or urlparse(new_url).hostname not in hostnames:
                                    continue
                                self.all_links.add(new_url)
                                self.push_host_url(
                                    host_frontiers, host_rotation, scheduled_hosts,
                                    new_url, self.calc_priority(new_url, final_url)
                                    )
                if count % self.save_interval == 0:
                    self.save_checkpoint(self.flatten_host_frontiers(host_frontiers), count)
                    remaining_count = sum(len(host_queue) for host_queue in host_frontiers.values())
                    print(f'已保存断点, 共 {count} 个页面, 剩余 {remaining_count} 个页面')
        except KeyboardInterrupt:
            print(f'程序被中断, 断点已保存')
        finally:
            current_frontier = self.flatten_host_frontiers(host_frontiers)
            self.save_checkpoint(current_frontier, count)

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
                return response.content, response.url
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

    def add_host_item(self, host_frontiers, host_rotation, scheduled_hosts, item):
        _, _, url = item
        hostname = urlparse(url).hostname
        if not hostname:
            return
        host_queue = host_frontiers.setdefault(hostname, [])
        heapq.heappush(host_queue, item)
        if hostname not in scheduled_hosts:
            host_rotation.append(hostname)
            scheduled_hosts.add(hostname)

    def pop_host_url(self, host_frontiers, host_rotation, scheduled_hosts):
        hostname = host_rotation.popleft()
        scheduled_hosts.remove(hostname)
        host_queue = host_frontiers[hostname]
        item = heapq.heappop(host_queue)

        if host_queue:
            host_rotation.append(hostname)
            scheduled_hosts.add(hostname)
        else:
            del host_frontiers[hostname]
        return item

    def push_host_url(self, host_frontiers, host_rotation, scheduled_hosts, url, priority):
        self.sequence += 1
        item = (-priority, self.sequence, url)
        self.add_host_item(host_frontiers, host_rotation, scheduled_hosts, item)

    def flatten_host_frontiers(self, host_frontiers):
        return [item for host_queue in host_frontiers.values() for item in host_queue]

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
            'sequence': self.sequence,
            'redirect_recovery_version': self.redirect_recovery_version,
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
                self.redirect_recovery_version = state.get(
                    'redirect_recovery_version',
                    0,
                )
                return frontier, all_links, last_fetch_time, count
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
                print(f'断点恢复失败, 重新开始 {error}')

        frontier = []
        if isinstance(start_urls, str):
            start_urls = [start_urls]
        
        start_urls = list(dict.fromkeys(start_urls))
        for url in start_urls:
            self.sequence += 1
            item = (-self.calc_priority(url), self.sequence, url)
            heapq.heappush(frontier, item)
        self.redirect_recovery_version = 1
        return frontier, set(start_urls), dict(), 0

    def recover_saved_redirects(self, frontier, allowed_hostnames):
        '''从已经保存的 HTML 中一次性找回以前漏掉的静态跳转。'''
        if self.redirect_recovery_version >= 1:
            return
        if not os.path.exists(self.url_index_file):
            self.redirect_recovery_version = 1
            return

        html_root = os.path.abspath(self.html_dir)
        indexed_pages = {}
        try:
            with open(self.url_index_file, 'r', encoding='utf-8') as index_file:
                for line in index_file:
                    try:
                        record = json.loads(line)
                        indexed_pages[record['file']] = record['url']
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue
        except OSError as error:
            print(f'读取 HTML 索引失败，跳过跳转恢复: {error}')
            return

        recovered_count = 0
        for relative_path, source_url in indexed_pages.items():
            file_path = os.path.abspath(os.path.join(self.html_dir, relative_path))
            try:
                if os.path.commonpath((html_root, file_path)) != html_root:
                    continue
                with open(file_path, 'rb') as html_file:
                    html = html_file.read()
            except (OSError, ValueError):
                continue

            lower_html = html.lower()
            if b'location.href' not in lower_html \
                    and b'location.replace' not in lower_html \
                    and b'http-equiv' not in lower_html:
                continue

            redirect_links = ExtractHTML(html).extract_redirect_links(source_url)
            for new_url in redirect_links:
                hostname = urlparse(new_url).hostname
                if (new_url in self.all_links
                        or hostname not in allowed_hostnames
                        or self.is_ignored_file(new_url)):
                    continue
                self.all_links.add(new_url)
                self.sequence += 1
                heapq.heappush(
                    frontier,
                    (
                        -self.calc_priority(new_url, source_url),
                        self.sequence,
                        new_url,
                    ),
                )
                recovered_count += 1

        self.redirect_recovery_version = 1
        print(f'从已保存 HTML 中恢复 {recovered_count} 个跳转目标')
    def load_saved_urls(self):
        saved_urls = set()

        if not os.path.exists(self.url_index_file):
            return saved_urls

        try:
            with open(
                self.url_index_file,
                'r',
                encoding='utf-8',
            ) as index_file:
                for line in index_file:
                    try:
                        record = json.loads(line)
                        url = record.get('url')
                        if isinstance(url, str):
                            saved_urls.add(url)
                    except json.JSONDecodeError:
                        continue
        except OSError as error:
            print(f'读取已保存 URL 失败: {error}')

        return saved_urls

if __name__ == "__main__":
    start_urls = [
        'http://pd.ruc.edu.cn/',
        'http://sph.ruc.edu.cn/',
        'https://clr.ruc.edu.cn/zwwz/index.htm',
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
                           max_count=200000,
                           checkpoint_file=str(
                               PROJECT_ROOT / 'crawler_checkpoint.json'
                           ),
                           html_dir=str(
                               PROJECT_ROOT / 'downloaded_html'
                           ))
