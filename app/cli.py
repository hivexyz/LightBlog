"""命令行工具：初始化数据库、清理未引用的上传文件"""
import os
import re
import sys
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine, Base
from app.models import User, Post, Setting
from app.config import settings
from app.auth import hash_password


def init_db():
    """初始化数据库：创建表、管理员、默认设置（幂等）"""
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    try:
        # 创建管理员
        if not db.query(User).filter(User.username == settings.ADMIN_USERNAME).first():
            admin = User(
                username=settings.ADMIN_USERNAME,
                password_hash=hash_password(settings.ADMIN_PASSWORD),
                is_admin=True
            )
            db.add(admin)
            print(f'[init-db] 创建管理员: {settings.ADMIN_USERNAME}')

        # 默认设置
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
                print(f'[init-db] 创建设置: {key}')

        db.commit()
        print('[init-db] 数据库初始化完成')
    finally:
        db.close()


def cleanup_uploads():
    """清理未被文章引用的上传文件"""
    db: Session = SessionLocal()
    try:
        posts = db.query(Post).all()
        # 收集所有文章中引用的图片路径
        referenced = set()
        for post in posts:
            # 匹配 /uploads/ 开头的路径
            refs = re.findall(r'(/uploads/[\w\-./]+)', post.content)
            referenced.update(refs)
            if post.cover_image:
                referenced.add(post.cover_image)

        upload_dir = settings.UPLOAD_DIR
        deleted = 0
        for root, _, files in os.walk(upload_dir):
            for f in files:
                filepath = os.path.join(root, f)
                rel_path = '/' + os.path.relpath(filepath, '.').replace('\\', '/')
                if rel_path not in referenced:
                    os.remove(filepath)
                    deleted += 1
                    print(f'[cleanup] 删除: {rel_path}')

        print(f'[cleanup] 共删除 {deleted} 个未引用文件')
    finally:
        db.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('用法: python -m app.cli <init-db|cleanup-uploads>')
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == 'init-db':
        init_db()
    elif cmd == 'cleanup-uploads':
        cleanup_uploads()
    else:
        print(f'未知命令: {cmd}')
        sys.exit(1)
