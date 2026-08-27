from day1.ExtractHTML import ExtractHTML
from collections import defaultdict
from collections import Counter
from math import log10, sqrt
import json
import os
import jieba

class Inverted_index:
    '''
    {
        "document_count": 15947,
        "docID2url": {
            '0': "https://clr.ruc.edu.cn/"
            ... 
        }
        "terms": {
            "人工智能": {
                "df": 120,
                "idf": 2.12, 
                "postings": [
                    {"docID": 3, "tf": 2},
                    {"docID": 15, "tf": 4},
                    ...
                ]
            }
        },
        "doc_lengths":[
            12.34,
            8.91
        ]
    }
    '''
    def __init__(self, docID_path, index_path, stopwords_path=None, remake=False):
        self.stopwords = self.load_stopwords(stopwords_path)
        self.document_count = 0
        self.docID2url = dict()

        if not remake and os.path.exists(index_path):
            self.load_index(index_path)
            return

        self.terms = defaultdict(lambda: dict())
        self.doc_lengths = []
        self.build_index(docID_path)
        self.calc_doc_lengths()
        self.save_index(index_path)
        
    def load_stopwords(self, stopwords_path):
        if stopwords_path is None:
            return set()
        with open(stopwords_path, 'r', encoding='utf-8') as r:
            return {line.strip().casefold() for line in r if line.strip()}
    def normalize_words(self, words: list[str])-> list[str]:
        result = []
        for raw_word in words:
            word = raw_word.strip().casefold()
            if not word or word in self.stopwords:
                continue
            result.append(word)
        return result
    def build_index(self, docID_path):
        # init self.terms
        with open(docID_path, 'r', encoding='utf-8') as docID_reader:
            for line in docID_reader:
                state = json.loads(line)
                docID, url, file = state['docID'], state['url'], state['file']
                self.document_count += 1
                self.docID2url[docID] = url
                with open(file, 'r', encoding='utf-8') as file_reader:
                    content = file_reader.read()
                html = ExtractHTML(content)
                _, _, _, title_words, doctitle_words, body_words = html.extract_title_and_body_words()
                # words = self.normalize_words(title_words + doctitle_words + body_words)
                # term_counts = Counter(words)
                title_counts = Counter(self.normalize_words(title_words))
                doctitle_counts = Counter(self.normalize_words(doctitle_words))
                body_counts = Counter(self.normalize_words(body_words))
                all_terms = (set(title_counts) | set(doctitle_counts) | set(body_counts))

                for word in all_terms:
                    tf = title_counts[word] + doctitle_counts[word] + body_counts[word]
                    weighted_tf = 3 * title_counts[word] + 2 * doctitle_counts[word] + 1 * body_counts[word]
                    term_data = self.terms.setdefault(word, {'df': 0, 'postings': []})
                    term_data['df'] += 1
                    term_data['postings'].append({'docID': docID, 'tf': tf, 'weighted_tf': weighted_tf})

                # for word, tf in term_counts.items():
                #     term_data = self.terms.setdefault(word, {'df': 0, 'postings': []})
                #     term_data['df'] += 1
                #     term_data['postings'].append({'docID': docID, 'tf': tf})
            for term_data in self.terms.values():
                term_data['idf'] = self.idf(term_data['df']);
    def calc_doc_lengths(self):
        self.doc_lengths = [.0] * self.document_count
        for term_data in self.terms.values():
            for posting in term_data['postings']:
                docID = posting['docID']
                # tf = posting['tf']
                tf = posting['weighted_tf']

                weight = self.log_tf(tf) * term_data['idf']
                self.doc_lengths[docID] += weight ** 2
        self.doc_lengths = [sqrt(value) for value in self.doc_lengths]

    def save_index(self, index_path):
        output_dir = os.path.dirname(index_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        temp_path = index_path + '.tmp'

        state = {
            'document_count': self.document_count,
            'terms': self.terms,
            'doc_lengths': self.doc_lengths,
            'docID2url': self.docID2url
        }
        try:
            with open(temp_path, 'w', encoding='utf-8') as file_writer:
                json.dump(state, file_writer, ensure_ascii=False)
            os.replace(temp_path, index_path)
        except Exception as error:
            print(f'保存失败, 原因: {error}')
            raise
    def load_index(self, index_path):
        try:
            with open(index_path, 'r', encoding='utf-8') as reader:
                state = json.load(reader)
            self.document_count = state['document_count']
            self.terms = state['terms']
            self.doc_lengths = state['doc_lengths']
            self.docID2url = state['docID2url']
        except Exception as error:
            print(f'读取 {index_path} 失败, 原因: {error}')
            raise

    def log_tf(self, tf):
        return 0 if tf == 0 else 1 + log10(tf)
    def idf(self, df):
        return log10(self.document_count / df)

    def query(self, sentence: str, k = 10):
        if not isinstance(sentence, str):
            raise TypeError('sentence 必须是字符串')
        if not isinstance(k, int):
            raise TypeError('k 必须是整数')
        if k <= 0:
            return []

        query_terms = Counter(term for term in self.normalize_words(jieba.lcut_for_search(sentence)))
        scores = defaultdict(float)
        query_length = 0.
        for term, query_tf in query_terms.items():
            if term not in self.terms:
                continue
            term_data = self.terms[term]
            idf = term_data['idf']
            query_weight = self.log_tf(query_tf) * idf
            if query_weight == 0:
                continue
            query_length += query_weight ** 2
            for posting in term_data['postings']:
                # doc_weight = self.log_tf(posting['tf']) * idf
                doc_weight = self.log_tf(posting['weighted_tf']) * idf
                scores[posting['docID']] += query_weight * doc_weight
        query_length = sqrt(query_length)
        if query_length == 0:
            return []

        results:list[tuple[int, float]] = [(docid, score / self.doc_lengths[docid] / query_length)
                                            for docid, score in scores.items() 
                                            if self.doc_lengths[docid] != 0]
        results.sort(key=lambda x: x[1], reverse=True)
        return [self.docID2url[str(docID)] for docID, score in results[:k]]


if __name__ == "__main__":
    docID_path = 'downloaded_html/docID.jsonl'
    index_path = 'inverted_index/inverted_index.json'
    stopwords_path = 'stopwords.txt'
    tester = Inverted_index(docID_path, index_path, stopwords_path, remake=False)
    try:
        while True:
            question = input()
            print(tester.query(question))
            print('')
    except KeyboardInterrupt:
        pass