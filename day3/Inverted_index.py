import day1.ExtractHTML
import json
import os

class Inverted_index:
    def __init__(self, url_index, docID_path):
        self.make_docID(url_index, docID_path)

    def make_docID(self, url_index, file_path):
        temp_path = file_path + '.tmp'
        if os.path.exists(temp_path):
            os.remove(temp_path)
        docid, done_url = 0, set()
        try:
            with open(url_index, 'r', encoding='utf-8') as r:
                for line in r:
                    state = json.loads(line)
                    url, file = state['url'], state['file']
                    if url in done_url:
                        continue
                    done_url.add(url)
                    docid += 1
                    state['docID'] = docid
                    with open(temp_path, 'a', encoding='utf-8') as w:
                        w.write(json.dumps(state, ensure_ascii=False) + '\n')
            os.replace(temp_path, file_path)
        except Exception as error:
            print(f'docID 构建失败: {error}')
    def query_AND(self, ):
        pass
    def query_OR(self, ):
        pass

if __name__ == "__main__":
    url_index = 'downloaded_html/url_index.jsonl'
    docID_path = 'downloaded_html/docID.jsonl'
    index_maker = Inverted_index(url_index, docID_path)