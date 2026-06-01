#!/usr/bin/env bash
set -e

# macOS ObjC fork-safety: CoreFoundation in parent poisons fork()s; setting
# this env var before gunicorn prevents the SIGKILL spiral after worker recycles.
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

PORTS=(9080)
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$PROJECT_DIR/cgm_portal"
VENV_DIR="$APP_DIR/venv"
DC="docker-compose"
if [ -x /opt/homebrew/bin/docker-compose ]; then
    DC="/opt/homebrew/bin/docker-compose"
fi

# --- Load .env ---
if [ -f "$APP_DIR/.env" ]; then
    set -a
    source "$APP_DIR/.env"
    set +a
fi

# --- Graceful stop via pid file (preferred over SIGKILL) ---
#     Gives the existing master 10 s to drain workers cleanly before we
#     escalate. SIGKILL during a HUP/restart is what historically kicked
#     cgm.pdhc into the "worker OOM respawn loop" (see CLAUDE.md §10 notes).
PID_FILE="$APP_DIR/gunicorn.pid"
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping previous gunicorn master (pid $OLD_PID) with TERM..."
        kill -TERM "$OLD_PID" 2>/dev/null || true
        for i in 1 2 3 4 5 6 7 8 9 10; do
            kill -0 "$OLD_PID" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "  Master did not exit after 10 s — escalating to KILL."
            kill -KILL "$OLD_PID" 2>/dev/null || true
        fi
    fi
    rm -f "$PID_FILE"
fi

# --- Belt-and-braces: clear any stray listener on our own port block ---
echo "Clearing ports ${PORTS[*]}..."
for port in "${PORTS[@]}"; do
    PIDS=$(lsof -ti :"$port" 2>/dev/null) && [ -n "$PIDS" ] && echo "$PIDS" | xargs kill -9 2>/dev/null || true
done

# --- Ensure Docker is running (managed by restart_all.sh or manually) ---
if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker is not running. Start Colima first:"
    echo "  colima start && docker context use colima"
    exit 1
fi

# --- Create venv if needed ---
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# --- Activate venv ---
source "$VENV_DIR/bin/activate"

# --- Install dependencies ---
echo "Installing dependencies..."
pip install -q -r "$APP_DIR/requirements.txt"

# --- Start PostgreSQL via Docker ---
echo "Starting PostgreSQL on port 9081..."
cd "$APP_DIR"
$DC up -d db
echo "Waiting for PostgreSQL..."
until $DC exec -T db pg_isready -U "${POSTGRES_USER:-cgm_portal}" >/dev/null 2>&1; do
    sleep 1
done
echo "PostgreSQL is ready."

# --- Run migrations ---
cd "$APP_DIR"
export FLASK_APP=app
if [ ! -d "migrations/versions" ]; then
    echo "Initializing migrations..."
    flask db init
    flask db migrate -m "Initial migration"
fi
echo "Running migrations..."
flask db upgrade

# --- Start gunicorn (hardened, per CLAUDE.md §6 step 7) ---
#     --max-requests / --max-requests-jitter: workers auto-recycle before
#       they drift into the SIGKILL/OOM region (proven fix for cgm.pdhc's
#       historical worker-respawn loop).
#     --graceful-timeout 30: give workers time to drain on shutdown.
#     --daemon: proper process-group detachment (no `nohup ... &`).
#     --pid: stable pid file for the graceful-stop block above.
echo "Starting gunicorn on port 9080..."
mkdir -p "$APP_DIR/logs"
gunicorn \
    --bind 127.0.0.1:9080 \
    --workers 2 \
    --timeout 120 \
    --graceful-timeout 30 \
    --max-requests 500 \
    --max-requests-jitter 50 \
    --daemon \
    --pid "$APP_DIR/gunicorn.pid" \
    --access-logfile "$APP_DIR/logs/access.log" \
    --error-logfile "$APP_DIR/logs/error.log" \
    "app:create_app()"

sleep 2

# --- Health check ---
if curl -sf http://localhost:9080/api/v1/health >/dev/null 2>&1; then
    echo "  Application is healthy!"
else
    echo "  WARNING: Health check not passing yet"
fi

echo ""
echo "=== cgm.pdhc is running ==="
echo "  App:      http://localhost:9080"
echo "  Web UI:   http://localhost:9080/login"
echo "  Database: localhost:9081"
echo "  PID:      $APP_DIR/gunicorn.pid"
echo "  Logs:     $APP_DIR/logs/"
echo "  Stop DB:  cd $APP_DIR && $DC down"
echo ""
