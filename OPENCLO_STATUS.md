# 오픈클로 작업 현황 (2026-03-02)

## 요약

슬로우레터 파이프라인의 인프라·배포·자동화 작업이 완료되어 EC2 서버에서 자동 운영 중입니다. 오픈클로는 이제 **지면 분석(컨텍스트 에이전트)** 품질 개선에만 집중하면 됩니다.

---

## 1. 건드리지 말아야 할 것들

아래 항목들은 이미 안정적으로 작동 중이므로 수정하지 마세요.

### 일일 파이프라인 (ec2_daily_update.sh)
- **매일 KST 08:15** (UTC 23:15) 자동 실행
- 크롤링 → 엔티티 추출 → CSV 생성 → 인덱스 빌드 → 서비스 재시작까지 전자동
- 크론: `15 23 * * *`
- 2026-03-02 정상 작동 확인 완료 (18,196건, 오늘 31건 추가)

### 엔티티 추출 (Solar API)
- Upstage Solar Pro2로 자동 추출 (인물, 기관, 개념, 이벤트, 장소)
- 증분 처리: 새로운 기사만 추출, 기존 결과 보존
- test_connection에 재시도 로직(3회) 추가 완료
- 데이터는 `data/processed/entities.db` (SQLite)에 저장

### 인덱스 시스템
- BM25 인덱스: `data/processed/bm25_index.pkl` — 자동 리빌드
- 벡터 인덱스: Qdrant (localhost:6333) — 증분 업서트
- SQLite Entity DB: `data/processed/entities.db` — 자동 리빌드
- 하이브리드 검색 (BM25 + 벡터 + RRF) 정상 작동 중

### 파인더 페이지 (index.html)
- `?keyword=` URL 파라미터로 검색 결과 공유 가능
- 동적 OG 태그 (Facebook, Telegram 등 소셜 공유 지원)
- nginx에서 `?keyword=` 요청 → FastAPI `/finder` 프록시 설정 완료
- 정적 파일은 `/var/www/slownews/`에서 서빙

### 서비스 구성
- `slownews-api` (FastAPI, 포트 8000) — 검색 API + 파인더
- `slownews-app` (Streamlit, 포트 8510) — 컨텍스트 분석 UI
- nginx 리버스 프록시 — 정상 운영

---

## 2. 오픈클로가 할 일: 지면 분석 품질 개선

### 현재 에이전트 구조
- 모델: `claude-sonnet-4-5-20250929`
- max_tokens: 4096, max_tool_rounds: 5
- 파일: `agent/agent.py`

### 출력 포맷 규칙 (이미 설정됨, 유지할 것)
1. 도입 1~2문장 (소제목 없이)
2. `### ` 소제목 3~5개
3. 소제목 아래 모든 줄은 `• `로 시작
4. 각 `• `는 새 줄에서 시작
5. 마지막은 `### 왜 중요한가` 또는 `### 전망`
6. 오직 `• `만 사용 (-, *, 1. 금지)

### 개선 가능 영역
- **관련성**: 시간 감쇠(time decay) 적용 검토 — 오래된 기사가 최신 검색에 혼입되는 문제
- **답변 품질**: SYSTEM_PROMPT 튜닝, 프롬프트 엔지니어링
- **후처리**: `_reformat_answer()` 개선 (현재 2차 API 호출로 포맷 강제)

---

## 3. 현재 데이터 현황

| 항목 | 수치 |
|------|------|
| 총 기사 수 | 18,196건 |
| 날짜 범위 | 2023-04-10 ~ 2026-03-02 |
| 오늘 추가 | 31건 |
| 엔티티 (오늘) | 565건 |
| 고유 엔티티 | 139,359개 |
| 벡터 포인트 | 18,157개 |

---

## 4. 파일 수정 시 주의사항

| 파일 | 수정 가능 | 비고 |
|------|-----------|------|
| `agent/agent.py` | ✅ 수정 가능 | SYSTEM_PROMPT, _reformat_answer 튜닝 |
| `app.py` | ⚠️ 주의 | fix_answer_lines 후처리 건드리지 말 것 |
| `search/hybrid_search.py` | ⚠️ 주의 | initial_k 자동 계산 로직 유지할 것 |
| `index.html` | ❌ 건드리지 말 것 | URL 파라미터, OG 태그 등 연동 복잡 |
| `api/main.py` | ❌ 건드리지 말 것 | /finder 엔드포인트, OG 태그 동적 치환 |
| `slowletter_pipeline.py` | ❌ 건드리지 말 것 | 크롤링+엔티티 파이프라인 안정화 완료 |
| `ec2_daily_update.sh` | ❌ 건드리지 말 것 | 일일 자동 파이프라인 |
| `update_service_content.py` | ❌ 건드리지 말 것 | 불렛/링크 복원 로직 |
| `generate_web_csv.py` | ❌ 건드리지 말 것 | 웹 CSV 생성 |

---

## 5. 비용 참고

- Claude API (컨텍스트 분석): 쿼리당 약 $0.03~$0.09 (Sonnet 4.5 기준)
- Solar API (엔티티 추출): Upstage 크레딧 기반, 일일 자동 소비
- 이 비용은 Claude Max 플랜과 별개 (API 토큰 과금)
