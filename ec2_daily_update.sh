#!/usr/bin/env bash
# ec2_daily_update.sh — EC2 통합 파이프라인
# 크롤링 + 엔티티 추출 + CSV 생성 + 인덱스 빌드 + nginx 갱신 + 서비스 재시작
#
# crontab: 45 0 * * * /home/ubuntu/slowletter-pipeline/ec2_daily_update.sh
#          (UTC 00:45 = KST 09:45)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="$SCRIPT_DIR/data/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/ec2_daily_$(date +%Y%m%d_%H%M%S).log"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "===== $(date) EC2 daily update 시작 ====="

# --- venv 활성화 ---
source .venv/bin/activate

# --- .env 로드 ---
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

# --- 코드 업데이트 (코드 변경사항만) ---
echo "[1/7] git pull (코드 업데이트)"
git pull origin main || echo "[warn] git pull 실패, 기존 코드로 계속 진행"

# --- 크롤링 + 엔티티 추출 ---
echo "[2/7] 크롤링 + 엔티티 추출"
python slowletter_pipeline.py

# --- 엔티티 파일 동기화 ---
echo "[3/7] 엔티티 파일 동기화"
cp data/slowletter_entities.csv data/raw/slowletter_solar_entities.csv

# --- 불렛/링크 복원 ---
echo "[4/7] 불렛/링크 복원 (update_service_content)"
python update_service_content.py

# --- 웹 CSV 재생성 ---
echo "[5/7] 웹 CSV 재생성"
python generate_web_csv.py

# --- 인덱스 빌드 ---
echo "[6/7] 인덱스 증분 갱신"
python build_all.py data/raw/slowletter_solar_entities.csv

# --- nginx 정적 파일 갱신 + 서비스 재시작 ---
echo "[7/7] nginx 갱신 + 서비스 재시작"
sudo cp index.html /var/www/slownews/index.html
sudo cp -r data/raw/slowletter_web.csv /var/www/slownews/data/context/slowletter_web.csv 2>/dev/null || true
sudo systemctl restart slowletter-api slowletter-ui

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
git add data/raw/slowletter_solar_entities.csv data/raw/slowletter_web.csv data/slowletter_data_archives.csv data/slowletter_entities.csv
if git diff --cached --quiet; then
  echo "[backup] 변경사항 없음, push 건너뜀"
else
  git commit -m "자동 업데이트 $(date +%Y-%m-%d) [EC2]" || true
  git push origin main || echo "[warn] git push 실패"
fi

echo "===== $(date) EC2 daily update 완료 ====="
