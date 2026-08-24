# Day 1 Task：AI 使用记录

## 一、使用目的

在完成 Day 1 Task 的过程中，我使用 AI 对代码进行检查、调试和改进。任务内容包括：从 HTML 文档中提取链接，以及提取文档标题和正文并进行中文分词。

AI 主要用于辅助发现代码中的边界情况、解释开发工具给出的类型提示，并验证修改后的程序能否正常运行。程序的最终结构、代码修改和结果确认由我完成。

## 二、具体使用情况

### 1. 检查初始实现

我向 AI 提供了 `day1.ipynb`，请其检查实现是否满足任务要求。AI 指出了以下问题：

- 初始代码是直接执行的脚本，没有封装成类或函数；
- 同时遍历嵌套的 `div` 和 `p` 可能重复提取正文；
- 使用标签的 `.string` 属性可能遗漏包含子标签的文本；
- 分词结果中可能出现空格和换行等无效词；
- 链接结果中包含 `javascript:;` 之类不能正常访问的值。

### 2. 改进程序结构

根据检查结果，我将功能封装为 `ExtractHTML` 类，并分别实现：

- `extract_links()`：提取 HTML 中的链接；
- `extract_title_and_body_words()`：提取标题、正文并进行分词。

在正文提取中，我使用 BeautifulSoup 的 `get_text()` 获取标签内部文本，并在使用 jieba 分词后过滤空白词，以减少文本遗漏和无效结果。

### 3. 解决 Pylance 类型提示

在调用 `href.strip()` 时，Pylance 提示 `href` 可能是 `AttributeValueList`，不能确定其一定具有 `strip()` 方法。AI 解释了这是 BeautifulSoup 类型标注造成的静态检查问题，并建议先判断返回值类型：

```python
href = anchor.get('href')
if not isinstance(href, str):
    continue
```

确认 `href` 是字符串后，再进行清理和过滤：

```python
href = href.strip()
if href and not href.lower().startswith('javascript:'):
    all_links.add(href)
```

采用该方法后，Pylance 类型提示消失，同时程序能够排除空链接和 `javascript:` 链接。

### 4. 运行环境与结果验证

我说明本任务使用 `conda html` 环境运行。AI 随后在该环境中检查了 BeautifulSoup、html5lib 和 jieba 的使用情况，并执行当前实现进行验证。

验证结果如下：

- 程序可以正常创建 `ExtractHTML` 对象并调用两个方法；
- 共提取到 77 个过滤后的唯一链接；
- 提取结果中不再包含 `javascript:` 链接；
- 文档标题能够正常提取和分词；
- 正文能够正常提取和分词；
- 正文分词结果中没有空白词；
- 原页面没有 `h1`、`h2`、`h3` 标签，因此对应标题列表为空，这属于输入文档本身的情况，并非程序错误。

## 三、AI 建议的采纳情况

我采纳了以下建议：

- 将代码封装为类及类方法；
- 使用 `get_text()` 代替 `.string` 提取文本；
- 使用 `isinstance(href, str)` 进行类型判断；
- 清理链接两端空白字符；
- 过滤空链接和 `javascript:` 链接；
- 过滤分词结果中的空白词；
- 在指定的 `conda html` 环境中重新验证程序。

## 四、使用说明与声明

AI 在本次任务中主要承担代码审查、错误解释和测试建议的作用。我根据任务要求理解并调整了代码，对最终实现和运行结果进行了确认。本文仅记录与 HTML 提取、中文分词、类型检查及运行验证有关的 AI 使用情况。
