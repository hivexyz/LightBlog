# LightBlog

一个轻量级个人博客系统，基于 FastAPI + SQLite，面向 2 核 2G 服务器部署。当前站点品牌建议为“机器达尔文”，适合作为算法工程师的技术笔记、模型实验记录和 AI 工程实践沉淀。

## 特性

- 轻量：FastAPI + SQLite + Jinja2，无前端构建链路。
- Markdown 写作：支持代码块、表格、引用和基础排版。
- 数学公式：支持行内 `$E=mc^2$` 和块级 `$$...$$`，前台按需加载 KaTeX。
- 图片上传：后台支持头像、文章封面、正文图片从本地上传。
- 封面展示：首页文章卡片右侧显示封面缩略图，文章详情页不重复展示封面大图。
- 安全：bleach XSS 清洗、CSRF 防护、登录失败限流。
- SQLite 优化：WAL 模式、`busy_timeout`、浏览量内存缓冲，减少低配机器写锁压力。
- 前台优化：站点设置、分类、标签短 TTL 缓存；列表页避免加载正文大字段。
- Docker 部署：内置迁移和初始化入口。

## 快速开始

### 开发环境

```bash
# 安装依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 初始化数据库
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli init-db

# 启动开发服务器
DEBUG=true .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

访问：

```text
前台：http://127.0.0.1:8000
后台：http://127.0.0.1:8000/admin
```

默认账号：

```text
admin / admin123
```

### Docker 部署

```bash
# 修改 docker-compose.yml 中的密码和 SECRET_KEY
docker-compose up -d
```

如果使用新版 Docker Compose，也可以执行：

```bash
docker compose up -d
```

容器启动时会执行：

```bash
alembic upgrade head
python -m app.cli init-db
```

也就是自动迁移数据库并初始化默认数据。

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| SECRET_KEY | dev-secret-key-change-in-production | 会话密钥，生产环境必须修改 |
| ADMIN_USERNAME | admin | 管理员用户名 |
| ADMIN_PASSWORD | admin123 | 管理员密码 |
| DATABASE_URL | sqlite:///./data/blog.db | 数据库路径 |
| COOKIE_SECURE | false | Cookie Secure（HTTPS 环境设为 true） |
| POSTS_PER_PAGE | 10 | 每页文章数 |
| UPLOAD_DIR | ./uploads | 上传图片目录 |

注意：`ADMIN_USERNAME` / `ADMIN_PASSWORD` 只在数据库里不存在该管理员时用于首次创建。数据库已经初始化后，单独修改环境变量不会改变现有密码。

## 后台使用

后台入口：

```text
/admin
```

支持：

- 文章新建、编辑、删除
- 草稿和发布状态
- 分类管理
- 标签管理
- 站点标题、副标题、描述、头像、GitHub 链接、关于页内容
- 本地图片上传

图片上传位置：

- `站点设置 -> 头像 URL -> 上传头像`
- `文章编辑 -> 封面图 URL -> 上传封面`
- `文章编辑 -> 内容 Markdown -> 上传正文图片`

上传限制：

- 支持 `jpg`、`jpeg`、`png`、`gif`、`webp`
- 单文件最大 `5MB`
- 文件保存在 `uploads/YYYY/MM/`

## 修改密码

如果还没有重要数据，可以删除数据库后重新初始化，让新的环境变量生效：

```bash
docker compose stop web
rm -f data/blog.db data/blog.db-wal data/blog.db-shm
docker compose up -d web
```

如果已有数据，不要删库，直接更新数据库中的密码哈希：

```bash
docker compose exec web python - <<'PY'
from getpass import getpass
from app.database import SessionLocal
from app.models import User
from app.auth import hash_password

username = input("用户名 [admin]: ").strip() or "admin"
password = getpass("新密码: ").strip()

if not password:
    raise SystemExit("密码不能为空")

db = SessionLocal()
try:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise SystemExit(f"用户不存在: {username}")
    user.password_hash = hash_password(password)
    db.commit()
    print(f"已修改用户 {username} 的密码")
finally:
    db.close()
PY
```

如果连续输错密码超过限制，会触发 15 分钟登录锁定。开发或自用部署时可以重启 web 容器清除内存中的失败记录：

```bash
docker compose restart web
```

## 2 核 2G 部署建议

当前配置可以覆盖个人技术博客的常规流量。建议保持：

```python
# gunicorn.conf.py
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
```

不要盲目增加 worker。SQLite 是单写多读模型，worker 过多会增加内存占用和写锁竞争。

适合的使用规模：

- 个人博客日常访问
- 每天几百到几千 PV
- 偶发几十 QPS 的文章访问

可能需要进一步优化的场景：

- 文章数量达到几千篇后，搜索建议改 SQLite FTS5。
- 上传大量高清图片后，建议增加图片压缩和缩略图生成。
- 如果访问量持续升高，可以在 Nginx 增加匿名页面 micro-cache。

## 目录结构

```
app/
├── main.py              # 应用入口
├── config.py            # 配置
├── database.py          # 数据库连接
├── models.py            # 数据模型
├── auth.py              # 认证
├── utils.py             # 工具函数
├── view_counter.py      # 浏览量缓冲
├── cli.py               # 命令行工具
├── routes/
│   ├── main.py          # 前台路由
│   └── admin.py         # 后台路由
├── templates/           # 模板
└── static/              # 静态资源
```

## 备份

```bash
# 备份数据库（SQLite WAL 模式安全备份）
./scripts/backup.sh

# 恢复
docker-compose stop web
cp backups/blog_xxx.db data/blog.db
rm -f data/blog.db-wal data/blog.db-shm
docker-compose start web
```

建议同时备份：

```text
data/blog.db
uploads/
```

## 服务器更新

代码提交并推送到 GitHub 后，在服务器项目目录执行：

```bash
./scripts/deploy_update.sh
```

脚本会依次执行：

- 检查工作区是否干净，避免覆盖服务器上的未提交改动
- 备份 `data/blog.db`
- `git pull --ff-only`
- `docker compose build web`
- `docker compose up -d`
- 输出服务状态和最近 web 日志

可选参数：

```bash
./scripts/deploy_update.sh --skip-backup      # 跳过数据库备份
./scripts/deploy_update.sh --no-build         # 只拉代码并重启，不重新构建镜像
./scripts/deploy_update.sh --legacy-compose   # 使用 docker-compose 命令
```

## 技术方案

详见 [docs/technical-design.md](docs/technical-design.md)
