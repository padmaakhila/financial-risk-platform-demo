
#!/usr/bin/env bash
set -Eeuo pipefail

PORT="${PORT:-10000}"

export ERP_MOCK_URL="${ERP_MOCK_URL:-http://127.0.0.1:8101}"
export VENDOR_MOCK_URL="${VENDOR_MOCK_URL:-http://127.0.0.1:8102}"

PIDS=()

cleanup() {
    echo "Stopping application processes..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    for pid in "${PIDS[@]}"; do
        wait "$pid" 2>/dev/null || true
    done
}

trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

wait_for_service() {
    local url="$1"
    local pid="$2"
    local name="$3"

    for attempt in {1..60}; do
        if curl -fsS "$url" >/dev/null; then
            echo "$name is healthy."
            return 0
        fi

        if ! kill -0 "$pid" 2>/dev/null; then
            echo "$name stopped unexpectedly."
            return 1
        fi

        sleep 2
    done

    echo "$name health check timed out."
    return 1
}

echo "Starting ERP mock..."
uvicorn backend.integrations.erp_mock_app:app \
    --host 127.0.0.1 --port 8101 &
ERP_PID=$!
PIDS+=("$ERP_PID")

echo "Starting vendor mock..."
uvicorn backend.integrations.vendor_mock_app:app \
    --host 127.0.0.1 --port 8102 &
VENDOR_PID=$!
PIDS+=("$VENDOR_PID")

echo "Starting FastAPI backend..."
uvicorn backend.main:create_app --factory \
    --host 0.0.0.0 --port "$PORT" &
API_PID=$!
PIDS+=("$API_PID")

wait_for_service "http://127.0.0.1:8101/health" "$ERP_PID" "ERP mock"
wait_for_service "http://127.0.0.1:8102/health" "$VENDOR_PID" "Vendor mock"
wait_for_service "http://127.0.0.1:${PORT}/api/health" "$API_PID" "FastAPI"

echo "Starting background worker..."
python -m backend.workers.worker &
WORKER_PID=$!
PIDS+=("$WORKER_PID")

echo "All application processes started."

set +e
wait -n "${PIDS[@]}"
EXIT_CODE=$?
set -e

exit "$EXIT_CODE"
