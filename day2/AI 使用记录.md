# Day 2 Task：AI 使用记录

## 一、使用目的

在完成 Day 2 爬虫任务的过程中，我使用 AI 辅助理解爬虫的基本结构，检查和调试代码，并逐步实现广度优先抓取、断点续传、URL 过滤、优先级调度、按主机限速以及 HTML 本地保存等功能。

本次协作以讨论、解释和代码审查为主。AI 根据我提出的问题分析现有代码、指出潜在错误，并给出修改建议；我根据任务要求决定是否采纳。例如，AI 曾说明定期重新抓取旧页面的实现方式，但我确认本任务不需要反复抓取，因此最终没有保留该功能。程序的功能范围和最终取舍由我确定。

## 二、具体使用情况

### 1. 实现爬虫断点续传

我首先询问如何实现断点续传。AI 检查初始代码后，建议保存以下运行状态：

- 待抓取 URL 队列；
- 已经发现的 URL 集合；
- 已处理页面数量；
- 后续加入的优先级及主机访问时间等调度信息。

断点使用 JSON 文件保存。为避免程序在写入过程中退出并留下不完整文件，采用先写临时文件、再使用 `os.replace()` 替换正式文件的方式：

```python
temp_file = self.checkpoint_file + '.tmp'
with open(temp_file, 'w', encoding='utf-8') as file:
    json.dump(state, file, ensure_ascii=False)
os.replace(temp_file, self.checkpoint_file)
```

程序使用 `try`、`except KeyboardInterrupt` 和 `finally`，从而在按下 `Ctrl+C` 时仍然保存当前状态。重新运行后，程序读取断点并继续处理剩余 URL。

### 2. 解决包导入问题

项目目录为：

```text
hw/
├── day1/
│   ├── __init__.py
│   └── day1.py
└── day2/
    ├── __init__.py
    └── day2.py
```

我在直接执行 `python day2/day2.py` 时遇到 `ModuleNotFoundError`。AI 解释，直接执行文件时 Python 主要从 `day2` 目录寻找模块，可能找不到同级的 `day1` 包。最终采用从 `hw` 目录按模块运行的方式：

```bash
conda activate html
python -m day2.day2
```

同时在相关目录中保留空的 `__init__.py`，明确将其作为 Python 包使用。

### 3. 检查初始抓取流程

AI 在检查初始代码时指出了几个关键问题：

- `set(url)` 会把 URL 拆成字符集合，应使用 `{url}`；
- `ExtractHTML(url)` 会把 URL 字符串本身当作 HTML，应先通过 `requests` 下载网页，再将返回的 HTML 交给 `ExtractHTML`；
- 使用 `q.popleft()` 才是广度优先队列，使用 `q.pop()` 实际更接近深度优先；
- `__str__()` 必须返回字符串，不能直接返回集合；
- 空的 `except:` 会隐藏超时和连接失败等原因，应捕获 `requests.RequestException` 并输出错误。

在后续版本中，抓取和解析流程调整为：

```python
html = self.get_html(url, headers=self.headers, timeout=(3, 5))
if html is not None:
    links = ExtractHTML(html).extract_links(url)
```

### 4. 排查程序“卡住”的原因

运行时，终端在一段时间内没有新输出，我询问程序是否卡住。AI 根据代码说明，程序可能正在等待网络请求、请求超时或执行固定的 `sleep()`，而日志只在处理若干页面后打印一次，因此看起来像停止运行。

为方便观察，程序改为每次请求前打印当前进度和 URL，并将超时设置为：

```python
timeout=(3, 5)
```

其中第一个值是连接超时，第二个值是读取超时。AI还建议使用 `flush=True` 及时刷新终端输出，并避免使用空异常捕获，以便区分网络等待和真正的程序错误。

### 5. 正确处理 URL

为了处理网页中的相对链接、片段和不同协议，AI解释并建议使用：

- `urljoin()`：将相对链接转换为完整 URL；
- `urldefrag()`：删除 `#section` 等页面片段，减少重复抓取；
- `urlparse()`：拆分协议、主机名、路径和查询参数；
- `url_normalize()`：规范化 URL，减少同一页面因写法不同而重复出现。

在 Day 1 的 `ExtractHTML.extract_links()` 中，链接处理流程最终包括：检查 `href` 类型、去除空白、补全相对地址、删除片段、限制为 HTTP/HTTPS，并进行规范化。

### 6. 过滤压缩包和其他非 HTML 文件

我提出不希望访问 ZIP 等文件。最初只检查 `parsed.path`，但运行时发现下面这种 URL 仍会被访问：

```text
https://www.ruc.edu.cn/cms-proxy/file/download?file=ppt模板.zip
```

AI指出 `.zip` 位于查询参数而不是路径中，因此程序需要同时检查路径和查询参数。最终使用 `urlparse()`、`parse_qs()` 和 `unquote()`，检查可能包含文件名的所有候选字符串：

```python
parsed = urlparse(url)
candidates = [unquote(parsed.path).lower()]

for values in parse_qs(parsed.query).values():
    for value in values:
        candidates.append(unquote(value).lower())
```

随后通过 `endswith()` 检查 ZIP、PDF、Office 文档、图片、音视频等后缀。

此外，AI说明仅根据 URL 不能完全判断资源类型。例如 `/download?id=123` 可能返回任意内容。因此请求使用 `stream=True`，先检查服务器返回的 `Content-Type`；只有 `text/html` 或 `application/xhtml+xml` 才继续读取正文。

### 7. 实现优先级抓取

任务要求优先抓取“更高质量”的页面。AI建议将普通 `deque` 替换为 `heapq` 优先队列，队列元素采用：

```python
(-priority, sequence, url)
```

因为 `heapq` 是最小堆，所以将优先级取负，使分数更高的页面更早出队。`sequence` 是每次 URL 入队时递增的编号，用于在优先级相同时保持发现顺序。它不能简单由已处理页面数 `count` 代替，因为同一个页面可能一次发现许多新链接，而这些链接需要不同的入队编号。

当前使用的启发式优先级包括：

- HTTPS 页面加分；
- 没有查询参数的 URL 加分；
- 路径越深，分数越低；
- 网站首页加分；
- 与来源页面属于同一主机的链接加分。

AI同时说明，这只是根据 URL 结构估计页面质量，并不等价于真正的内容质量或 PageRank。

### 8. 实现不同主机的独立访问间隔

为了避免连续快速请求同一网站，程序使用字典记录每个主机最近一次请求完成的时间：

```python
self.last_fetch_time = {}
```

访问前通过 `urlparse(url).hostname` 取得主机名，并只计算该主机的剩余等待时间。访问 `info.ruc.edu.cn` 不会直接沿用 `news.ruc.edu.cn` 的计时记录。请求成功或失败后都会更新时间，以避免持续请求发生故障的主机。

AI也说明了当前单线程实现的限制：如果最高优先级 URL 所属主机仍需等待，整个线程会暂停，而不会立即改抓另一个已就绪主机。考虑到本次作业的规模和实现复杂度，我保留了这一较简单的方案。

### 9. 保存 HTML 到本地

我明确提出不需要反复抓取旧页面，但需要在成功访问后保存 HTML。AI据此移除了定期重新抓取逻辑，并将 `get_html()` 的返回值保留为 `response.content` 字节。BeautifulSoup 可以直接解析字节，同时保存时不会强制把 GBK、UTF-8 等网页统一转换为另一种编码。

HTML 按主机名分类保存：

```text
downloaded_html/
├── url_index.jsonl
├── info.ruc.edu.cn/
└── news.ruc.edu.cn/
```

文件名使用 URL 的 SHA-256 哈希。AI解释，不能安全地直接用完整 URL 作为文件名，因为 URL 可能包含 `/`、`?`、`#` 等特殊字符，可能超过文件名长度限制，也可能出现同名覆盖或路径穿越问题。

`url_index.jsonl` 用于记录原 URL 和本地文件之间的对应关系。HTML 文件同样采用先写临时文件、再原子替换的方式保存。

### 10. 配置多个起始网站

我提供了中国人民大学多个学院网站作为起始页面。程序支持传入 URL 列表，并使用：

```python
start_urls = list(dict.fromkeys(start_urls))
```

在保持首次出现顺序的同时删除重复 URL。

调试过程中，AI发现起始 URL 字符串之间缺少逗号时，Python 会自动将相邻字符串拼接成一个无效的超长 URL。补充逗号后，AI通过 AST 检查确认列表中包含 15 个独立起始 URL。

### 11. 修复断点恢复的数据类型

优先队列在内存中的元素是元组，`all_links` 是集合；但 JSON 读取后，元组和集合都会表现为列表。AI指出，如果直接使用读取结果，会出现以下问题：

- 恢复后的 `frontier` 是列表元素，新入队元素是元组，二者比较时可能报错；
- 恢复后的 `all_links` 是列表，没有 `.add()` 方法，且查找效率降低。

因此恢复时使用：

```python
frontier = [tuple(item) for item in state.get('frontier', [])]
heapq.heapify(frontier)
all_links = set(state.get('all_links', []))
```

同时加入断点文件读取异常处理，避免损坏的 JSON 直接终止程序。

### 12. Git 版本管理问题排查

在准备推送代码时，我发现 Git 版本状态异常。AI通过只读检查发现：

- 仓库处于 `detached HEAD`；
- 最新提交没有归属到 `main`；
- 工作区存在旧文件删除但尚未提交；
- 新版爬虫仍可能引用已经删除的旧模块路径。

AI建议先建立备份分支，再将当前提交接到 `main`，并在提交删除前确认导入路径是否同步更新。该建议用于避免直接 `git add -A` 后把无法运行的版本推送到远程仓库。

## 三、AI 建议的采纳与调整情况

我采纳了以下建议：

- 使用模块方式运行 Day 2 程序；
- 使用队列或优先队列维护待抓取 URL；
- 使用集合进行 URL 去重；
- 使用 JSON 保存断点，并采用临时文件原子替换；
- 使用 `urljoin()`、`urldefrag()` 和 `urlparse()` 正确处理 URL；
- 同时检查 URL 路径、查询参数和响应 `Content-Type`；
- 使用 `heapq` 实现启发式优先抓取；
- 使用字典记录不同主机的最近访问时间；
- 保存 HTML 原始字节，并使用哈希文件名和 JSONL 索引；
- 恢复断点时重建元组、集合和堆结构；
- 在 `conda html` 环境中进行语法、导入、队列、断点和 HTML 保存测试；
- 在 Git 推送前检查分支状态、未提交删除和模块导入路径。

我根据任务实际要求调整或未采纳的建议包括：

- 不限制只能抓取 `ruc.edu.cn`，因为任务需要继续访问页面指向的外部网站；
- 不启用定期重新抓取旧页面，只进行一次性抓取和断点续传；
- 保留较简单的单线程按主机等待机制，没有实现多线程或复杂的主机调度器。

## 四、验证情况

AI在我指定的 `conda html` 环境中进行了不发起公网请求的检查，包括：

- Python 语法和依赖导入检查；
- 多起始 URL 初始化；
- `heapq` 优先队列入队和出队；
- ZIP 文件位于查询参数时的过滤；
- HTML 原始字节保存；
- URL 与文件索引生成；
- JSON 断点保存；
- 起始 URL 列表元素数量检查。

网络抓取本身具有外部网站状态、网络环境和服务器限流等不确定性，因此正式的大规模运行由我在本地环境中启动并观察。

## 五、使用说明与声明

AI在本次任务中主要承担需求澄清、概念解释、代码审查、错误定位、修改建议和局部验证工作。AI在获得文件写入授权后，也曾协助生成或修改部分代码文件；我根据课程要求决定最终保留的功能、文件结构、抓取范围和运行参数，并负责确认最终提交版本。

本文记录了我与 AI 围绕 Day 2 爬虫任务的主要协作过程。最终代码、运行结果和提交内容由我检查并负责。
