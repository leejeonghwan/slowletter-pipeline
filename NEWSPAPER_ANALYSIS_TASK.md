# 신문 지면 분석 작업 지시서

> 이 파일은 별도 Claude 세션에서 신문 분석 작업을 이어갈 때 사용합니다.
> 작업 폴더: `slowletter-pipeline/`

---

## 프로젝트 개요

**SlowNews (slownews.net)** — 한국 주요 6개 신문의 지면 기사를 매일 수집·클러스터링·분석하여 기초자료 HTML을 생성하는 파이프라인입니다.

대상 언론사: 조선일보, 중앙일보, 동아일보, 한겨레, 경향신문, 한국일보

---

## 작업 흐름 (3단계)

### 1단계: 지면 기사 수집
```bash
python3 naver_newspaper_full_collect.py --date YYYYMMDD --max-links-per-press 140
```
- 네이버 뉴스 지면보기에서 6개 신문 전체 기사 수집
- 출력: `~/Downloads/newspaper_full_press_view_YYYYMMDD.csv`
- 컬럼: press, title, content, url, section 등

### 2단계: 클러스터링 + 기초자료 생성
```bash
python3 newspaper_cluster_materials.py --date YYYYMMDD
```
- TF-IDF 기반 제목+본문 유사도 → AgglomerativeClustering
- 클러스터별: 참여 언론사, 숫자/팩트, 직접 인용(발언자 포함), 온도차 분석
- 출력: `~/Downloads/newspaper_clusters_materials_YYYYMMDD.md`

### 2단계 대안: 통합 HTML 직접 생성
```bash
python3 generate_materials_v2_fixed.py newspaper_full_press_view_YYYYMMDD.csv --date YYYYMMDD
```
- CSV → 클러스터링 → 발언자/팩트 추출 → HTML 렌더링 (올인원)
- 출력: `~/Downloads/newspaper_clusters_materials_YYYYMMDD.html`
- **OPENCLO_HTML_GUIDE.md v3.1 규격 준수 필수**

### 별도: 오피니언 칼럼 분석
```bash
python3 naver_opinion_columns.py --max-pages 5 --max-articles 60
python3 naver_opinion_columns_incremental.py --prev-raw <이전CSV> --scan-pages 3
```
- 6개 신문 오피니언 칼럼 수집 + GPT-4o-mini로 핵심 주장/인용 추출
- `convert_opinion_columns_to_html.py`로 HTML 변환

---

## 핵심 파일 목록

| 파일 | 역할 |
|------|------|
| `naver_newspaper_full_collect.py` | 네이버 지면 기사 전체 수집 (6개 신문) |
| `newspaper_cluster_materials.py` | 클러스터링 + 기초자료 마크다운 생성 |
| `generate_materials_v2_fixed.py` | 통합 파이프라인: CSV → 클러스터링 → HTML (권장) |
| `convert_materials_to_html.py` | 마크다운 → HTML 변환 (v2의 렌더링 부분) |
| `naver_opinion_columns.py` | 오피니언 칼럼 수집 + LLM 추출 |
| `naver_opinion_columns_incremental.py` | 오피니언 증분 업데이트 |
| `convert_opinion_columns_to_html.py` | 오피니언 분석 HTML 변환 |
| `OPENCLO_HTML_GUIDE.md` | HTML 출력 규격서 (v3.1) — **반드시 먼저 읽을 것** |

---

## HTML 출력 규격 핵심 요약 (OPENCLO_HTML_GUIDE v3.1)

HTML 생성 전에 **반드시 `OPENCLO_HTML_GUIDE.md` 전문을 읽으세요.** 아래는 핵심만 발췌:

### 데이터 구조 우선 원칙
1. 먼저 Python dict/list로 데이터 구조를 만들고, 그 다음 HTML로 렌더링
2. 하나의 클러스터(기사) = 하나의 객체로 묶기
3. 원문 인용은 절대 자르지 말 것

### HTML 섹션 구조
- `<h2>주요 키워드</h2>` — 핵심 파악용 4개
- `<h2>쓸고퀄 디테일</h2>` — 단독/소수 기사 중 공적 가치 높은 것 최대 7개
- `<h2>오늘의 주요 이슈</h2>` — 클러스터 단위 15개
- 클러스터 상세 — 각 이슈의 팩트/인용/온도차/신문별 한줄

### 절대 하지 말 것
- ❌ `<li>` 태그를 `<ul>` 없이 단독 사용
- ❌ 숫자/팩트 `<ul>` 안에 발언/인용, 온도차, 신문별 한줄 섞기
- ❌ `nan`, `None`, 빈 문자열 HTML에 표시
- ❌ 섹션 제목을 `<p>` 대신 `<h2>` 미사용
- ❌ 기사 리드문·사진 캡션을 "발언"으로 분류
- ❌ 발언자를 모두 "(발언자 미상)"으로 처리
- ❌ 온도차를 피상적으로 쓰기 (신문명+구체적 프레임 차이 필수)

---

## 환경변수

```bash
export OPENAI_API_KEY="..."       # 오피니언 칼럼 LLM 추출용
export OPENAI_MODEL="gpt-4o-mini" # 기본값
```

---

## 현재 알려진 이슈 및 개선 포인트

### 발언자 추출 정확도
- `generate_materials_v2_fixed.py`에 정규식 기반 발언자 추출 로직 있음
- 직책 패턴(`TITLE_PATTERN`) + 불용어(`SPEAKER_STOPWORDS`) 조합
- **확인 불가능한 경우에만** "(발언자 미상)" 사용 — 전체의 절반 이상이면 로직 점검

### 클러스터 간 데이터 오염
- 관련 없는 기사가 같은 클러스터에 묶이는 문제 존재
- 클러스터링 후 검증 로직 강화 필요

### 온도차·신문별 한줄 품질
- 온도차: 신문명을 명시하고 각 신문의 구체적 프레임 차이를 써야 함
- 신문별 한줄: 참여 신문 전부 기재, 각 신문만의 앵글 한줄씩

---

## 최근 변경사항 (2026-03-06)

### 슬로우레터 파이프라인 (slownews.net)
- **제목 변경 감지** 추가: `step2_entities()`에서 ID는 같지만 제목이 바뀐 경우 재추출
- **2일분 리프레시**: 최근 2일분 엔티티 삭제 후 재추출 (당일 수정 반영)
- **벡터 2일분 리프레시**: `indexing/embedder.py`의 `delete_recent_points(days=2)`
- **고아 ID 제거**: 아카이브에 없는 기존 엔티티 자동 정리
- **배포 경로 확인**: `data/raw/slowletter_web.csv` → `/var/www/slownews/data/context/slowletter_web.csv`

### OpenClaw 상태
- `MEMORY.md` 미생성 — 매 세션마다 장기 기억 없이 시작하는 상태
- `BOOTSTRAP.md` 미삭제 — 초기 설정 후 삭제해야 하나 아직 남아 있음
- `OPENCLO_STATUS.md` — 3월 2일 기준, 금일 변경사항 미반영

---

## 이 파일 사용법

1. 새 Claude 세션(별도 창)을 열고 이 파일을 컨텍스트로 제공
2. 오늘 날짜의 신문 분석 작업 요청 (예: "오늘자 지면 분석 해주세요")
3. 필요시 `OPENCLO_HTML_GUIDE.md` 참조하여 HTML 품질 검수
4. 결과물은 `~/Downloads/`에 저장됨
