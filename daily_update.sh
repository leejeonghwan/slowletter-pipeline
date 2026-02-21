#!/bin/bash
# daily_update.sh — 슬로우레터 일일 자동 업데이트
# 크롤링 → 엔티티 추출 → 불렛/링크 복원 → 웹 CSV 생성 → git push

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/data/logs"
LOG_FILE="$LOG_DIR/daily_$(date +%Y%m%d_%H%M%S).log"
VENV="$SCRIPT_DIR/.venv/bin/activate"

mkdir -p "$LOG_DIR"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "===== $(date) 시작 ====="

# 환경 설정
cd "$SCRIPT_DIR"
source "$VENV"
export $(grep -v '^#' .env | xargs)

# 1. 크롤링 + 엔티티 추출
echo "[1/5] 크롤링 + 엔티티 추출"
python3 slowletter_pipeline.py

# 2. 파이프라인 엔티티 → raw 복사
echo "[2/5] 엔티티 파일 동기화"
cp data/slowletter_entities.csv data/raw/slowletter_solar_entities.csv

# 3. 불렛/링크 복원 (update_service_content)
echo "[3/5] 불렛/링크 복원"
python3 update_service_content.py

# 4. 웹 CSV 재생성
echo "[4/5] 웹 CSV 재생성"
python3 generate_web_csv.py

# 5. git push
echo "[5/5] GitHub push"
cd "$SCRIPT_DIR"
git add data/raw/slowletter_solar_entities.csv data/raw/slowletter_web.csv
if git diff --cached --quiet; then
    echo "변경사항 없음, push 건너뜀"
else
    git commit -m "자동 업데이트 $(date +%Y-%m-%d)"
    git push origin main
fi

echo "===== $(date) 완료 ====="
