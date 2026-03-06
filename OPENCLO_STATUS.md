# 오픈클로 작업 현황 (2026-03-06)

최종 업데이트: 2026-03-06 15:45

---

## ⚠️ 커밋 보호 규칙 (pre-commit hook)

이 저장소에는 **pre-commit hook**이 설치되어 있습니다.

### 자동 커밋 가능 (허용)
- `*.md` 파일 (MEMORY.md, OPENCLO_STATUS.md, IDENTITY.md 등)
- `memory/*` 디렉토리

### 자동 커밋 불가 (차단)
- `*.py`, `*.sh`, `*.html`, `*.json`, `*.css`, `*.js`, `*.csv`
- `data/`, `indexing/`, `search/`, `agent/`, `api/` 디렉토리

차단된 파일을 커밋하려 하면 hook이 거부합니다.
사람이 직접 커밋해야 할 때: `git commit --no-verify -m "메시지"`

### hook 설치 방법
```bash
git config core.hooksPath .githooks
```

### 왜 이 규칙이 있는가
2026-03-06 사고: generate_materials_v2.py의 CSS를 수정한 뒤 커밋 → EC2 daily update에서 pull → 불렛/링크 복원 순서가 꼬여 slownews.net 전체 데이터 깨짐. 코드 파일은 반드시 사람의 검토를 거쳐야 합니다.

---

## 요약

슬로우레터 파이프라인의 인프라·배포·자동화 작업이 완료되어 EC2 서버에서 자동 운영 중입니다. 오픈클로는 이제 **신문 지면 분석 품질 개선**에 집중합니다.

---

## 1. 건드리지 말아야 할 것들 (슬로우뉴스 검색엔진)

아래 항목들은 이미 안정적으로 작동 중이므로 수정하지 마세요.

### 일일 파이프라인 (ec2_daily_update.sh)
- **매일 KST 08:15** (UTC 23:15) 자동 실행
- 크롤링 → 엔티티 추출 → CSV 생성 → 인덱스 빌드 → 서비스 재시작까지 전자동
- 크론: `15 23 * * *`
- **최근 개선 (2026-03-06):**
  - 최근 2일분 엔티티 삭제 후 재추출 (당일 수정 반영)
  - 제목 변경 감지로 ID 밀림 자동 복구
  - 고아 ID(아카이브에서 사라진) 자동 제거
  - 최근 2일분 벡터 삭제 후 재임베딩

### 엔티티 추출 (Solar API)
- Upstage Solar Pro2로 자동 추출 (인물, 기관, 개념, 이벤트, 장소)
- **증분 처리 개선:** 최근 2일분은 매일 재추출하여 수정 사항 반영
- test_connection에 재시도 로직(3회) 추가 완료
- 데이터는 `data/processed/entities.db` (SQLite)에 저장

### 인덱스 시스템
- BM25 인덱스: `data/processed/bm25_index.pkl` — 자동 리빌드
- **벡터 인덱스:** Qdrant (localhost:6333) — 최근 2일분 자동 갱신
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

## 2. 오픈클로가 할 일: 신문 지면 분석 품질 개선

### 현재 파이프라인

**워크스페이스:** `/Users/slowclaw/.openclaw/workspace/`

**핵심 스크립트:**
1. **`naver_newspaper_full_collect.py`** — 네이버 4대 신문 지면 수집
2. **`generate_materials_v2.py`** — CSV → 클러스터링 → HTML (v3.1 통합)
3. **`convert_materials_to_html.py`** — 마크다운 → HTML (레거시)

**작업 흐름:**
```
네이버 지면 수집 (205개 기사)
    ↓
클러스터링 (14개 다수, 166개 단독)
    ↓
팩트/발언 추출 (발언자 검증)
    ↓
HTML 생성 (v3.1 규격)
    ↓
품질 검증 (자동)
    ↓
Telegram 전송
```

### OPENCLO_HTML_GUIDE v3.1 핵심 규칙

**절대 원칙 6가지:**
1. 데이터 구조 먼저 → HTML 렌더링
2. 클러스터 정보는 하나의 객체로 묶기
3. 원문 인용 절대 자르지 않기
4. `<li>`는 반드시 `<ul>` 안에
5. 값 없으면 출력 안 함
6. 섹션 제목은 `<h2>` 사용

**섹션 완전 분리 (v3.1 핵심):**
- **숫자/팩트:** 통계, 수치만 (발언 절대 혼입 금지)
- **발언/인용:** 실제 사람이 말한 것만 (기사 리드문·사진 캡션 제외)
- **온도차:** 신문별 프레임 차이 (독립 섹션)
- **신문별 한줄:** 각 신문의 차별적 관점 (독립 섹션)

**품질 검증 자동화:**
- "(발언자 미상)" 0건 체크
- 섹션 중복 차단
- 중요 코멘트↔발언/인용 중복 차단
- 캡션 혼입 차단

### 개선 가능 영역

- **발언자 추출:** 칼럼니스트 이름 검출 개선
- **온도차 분석:** 신문별 프레임 더 명확히 구분
- **클러스터링:** 주제 일관성 검증 강화
- **한줄 맥락:** 사진 캡션 대신 핵심 요약문

---

## 3. 현재 데이터 현황

### 슬로우뉴스 검색엔진
| 항목 | 수치 |
|------|------|
| 총 기사 수 | ~18,200건 |
| 날짜 범위 | 2023-04-10 ~ 현재 |
| 고유 엔티티 | ~139,400개 |
| 벡터 포인트 | ~18,200개 |

### 신문 지면 분석 (2026-03-06)
| 항목 | 수치 |
|------|------|
| 수집 기사 | 205개 (경향 84, 중앙 56, 조선 38, 동아 27) |
| 클러스터 | 14개 (다수 신문 교차) |
| HTML 출력 | 44,301자 (v3.1 품질 검증 통과) |

---

## 4. 파일 수정 시 주의사항

### 슬로우뉴스 검색엔진 (건드리지 말 것)

| 파일 | 수정 금지 | 비고 |
|------|-----------|------|
| `slowletter_pipeline.py` | ❌ | 크롤링+엔티티 파이프라인 (최근 2일분 자동 갱신 포함) |
| `indexing/embedder.py` | ❌ | 벡터 임베딩 (최근 2일분 삭제+재임베딩 로직) |
| `ec2_daily_update.sh` | ❌ | 일일 자동 파이프라인 |
| `index.html` | ❌ | URL 파라미터, OG 태그 등 연동 복잡 |
| `api/main.py` | ❌ | /finder 엔드포인트, OG 태그 동적 치환 |
| `update_service_content.py` | ❌ | 불렛/링크 복원 로직 |
| `generate_web_csv.py` | ❌ | 웹 CSV 생성 |

### 신문 지면 분석 (수정 가능)

| 파일 | 수정 가능 | 비고 |
|------|-----------|------|
| `generate_materials_v2.py` | ✅ | v3.1 통합 파이프라인 (발언자 추출, 클러스터링 개선) |
| `naver_newspaper_full_collect.py` | ✅ | 수집 범위 조정 (신문사/페이지) |
| `OPENCLO_HTML_GUIDE.md` | ✅ | 품질 기준 문서화 |

---

## 5. 워크스페이스 관리

### 깃허브 동기화 (2026-03-06 추가)

**저장소:** https://github.com/leejeonghwan/slowletter-pipeline

**동기화된 파일:**
- 워크스페이스 컨텍스트: `AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `TOOLS.md`, `HEARTBEAT.md`
- 신문 분석 스크립트: `generate_materials_v2.py`, `naver_newspaper_full_collect.py`, 등
- 가이드 문서: `OPENCLO_HTML_GUIDE.md`, `OPENCLO_STATUS.md`, `HANDOVER.md`

**제외된 파일 (.gitignore):**
- 개인정보: `memory/`, `USER.md`, `MEMORY.md`
- 작업 결과물: `*.html`, `*.csv`
- 임시 파일: `tmp_*`

**클로 리셋 후 복원:**
```bash
cd ~/.openclaw/workspace
git pull origin main
```

### 메모리 관리

- **daily notes:** `memory/YYYY-MM-DD.md` — 일별 작업 로그
- **장기 기억:** `MEMORY.md` — 핵심 결정, 교훈, 패턴
- **원칙:** "Mental notes" 금지, 모든 기억은 파일로

---

## 6. 비용 참고

- Claude API (컨텍스트 분석): 쿼리당 약 $0.03~$0.09 (Sonnet 4.5 기준)
- Solar API (엔티티 추출): Upstage 크레딧 기반, 일일 자동 소비
- 이 비용은 Claude Max 플랜과 별개 (API 토큰 과금)

---

## 7. 최근 주요 업데이트

### 2026-03-06
- ✅ **워크스페이스 깃허브 동기화** - 클로 리셋 대비
- ✅ **MEMORY.md 생성** - 장기 기억 복원
- ✅ **품질 검증 강화** - 중복/캡션 혼입 차단

### 2026-03-05
- ✅ **최근 2일분 자동 갱신** - 엔티티/벡터 재추출
- ✅ **제목 변경 감지** - ID 밀림 자동 복구

### 2026-03-04
- ✅ **generate_materials_v2.py** - v3.1 통합 파이프라인
- ✅ **OPENCLO_HTML_GUIDE v3.1** - 섹션 분리 규칙 확립

### 2026-02-26
- ✅ **인용문 품질 개선** - 상투적 표현 필터 20개
- ✅ **HTML 자동 변환** - 마크다운 → HTML

---

_이 문서는 오픈클로의 작업 범위와 최신 상태를 기록합니다._
