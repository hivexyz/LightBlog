#!/bin/bash
# LightBlog server update script
# Usage:
#   ./scripts/deploy_update.sh
#   ./scripts/deploy_update.sh --skip-backup
#   ./scripts/deploy_update.sh --no-build
#   ./scripts/deploy_update.sh --legacy-compose

set -euo pipefail

SKIP_BACKUP=false
NO_BUILD=false
COMPOSE_CMD="docker compose"

for arg in "$@"; do
    case "$arg" in
        --skip-backup)
            SKIP_BACKUP=true
            ;;
        --no-build)
            NO_BUILD=true
            ;;
        --legacy-compose)
            COMPOSE_CMD="docker-compose"
            ;;
        -h|--help)
            sed -n '1,8p' "$0"
            exit 0
            ;;
        *)
            echo "[error] Unknown option: $arg"
            exit 1
            ;;
    esac
done

cd "$(dirname "$0")/.."

echo "[info] Working directory: $(pwd)"

if ! command -v git >/dev/null 2>&1; then
    echo "[error] git is not installed"
    exit 1
fi

if ! $COMPOSE_CMD version >/dev/null 2>&1; then
    echo "[error] Docker Compose is unavailable: $COMPOSE_CMD"
    echo "[hint] Try: ./scripts/deploy_update.sh --legacy-compose"
    exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
    echo "[error] Working tree is not clean. Commit, stash, or inspect changes before updating."
    git status --short
    exit 1
fi

if [ "$SKIP_BACKUP" = false ] && [ -f "./data/blog.db" ]; then
    echo "[info] Backing up SQLite database..."
    ./scripts/backup.sh
fi

echo "[info] Pulling latest code..."
git pull --ff-only

if [ "$NO_BUILD" = false ]; then
    echo "[info] Building web image..."
    $COMPOSE_CMD build web
fi

echo "[info] Starting services..."
$COMPOSE_CMD up -d

echo "[info] Service status:"
$COMPOSE_CMD ps

echo "[info] Recent web logs:"
$COMPOSE_CMD logs web --tail=80

echo "[success] Update completed."
