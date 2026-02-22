"""
Kiwi 형태소 분석 기반 BM25 인덱스
- 한국어 교착어 특성을 고려한 형태소 분석
- 명사/동사/형용사 위주 토큰화
"""
from __future__ import annotations
import csv
import pickle
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

try:
    from kiwipiepy import Kiwi
    HAS_KIWI = True
except ImportError:
    HAS_KIWI = False
    print("Warning: kiwipiepy not installed. Falling back to simple tokenizer.")
    print("Install: pip install kiwipiepy")


class KiwiBM25:
    """Kiwi 형태소 분석 기반 BM25 검색 엔진"""

    # BM25 파라미터
    K1 = 1.5
    B = 0.75

    def __init__(self):
        if HAS_KIWI:
            self.kiwi = Kiwi()
        else:
            self.kiwi = None

        self.doc_ids: list[str] = []
        self.doc_metadata: list[dict] = []
        self.doc_tokens: list[list[str]] = []
        self.df: Counter = Counter()  # Document frequency
        self.doc_lengths: list[int] = []
        self.avg_doc_length: float = 0.0
        self.n_docs: int = 0

        # 역인덱스
        self.inverted_index: dict[str, list[tuple[int, int]]] = defaultdict(list)

    def tokenize(self, text: str) -> list[str]:
        """텍스트를 형태소 분석하여 토큰 리스트를 반환합니다.

        주의:
        - Kiwi는 한국인 인명(예: "김/낙/호")을 1글자 단위로 쪼개는 경우가 있어,
          기존 규칙(1글자 한국어 제외)을 그대로 적용하면 인명 검색이 거의 불가능해집니다.
        - 그래서 "연속된 1글자 명사(NN*)"는 합쳐서(예: 김+낙+호 → 김낙호) 토큰으로 추가합니다.
        """
        if self.kiwi:
            result = self.kiwi.tokenize(text)

            tokens: list[str] = []
            hangul_nn_1char_buf: list[str] = []

            def flush_buf():
                nonlocal hangul_nn_1char_buf, tokens
                if len(hangul_nn_1char_buf) >= 2:
                    tokens.append("".join(hangul_nn_1char_buf))
                hangul_nn_1char_buf = []

            for token in result:
                tag = token.tag
                form = token.form.lower()

                is_hangul_1char_nn = (
                    tag.startswith("NN")
                    and len(form) == 1
                    and ('가' <= form <= '힣')
                )

                if is_hangul_1char_nn:
                    hangul_nn_1char_buf.append(form)
                    continue

                # 버퍼를 끊는 지점
                flush_buf()

                # 명사(NNG, NNP), 동사(VV), 형용사(VA), 외래어(SL/SH) 등
                if tag.startswith(("NN", "VV", "VA", "SL", "SH")):
                    # 1글자 한국어는 노이즈가 많아 기본적으로 제외하되,
                    # 외래어(SL)는 1글자여도 남긴다.
                    if len(form) >= 2 or tag.startswith(("SL", "SH")):
                        tokens.append(form)

            flush_buf()
            return tokens

        # Fallback: 간단한 공백 분리
        return [w.lower() for w in text.split() if len(w) >= 2]

    def build_index(self, doc_ids: list[str], texts: list[str], metadata: list[dict]):
        """BM25 인덱스를 구축합니다."""
        self.doc_ids = doc_ids
        self.doc_metadata = metadata
        self.n_docs = len(doc_ids)

        print(f"Tokenizing {self.n_docs} documents...")
        for i, text in enumerate(texts):
            tokens = self.tokenize(text)
            self.doc_tokens.append(tokens)
            self.doc_lengths.append(len(tokens))

            # DF 계산 (문서당 한 번만)
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self.df[token] += 1

            # 역인덱스 구축
            tf = Counter(tokens)
            for token, count in tf.items():
                self.inverted_index[token].append((i, count))

            if (i + 1) % 5000 == 0:
                print(f"  Processed {i + 1}/{self.n_docs}")

        self.avg_doc_length = sum(self.doc_lengths) / self.n_docs if self.n_docs > 0 else 1.0
        print(f"Index built: {len(self.df)} unique tokens, avg doc length: {self.avg_doc_length:.1f}")

    def search(
        self,
        query: str,
        top_k: int = 10,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> list[dict]:
        """BM25 검색을 수행합니다."""
        query_tokens = self.tokenize(query)
        if not query_tokens:
            return []

        scores = defaultdict(float)

        for token in query_tokens:
            if token not in self.inverted_index:
                continue

            # IDF
            df = self.df[token]
            idf = math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)

            for doc_idx, tf in self.inverted_index[token]:
                # 날짜 필터
                if date_start or date_end:
                    doc_date = self.doc_metadata[doc_idx].get("date", "")
                    if date_start and doc_date < date_start:
                        continue
                    if date_end and doc_date > date_end:
                        continue

                # BM25 점수
                doc_len = self.doc_lengths[doc_idx]
                tf_norm = (tf * (self.K1 + 1)) / (
                    tf + self.K1 * (1 - self.B + self.B * doc_len / self.avg_doc_length)
                )
                scores[doc_idx] += idf * tf_norm

        # 정렬 및 상위 K개 반환
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        results = []
        for doc_idx, score in ranked:
            meta = self.doc_metadata[doc_idx]
            results.append({
                "doc_id": self.doc_ids[doc_idx],
                "score": score,
                "date": meta.get("date", ""),
                "title": meta.get("title", ""),
                "content": meta.get("content", ""),
                "persons": meta.get("persons", ""),
                "organizations": meta.get("organizations", ""),
                "concepts": meta.get("concepts", ""),
            })

        return results

    def save(self, path: str):
        """인덱스를 파일로 저장합니다."""
        data = {
            "doc_ids": self.doc_ids,
            "doc_metadata": self.doc_metadata,
            "doc_tokens": self.doc_tokens,
            "df": dict(self.df),
            "doc_lengths": self.doc_lengths,
            "avg_doc_length": self.avg_doc_length,
            "n_docs": self.n_docs,
            "inverted_index": dict(self.inverted_index),
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)
        print(f"BM25 index saved: {path}")

    def load(self, path: str):
        """파일에서 인덱스를 로드합니다."""
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.doc_ids = data["doc_ids"]
        self.doc_metadata = data["doc_metadata"]
        self.doc_tokens = data["doc_tokens"]
        self.df = Counter(data["df"])
        self.doc_lengths = data["doc_lengths"]
        self.avg_doc_length = data["avg_doc_length"]
        self.n_docs = data["n_docs"]
        self.inverted_index = defaultdict(list, data["inverted_index"])
        print(f"BM25 index loaded: {self.n_docs} docs, {len(self.df)} tokens")


def build_bm25_index(csv_path: str, index_path: str):
    """CSV에서 BM25 인덱스를 구축합니다."""
    print("=== BM25 Index Build ===")

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    doc_ids = []
    texts = []
    metadata = []

    for row in rows:
        doc_id = row.get("ID", "")
        title = row.get("title", "")
        content = row.get("cleaned_content_for_api", "")
        if not doc_id or not content:
            continue

        doc_ids.append(doc_id)
        # 제목 + 콘텐츠 + 엔티티 통합
        full_text = f"{title} {content}"
        persons = row.get("solar_persons", "")
        orgs = row.get("solar_organizations", "")
        if persons:
            full_text += f" {persons}"
        if orgs:
            full_text += f" {orgs}"
        texts.append(full_text)
        metadata.append({
            "date": row.get("date", "")[:10],
            "title": title,
            "content": content,
            "persons": persons,
            "organizations": orgs,
            "concepts": row.get("solar_concepts", ""),
        })

    bm25 = KiwiBM25()
    bm25.build_index(doc_ids, texts, metadata)
    bm25.save(index_path)

    print("=== Build Complete ===")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python bm25_index.py <csv_path> <index_path>")
        sys.exit(1)
    build_bm25_index(sys.argv[1], sys.argv[2])
