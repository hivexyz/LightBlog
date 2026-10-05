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

    # AI 共创（OpenAI-compatible API）
    AI_API_BASE: str = os.environ.get('AI_API_BASE', 'https://api.openai.com/v1').rstrip('/')
    AI_API_KEY: str = os.environ.get('AI_API_KEY', '')
    AI_TEXT_MODEL: str = os.environ.get('AI_TEXT_MODEL', '')
    AI_IMAGE_MODEL: str = os.environ.get('AI_IMAGE_MODEL', '')
    AI_REQUEST_TIMEOUT: float = float(os.environ.get('AI_REQUEST_TIMEOUT', '180'))
    AI_MAX_CONTEXT_CHARS: int = int(os.environ.get('AI_MAX_CONTEXT_CHARS', '50000'))
    AI_MAX_INLINE_IMAGES: int = max(0, min(6, int(os.environ.get('AI_MAX_INLINE_IMAGES', '2'))))
    AI_FINAL_MAX_TOKENS: int = max(1000, min(8000, int(os.environ.get('AI_FINAL_MAX_TOKENS', '4800'))))
    AI_IMAGE_PLAN_MAX_TOKENS: int = max(500, min(3000, int(os.environ.get('AI_IMAGE_PLAN_MAX_TOKENS', '1800'))))
    AI_HUMANIZE_MAX_TOKENS: int = max(1000, min(8000, int(os.environ.get('AI_HUMANIZE_MAX_TOKENS', '4800'))))
    AI_JOB_WORKER_ENABLED: bool = os.environ.get('AI_JOB_WORKER_ENABLED', 'true').lower() == 'true'
    AI_JOB_POLL_INTERVAL: float = max(0.25, float(os.environ.get('AI_JOB_POLL_INTERVAL', '1')))
    AI_JOB_STALE_SECONDS: int = max(300, int(os.environ.get('AI_JOB_STALE_SECONDS', '600')))
    AI_JOB_MAX_ATTEMPTS: int = max(1, min(5, int(os.environ.get('AI_JOB_MAX_ATTEMPTS', '2'))))
    AI_WRITING_STYLE: str = os.environ.get(
        'AI_WRITING_STYLE',
        '面向技术读者写作，像在和同行复盘一个真实问题；优先写具体场景、判断冲突和工程取舍，少做面面俱到的总结。'
    )

    # 按需网络搜索。必须显式配置 Tavily 或 Tavily Hub，不回退到文本模型搜索。
    WEB_SEARCH_PROVIDER: str = os.environ.get('WEB_SEARCH_PROVIDER', '').lower()
    WEB_SEARCH_API_BASE: str = os.environ.get('WEB_SEARCH_API_BASE', '').rstrip('/')
    WEB_SEARCH_API_KEY: str = os.environ.get('WEB_SEARCH_API_KEY', '')
    WEB_SEARCH_MAX_QUERIES: int = max(1, min(5, int(os.environ.get('WEB_SEARCH_MAX_QUERIES', '3'))))
    WEB_SEARCH_MAX_RESULTS: int = max(1, min(10, int(os.environ.get('WEB_SEARCH_MAX_RESULTS', '5'))))
    WEB_SEARCH_TIMEOUT: float = float(os.environ.get('WEB_SEARCH_TIMEOUT', '30'))

    @property
    def AI_TEXT_ENABLED(self) -> bool:
        return bool(self.AI_API_KEY and self.AI_TEXT_MODEL)

    @property
    def AI_IMAGE_ENABLED(self) -> bool:
        return bool(self.AI_API_KEY and self.AI_IMAGE_MODEL)

    @property
    def WEB_SEARCH_ENABLED(self) -> bool:
        if self.WEB_SEARCH_PROVIDER in {'tavily', 'tavily_hub'}:
            return bool(self.WEB_SEARCH_API_BASE and self.WEB_SEARCH_API_KEY)
        return False

    class Config:
        env_file = '.env'


settings = Settings()
