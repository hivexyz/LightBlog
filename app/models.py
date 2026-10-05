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
    ai_writing_sessions = relationship('AIWritingSession', back_populates='author')


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
    ai_writing_sessions = relationship('AIWritingSession', back_populates='post')

    __table_args__ = (
        Index('ix_post_status_created', 'status', 'created_at'),
    )


class Setting(Base):
    __tablename__ = 'setting'

    key = Column(String(64), primary_key=True)
    value = Column(Text, default='')


class AIWritingSession(Base):
    __tablename__ = 'ai_writing_session'

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey('post.id', ondelete='SET NULL'), nullable=True, index=True)
    author_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    topic = Column(String(500), nullable=False)
    core_points = Column(Text, nullable=False)
    target_audience = Column(String(300), default='')
    desired_length = Column(String(50), default='中等')
    writing_mode = Column(String(32), default='personal_opinion', nullable=False)
    style_notes = Column(Text, default='')
    draft_title = Column(String(200), default='')
    final_title = Column(String(200), default='')
    initial_draft = Column(Text, default='')
    current_content = Column(Text, default='')
    final_content = Column(Text, default='')
    pre_humanized_title = Column(String(200), default='')
    pre_humanized_content = Column(Text, default='')
    humanize_summary = Column(Text, default='')
    confirmed_brief = Column(Text, default='')
    research_queries = Column(Text, default='[]')
    citation_warnings = Column(Text, default='[]')
    status = Column(String(32), default='created', nullable=False, index=True)
    last_error = Column(Text, default='')
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    post = relationship('Post', back_populates='ai_writing_sessions')
    author = relationship('User', back_populates='ai_writing_sessions')
    messages = relationship(
        'AIWritingMessage', back_populates='session', cascade='all, delete-orphan',
        order_by='AIWritingMessage.created_at'
    )
    images = relationship(
        'AIWritingImage', back_populates='session', cascade='all, delete-orphan',
        order_by='AIWritingImage.id'
    )
    research_sources = relationship(
        'AIResearchSource', back_populates='session', cascade='all, delete-orphan',
        order_by='AIResearchSource.id'
    )
    jobs = relationship(
        'AIWritingJob', back_populates='session', cascade='all, delete-orphan',
        order_by='AIWritingJob.created_at'
    )


class AIWritingMessage(Base):
    __tablename__ = 'ai_writing_message'

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer, ForeignKey('ai_writing_session.id', ondelete='CASCADE'),
        nullable=False, index=True
    )
    role = Column(String(20), nullable=False)
    message_type = Column(String(32), default='discussion', nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship('AIWritingSession', back_populates='messages')


class AIWritingImage(Base):
    __tablename__ = 'ai_writing_image'

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer, ForeignKey('ai_writing_session.id', ondelete='CASCADE'),
        nullable=False, index=True
    )
    slot = Column(String(64), nullable=False)
    image_type = Column(String(20), default='illustration', nullable=False)
    prompt = Column(Text, nullable=False)
    alt_text = Column(String(500), default='')
    placement_heading = Column(String(300), default='')
    aspect_ratio = Column(String(20), default='3:2')
    status = Column(String(20), default='planned', nullable=False, index=True)
    file_path = Column(String(500), default='')
    error = Column(Text, default='')
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    session = relationship('AIWritingSession', back_populates='images')

    __table_args__ = (
        Index('ix_ai_writing_image_session_slot', 'session_id', 'slot', unique=True),
    )


class AIResearchSource(Base):
    __tablename__ = 'ai_research_source'

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer, ForeignKey('ai_writing_session.id', ondelete='CASCADE'),
        nullable=False, index=True
    )
    query = Column(String(1000), nullable=False)
    purpose = Column(String(500), default='')
    title = Column(String(500), nullable=False)
    url = Column(String(2000), nullable=False)
    snippet = Column(Text, default='')
    source_content = Column(Text, default='')
    source_name = Column(String(200), default='')
    published_at = Column(String(100), default='')
    retrieved_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    selected = Column(Boolean, default=False, nullable=False, index=True)
    content_hash = Column(String(64), default='')
    fetch_status = Column(String(20), default='ready', nullable=False)

    session = relationship('AIWritingSession', back_populates='research_sources')

    __table_args__ = (
        Index('ix_ai_research_source_session_url', 'session_id', 'url', unique=True),
    )


class AIWritingJob(Base):
    __tablename__ = 'ai_writing_job'

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer, ForeignKey('ai_writing_session.id', ondelete='CASCADE'),
        nullable=False, index=True
    )
    author_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    job_type = Column(String(32), nullable=False, default='finalize')
    status = Column(String(20), nullable=False, default='queued', index=True)
    phase = Column(String(32), nullable=False, default='queued')
    progress = Column(Integer, nullable=False, default=0)
    payload_json = Column(Text, nullable=False, default='{}')
    result_json = Column(Text, nullable=False, default='{}')
    error = Column(Text, default='')
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)
    finished_at = Column(DateTime, nullable=True)

    session = relationship('AIWritingSession', back_populates='jobs')
