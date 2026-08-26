from day1.ExtractHTML import ExtractHTML
from collections import defaultdict
import json
import os

class Inverted_index:
    def __init__(self, url_index, docID_path, inverted_index_path, remake = False):
        if remake or not os.path.exists(docID_path):  # 新建 docID
            self.make_docID(url_index, docID_path)
        if not remake and os.path.exists(inverted_index_path): # 倒排索引已经被构建过
            self.load_inverted_index(inverted_index_path)
            return
        
        # 构建倒排索引
        self.make_inverted_index(docID_path)
        self.save_inverted_index(inverted_index_path)

    def make_docID(self, url_index, file_path):
        temp_path = file_path + '.tmp'
        if os.path.exists(temp_path):
            os.remove(temp_path)
        docid, done_url = 0, set()
        try:
            with open(url_index, 'r', encoding='utf-8') as r:
                for line in r:
                    state = json.loads(line)
                    url, file = state['url'], 'downloaded_html/' + state['file']
                    if url in done_url:
                        continue
                    done_url.add(url)
                    with open(temp_path, 'a', encoding='utf-8') as w:
                        w.write(json.dumps({'docID': docid, 'url': url, 'file': file}, ensure_ascii=False) + '\n')
                    docid += 1
            os.replace(temp_path, file_path)
        except Exception as error:
            print(f'docID 构建失败: {error}')

    def make_inverted_index(self, docID_path):
        self.inverted_index = defaultdict(lambda: [-1])
        with open(docID_path, 'r', encoding='utf-8') as r:
            for line in r:
                state = json.loads(line)
                url, file, docID = state['url'], state['file'], state['docID']
                with open(file, 'r', encoding='utf-8') as file_reader:
                    content = file_reader.read()
                html = ExtractHTML(content)
                _, _, _, title_words, doctitle_words, body_words = html.extract_title_and_body_words()
                for word in title_words + doctitle_words + body_words:
                    if docID != self.inverted_index[word][-1]:
                        self.inverted_index[word].append(docID)
    def save_inverted_index(self, inverted_index_path):
        output_dir = os.path.dirname(inverted_index_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(inverted_index_path, 'w', encoding='utf-8') as w:
            json.dump(self.inverted_index, w, ensure_ascii=False)
    def load_inverted_index(self, inverted_index_path):
        with open(inverted_index_path, 'r', encoding='utf-8') as r:
            data = json.load(r)
        self.inverted_index = defaultdict(lambda: [-1], data)

    def query_AND(self, ):
        pass
    def query_OR(self, ):
        pass

if __name__ == "__main__":
    url_index = 'downloaded_html/url_index.jsonl'
    docID_path = 'downloaded_html/docID.jsonl'
    inverted_index_path = 'inverted_index/inverted_index.jsonl'
    index_maker = Inverted_index(url_index, docID_path, inverted_index_path)