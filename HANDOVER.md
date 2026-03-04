# SlowNews Pipeline 인수인계 (2026-03-02 세션 5)

최종 업데이트: 2026-03-02

---

## 1. 현재 상태

- Git: `main` 브랜치, 서버 최신 커밋 `358b483` (자동 업데이트 2026-03-02)
- 로컬: `d241a26` (test_connection 재시도 + --rebuild-entity) — push 대기
- 서비스: slownews.net 정상 운영 중
- 데이터: 18,196건, 오늘(3/2) 31건 정상 반영
- 파이프라인: 매일 KST 08:15 자동 실행, 정상 작동 확인 완료

### 즉시 배포 명령어

```bash
cd ~/slowletter-pipeline && git push origin main && \
ssh -i slowkey.pem ubuntu@15.165.13.179 \
  'cd ~/slowletter-pipeline && git pull origin main && \
   sudo cp index.html /var/www/slownews/index.html && \
   sudo systemctl restart slownews-api slownews-app'
```

### 서버에서 수동 파이프라인 실행

```bash
ssh -i slowkey.pem ubuntu@15.165.13.179 \
  'cd ~/slowletter-pipeline && source .venv/bin/activate && set -a && source .env && set +a && python3 slowletter_pipeline.py --skip-crawl'
```

## 2. 이번 세션에서 한 작업 (세션 5)

### 2-1. test_connection() 재시도 로직 추가 (`d241a26`)

**slowletter_pipeline.py**
- 기존: Solar API 연결 테스트 1회 시도, 실패 시 즉시 False
- 변경: 최대 3회 재시도, 시도 간 5초·10초 대기, 실패 시 warning 로그 출력
- 실제 추출 호출의 SOLAR_MAX_RETRIES=10과 별개로, 초기 연결 확인만 3회 재시도

### 2-2. --rebuild-entity 옵션 추가 (`d241a26`)

**slowletter_pipeline.py**
- `--rebuild-entity` 플래그 추가: 기존 엔티티 결과를 무시하고 전체 재추출
- 사용법:
  - 신규분만 증분 추출: `python3 slowletter_pipeline.py --skip-crawl`
  - 전체 재추출: `python3 slowletter_pipeline.py --skip-crawl --rebuild-entity`
- 주의: 서버 코드가 SQLite DB 기반으로 이미 변경되어 있어, 이 옵션이 서버에서 실제 작동하는지 확인 필요

## 3. 세션 4 작업 (이미 서버 배포 완료)

### 3-1. 인덱스 정렬 옵션 마침표 추가 (`61d7f29`)

**index.html**
- 정렬 드롭다운: 최신순 → 최신순., 과거순 → 과거순., 관련도순 → 관련도순.

### 3-2. 사이드바 라디오 버튼 정렬 (`447d326`)

**app.py**
- CSS `padding-left: 0.75rem` 추가: 라디오 버튼을 "API 연결됨" 텍스트와 왼쪽 정렬

### 3-3. 검색 키워드 URL 파라미터 지원 (`66ca93c`)

**index.html**
- `?keyword=` URL 파라미터로 검색 결과 공유 가능
- `history.replaceState`로 URL 업데이트 (페이지 리로드 없음)
- `?date=`, `?doc=`, `?sort=` 파라미터도 지원
- `popstate` 이벤트로 브라우저 뒤로가기/앞으로가기 대응

### 3-4. 동적 제목 + 소셜 공유 OG 태그 (`07e2cc6`, `8f22929`, `2958ead`)

**index.html**
- 기본 제목: "슬로우레터 빠른 검색."
- 검색 시: "슬로우레터: {검색어}." (브라우저 탭 + document.title)

**api/main.py**
- `/finder` 엔드포인트 추가: `?keyword=` 요청 시 동적 OG 태그 생성
- og:title, og:description, og:url, twitter:title, twitter:description 동적 치환
- HTML 캐싱으로 서버 부하 최소화

**nginx 설정** (서버에서 직접 설정)
- `?keyword=` 요청을 FastAPI `/finder` 엔드포인트로 프록시

### 3-5. 크론 시간 변경

**ec2_daily_update.sh**
- `45 0 * * *` (KST 09:45) → `15 23 * * *` (KST 08:15)
- 서버 crontab도 변경 완료

### 3-6. 샘플 출력 정렬 수정

**update_service_content.py**
- `entities_df.head(3)` → `entities_df.sort_values("date", ascending=False).head(3)`
- 샘플이 항상 최신 데이터를 보여주도록 변경

## 4. 이전 세션 작업 (세션 1~3, 이미 배포 완료)

- **불렛 포맷 강화 + 검색 상한 해제** (`13874f5`): SYSTEM_PROMPT 규칙 강화, `initial_k` 자동 계산
- **인라인 불렛 강제 줄바꿈** (`51a6f96`, `5c3ca3a`): regex 후처리로 `\n\n` 줄바꿈 보장
- **공백 보존** (`d80b5e8`): `extract_li_content()`에서 `<span>` 태그 사이 공백 누락 수정
- **nan 엔티티 필터** (`4dd7bb4`): `_normalize_entities()` 진입점에서 nan 체크
- **일일 업데이트 스크립트** (`0f7d352`): 서비스명 수정 + CDN 캐시 버스팅
- **관련 기사 50건** (`4cb1ad6`): app.py `top_k=50`, `max_items=50`
- **물결표 이스케이프** (`cfe8222`): `~` → `\~` 마크다운 취소선 방지
- **답변 후처리** (`954aa76`): `_reformat_answer()` 2차 API 호출로 포맷 변환

## 5. 인프라

### EC2 서버
- IP: `15.165.13.179`, SSH key: `slowkey.pem`
- Python venv: `source ~/slowletter-pipeline/.venv/bin/activate`
- 환경변수: `.env` 파일 (`set -a && source .env && set +a`로 로드)

### Systemd 서비스
| 서비스명 | 역할 | 상태 |
|----------|------|------|
| `slownews-api` | FastAPI (포트 8000) | ✅ 사용 중 |
| `slownews-app` | Streamlit (포트 8510) | ✅ 사용 중 |
| `slowletter-api` | 구 API (충돌 원인) | ❌ 비활성화 대상 |
| `nginx` | 리버스 프록시 | ✅ 사용 중 |

⚠️ `slowletter-api`와 `slownews-api`가 동일 Qdrant 폴더 사용 → 동시 실행 시 잠금 충돌

### 경로
- nginx 웹 루트: `/var/www/slownews/`
- 웹 CSV: `/var/www/slownews/data/context/slowletter_web.csv`
- 프로젝트: `~/slowletter-pipeline/`
- 일일 크론: `15 23 * * *` (UTC) = KST 08:15 → `ec2_daily_update.sh`

### 데이터 구조 (서버)
- 아카이브 CSV: `data/slowletter_data_archives.csv` (18,196건)
- 엔티티 DB: `data/processed/entities.db` (SQLite, documents/entities/daily_summaries 테이블)
- 엔티티 CSV: `data/raw/slowletter_solar_entities.csv` (서비스용)
- BM25 인덱스: `data/processed/bm25_index.pkl`
- 벡터 인덱스: Qdrant (localhost:6333)

### 외부 API
| API | 용도 | 비고 |
|-----|------|------|
| Upstage Solar Pro2 | 엔티티 추출 (인물/기관/개념 등) | 크레딧 기반, `.env`에 키 |
| Claude Sonnet 4.5 | RAG 에이전트 컨텍스트 분석 | API 토큰 별도 (Max 플랜과 무관) |
| OpenAI Embedding | 벡터 임베딩 생성 | `.env`에 키 |

## 6. 주요 파일

| 파일 | 역할 |
|------|------|
| `index.html` | 정적 파인더 페이지 (nginx 서빙, 배포 시 `/var/www/slownews/`에 복사 필요) |
| `app.py` | Streamlit 프론트엔드 (`fix_answer_lines` 후처리) |
| `api/main.py` | FastAPI 백엔드 (`/finder` 동적 OG, `/search` API) |
| `agent/agent.py` | Claude RAG 에이전트 (SYSTEM_PROMPT, `_reformat_answer`) |
| `search/hybrid_search.py` | RRF 하이브리드 검색 (BM25 + 벡터) |
| `slowletter_pipeline.py` | 크롤러 + 엔티티 추출 파이프라인 |
| `update_service_content.py` | 불렛/링크 복원, 서비스 콘텐츠 갱신 |
| `generate_web_csv.py` | 웹용 CSV 생성 (`_normalize_entities`) |
| `ec2_daily_update.sh` | 일일 자동 파이프라인 (7단계) |

## 7. 에이전트 출력 포맷

### 규칙 (SYSTEM_PROMPT + _reformat_answer 동일)
1. 도입 1~2문장 (소제목 없이)
2. `### ` 소제목 3~5개
3. 소제목 아래 **모든 줄**은 `• `로 시작 (불렛 없는 줄 금지)
4. 각 `• `는 새 줄에서 시작 (한 줄에 2개 금지)
5. 마지막은 `### 왜 중요한가` 또는 `### 전망`
6. 오직 `• `만 사용 (-, *, 1. 금지)

## 8. 알려진 이슈 / 추후 작업

- [ ] **로컬-서버 코드 동기화**: 서버는 SQLite DB 기반, 로컬은 CSV 기반으로 `slowletter_pipeline.py`가 다름. `git pull`로 서버 코드를 로컬에 동기화 필요
- [ ] **test_connection 재시도 + --rebuild-entity**: 로컬 커밋 `d241a26` push 후 서버 반영 필요
- [ ] **관련성 개선**: 시간 감쇠(time decay) 검토
- [ ] **`slowletter-api` 비활성화**: `sudo systemctl stop slowletter-api && sudo systemctl disable slowletter-api`
- [ ] **비용 모니터링**: Claude API ~$0.03-$0.09/쿼리, Solar API 크레딧 기반

## 9. 일일 파이프라인 흐름 (ec2_daily_update.sh)

1. `git pull` — 코드 업데이트
2. `slowletter_pipeline.py` — 크롤링(증분) + 엔티티 추출(Solar API)
3. 엔티티 파일 동기화
4. `update_service_content.py` — 불렛/링크 복원
5. `generate_web_csv.py` — 웹 CSV 재생성
6. 인덱스 갱신 — SQLite DB + BM25 + 벡터(Qdrant)
7. nginx 갱신 + 서비스 재시작

## 10. Git 최근 커밋

```
d241a26 엔티티 추출: test_connection 재시도 로직 + --rebuild-entity 옵션 추가  ← 로컬, push 대기
358b483 자동 업데이트 2026-03-02 [EC2]
dac1e8d 데이터 업데이트 2026-03-01
2958ead 검색 제목 간결화: '슬로우레터 빠른 검색: X' → '슬로우레터: X'
8f22929 OG url 동적 치환 추가: 페이스북 공유 시 정식 URL 인식 수정
07e2cc6 검색 키워드 동적 제목 + 소셜 공유 OG 태그 지원
66ca93c 검색 키워드 URL 파라미터 지원: ?keyword=검색어 공유 가능
447d326 사이드바 라디오 버튼 왼쪽 정렬: alert 박스 텍스트와 맞춤
a8c0559 인수인계 메모 업데이트 (세션 4)
61d7f29 인덱스 정렬 옵션 마침표 추가: 최신순. 과거순. 관련도순.
```
