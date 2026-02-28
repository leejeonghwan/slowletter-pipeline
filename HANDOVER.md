# SlowNews Pipeline 인수인계 (2026-02-28 세션 3)

최종 업데이트: 2026-02-28 23:50

---

## 1. 현재 상태

- Git: `main` 브랜치, 최신 커밋 `5c3ca3a` — **push 및 EC2 배포 필요**
- 서비스: slownews.net 정상 운영 중

### 즉시 배포 명령어

```bash
cd ~/slowletter-pipeline && git push origin main && \
ssh -i slowkey.pem ubuntu@15.165.13.179 \
  'cd ~/slowletter-pipeline && git pull origin main && \
   sudo systemctl restart slownews-api slownews-app'
```

## 2. 이번 세션에서 한 작업 (커밋 3개, 모두 push 대기)

### 2-1. 불렛 포맷 통일 + 검색 상한 해제 (`13874f5`)

**agent/agent.py**
- SYSTEM_PROMPT 규칙 3~4번: "소제목 아래 **모든** 내용 줄은 `• `로 시작, 불렛 없는 줄 금지, 각 불렛 새 줄에서 시작"
- `_reformat_answer()` 프롬프트: 동일 규칙으로 통일
- 예시에서 맥락 서술 문장에도 모두 `• ` 추가

**search/hybrid_search.py**
- `initial_k=30` 하드코딩 → `initial_k = max(top_k * 2, 60)` 자동 계산
- top_k=50 요청 시 각 엔진에서 100건 후보 → 50건 이상 반환 가능

### 2-2. 인라인 불렛 강제 줄바꿈 (`51a6f96`)

**app.py** `fix_answer_lines()`
- LLM이 `• `를 줄바꿈 없이 이어 붙이는 경우 대비
- regex로 `• ` 앞, `### ` 앞에 줄바꿈 삽입

### 2-3. 마크다운 줄바꿈 수정 (`5c3ca3a`) ← 최신

**app.py** `fix_answer_lines()`
- `\n` 하나로는 `st.markdown()`에서 줄바꿈 안 됨 (마크다운 규칙)
- `\n\n`(빈 줄)으로 변경하여 실제 렌더링에서 줄바꿈 보장
- 핵심 코드:
  ```python
  answer = re.sub(r'(?<!\n)(• )', r'\n\n\1', answer)      # 인라인 불렛 분리
  answer = re.sub(r'(?<!\n)\n(• )', r'\n\n\1', answer)     # 단일 \n → \n\n
  answer = re.sub(r'(?<!\n)(### )', r'\n\n\1', answer)     # 소제목 분리
  ```

## 3. 이전 세션 작업 (이미 배포 완료)

- **공백 보존** (`d80b5e8`): `extract_li_content()`에서 `<span>` 태그 사이 공백 누락 수정
- **nan 엔티티 필터** (`4dd7bb4`): `generate_web_csv.py`의 `_normalize_entities()` 진입점에서 nan 체크
- **일일 업데이트 스크립트** (`0f7d352`): 서비스명 `slownews-api`/`slownews-app`으로 수정 + CDN 캐시 버스팅
- **관련 기사 50건** (`4cb1ad6`): app.py `top_k=50`, `max_items=50`
- **물결표 이스케이프** (`cfe8222`): `~` → `\~` 마크다운 취소선 방지
- **답변 후처리** (`954aa76`): `_reformat_answer()` 2차 API 호출로 포맷 변환

## 4. 인프라

### EC2 서버
- IP: `15.165.13.179`, SSH key: `slowkey.pem`
- Python venv: `source ~/slowletter-pipeline/.venv/bin/activate`

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
- 일일 크론: `45 0 * * *` → `ec2_daily_update.sh`

## 5. 주요 파일

| 파일 | 역할 |
|------|------|
| `app.py` | Streamlit 프론트엔드 (`fix_answer_lines` 후처리) |
| `agent/agent.py` | Claude RAG 에이전트 (SYSTEM_PROMPT, `_reformat_answer`) |
| `search/hybrid_search.py` | RRF 하이브리드 검색 (BM25 + 벡터) |
| `slowletter_pipeline.py` | 크롤러/파서 (`extract_li_content`) |
| `generate_web_csv.py` | 웹용 CSV 생성 (`_normalize_entities`) |
| `ec2_daily_update.sh` | 일일 데이터 업데이트 + CDN 캐시 버스팅 |

## 6. 에이전트 출력 포맷

### 규칙 (SYSTEM_PROMPT + _reformat_answer 동일)
1. 도입 1~2문장 (소제목 없이)
2. `### ` 소제목 3~5개
3. 소제목 아래 **모든 줄**은 `• `로 시작 (불렛 없는 줄 금지)
4. 각 `• `는 새 줄에서 시작 (한 줄에 2개 금지)
5. 마지막은 `### 왜 중요한가` 또는 `### 전망`
6. 오직 `• `만 사용 (-, *, 1. 금지)

### 핵심 교훈
claude-sonnet-4-5는 멀티턴 도구 사용 중 포맷 지시를 잘 무시함. `_reformat_answer()` 후처리(2차 API 호출)가 가장 확실한 해법. 거기에 더해 `app.py`의 regex 후처리로 인라인 불렛도 강제 줄바꿈.

## 7. 알려진 이슈 / 추후 작업

- [ ] **배포 후 불렛 줄바꿈 확인**: `5c3ca3a` 배포 후 실제 쿼리로 `\n\n` 줄바꿈 동작 확인
- [ ] **관련성 개선**: "뉴 이재명" 검색 시 2024년 대선 이전 콘텐츠 혼입. 시간 감쇠(time decay) 검토
- [ ] **`slowletter-api` 비활성화**: `sudo systemctl stop slowletter-api && sudo systemctl disable slowletter-api`
- [ ] **`og-image_.png`**: git untracked. .gitignore 추가 또는 삭제
- [ ] **`deploy_patch.sh`**: 임시 파일. 삭제 가능

## 8. Git 최근 커밋

```
5c3ca3a 불렛 줄바꿈: \n → \n\n (마크다운 렌더링 수정)     ← push 대기
51a6f96 인라인 불렛·소제목 강제 줄바꿈 후처리 추가          ← push 대기
13874f5 불렛 포맷 강화 + 검색 결과 상한 해제               ← push 대기
0f7d352 일일 업데이트: 서비스명 수정 + CDN 캐시 버스팅 추가
4dd7bb4 nan 엔티티 필터링: 값 자체가 nan인 경우도 제거
d80b5e8 extract_li_content 공백 보존: span/strong 태그 사이 공백 누락 수정
4cb1ad6 관련 기사 top_k 50 확대 + 소제목 마침표 추가 + 인수인계 메모
cfe8222 물결표 이스케이프 + 후처리 포맷 디버깅 로그 추가
954aa76 답변 후처리 포맷 변환 추가: _reformat_answer
```
