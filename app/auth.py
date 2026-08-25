import time
import secrets
from typing import Optional
from fastapi import Request, HTTPException, status, Depends
from fastapi.responses import RedirectResponse
from passlib.context import CryptContext
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import User

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
serializer = URLSafeTimedSerializer(settings.SECRET_KEY)

# 登录失败记录：{ip: [timestamp, ...]}
login_attempts: dict[str, list[float]] = {}
MAX_ATTEMPTS = 5
LOCK_TIME = 15 * 60  # 15 分钟


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_session(user_id: int) -> str:
    """创建 session：包含 user_id 和独立的 csrf_nonce，不把 session cookie 值暴露给前端"""
    csrf_nonce = secrets.token_urlsafe(32)
    return serializer.dumps({'user_id': user_id, 'csrf_nonce': csrf_nonce})


def get_session_id(request: Request) -> Optional[str]:
    """获取当前 session cookie 值"""
    return request.cookies.get('session')


def _load_session(session_id: str) -> Optional[dict]:
    """解析 session cookie，返回 payload 或 None"""
    try:
        return serializer.loads(session_id, max_age=7 * 24 * 3600)
    except (BadSignature, SignatureExpired):
        return None


def get_csrf_nonce(session_id: Optional[str]) -> str:
    """从 session 中解出 csrf_nonce；未登录时返回空字符串"""
    if not session_id:
        return ''
    data = _load_session(session_id)
    if not data:
        return ''
    return data.get('csrf_nonce', '')


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    session_id = get_session_id(request)
    if not session_id:
        return None
    return _get_user_by_session(session_id, db)


def _get_user_by_session(session_id: str, db: Session) -> Optional[User]:
    """根据 session 获取用户（内部函数，不依赖 FastAPI 注入）"""
    data = _load_session(session_id)
    if not data:
        return None
    user_id = data.get('user_id')
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_admin(user: Optional[User] = Depends(get_current_user)) -> User:
    if not user or not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={'Location': '/admin/login'}
        )
    return user


def is_login_locked(ip: str) -> bool:
    """检查 IP 是否被锁定"""
    attempts = login_attempts.get(ip, [])
    now = time.time()
    attempts = [t for t in attempts if now - t < LOCK_TIME]
    login_attempts[ip] = attempts
    return len(attempts) >= MAX_ATTEMPTS


def record_login_failure(ip: str):
    """记录登录失败"""
    if ip not in login_attempts:
        login_attempts[ip] = []
    login_attempts[ip].append(time.time())


def clear_login_attempts(ip: str):
    """登录成功后清除记录"""
    login_attempts.pop(ip, None)


def generate_csrf_token(csrf_nonce: str = '') -> str:
    """生成 CSRF token，只包含 csrf_nonce，不包含完整 session cookie"""
    return serializer.dumps({'csrf': True, 'nonce': csrf_nonce})


def verify_csrf_token(token: str, csrf_nonce: str = '') -> bool:
    """校验 CSRF token：验证 token 中的 nonce 与当前 session 的 csrf_nonce 一致"""
    try:
        data = serializer.loads(token, max_age=3600)
        if data.get('csrf') is not True:
            return False
        return data.get('nonce', '') == csrf_nonce
    except (BadSignature, SignatureExpired):
        return False
