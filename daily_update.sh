#!/usr/bin/env bash
# daily_update.sh — 슬로우레터 일일 자동 업데이트
# 1) 크롤링 + 엔티티 추출 (slowletter_pipeline.py)
# 2) 파이프라인 엔티티(data/slowletter_entities.csv) → raw(data/raw/slowletter_solar_entities.csv) 동기화
# 3) 불렛/링크 복원(update_service_content.py)
# 4) 웹 CSV 재생성(generate_web_csv.py)
# 5) (옵션) git commit/push

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/data/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily_$(date +%Y%m%d_%H%M%S).log"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "===== $(date) 시작 ====="
cd "$SCRIPT_DIR"

# --- activate venv ---
if [[ -n "${VENV_PATH:-}" && -f "$VENV_PATH/bin/activate" ]]; then
  source "$VENV_PATH/bin/activate"
elif [[ -f "$SCRIPT_DIR/.venv/bin/activate" ]]; then
  source "$SCRIPT_DIR/.venv/bin/activate"
elif [[ -f "$HOME/Downloads/work/.venv/bin/activate" ]]; then
  # OpenClaw dev environment default
  source "$HOME/Downloads/work/.venv/bin/activate"
else
  echo "[ERR] venv not found. Set VENV_PATH or create .venv in repo." >&2
  exit 1
fi

# --- load env vars ---
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.env"
  set +a
fi

echo "[1/5] 크롤링 + 엔티티 추출"
python slowletter_pipeline.py

echo "[2/5] 엔티티 파일 동기화 (data/slowletter_entities.csv → data/raw/slowletter_solar_entities.csv)"
cp data/slowletter_entities.csv data/raw/slowletter_solar_entities.csv

echo "[3/5] 불렛/링크 복원 (update_service_content)"
python update_service_content.py

echo "[4/5] 웹 CSV 재생성"
python generate_web_csv.py

echo "[5/5] sanity check"
python - <<'PY'
import pandas as pd
web = pd.read_csv('data/raw/slowletter_web.csv')
print(f"[OK] web.csv rows={len(web)} date={web['date'].min()} ~ {web['date'].max()}")
entities = pd.read_csv('data/raw/slowletter_solar_entities.csv')
bullets = entities['cleaned_content_for_service'].astype(str).str.contains('•', na=False).sum()
print(f"[OK] entities rows={len(entities)} bullets={bullets}")
PY

# Optional git push
if [[ "${GIT_PUSH:-0}" == "1" ]]; then
  echo "[git] add/commit/push"
  git add data/raw/slowletter_solar_entities.csv data/raw/slowletter_web.csv
  if git diff --cached --quiet; then
    echo "[git] 변경사항 없음, push 건너뜀"
  else
    git commit -m "자동 업데이트 $(date +%Y-%m-%d)" || true
    git push origin main
  fi
fi

echo "===== $(date) 완료 ====="