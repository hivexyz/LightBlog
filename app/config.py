import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 应用
    SECRET_KEY: str = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG: bool = os.environ.get('DEBUG', 'false').lower() == 'true'

    # 数据库
    DATABASE_URL: str = os.environ.get('DATABASE_URL', 'sqlite:///./data/blog.db')

    # 管理员
    ADMIN_USERNAME: str = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD: str = os.environ.get('ADMIN_PASSWORD', 'admin123')

    # 分页
    POSTS_PER_PAGE: int = 10

    # 上传
    UPLOAD_DIR: str = os.environ.get('UPLOAD_DIR', './uploads')
    MAX_UPLOAD_SIZE: int = 5 * 1024 * 1024  # 5MB
    ALLOWED_EXTENSIONS: set = {'jpg', 'jpeg', 'png', 'gif', 'webp'}

    # 浏览量缓冲
    VIEW_FLUSH_INTERVAL: int = 60  # 秒
    VIEW_FLUSH_THRESHOLD: int = 100  # 累计次数

    # Cookie 安全
    COOKIE_SECURE: bool = os.environ.get('COOKIE_SECURE', 'false').lower() == 'true'

    class Config:
        env_file = '.env'


settings = Settings()
