#!/usr/bin/env bash
# daily_update_rag.sh — 09:00 자동 실행용(데이터 업데이트 + RAG 인덱스 재빌드 + 서버 재시작)
#
# 순서:
# 0) venv/.env 로드
# 1) FastAPI/Streamlit 종료(로컬 Qdrant(path) 동시 접근 방지)
# 2) daily_update.sh 실행(크롤링/엔티티/웹CSV + (옵션) git push)
# 3) build_all.py로 인덱스 재빌드(SQLite/BM25/Qdrant)
# 4) FastAPI/Streamlit 재기동

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="$SCRIPT_DIR/data/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily_rag_$(date +%Y%m%d_%H%M%S).log"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "===== $(date) daily_update_rag 시작 ====="

# --- activate venv ---
if [[ -n "${VENV_PATH:-}" && -f "$VENV_PATH/bin/activate" ]]; then
  source "$VENV_PATH/bin/activate"
elif [[ -f "$SCRIPT_DIR/.venv/bin/activate" ]]; then
  source "$SCRIPT_DIR/.venv/bin/activate"
elif [[ -f "$HOME/Downloads/work/.venv/bin/activate" ]]; then
  source "$HOME/Downloads/work/.venv/bin/activate"
else
  echo "[ERR] venv not found. Set VENV_PATH or create .venv in repo." >&2
  exit 1
fi

# --- load env vars (.env) ---
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.env"
  set +a
fi

# --- stop services (avoid qdrant path concurrency) ---
echo "[0/4] stop services"
pkill -f "uvicorn api\.main:app" 2>/dev/null || true
pkill -f "streamlit run app.py" 2>/dev/null || true
sleep 1

# --- daily update ---
echo "[1/4] daily_update.sh"
bash "$SCRIPT_DIR/daily_update.sh"

# --- rebuild indexes ---
echo "[2/4] build_all.py (rebuild rag indexes)"
python -u "$SCRIPT_DIR/build_all.py" "$SCRIPT_DIR/data/raw/slowletter_solar_entities.csv"

# --- restart services ---
echo "[3/4] restart services"
nohup uvicorn api.main:app --host 0.0.0.0 --port 8000 > "$SCRIPT_DIR/server.log" 2>&1 &
nohup streamlit run app.py --server.port 8510 --server.headless true --server.address 127.0.0.1 > "$SCRIPT_DIR/streamlit.log" 2>&1 &

sleep 3

# --- quick health checks ---
echo "[check] /health"
curl -s --max-time 8 http://127.0.0.1:8000/health || true

echo "===== $(date) daily_update_rag 완료 ====="
