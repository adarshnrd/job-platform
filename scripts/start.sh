#!/usr/bin/env bash
# Start both backend and frontend dev servers.
# Usage: ./scripts/start.sh

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Starting backend (FastAPI)..."
cd "$REPO_ROOT/apps/api"
python -m uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

echo "Starting frontend (Next.js)..."
cd "$REPO_ROOT/apps/web"
npm run dev &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT

echo ""
echo "Backend:  http://localhost:8000/docs"
echo "Frontend: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both servers."

wait
