from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Table, Index
)
from sqlalchemy.orm import relationship
from app.database import Base

# 文章-标签关联表
post_tags = Table(
    'post_tags',
    Base.metadata,
    Column('post_id', Integer, ForeignKey('post.id', ondelete='CASCADE'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tag.id', ondelete='CASCADE'), primary_key=True)
)


class User(Base):
    __tablename__ = 'user'

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    is_admin = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    posts = relationship('Post', back_populates='author')


class Category(Base):
    __tablename__ = 'category'

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    slug = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(String(200), default='')

    posts = relationship('Post', back_populates='category')


class Tag(Base):
    __tablename__ = 'tag'

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    slug = Column(String(50), unique=True, nullable=False, index=True)

    posts = relationship('Post', secondary=post_tags, back_populates='tags')


class Post(Base):
    __tablename__ = 'post'

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    slug = Column(String(200), unique=True, nullable=False, index=True)
    content = Column(Text, nullable=False)
    content_html = Column(Text, nullable=False)
    summary = Column(String(500), default='')
    cover_image = Column(String(500), default='')
    status = Column(Integer, default=1, index=True)  # 0=草稿, 1=已发布
    views = Column(Integer, default=0)

    category_id = Column(Integer, ForeignKey('category.id'), index=True)
    author_id = Column(Integer, ForeignKey('user.id'))

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship('Category', back_populates='posts')
    author = relationship('User', back_populates='posts')
    tags = relationship('Tag', secondary=post_tags, back_populates='posts')

    __table_args__ = (
        Index('ix_post_status_created', 'status', 'created_at'),
    )


class Setting(Base):
    __tablename__ = 'setting'

    key = Column(String(64), primary_key=True)
    value = Column(Text, default='')
