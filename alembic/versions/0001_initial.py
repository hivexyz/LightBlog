"""initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.String(64), nullable=False),
        sa.Column('password_hash', sa.String(256), nullable=False),
        sa.Column('is_admin', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.UniqueConstraint('username'),
    )

    op.create_table(
        'category',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('slug', sa.String(50), nullable=False),
        sa.Column('description', sa.String(200), default=''),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('slug'),
    )

    op.create_table(
        'tag',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('slug', sa.String(50), nullable=False),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('slug'),
    )

    op.create_table(
        'post',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('slug', sa.String(200), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_html', sa.Text(), nullable=False),
        sa.Column('summary', sa.String(500), default=''),
        sa.Column('cover_image', sa.String(500), default=''),
        sa.Column('status', sa.Integer(), default=1),
        sa.Column('views', sa.Integer(), default=0),
        sa.Column('category_id', sa.Integer(), sa.ForeignKey('category.id')),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('user.id')),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), default=sa.func.now()),
        sa.UniqueConstraint('slug'),
    )
    op.create_index('ix_post_slug', 'post', ['slug'])
    op.create_index('ix_post_status', 'post', ['status'])
    op.create_index('ix_post_category_id', 'post', ['category_id'])
    op.create_index('ix_post_created_at', 'post', ['created_at'])
    op.create_index('ix_post_status_created', 'post', ['status', 'created_at'])

    op.create_table(
        'post_tags',
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('post.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('tag_id', sa.Integer(), sa.ForeignKey('tag.id', ondelete='CASCADE'), primary_key=True),
    )

    op.create_table(
        'setting',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('value', sa.Text(), default=''),
    )


def downgrade() -> None:
    op.drop_table('setting')
    op.drop_table('post_tags')
    op.drop_table('post')
    op.drop_table('tag')
    op.drop_table('category')
    op.drop_table('user')
