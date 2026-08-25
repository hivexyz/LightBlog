#!/bin/sh
set -e

echo "[entrypoint] 运行数据库迁移..."
alembic upgrade head

echo "[entrypoint] 初始化默认数据..."
python -m app.cli init-db

echo "[entrypoint] 启动应用..."
exec gunicorn app.main:app -c gunicorn.conf.py
