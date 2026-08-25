# LightBlog 技术方案设计（FastAPI 版）

> 版本：v2.1 | 状态：可作为实现依据
> 技术栈：FastAPI + SQLite + Jinja2 服务端渲染

---

## 一、目标与约束

### 1.1 目标
构建一个轻量级、易部署、低资源占用的个人博客系统，支持 Markdown 写作、文章管理、分类标签等核心功能。

### 1.2 资源约束
- **服务器规格**：2 核 CPU / 2GB 内存
- **内存目标**：
  - 应用进程（Uvicorn workers）总内存 **< 200MB**
  - 整机内存占用（含系统）**< 600MB**，预留 1.4GB 给文件缓存和突发流量
- **并发目标**：支持日 PV 1万+，峰值 QPS 50+
- **部署方式**：单机 Docker 部署，无需独立数据库服务

### 1.3 非目标（明确不做）
- 不做多用户/多租户（仅单管理员）
- 不做评论系统（预留扩展位，推荐接入第三方）
- 不做全文搜索引擎（用 SQLite LIKE 即可，后续可扩展 FTS5）

---

## 二、技术选型

| 层级 | 技术 | 选型理由 |
|------|------|----------|
| **Web 框架** | FastAPI 0.111 | 异步支持、自动 API 文档、Pydantic 校验，内存约 50-80MB |
| **ASGI 服务器** | Uvicorn (gunicorn 管理) | 异步高性能，2 workers 约 100-160MB |
| **数据库** | SQLite 3 (WAL 模式) | 零配置、文件型，WAL 模式支持读写并发 |
| **ORM** | SQLAlchemy 2.0 (同步) | SQLite 异步驱动收益有限，同步更简单稳定 |
| **模板引擎** | Jinja2 | 服务端渲染，SEO 友好 |
| **认证** | Session (itsdangerous 签名) | 轻量，无需 JWT 服务端存储 |
| **密码加密** | passlib[bcrypt] | 行业标准 |
| **Markdown** | python-markdown + pymdown-extensions + bleach | 服务端渲染 Markdown，arithmatex 输出公式标记，bleach 做 HTML 白名单清洗防 XSS |
| **数学公式** | KaTeX (CDN) | 前端渲染行内 `$...$` 和块级 `$$...$$` 公式 |
| **代码高亮** | Pygments | 服务端渲染，无前端开销 |
| **表单处理** | python-multipart | FastAPI 表单解析 |
| **图片校验** | Pillow | Image.verify() 校验真实图片类型 |
| **数据库迁移** | Alembic | SQLAlchemy 官方迁移工具 |
| **反向代理** | Nginx | 静态资源、gzip、HTTPS |
| **容器化** | Docker + docker-compose | 一键部署 |

### 选型说明
- **为什么用 FastAPI 而非 Flask**：自动 API 文档、Pydantic 类型校验、异步能力，内存仅比 Flask 高 10-20MB，可接受
- **为什么 SQLAlchemy 用同步**：SQLite 是文件数据库，aiosqlite 异步驱动在 WAL 模式下收益有限，同步代码更简单、调试方便
- **为什么不用 MySQL/PostgreSQL**：独立数据库进程至少占 100-200MB，2G 服务器不划算
- **为什么用 Pillow 校验图片**：imghdr 已废弃，python-magic 依赖系统 libmagic；Pillow 纯 Python，`Image.verify()` 可校验真实图片格式

---

## 三、系统架构

```
┌─────────────────────────────────────────────────┐
│                   Nginx                          │
│  (静态资源 / gzip / HTTPS / 反向代理)             │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│         Gunicorn + Uvicorn workers (2个)         │
│         每个 worker 约 50-80MB 内存              │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│              FastAPI Application                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ 前台路由  │ │ 后台路由  │ │  认证 & 权限      │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ 模板渲染  │ │ Markdown │ │  浏览量缓冲       │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│              SQLite (WAL 模式)                    │
│         blog.db + blog.db-wal + blog.db-shm      │
└─────────────────────────────────────────────────┘
```

### 3.1 进程模型
- **Worker 数量**：2（2 核 CPU，内存有限取 2）
- **Worker 类型**：Uvicorn worker（异步）
- **内存预估**：
  - Gunicorn master：~15MB
  - Uvicorn worker ×2：~100-160MB
  - **应用进程总计：~115-175MB（< 200MB ✓）**
  - Nginx：~10MB
  - 系统开销：~200-300MB
  - **整机总计：~325-485MB（< 600MB ✓）**

### 3.2 同步 ORM 与异步 FastAPI 的执行模型

**核心原则：所有涉及数据库访问的路由函数使用普通 `def`，不使用 `async def`。**

FastAPI 对 `def` 路由的处理机制：
- `async def` 路由：直接在 event loop 中执行，不能有阻塞调用
- `def` 路由：FastAPI 自动将其放到**线程池**（anyio threadpool）中执行，不会阻塞 event loop

因此：
- 数据库访问路由 → 用 `def`，同步 SQLAlchemy 在线程池中运行，不阻塞 event loop
- 纯异步路由（如健康检查）→ 可用 `async def`

```python
# ✅ 正确：数据库操作用 def，FastAPI 自动放线程池
@app.get('/post/{slug}')
def post_detail(slug: str, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.slug == slug).first()
    return post

# ❌ 错误：async def 中直接调用同步 ORM 会阻塞 event loop
@app.get('/post/{slug}')
async def post_detail(slug: str, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.slug == slug).first()  # 阻塞！
    return post
```

如果确实需要在 `async def` 中调用同步 DB 操作，必须用 `run_in_threadpool`：
```python
from fastapi.concurrency import run_in_threadpool

async def get_post(db, slug):
    return await run_in_threadpool(db.query(Post).filter(Post.slug == slug).first)
```

**本项目统一采用 `def` 路由 + 同步 SQLAlchemy**，简单且不阻塞。

---

## 四、数据模型设计

### 4.1 ER 关系

```
User (1) ──────< (N) Post
Post (N) >──────< (N) Tag  (通过 post_tags 关联表)
Post (N) >────── (1) Category
Setting (键值对表，存储站点配置)
```

### 4.2 表结构

#### User（用户表）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK | 主键 |
| username | String(64) | unique, not null | 用户名 |
| password_hash | String(256) | not null | bcrypt 密码哈希 |
| is_admin | Boolean | default true | 是否管理员 |
| created_at | DateTime | default now | 创建时间 |

#### Post（文章表）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK | 主键 |
| title | String(200) | not null | 标题 |
| slug | String(200) | unique, not null, index | URL 别名 |
| content | Text | not null | Markdown 原文 |
| content_html | Text | not null | 渲染并清洗后的 HTML（缓存） |
| summary | String(500) | default '' | 摘要 |
| cover_image | String(500) | default '' | 封面图路径 |
| status | Integer | default 1, index | 0=草稿, 1=已发布 |
| views | Integer | default 0 | 浏览量 |
| category_id | Integer | FK, index | 分类 ID |
| author_id | Integer | FK | 作者 ID |
| created_at | DateTime | default now, index | 创建时间 |
| updated_at | DateTime | default now, onupdate | 更新时间 |

#### Category（分类表）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK | 主键 |
| name | String(50) | unique, not null | 分类名 |
| slug | String(50) | unique, not null, index | URL 别名 |
| description | String(200) | default '' | 描述 |

#### Tag（标签表）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK | 主键 |
| name | String(50) | unique, not null | 标签名 |
| slug | String(50) | unique, not null, index | URL 别名 |

#### post_tags（文章-标签关联表）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| post_id | Integer | FK, PK | 文章 ID |
| tag_id | Integer | FK, PK | 标签 ID |

#### Setting（站点设置表）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| key | String(64) | PK | 配置键 |
| value | Text | | 配置值 |

**预置配置项**：
| key | 默认值 | 说明 |
|-----|--------|------|
| site_title | LightBlog | 站点标题 |
| site_subtitle | 一个轻量级的博客 | 站点副标题 |
| site_description | 记录生活与技术 | 站点描述 |
| site_avatar | | 头像 URL |
| github_url | | GitHub 链接 |
| about_content | | 关于页面 Markdown 内容 |

### 4.3 索引策略
- `post.slug`：唯一索引（详情页查询）
- `post.status` + `post.created_at`：联合索引（首页列表筛选已发布并排序）
- `post.category_id`：索引（分类筛选）
- `category.slug`、`tag.slug`：唯一索引

### 4.4 迁移策略
- 使用 **Alembic** 管理数据库迁移
- 首次部署：容器 entrypoint 执行 `alembic upgrade head`
- 后续变更：生成迁移脚本 `alembic revision --autogenerate -m "xxx"`，再执行 `alembic upgrade head`
- 备份：迁移前自动执行 SQLite online backup（见 9.3）

---

## 五、功能模块

### 5.1 前台功能（无需登录）
| 功能 | 路由 | 说明 |
|------|------|------|
| 首页 | `GET /` | 已发布文章列表，分页（每页 10 篇） |
| 文章详情 | `GET /post/{slug}` | 渲染 HTML，浏览量+1（缓冲写入） |
| 分类 | `GET /category/{slug}` | 按分类筛选已发布文章 |
| 标签 | `GET /tag/{slug}` | 按标签筛选已发布文章 |
| 归档 | `GET /archive` | 按年份分组展示已发布文章 |
| 搜索 | `GET /search?q=` | 标题+摘要 LIKE 搜索 |
| 关于 | `GET /about` | 读取 Setting 表 about_content 渲染 |
| RSS | `GET /feed.xml` | 最近 20 篇已发布文章 |

### 5.2 后台功能（需登录）
| 功能 | 路由 | 说明 |
|------|------|------|
| 登录 | `GET/POST /admin/login` | 用户名密码登录，失败限流 |
| 登出 | `GET /admin/logout` | 清除 session |
| 仪表盘 | `GET /admin/` | 文章数、浏览量、分类数统计 |
| 文章列表 | `GET /admin/posts` | 所有文章（含草稿），分页 |
| 新建文章 | `GET/POST /admin/post/new` | Markdown 编辑器 |
| 编辑文章 | `GET/POST /admin/post/{id}/edit` | 修改文章 |
| 删除文章 | `POST /admin/post/{id}/delete` | 删除文章及关联 |
| 分类管理 | `GET/POST /admin/categories` | 分类增删 |
| 标签管理 | `GET/POST /admin/tags` | 标签增删 |
| 站点设置 | `GET/POST /admin/settings` | 标题、副标题、关于等 |
| 图片上传 | `POST /admin/upload` | 上传图片，返回 URL |

### 5.3 Markdown 编辑器
- 使用 **EasyMDE**（~100KB），支持实时预览
- 工具栏：标题、粗体、斜体、代码块、链接、图片、列表
- 图片上传：调用 `/admin/upload` 接口，返回 URL 插入编辑器
- 数学公式：支持行内 `$E=mc^2$` 和块级 `$$...$$`，预览区用 KaTeX 渲染

---

## 六、安全设计

### 6.1 XSS 防护

**Markdown 渲染后用 bleach 清洗，分两步：**

1. **bleach.clean**：白名单标签和属性
2. **bleach.linkify**：自动给链接加 `rel="nofollow noopener noreferrer"`

```python
import bleach
from bleach.css_sanitizer import CSSSanitizer

ALLOWED_TAGS = [
    'a', 'abbr', 'acronym', 'b', 'blockquote', 'code', 'em', 'i', 'li',
    'ol', 'p', 'pre', 'strong', 'ul', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'br', 'hr', 'div', 'span', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'img', 'figure', 'figcaption'
]

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'rel'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    'code': ['class'],
    'pre': ['class'],
    'span': ['class'],
    'div': ['class'],
    'table': ['class'],
}

# 限制 img src，仅允许 http/https 协议及本站 /uploads/、/static/ 路径
def allow_img_src(tag, name, value):
    if name == 'src':
        return value.startswith(('http://', 'https://', '/uploads/', '/static/'))
    return True

def sanitize_html(html):
    # 第一步：白名单清洗
    html = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes={
            **ALLOWED_ATTRIBUTES,
            'img': {'src': allow_img_src, 'alt': True, 'title': True, 'width': True, 'height': True},
        },
        css_sanitizer=CSSSanitizer(),
        strip=True
    )
    # 第二步：链接自动加 rel
    html = bleach.linkify(html, callbacks=[set_link_rel])
    return html

def set_link_rel(attrs, new=False):
    attrs[(None, 'rel')] = 'nofollow noopener noreferrer'
    return attrs
```

**数学公式安全处理：**
- 使用 `pymdownx.arithmatex` (generic 模式) 将 `$...$` 渲染为 `<span class="arithmatex">\(...\)</span>`，`$$...$$` 渲染为 `<div class="arithmatex">\[...\]</div>`
- `span` 和 `div` 的 `class` 属性在白名单内，公式内容为纯文本（LaTeX 语法），不含 HTML 标签
- 前端 KaTeX auto-render 负责渲染，不执行任意 HTML
- 不放开 `script`、事件属性（onerror/onclick 等）、`javascript:` 协议等危险内容

- 模板中文章内容用 `|safe` 标记（已清洗）
- 其他用户输入由 Jinja2 自动转义

### 6.2 认证与授权
- 密码：bcrypt 哈希（passlib），cost factor = 12
- Session：itsdangerous 签名 cookie
- **Cookie 属性**：
  - `HttpOnly: true`（防止 XSS 窃取）
  - `SameSite: lax`
  - `Secure`: 根据环境变量 `COOKIE_SECURE` 决定
    - 开发环境（HTTP）：`Secure=false`
    - 生产环境（HTTPS）：`Secure=true`
- 登录限流：同 IP 5 分钟内最多 5 次失败，超过锁定 15 分钟
- 后台所有路由校验 `is_admin`

### 6.3 CSRF 防护
- 登录成功后生成独立随机 `csrf_nonce = secrets.token_urlsafe(32)`，与 `user_id` 一起写入签名 session cookie
- CSRF token 仅包含 `csrf_nonce`（不包含完整 session cookie 值），避免削弱 HttpOnly 防护
- 校验时从当前 session 解出 `csrf_nonce`，验证 token 中的 nonce 一致
- 后台所有 POST 表单和上传接口均校验 CSRF token（itsdangerous 签名，1 小时有效）
- 登录页未登录状态使用空 nonce 的匿名 token

### 6.4 SQL 注入
- 全部使用 SQLAlchemy ORM 参数化查询，禁止拼接 SQL

### 6.5 文件上传安全
- 白名单后缀：`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`
- 文件大小限制：单文件 ≤ 5MB
- **真实图片校验**：Pillow `Image.verify()` 验证图片完整性
- 文件名：UUID 重命名，避免路径遍历
- 存储路径：`/app/uploads/`，Nginx 只读暴露
- 删除文章时不自动删除图片（避免误删，提供手动清理脚本）

---

## 七、性能优化

### 7.1 浏览量写入策略

**设计决策：允许少量丢失的内存缓冲 + 定时批量刷盘。**

原因：
- 浏览量是统计指标，少量丢失不影响业务
- SQLite 单写者模型，每次请求写库会造成写锁竞争
- 2 个 worker 各有独立内存缓冲，worker 重启/崩溃时该 worker 未刷盘的计数会丢失

实现：
- 每个 worker 维护 `dict[post_id, count]` 内存缓冲
- 触发刷盘条件（满足任一）：
  - 定时：每 60 秒
  - 阈值：单 worker 累计 100 次
  - 进程关闭：FastAPI lifespan shutdown 事件中 flush
- 刷盘 SQL：`UPDATE post SET views = views + :count WHERE id = :post_id`

**丢失场景与影响**：
| 场景 | 丢失量 | 影响 |
|------|--------|------|
| worker 正常滚动重启 | ≤ 60 秒内的计数 | 可忽略 |
| worker 崩溃 | ≤ 60 秒内的计数 | 可忽略 |
| 容器宕机 | 所有 worker 未刷盘计数 | 少量丢失 |

如果后续需要精确统计，可改为：
- 方案 A：直接写库（牺牲并发性能）
- 方案 B：用 Redis 做计数缓冲（增加依赖）
- 方案 C：单 worker 部署（牺牲并发能力）

### 7.2 SQLite WAL 模式
- 连接时执行 `PRAGMA journal_mode=WAL`
- 读写可并发，读不阻塞写，写不阻塞读
- `PRAGMA synchronous=NORMAL` 平衡性能和安全

### 7.3 数据库查询优化
- 文章列表只查 `id, title, slug, summary, cover_image, created_at, views`，不查 `content`
- 分类、标签列表用 `joinedload` 预加载
- `content_html` 缓存：保存文章时渲染并清洗，存入 DB，详情页直接读取

### 7.4 前端优化
- 无重型框架，原生 CSS + 少量 JS，首屏 < 50KB
- Nginx 开启 gzip，压缩率 60-80%
- 静态资源 `Cache-Control: max-age=31536000`
- 图片 `loading="lazy"` 懒加载

---

## 八、文件上传设计

### 8.1 上传流程
1. 编辑器点击图片上传 → 选择文件
2. POST `/admin/upload`，form-data 字段 `file`
3. 后端校验：后缀白名单 → 大小 ≤ 5MB → Pillow `Image.verify()` 校验真实图片
4. 生成 UUID 文件名，保存到 `/app/uploads/{yyyy}/{mm}/{uuid}.{ext}`
5. 返回 JSON `{"url": "/uploads/2024/01/xxx.jpg"}`
6. 编辑器将 URL 插入 Markdown

### 8.2 存储与暴露
- 物理路径：`/app/uploads/`（Docker volume 挂载到宿主机 `./uploads`）
- URL 路径：`/uploads/...`
- Nginx 配置：`location /uploads/ { alias /app/uploads/; expires 30d; }`

### 8.3 清理策略
- 不自动删除（文章可能引用）
- 提供管理命令 `python -m app.cli cleanup-uploads`：扫描所有文章 content 中引用的图片，删除未被引用的文件

---

## 九、部署方案

### 9.1 Docker Compose

默认 HTTP 模式配置（可直接 `docker-compose up -d` 启动）：

```yaml
services:
  web:
    build: .
    expose:
      - "8000"
    volumes:
      - ./data:/app/data
      - ./uploads:/app/uploads
    environment:
      - SECRET_KEY=change-me-in-production
      - ADMIN_USERNAME=admin
      - ADMIN_PASSWORD=change-me
      - COOKIE_SECURE=false  # 默认 HTTP；生产 HTTPS 时改为 true
    restart: always

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./uploads:/app/uploads:ro
    depends_on:
      - web
    restart: always
```

> 生产环境启用 HTTPS 请参考 9.4 节，需将 `COOKIE_SECURE` 改为 `true`，并在 nginx 中配置 443 端口和证书挂载。

### 9.2 启动初始化闭环（entrypoint.sh）

容器启动时由 `entrypoint.sh` 负责：
1. 执行 `alembic upgrade head`（幂等：已迁移则跳过）
2. 执行 `python -m app.cli init-db`（幂等：管理员和默认设置已存在则跳过）
3. 启动 gunicorn

```bash
#!/bin/sh
set -e

# 1. 数据库迁移
alembic upgrade head

# 2. 初始化默认数据（管理员、站点设置）
python -m app.cli init-db

# 3. 启动应用
exec gunicorn app.main:app -c gunicorn.conf.py
```

**幂等保证**：
- `init-db` 命令检查管理员用户名是否存在，不存在才创建
- 默认设置项检查 key 是否存在，不存在才插入

### 9.3 Gunicorn 配置
```python
# gunicorn.conf.py
bind = "0.0.0.0:8000"
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
max_requests = 1000
max_requests_jitter = 50
timeout = 30
```

### 9.4 HTTPS 配置

**默认部署为 HTTP 模式**（`COOKIE_SECURE=false`，nginx 监听 80），可直接 `docker-compose up -d` 启动。

**生产环境必须启用 HTTPS**，步骤如下：

1. 将证书文件放入 `./certs/` 目录：
   - `fullchain.pem`（证书链）
   - `privkey.pem`（私钥）

2. 修改 `docker-compose.yml`：
   - `COOKIE_SECURE=true`
   - nginx 端口增加 `"443:443"`
   - 挂载证书：`./certs:/etc/nginx/certs:ro`

3. 替换 `nginx.conf` 为 HTTPS 配置：
```nginx
server {
    listen 80;
    server_name example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name example.com;

    ssl_certificate /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;

    location / {
        proxy_pass http://web:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /uploads/ {
        alias /app/uploads/;
        expires 30d;
    }
}
```

证书可通过 Let's Encrypt 免费获取：`certbot certonly --standalone -d example.com`

### 9.5 SQLite WAL 模式备份

**不能直接 `cp blog.db`**，因为 WAL 模式下活跃数据可能在 `blog.db-wal` 中。

正确备份方式（三选一）：

**方式 1：SQLite Online Backup（推荐，不中断服务）**
```bash
sqlite3 data/blog.db ".backup 'backups/blog_$(date +%Y%m%d_%H%M).db'"
```

**方式 2：Checkpoint 后复制**
```bash
sqlite3 data/blog.db "PRAGMA wal_checkpoint(TRUNCATE);"
cp data/blog.db backups/blog_$(date +%Y%m%d_%H%M).db
```

**方式 3：停止服务后复制所有文件**
```bash
docker-compose stop web
cp data/blog.db data/blog.db-wal data/blog.db-shm backups/
docker-compose start web
```

**定时备份脚本**（crontab 每天凌晨 3 点）：
```bash
#!/bin/bash
BACKUP_DIR="/path/to/backups"
mkdir -p $BACKUP_DIR
sqlite3 /path/to/data/blog.db ".backup '$BACKUP_DIR/blog_$(date +%Y%m%d_%H%M).db'"
# 保留最近 30 天
find $BACKUP_DIR -name "blog_*.db" -mtime +30 -delete
```

**恢复**：
```bash
docker-compose stop web
cp backups/blog_xxx.db data/blog.db
rm -f data/blog.db-wal data/blog.db-shm
docker-compose start web
```

---

## 十、当前仓库实现状态

> 状态：当前核心功能与配套文档已实现，后续以验收测试为准。

| 文件/模块 | 状态 | 说明 |
|-----------|------|------|
| `app/config.py` | ✅ 已完成 | 配置类，含 COOKIE_SECURE |
| `app/database.py` | ✅ 已完成 | SQLAlchemy 引擎、WAL 模式、Session |
| `app/models.py` | ✅ 已完成 | User, Post, Category, Tag, Setting 模型 |
| `app/auth.py` | ✅ 已完成 | 密码哈希、Session、CSRF、登录限流 |
| `app/utils.py` | ✅ 已完成 | Markdown 渲染、bleach 清洗（img src callable）、slug |
| `app/view_counter.py` | ✅ 已完成 | 浏览量内存缓冲 + 定时刷盘 |
| `app/cli.py` | ✅ 已完成 | init-db、cleanup-uploads 命令 |
| `app/routes/main.py` | ✅ 已完成 | 前台路由（def，同步 ORM 在线程池执行） |
| `app/routes/admin.py` | ✅ 已完成 | 后台路由（def，Pillow 图片校验） |
| `app/main.py` | ✅ 已完成 | FastAPI 入口，DEBUG 模式 create_all，生产用 Alembic |
| `app/templates/` | ✅ 已完成 | base, index, post, category, tag, archive, search, about, feed.xml, admin/* |
| `app/static/css/style.css` | ✅ 已完成 | 全局样式 |
| `alembic/` | ✅ 已完成 | env.py、0001_initial 迁移脚本 |
| `Dockerfile` | ✅ 已完成 | 容器构建 |
| `docker-compose.yml` | ✅ 已完成 | 编排 |
| `nginx.conf` | ✅ 已完成 | 反向代理、HTTPS、gzip |
| `gunicorn.conf.py` | ✅ 已完成 | 2 workers、UvicornWorker |
| `entrypoint.sh` | ✅ 已完成 | alembic upgrade head + init-db + gunicorn（迁移失败阻断启动） |
| `scripts/backup.sh` | ✅ 已完成 | SQLite online backup（`.backup` 命令，WAL 模式安全） |
| `README.md` | ✅ 已完成 | 使用说明 |

---

## 十一、验收标准

### 11.1 功能验收
- [ ] 首页展示已发布文章，分页正常，草稿不可见
- [ ] 文章详情页正确渲染 Markdown（含代码高亮、表格）
- [ ] 分类、标签页正确筛选文章
- [ ] 归档页按年份分组
- [ ] 搜索能匹配标题和摘要
- [ ] RSS feed 格式正确，包含最近 20 篇
- [ ] 管理员登录成功/失败提示正确
- [ ] 后台可新建/编辑/删除文章
- [ ] 后台可管理分类、标签
- [ ] 后台可修改站点设置（标题、关于等）
- [ ] 图片上传成功，返回可访问 URL
- [ ] 草稿文章通过直接 URL 访问返回 404

### 11.2 安全验收
- [ ] 文章中注入 `<script>alert(1)</script>` 不执行
- [ ] 文章中注入 `<img src=x onerror=alert(1)>` 不执行
- [ ] 文章中注入 `<a href="javascript:alert(1)">` 被过滤
- [ ] 链接自动添加 `rel="nofollow noopener noreferrer"`
- [ ] img src 仅允许 http/https、/uploads/、/static/ 路径
- [ ] 密码不以明文存储（bcrypt 哈希）
- [ ] 未登录访问 `/admin/*` 重定向到登录页
- [ ] 登录失败 5 次后锁定 15 分钟
- [ ] 上传非图片文件被拒绝
- [ ] 上传超过 5MB 文件被拒绝
- [ ] 上传伪造后缀的非图片文件被 Pillow 校验拒绝

### 11.3 性能验收
- [ ] `docker stats` 显示 web 容器内存 < 200MB
- [ ] `ab -n 1000 -c 50 http://localhost/` 无 5xx 错误
- [ ] 首页响应时间 < 200ms（P95）
- [ ] 文章详情页响应时间 < 100ms（P95，content_html 已缓存）

### 11.4 部署验收
- [ ] `docker-compose up -d` 一键启动成功
- [ ] 访问 `http://服务器IP` 显示博客首页
- [ ] 访问 `http://服务器IP/admin/login` 显示登录页
- [ ] `data/blog.db` 持久化，重启容器数据不丢失
- [ ] 备份脚本可正常备份和恢复
- [ ] HTTPS 环境下 Cookie Secure 生效，登录正常

---

## 十二、目录结构

```
LightBlog/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # 配置
│   ├── database.py          # 数据库连接、Session
│   ├── models.py            # SQLAlchemy 模型
│   ├── auth.py              # 认证、Session、CSRF、限流
│   ├── utils.py             # Markdown 渲染、bleach 清洗、slug
│   ├── view_counter.py      # 浏览量内存缓冲
│   ├── cli.py               # 命令行工具 (init-db, cleanup-uploads)
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── main.py          # 前台路由
│   │   └── admin.py         # 后台路由
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── post.html
│   │   ├── archive.html
│   │   ├── category.html
│   │   ├── tag.html
│   │   ├── search.html
│   │   ├── about.html
│   │   ├── feed.xml
│   │   └── admin/
│   │       ├── login.html
│   │       ├── dashboard.html
│   │       ├── posts.html
│   │       ├── post_form.html
│   │       ├── categories.html
│   │       ├── tags.html
│   │       └── settings.html
│   └── static/
│       ├── css/style.css
│       ├── js/editor.js
│       └── favicon.ico
├── alembic/                 # 数据库迁移
│   ├── env.py
│   └── versions/
├── alembic.ini
├── uploads/                 # 上传文件
├── data/                    # SQLite 数据库
├── backups/                 # 备份
├── scripts/
│   └── backup.sh
├── entrypoint.sh
├── Dockerfile
├── docker-compose.yml
├── gunicorn.conf.py
├── nginx.conf
├── requirements.txt
└── README.md
```
