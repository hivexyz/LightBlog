# LightBlog

一个轻量级个人博客系统，基于 FastAPI + SQLite，面向 2 核 2G 服务器部署。当前站点品牌建议为“机器达尔文”，适合作为算法工程师的技术笔记、模型实验记录和 AI 工程实践沉淀。

## 特性

- 轻量：FastAPI + SQLite + Jinja2，无前端构建链路。
- Markdown 写作：支持代码块、表格、引用和基础排版。
- 数学公式：支持行内 `$E=mc^2$` 和块级 `$$...$$`，前台按需加载 KaTeX。
- 图片上传：后台支持头像、文章封面、正文图片从本地上传。
- AI 共创：根据主题和核心观点生成初稿，通过采访补充作者观点，生成带封面和正文插画的最终草稿。
- 按需研究：主动规划和执行网络搜索，选择可信资料后生成带可追溯引用的文章。
- 长图导出：后台可选择模板，按 Markdown 一级/二级标题拆分文章并导出 PNG 长图 ZIP。
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
| AI_API_BASE | https://api.openai.com/v1 | OpenAI-compatible API 根地址 |
| AI_API_KEY | 空 | 模型服务密钥；为空时 AI 功能禁用 |
| AI_TEXT_MODEL | 空 | 文本模型名；与 API Key 同时配置后启用共创 |
| AI_IMAGE_MODEL | 空 | 图片模型名；为空时仍可生成文字，但不能生成配图 |
| AI_REQUEST_TIMEOUT | 180 | 单次文本模型调用超时秒数；最终文章与配图规划已拆成两个请求 |
| AI_MAX_CONTEXT_CHARS | 50000 | 单次发送给模型的文章上下文字符上限 |
| AI_MAX_INLINE_IMAGES | 2 | 每篇文章最多规划的正文配图数（不含封面） |
| AI_FINAL_MAX_TOKENS | 4800 | 最终文章生成的最大输出 token |
| AI_IMAGE_PLAN_MAX_TOKENS | 1800 | 配图规划的最大输出 token |
| AI_HUMANIZE_MAX_TOKENS | 4800 | “去除 AI 腔”编辑的最大输出 token |
| AI_JOB_WORKER_ENABLED | true | 是否启动 SQLite 后台写作任务 worker |
| AI_JOB_POLL_INTERVAL | 1 | worker 查询待执行任务的间隔秒数 |
| AI_JOB_STALE_SECONDS | 600 | 运行中任务超过该时间未更新时允许恢复 |
| AI_JOB_MAX_ATTEMPTS | 2 | 中断任务的最大领取次数 |
| AI_WRITING_STYLE | 内置技术写作规范 | 自定义博客写作风格提示词 |
| WEB_SEARCH_PROVIDER | 空 | 必须显式设置为 `tavily` 或 `tavily_hub`；不使用模型原生搜索 |
| WEB_SEARCH_API_BASE | 空 | 搜索 API 根地址，必须显式配置 |
| WEB_SEARCH_API_KEY | 空 | 搜索服务密钥，必须显式配置 |
| WEB_SEARCH_MAX_QUERIES | 3 | 每次 AI 最多规划的检索词数量 |
| WEB_SEARCH_MAX_RESULTS | 5 | 单次搜索最多保留的结果数 |
| WEB_SEARCH_TIMEOUT | 30 | 搜索请求超时秒数 |

注意：`ADMIN_USERNAME` / `ADMIN_PASSWORD` 只在数据库里不存在该管理员时用于首次创建。数据库已经初始化后，单独修改环境变量不会改变现有密码。

### 配置 AI 共创

AI 共创使用 OpenAI-compatible 的 `/chat/completions` 和 `/images/generations` 接口，模型运行在外部服务，不占用博客服务器的推理内存。在项目根目录创建不入库的 `.env`：

```dotenv
AI_API_BASE=https://api.openai.com/v1
AI_API_KEY=your-api-key
AI_TEXT_MODEL=your-text-model
AI_IMAGE_MODEL=your-image-model
WEB_SEARCH_PROVIDER=tavily_hub
WEB_SEARCH_API_BASE=https://tavily.sharyuke.com/api/proxy
WEB_SEARCH_API_KEY=your-hub-key
```

使用标准 Tavily 时改为：

```dotenv
WEB_SEARCH_PROVIDER=tavily
WEB_SEARCH_API_BASE=https://api.tavily.com
WEB_SEARCH_API_KEY=your-tavily-key
```

未完整配置这三个变量时，写作功能保持可用；点击“搜索资料”或“核实选中文字”会弹窗提示网络搜索未配置。

重新构建并启动容器：

```bash
docker compose up -d --build
```

进入“后台 -> 新建文章”即可看到 AI 共创手记。使用顺序为：

1. 输入主题和核心观点，选择“个人判断、技术教程、问题复盘、观点辩论或研究笔记”，并可补充作者口吻。
2. 可选：规划检索词、主动搜索，并勾选要使用的资料。普通对话不会自动搜索。
3. 生成初稿，让 AI 提问，并在对话框回答或提出修改要求。
4. 检查并编辑“已确认写作要点”。
5. 提交最终稿后台任务。页面会显示队列、文章生成和配图规划进度，刷新后可继续恢复。
6. 可执行“去除 AI 腔”，查看前后版本并随时恢复润色前内容。
7. 将最终稿应用到编辑器。系统会自动切换为草稿，仍需点击“保存”才会写入文章。

AI 会话、问答、研究来源与配图状态保存在 SQLite；生成图片经 Pillow 校验后压缩为 WebP，保存在现有 `uploads/YYYY/MM/` 目录。只有被勾选的网络资料会进入写作上下文，模型生成的外部链接还会经过来源白名单校验。API Key 只在服务器端读取，不会返回浏览器。详细设计见 [AI 共创 MVP](docs/ai-writing-mvp.md)。

最终稿生成使用 SQLite 持久化任务队列，不依赖浏览器请求持续连接。后台先生成文章并在约 70% 进度时落库，再规划配图；进程中断后会从已保存文章继续，不重复生成正文。多 Gunicorn worker 通过条件更新原子领取任务，不需要 Redis 或 Celery。

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
- 文章列表中选择长图模板并导出，下载结果为 ZIP，内部按章节生成 `01-章节名.png`

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
timeout = 240
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
