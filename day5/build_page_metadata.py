import json
import re
from pathlib import Path

from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC_ID_PATH = PROJECT_ROOT / "downloaded_html" / "docID.jsonl"
OUTPUT_PATH = PROJECT_ROOT / "inverted_index" / "page_metadata.jsonl"


def clean_text(text: str) -> str:
    """合并连续空白字符。"""
    return re.sub(r"\s+", " ", text).strip()


def get_meta_content(soup: BeautifulSoup, attributes: list[dict]) -> str:
    for attrs in attributes:
        node = soup.find("meta", attrs=attrs)
        if node is None:
            continue

        content = node.get("content")
        if isinstance(content, str) and content.strip():
            return clean_text(content)

    return ""


def extract_page_info(html_path: Path, url: str) -> dict:
    html = html_path.read_bytes()
    soup = BeautifulSoup(html, "html.parser")

    title = get_meta_content(
        soup,
        [
            {"name": "citation_title"},
            {"property": "og:title"},
            {"name": "twitter:title"},
        ],
    )

    if not title and soup.title is not None:
        title = clean_text(soup.title.get_text(" ", strip=True))

    if not title:
        title = url

    abstract = get_meta_content(
        soup,
        [
            {"name": "citation_abstract"},
            {"name": "description"},
            {"property": "og:description"},
            {"name": "twitter:description"},
        ],
    )

    # 页面没有 description 时，用正文前 200 个字符作为摘要
    if not abstract:
        paragraphs = [
            node.get_text(" ", strip=True)
            for node in soup.find_all("p")
        ]
        body_text = clean_text(" ".join(paragraphs))
        abstract = body_text[:200]

    return {
        "title": title,
        "abstract": abstract,
    }


def build_metadata() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = OUTPUT_PATH.with_suffix(".jsonl.tmp")

    success_count = 0
    failure_count = 0

    with (
        DOC_ID_PATH.open("r", encoding="utf-8") as reader,
        temp_path.open("w", encoding="utf-8") as writer,
    ):
        for line in reader:
            document = json.loads(line)

            doc_id = document["docID"]
            url = document["url"]
            html_path = PROJECT_ROOT / document["file"]

            try:
                page_info = extract_page_info(html_path, url)
                success_count += 1
            except Exception as error:
                print(f"处理失败: docID={doc_id}, 原因={error}")
                page_info = {
                    "title": url,
                    "abstract": "",
                }
                failure_count += 1

            record = {
                "docID": doc_id,
                "url": url,
                **page_info,
            }

            writer.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )

    temp_path.replace(OUTPUT_PATH)

    print(f"元数据已保存到: {OUTPUT_PATH}")
    print(f"成功: {success_count}, 失败: {failure_count}")


if __name__ == "__main__":
    build_metadata()