import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.config import settings
from app.database import engine, Base, SessionLocal
from app.models import User, Setting
from app.auth import hash_password
from app.routes.main import router as main_router
from app.routes.admin import router as admin_router
from app.view_counter import view_counter


def init_default_data():
    """初始化默认数据（管理员、站点设置）。表结构由 Alembic 迁移创建。"""
    db = SessionLocal()
    try:
        # 创建管理员
        if not db.query(User).filter(User.username == settings.ADMIN_USERNAME).first():
            admin = User(
                username=settings.ADMIN_USERNAME,
                password_hash=hash_password(settings.ADMIN_PASSWORD),
                is_admin=True
            )
            db.add(admin)

        # 初始化站点设置
        default_settings = {
            'site_title': 'LightBlog',
            'site_subtitle': '一个轻量级的博客',
            'site_description': '记录生活与技术',
            'site_avatar': '',
            'github_url': '',
            'about_content': '## 关于我\n\n这是一个用 FastAPI 构建的轻量级博客。',
        }
        for key, value in default_settings.items():
            if not db.query(Setting).filter(Setting.key == key).first():
                db.add(Setting(key=key, value=value))

        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：开发环境自动建表（生产环境由 entrypoint 执行 alembic upgrade head）
    if settings.DEBUG:
        Base.metadata.create_all(bind=engine)
    # 初始化默认数据（幂等）
    init_default_data()
    yield
    # 关闭时：刷入浏览量
    view_counter.flush()


app = FastAPI(lifespan=lifespan, debug=settings.DEBUG)

# 静态文件
app.mount('/static', StaticFiles(directory='app/static'), name='static')
app.mount('/uploads', StaticFiles(directory=settings.UPLOAD_DIR), name='uploads')

# 模板
templates = Jinja2Templates(directory='app/templates')
app.state.templates = templates

# 路由
app.include_router(main_router)
app.include_router(admin_router)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return HTMLResponse(status_code=404, content='<h1>404 - 页面未找到</h1>')


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app', host='0.0.0.0', port=8000, reload=settings.DEBUG)
