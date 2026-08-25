#!/bin/bash
# LightBlog SQLite 备份脚本
# 用法: ./scripts/backup.sh [备份目录]
# 注意：SQLite WAL 模式下不能直接 cp blog.db，需要用 .backup 命令

set -e

BACKUP_DIR="${1:-./backups}"
DB_PATH="./data/blog.db"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/blog_${TIMESTAMP}.db"

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_PATH" ]; then
    echo "[错误] 数据库文件不存在: $DB_PATH"
    exit 1
fi

# 使用 SQLite online backup（不中断服务）
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

if [ -f "$BACKUP_FILE" ]; then
    echo "[成功] 备份已保存: $BACKUP_FILE"
else
    echo "[错误] 备份失败"
    exit 1
fi

# 保留最近 30 天的备份
find "$BACKUP_DIR" -name "blog_*.db" -mtime +30 -delete
echo "[信息] 已清理 30 天前的旧备份"
