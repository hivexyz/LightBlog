# LightBlog

一个轻量级的博客系统，基于 FastAPI + SQLite，专为 2核2G 服务器设计。

## 特性

- 🚀 轻量：应用内存 < 200MB，整机 < 600MB
- 📝 Markdown 写作，支持代码高亮
- 🧮 数学公式：行内 `$E=mc^2$` 和块级 `$$...$$`，KaTeX 渲染
- 🔒 安全：bleach XSS 清洗、CSRF 防护、登录限流
- 🗄️ SQLite WAL 模式，无需独立数据库
- 🐳 Docker 一键部署
- 📊 浏览量统计（内存缓冲，减少写锁）

## 快速开始

### 开发环境

```bash
# 安装依赖
pip install -r requirements.txt

# 初始化数据库
alembic upgrade head
python -m app.cli init-db

# 启动开发服务器
DEBUG=true uvicorn app.main:app --reload
```

访问 http://localhost:8000，后台 http://localhost:8000/admin

默认账号：`admin` / `admin123`

### Docker 部署

```bash
# 修改 docker-compose.yml 中的密码和 SECRET_KEY
docker-compose up -d
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| SECRET_KEY | dev-secret-key | 会话密钥，生产环境必须修改 |
| ADMIN_USERNAME | admin | 管理员用户名 |
| ADMIN_PASSWORD | admin123 | 管理员密码 |
| DATABASE_URL | sqlite:///./data/blog.db | 数据库路径 |
| COOKIE_SECURE | false | Cookie Secure（HTTPS 环境设为 true） |
| POSTS_PER_PAGE | 10 | 每页文章数 |

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

## 技术方案

详见 [docs/technical-design.md](docs/technical-design.md)
