# SlowNews.net 프로젝트 현재 상태 (2026-02-27)

## 프로젝트 개요
- **목적**: 슬로우레터 아카이브 검색 + RAG 기반 뉴스 분석 서비스
- **URL**: https://slownews.net
- **구조**:
  - `/` → Archives Search (정적 HTML, index.html)
  - `/context/` → Context Analytics (Streamlit RAG UI, app.py)
  - `/api/` → FastAPI 백엔드 (api/main.py)

## 인프라
- **맥북**: 데이터 수집만 (03:45 지면 분석, 08:45 슬로우레터 데이터)
- **GitHub**: 데이터 저장소 (leejeonghwan/slowletter-pipeline)
- **AWS EC2**: 24시간 RAG 서버 (15.165.13.179, t2.large 8GB)
  - Qdrant: Docker 서버 모드 (localhost:6333)
  - systemd: slowletter-api.service (FastAPI), slowletter-ui.service (Streamlit)
  - nginx: 리버스 프록시
  - cron: UTC 23:50 (KST 08:50) 자동 갱신
- **Cloudflare**: DNS + SSL/TLS Flexible 프록시

## 최근 작업 (2026-02-27 15:10)

### 완료한 작업
1. **app.py 완전 재작성**
   - index.html과 동일한 디자인 적용
   - 사이드바: 어두운 배경 (#1c1917), 통계, 네비게이션
   - 메인: 노란색 배경 (#fdad00)에 검색창만
   - 검색 결과: 흰색 박스에 검정 텍스트
   - 불필요한 모드/버튼 모두 제거

2. **패스워드 페이지에도 사이드바 추가**
   - `render_sidebar()`를 `check_password()` 전에 호출
   - 패스워드 입력창도 흰색 박스 스타일

3. **API 422 오류 수정**
   - 요청 필드명 `query` → `question`으로 변경

### 핵심 파일

#### 1. index.html (정적 검색)
- 위치: `/Users/slowclaw/slowletter-pipeline/index.html`
- EC2: `/var/www/slownews/index.html` (nginx static)
- 데이터: `data/context/slowletter_web.csv`
- 특징: 클라이언트 검색, permalink 지원 (`?doc=<id>`)

#### 2. app.py (RAG UI)
- 위치: `/Users/slowclaw/slowletter-pipeline/app.py`
- Streamlit, port 8510, baseUrlPath `/context`
- 패스워드 보호 (preview/justice, 만료일 3/3, 3/31)
- API 호출: POST `/query` with `{"question": query}`

#### 3. api/main.py (FastAPI 백엔드)
- 위치: `/Users/slowclaw/slowletter-pipeline/api/main.py`
- port 8000
- 엔드포인트:
  - `/query`: Agent 기반 질의응답 (QueryRequest: question, conversation_history)
  - `/search`: 직접 검색
  - `/timeline`: 엔티티 타임라인
  - `/trend`: 트렌드 분석
  - `/health`: 헬스체크
  - `/doc/{doc_id}`: 개별 문서 조회

#### 4. 데이터 파일
- `data/slowletter_data_archives.csv` (18,165건)
- `data/slowletter_entities.csv`
- `data/raw/slowletter_web.csv` (GitHub Pages용, 엔티티 정규화 적용)
- `data/processed/entities.db` (SQLite)
- `data/processed/bm25_index.pkl`
- EC2 Qdrant: Docker 서버 모드 (path 모드 아님)

## 디자인 시스템 (index.html 기준)

### 색상
```
--bg-yellow: #fdad00 (메인 배경)
--bg-dark: #1c1917 (사이드바 배경)
--text-light: #e7e5e4 (사이드바 텍스트)
--text-gray: #a8a29e (사이드바 보조)
--text-dark: #111111 (본문 텍스트)
--white: #ffffff (박스 배경)
```

### 사이드바 구조
- 로고 (180px, 클릭 시 홈)
- 통계: 아카이브 건수, 기간
- 구분선
- 네비게이션:
  - Archives Search. (active: #fdad00 배경)
  - Context Analytics(AI). (active: #fdad00 배경)
  - Slow News. (외부 링크)
- 푸터: slownews.net

### 박스 스타일
```css
.box {
  background: white;
  border-radius: 8px;
  padding: 1.5rem;
  margin-bottom: 1rem;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
```

### 검색 입력
- 흰색 배경, 검정 텍스트
- border: 1px solid rgba(0,0,0,0.18)
- focus: border-color #fdad00, box-shadow rgba(253,173,0,0.1)

## 다음 작업 후보

### 1. RAG 답변 표시 개선
- 현재: 답변이 그냥 텍스트로 표시됨
- 개선안:
  - 답변 박스 스타일 강화 (제목, 아이콘 등)
  - 근거 문장 하이라이트
  - 출처 링크 표시 개선

### 2. 관련 기사 표시 개선
- 현재: 상위 10개만, 내용 300자 자르기
- 개선안:
  - 관련도에 따라 동적 개수 조정 (cutoff_ratio 활용)
  - 제목 클릭 시 permalink로 이동
  - 날짜/엔티티 태그 표시

### 3. 검색 UX 개선
- 검색어 히스토리
- 추천 검색어
- 검색 결과 없을 때 fallback 메시지

### 4. 모바일 최적화
- 사이드바 토글 버튼
- 반응형 레이아웃

## 환경 변수 (.env)
```
# API Keys
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...

# RAG 엔진
AGENT_MODEL=claude-sonnet-4-5
OPENAI_EMBEDDING_MODEL=text-embedding-3-large

# 패스워드
PASSWORD_PUBLIC=preview
PASSWORD_PREMIUM=justice
EXPIRY_PUBLIC=2026-03-03
EXPIRY_PREMIUM=2026-03-31

# Qdrant
QDRANT_URL=localhost:6333  # EC2에서 (맥북은 data/processed/qdrant path 모드)

# API URL
API_URL=http://localhost:8000  # Streamlit → FastAPI
```

## 배포 워크플로우
1. 로컬에서 수정
2. `git add . && git commit -m "..." && git push`
3. EC2 배포:
   ```bash
   ssh -i ~/.ssh/ec2-slowserver.pem ubuntu@15.165.13.179
   cd ~/slowletter-pipeline
   git pull
   sudo systemctl restart slowletter-ui.service  # 또는 slowletter-api.service
   ```

## 주의사항
- **버전 관리**: EC2에서 직접 수정 금지, 항상 로컬 → Git → EC2
- **백업 파일**: .gitignore에 추가 (*.bak, *.backup, *_patched.py)
- **Qdrant 모드**: 환경변수 QDRANT_URL로 제어 (path vs 서버 모드)
- **증분 인덱싱 문제**: 현재 전체 재빌드로 작동 (10-15분), 증분 갱신 수정 필요

## 문제 해결

### Streamlit 재시작
```bash
ssh -i ~/.ssh/ec2-slowserver.pem ubuntu@15.165.13.179
sudo systemctl restart slowletter-ui.service
sudo systemctl status slowletter-ui.service
```

### FastAPI 재시작
```bash
sudo systemctl restart slowletter-api.service
sudo systemctl status slowletter-api.service
```

### 로그 확인
```bash
sudo journalctl -u slowletter-ui.service -n 50 --no-pager
sudo journalctl -u slowletter-api.service -n 50 --no-pager
```

### nginx 설정
```
/etc/nginx/sites-available/slownews
sudo systemctl restart nginx
```

## Git 정보
- Repo: https://github.com/leejeonghwan/slowletter-pipeline
- Branch: main
- 최근 커밋: "API 요청 필드명 수정: query → question" (f4922db)
