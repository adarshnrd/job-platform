#!/usr/bin/env bash
# Start both backend and frontend dev servers dynamically without hardcoded paths.
# Usage: ./scripts/start.sh

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Auto-install frontend dependencies if missing
if [ ! -d "$REPO_ROOT/apps/web/node_modules" ]; then
    echo "⚠️  Frontend dependencies missing. Installing node modules in apps/web..."
    (cd "$REPO_ROOT/apps/web" && npm install)
fi

# Auto-install backend dependencies if missing
if [ ! -d "$REPO_ROOT/apps/api/venv" ] && [ ! -d "$REPO_ROOT/apps/api/.venv" ]; then
    echo "⚠️  Python virtual environment missing. Setting up apps/api/venv..."
    (cd "$REPO_ROOT/apps/api" && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt)
fi

# Ensure apps/web and apps/api have access to root .env

if [ -f "$REPO_ROOT/.env" ]; then
    [ -e "$REPO_ROOT/apps/web/.env.local" ] || ln -sf ../../.env "$REPO_ROOT/apps/web/.env.local" 2>/dev/null || cp "$REPO_ROOT/.env" "$REPO_ROOT/apps/web/.env.local"
    [ -e "$REPO_ROOT/apps/api/.env" ] || ln -sf ../../.env "$REPO_ROOT/apps/api/.env" 2>/dev/null || cp "$REPO_ROOT/.env" "$REPO_ROOT/apps/api/.env"
elif [ -f "$REPO_ROOT/.env.example" ]; then
    echo "⚠️  No .env file found in root! Creating .env from .env.example..."
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    ln -sf ../../.env "$REPO_ROOT/apps/web/.env.local" 2>/dev/null || cp "$REPO_ROOT/.env" "$REPO_ROOT/apps/web/.env.local"
    ln -sf ../../.env "$REPO_ROOT/apps/api/.env" 2>/dev/null || cp "$REPO_ROOT/.env" "$REPO_ROOT/apps/api/.env"
fi

echo "Starting backend (FastAPI)..."
cd "$REPO_ROOT/apps/api"



if [ -f "venv/bin/python" ]; then
    PYTHON_CMD="./venv/bin/python"
elif [ -f ".venv/bin/python" ]; then
    PYTHON_CMD="./.venv/bin/python"
elif [ -f "venv/Scripts/python.exe" ]; then
    PYTHON_CMD="./venv/Scripts/python.exe"
else
    PYTHON_CMD="python3"
fi

$PYTHON_CMD -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
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

