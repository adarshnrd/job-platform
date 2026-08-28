.PHONY: start stop api web install help

# Default: start both servers concurrently
start:
	@bash ./scripts/start.sh

help:
	@echo "Usage:"
	@echo "  make start   — Start API + frontend concurrently"
	@echo "  make api     — Start FastAPI backend only"
	@echo "  make web     — Start Next.js frontend only"
	@echo "  make stop    — Stop all background processes"
	@echo "  make install — Install all dependencies"

api:
	@echo "Starting FastAPI backend on http://localhost:8000 ..."
	cd apps/api && ( [ -f venv/bin/python ] && ./venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload || python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload )

web:
	@echo "Starting Next.js frontend on http://localhost:3000 ..."
	cd apps/web && npm run dev

stop:
	@echo "Stopping servers..."
	-pkill -f "uvicorn main:app" 2>/dev/null || true
	-pkill -f "next dev" 2>/dev/null || true
	@echo "Done."

install:
	@echo "Creating Python virtual environment in apps/api/venv..."
	cd apps/api && ( [ -d venv ] || python3 -m venv venv || python -m venv venv )
	@echo "Installing Python dependencies..."
	cd apps/api && ( [ -f venv/bin/pip ] && ./venv/bin/pip install -r requirements.txt || pip install -r requirements.txt )
	@echo "Installing Playwright browsers..."
	cd apps/api && ( [ -f venv/bin/python ] && ./venv/bin/python -m playwright install chromium || python3 -m playwright install chromium )
	@echo "Installing Node dependencies..."
	cd apps/web && npm install
	@echo "All dependencies installed successfully!"

