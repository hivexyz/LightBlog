"""add AI-assisted writing sessions

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_writing_session',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('post.id', ondelete='SET NULL'), nullable=True),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('topic', sa.String(500), nullable=False),
        sa.Column('core_points', sa.Text(), nullable=False),
        sa.Column('target_audience', sa.String(300), default=''),
        sa.Column('desired_length', sa.String(50), default='中等'),
        sa.Column('draft_title', sa.String(200), default=''),
        sa.Column('final_title', sa.String(200), default=''),
        sa.Column('initial_draft', sa.Text(), default=''),
        sa.Column('current_content', sa.Text(), default=''),
        sa.Column('final_content', sa.Text(), default=''),
        sa.Column('confirmed_brief', sa.Text(), default=''),
        sa.Column('status', sa.String(32), nullable=False, default='created'),
        sa.Column('last_error', sa.Text(), default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, default=sa.func.now()),
    )
    op.create_index('ix_ai_writing_session_post_id', 'ai_writing_session', ['post_id'])
    op.create_index('ix_ai_writing_session_author_id', 'ai_writing_session', ['author_id'])
    op.create_index('ix_ai_writing_session_status', 'ai_writing_session', ['status'])

    op.create_table(
        'ai_writing_message',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('ai_writing_session.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('message_type', sa.String(32), nullable=False, default='discussion'),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, default=sa.func.now()),
    )
    op.create_index('ix_ai_writing_message_session_id', 'ai_writing_message', ['session_id'])

    op.create_table(
        'ai_writing_image',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('ai_writing_session.id', ondelete='CASCADE'), nullable=False),
        sa.Column('slot', sa.String(64), nullable=False),
        sa.Column('image_type', sa.String(20), nullable=False, default='illustration'),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('alt_text', sa.String(500), default=''),
        sa.Column('placement_heading', sa.String(300), default=''),
        sa.Column('aspect_ratio', sa.String(20), default='3:2'),
        sa.Column('status', sa.String(20), nullable=False, default='planned'),
        sa.Column('file_path', sa.String(500), default=''),
        sa.Column('error', sa.Text(), default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, default=sa.func.now()),
    )
    op.create_index('ix_ai_writing_image_session_id', 'ai_writing_image', ['session_id'])
    op.create_index('ix_ai_writing_image_status', 'ai_writing_image', ['status'])
    op.create_index(
        'ix_ai_writing_image_session_slot', 'ai_writing_image', ['session_id', 'slot'], unique=True
    )


def downgrade() -> None:
    op.drop_table('ai_writing_image')
    op.drop_table('ai_writing_message')
    op.drop_table('ai_writing_session')
