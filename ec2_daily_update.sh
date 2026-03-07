#!/usr/bin/env bash
# ec2_daily_update.sh — EC2 통합 파이프라인
# 크롤링 + 엔티티 추출 + CSV 생성 + 인덱스 빌드 + nginx 갱신 + 서비스 재시작
#
# 듀얼 크론 스케줄:
#   crontab:
#     0 23 * * * /home/ubuntu/slowletter-pipeline/ec2_daily_update.sh          # 1차: KST 08:00 순수 증분
#     0  1 * * * /home/ubuntu/slowletter-pipeline/ec2_daily_update.sh --refresh # 2차: KST 10:00 오늘분 리프레시
#
# --refresh 옵션: 오늘분 엔티티를 삭제 후 재추출 (교정·교열 반영)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- 옵션 파싱 ---
REFRESH_DAYS=0
RUN_LABEL="incremental"
if [[ "${1:-}" == "--refresh" ]]; then
  REFRESH_DAYS=1
  RUN_LABEL="refresh"
fi

LOG_DIR="$SCRIPT_DIR/data/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/ec2_daily_${RUN_LABEL}_$(date +%Y%m%d_%H%M%S).log"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "===== $(date) EC2 daily update 시작 (${RUN_LABEL}, refresh_days=${REFRESH_DAYS}) ====="

# --- venv 활성화 ---
source .venv/bin/activate

# --- .env 로드 ---
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

# --- 코드 업데이트 (코드 변경사항만) ---
echo "[1/8] git pull (코드 업데이트)"
git pull origin main || echo "[warn] git pull 실패, 기존 코드로 계속 진행"

# --- 크롤링 + 엔티티 추출 ---
echo "[2/8] 크롤링 + 엔티티 추출 (refresh_days=${REFRESH_DAYS})"
python slowletter_pipeline.py --refresh-days "$REFRESH_DAYS"

# --- 엔티티 파일 동기화 ---
echo "[3/8] 엔티티 파일 동기화"
cp data/slowletter_entities.csv data/raw/slowletter_solar_entities.csv

# --- 불렛/링크 복원 ---
echo "[4/8] 불렛/링크 복원 (update_service_content)"
python update_service_content.py

# --- 웹 CSV 재생성 ---
echo "[5/8] 웹 CSV 재생성"
python generate_web_csv.py

# --- recent.json 생성 (메인 즉시 렌더링용) ---
echo "[6/8] recent.json 생성"
python generate_recent_json.py

# --- 인덱스 빌드 ---
echo "[7/8] 인덱스 갱신 (refresh_days=${REFRESH_DAYS})"
if ! python build_all.py data/raw/slowletter_solar_entities.csv --refresh-days "$REFRESH_DAYS"; then
  echo "[ERROR] 인덱스 빌드 실패, 기존 인덱스로 계속 진행"
fi

# --- nginx 정적 파일 갱신 + 서비스 재시작 ---
echo "[8/8] nginx 갱신 + 서비스 재시작"
sudo cp index.html /var/www/slownews/index.html
sudo cp data/raw/slowletter_web.csv /var/www/slownews/data/context/slowletter_web.csv 2>/dev/null || true
sudo cp data/context/recent.json /var/www/slownews/data/context/recent.json 2>/dev/null || true

# CDN 캐시 버스팅: CSV URL에 타임스탬프 추가
CACHE_TS=$(date +%s)
sudo sed -i "s|slowletter_web\.csv[^'\"]*|slowletter_web.csv?v=${CACHE_TS}|g" /var/www/slownews/index.html

sudo systemctl restart slownews-api slownews-app

sleep 3

# --- sanity check ---
echo "[check] web.csv 확인"
python - <<'PY'
import pandas as pd
web = pd.read_csv('data/raw/slowletter_web.csv')
print(f"[OK] web.csv rows={len(web)} date={web['date'].min()} ~ {web['date'].max()}")
PY

echo "[check] /health"
curl -s --max-time 8 http://127.0.0.1:8000/health || true

# --- 데이터 백업 (git push) ---
echo "[backup] git commit + push"
git add data/raw/slowletter_solar_entities.csv data/raw/slowletter_web.csv data/context/recent.json data/slowletter_data_archives.csv data/slowletter_entities.csv
if git diff --cached --quiet; then
  echo "[backup] 변경사항 없음, push 건너뜀"
else
  git commit -m "자동 업데이트 $(date +%Y-%m-%d) ${RUN_LABEL} [EC2]" || true
  git push origin main || echo "[warn] git push 실패"
fi

echo "===== $(date) EC2 daily update 완료 (${RUN_LABEL}) ====="
