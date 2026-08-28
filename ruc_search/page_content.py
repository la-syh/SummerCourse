from pathlib import Path
import re

from resiliparse.extract.html2text import extract_plain_text
from resiliparse.parse.encoding import detect_encoding
from resiliparse.parse.html import HTMLTree

def get_attribute(node, name: str) -> str:
    if node is None:
        return ""

    try:
        return str(node[name]).strip()
    except (KeyError, ValueError, TypeError):
        return ""


def extract_title(tree: HTMLTree) -> str:
    if tree.head is not None:
        selectors = [
            'meta[name="ArticleTitle"]',
            'meta[property="og:title"]',
            'meta[name="title"]',
        ]

        for selector in selectors:
            node = tree.head.query_selector(selector)
            title = get_attribute(node, "content")

            if title:
                return title

    if tree.body is not None:
        h1 = tree.body.query_selector("h1")

        if h1 is not None:
            title = h1.text.strip()

            if title:
                return title

    return (tree.title or "").strip()

def extract_page_content(
    html_path: str | Path,
) -> tuple[str, str]:
    try:
        html_bytes = Path(html_path).read_bytes()
    except OSError:
        return "", ""

    try:
        encoding = detect_encoding(html_bytes) or "utf-8"

        tree = HTMLTree.parse_from_bytes(
            html_bytes,
            encoding=encoding,
        )

        title = extract_title(tree)
        content = extract_plain_text(
            tree,
            main_content=False,
            preserve_formatting=True,
            links=False,
            alt_texts=False,
            form_fields=False,
            noscript=False,
            list_bullets=False,
        )
    except (TypeError, ValueError):
        return "", ""

    if not content:
        return title, ""

    # 清理行内多余空格，但保留换行，方便按段落分块。
    lines = []

    for line in content.splitlines():
        line = re.sub(
            r"[ \t]+",
            " ",
            line,
        ).strip()

        if line:
            lines.append(line)

    return title, "\n".join(lines)