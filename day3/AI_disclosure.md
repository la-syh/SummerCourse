# Day 3 Task：AI 使用记录

## 一、使用目的

在完成 Day 3 倒排索引作业的过程中，我使用 AI 辅助检查未完成的 `Inverted_index.py`，排查运行错误，并核对 docID 生成、倒排表构建、索引持久化和加载的逻辑。

本次协作以代码审查、错误解释和修改建议为主。AI 未直接修改 `Inverted_index.py`，代码的具体修改由我根据作业要求完成。

## 二、具体使用情况

### 1. 检查初始的倒排索引实现

我请 AI 检查尚未完成的 `Inverted_index.py` 是否正确。AI 对照 Day 3 课堂 notebook 和已保存的爬虫数据进行了检查，认为倒排表的核心构建思路基本正确：按 docID 顺序处理文档，并通过比较 postings list 的最后一个 docID，可以避免同一个词在同一文档中被重复记录。

AI 同时指出了以下问题：

- 已存在索引文件时直接从构造函数返回，但没有将索引读入 `self.inverted_index`；
- 输出目录不存在时，`open(..., 'w')` 不会自动创建父目录；
- 直接执行 `python day3/Inverted_index.py` 时，可能无法从同级目录导入 `day1`，应当从 `hw` 目录使用模块方式运行；
- HTML 文件路径硬编码为 `downloaded_html/`，因此依赖当前工作目录；
- `make_docID()` 捕获异常后只打印错误，可能使后续代码继续读取不存在或过期的文件；
- 未过滤空白、标点和其他无意义词项，会降低索引质量。

`query_AND()` 和 `query_OR()` 尚未完成，因此本阶段主要检查索引构建与保存逻辑。

### 2. 排查索引输出目录不存在的错误

使用模块方式运行后，程序在写入索引时报出：

```text
FileNotFoundError: [Errno 2] No such file or directory:
'inverted_index/inverted_index.jsonl'
```

AI 解释，`open()` 可以创建不存在的文件，但不会创建父目录，因此建议在写入前创建输出目录：

```python
output_dir = os.path.dirname(inverted_index_path)
if output_dir:
    os.makedirs(output_dir, exist_ok=True)
```

AI 还说明，终端中的 `Prefix dict has been built successfully.` 是 jieba 初始化成功的提示，不是异常。

### 3. 检查修改后的保存与加载逻辑

我增加了 `make_inverted_index()`、`save_inverted_index()` 和 `load_inverted_index()`，并加入 `remake` 参数。AI 再次检查后确认：

- 输出目录自动创建的问题已修复；
- docID 已改为从 0 开始，与课堂 notebook 保持一致；
- 已生成的索引文件是一个包含词项和 postings list 的完整 JSON 对象。

但新的保存实现遍历字典时，只将词项 key 写入文件，没有保存对应的 docID 列表。而加载时又使用 `json.load()` 将整个文件当作一个 JSON 对象，两者的文件格式不匹配。AI 建议直接保存完整字典：

```python
with open(inverted_index_path, 'w', encoding='utf-8') as w:
    json.dump(self.inverted_index, w, ensure_ascii=False)
```

加载时，`json.load()` 返回的是普通 `dict`。为了保留查询不存在词项时的默认 postings list，AI 建议重新包装为 `defaultdict`：

```python
with open(inverted_index_path, 'r', encoding='utf-8') as r:
    data = json.load(r)
self.inverted_index = defaultdict(lambda: [-1], data)
```

AI 还指出，主程序固定传入 `remake=True` 会在每次运行时重新构建并覆盖索引。完成调试后应改为 `False`，只在确实需要重建时才显式开启。

### 4. 检查 Python 环境

按照本项目的环境要求，AI 激活 `conda ML` 环境进行语法和运行检查。`Inverted_index.py` 的语法检查通过，但运行在导入 `BeautifulSoup` 时报出 `ModuleNotFoundError: No module named 'bs4'`。进一步检查显示当前 `ML` 环境没有 `beautifulsoup4` 包。这表明先前成功构建索引时可能使用了另一个 Python 环境，或者当前 `ML` 环境仍需补充依赖。

### 5. 使用停用词表过滤词项

我已经准备了 `stopwords.txt`，并询问如何在构建倒排索引时使用它。AI 检查后确认，该文件是 UTF-8 编码，共 1396 行，每行一个中文或英文停用词。

AI 建议在构建索引前只读取一次文件，并保存为 `set`，以便快速判断词项是否应被过滤。遍历分词结果时，先使用 `strip()` 清理词项，再跳过空字符串和停用词。如果希望英文停用词不区分大小写，还应对停用词和索引词项统一使用 `casefold()`，并在后续查询时使用相同的归一化规则。

由于已经存在未经停用词过滤的索引文件，实现过滤后需要使用 `remake=True` 重建一次索引；否则程序会直接加载旧索引，新的过滤逻辑不会生效。

### 6. 理解 `casefold()` 的作用

我进一步询问 `casefold()` 是否就是将大写字母转换为小写字母。AI 说明，对于普通英文可以这样理解，但 `casefold()` 比 `lower()` 更彻底，主要用于不区分大小写的 Unicode 文本比较。例如，`"Apple".casefold()` 得到 `"apple"`；对中文字符则基本没有影响。在倒排索引中使用它时，建立索引和处理查询词必须使用相同的归一化规则。

### 7. 检查单词查询和逻辑与查询

我编写了 `query()` 和基于有序 postings list 双指针合并的 `query_AND()`，但代码无法通过 Pylance 静态检查。AI 检查后指出，`query()` 使用 `[1:-1]` 会在删除开头哨兵值 `-1` 的同时误删最后一个真实 docID，正确切片应为 `[1:]`。查询词也应与建索引时一样执行 `strip().casefold()`。

`query_AND()` 中的主要问题是混淆了迭代器和迭代器当前取出的 docID：`iter(now_list)` 返回迭代器，而 `next(iter(...))` 只返回第一个整数；二者不能直接使用大小比较。此外，`next(p1, p2)` 的第二个参数是迭代结束时的默认返回值，不是“同时读取两个迭代器”。AI 建议将两个迭代器与两个当前 docID 分别保存，并补充空查询列表、元素类型和返回值的检查。

### 8. 复查逻辑与并实现逻辑或查询

我修正了 `query_AND()` 中的迭代器使用，并增加了 `query_OR()`，然后请 AI 再次检查。AI 通过语法编译检查确认当前文件没有 Python 语法错误，并确认 `query_AND()` 的双指针交集主体逻辑已基本正确。

AI 同时指出了三个待修正点：第一，`query()` 还没有对查询词执行 `strip().casefold()`，因而可能无法匹配建立索引时已归一化的词项；第二，`query_OR()` 在其中一个 postings list 耗尽后直接捕获 `StopIteration`，但没有将另一个列表的当前 docID 和剩余尾部加入结果，所以并集会丢失文档；第三，逻辑或中的 `if not now_list: break` 不成立，因为前面的查询词没有结果时，后面的查询词仍然可能有结果。AI 建议在逻辑或合并中使用整数下标，主循环结束后分别追加两个有序列表的剩余尾部。

### 9. 按 Day 3 任务要求进行最终验收

我请 AI 按照“实现倒排索引、支持 AND 和 OR 布尔查询、在 Day 2 抓取的网页上建立索引”三项要求进行最终检查。AI 没有再次触发完整索引重建，而是对已生成的数据和查询方法进行了只读验证和轻量单元测试。

验收结果如下：

- `url_index.jsonl` 和 `docID.jsonl` 都包含 15947 条记录；
- docID 从 0 到 15946 连续编号，且所有 docID 记录指向的本地 HTML 文件都存在；
- 已生成的倒排索引包含 170665 个词项；
- 每个 postings list 都以 `-1` 开头，后续 docID 升序、无重复且不越界；
- 停用词集合与倒排索引词项没有交集，说明停用词过滤已应用到当前索引；
- `query()` 能处理查询词两端空白和英文大小写，并在词项不存在时返回空列表；
- `query_AND()` 和 `query_OR()` 通过了空输入、单词、多词、无结果词项和有序去重结果等测试。

AI 判断三项核心任务要求已经完成。尚存的非核心问题包括：`query_OR()` 的两条类型错误提示仍误写为 `query_AND`；程序仍依赖从 `hw` 目录启动时的相对路径；当前 `conda ML` 环境中缺少 `beautifulsoup4`，因此在该环境中直接导入完整模块仍需先补齐依赖。

## 三、AI 建议的采纳与待处理情况

目前已采纳的建议包括：

- 为索引输出文件自动创建父目录；
- 将构建、保存和加载倒排索引拆分为独立方法；
- 在索引已存在时尝试加载，而不是直接返回；
- 将 docID 改为从 0 开始。
- 统一索引的保存与加载格式，并在加载后恢复 `defaultdict`；
- 使用停用词表、`strip()` 和 `casefold()` 过滤并归一化词项；
- 完成单词查询、逻辑与查询和逻辑或查询；
- 将日常运行的 `remake` 设为 `False`。

仍待确认或处理的项目包括：

- 处理路径对当前工作目录的依赖；
- 将 `query_OR()` 的异常提示中误写的 `query_AND` 改为 `query_OR`；
- 确认并补齐 `conda ML` 环境中的 HTML 解析依赖。

## 四、使用说明与声明

AI 在本次作业中主要承担代码审查、异常原因分析、文件格式检查和修改建议的作用。我根据作业要求理解并选择是否采纳这些建议，并对最终代码和运行结果负责。

后续每次就 Day 3 作业与 AI 进行实质交流后，本文档将继续按实际交流和采纳情况更新。
