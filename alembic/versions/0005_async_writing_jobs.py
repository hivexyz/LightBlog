"""add persistent async writing jobs

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-02 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_writing_job',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('ai_writing_session.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('job_type', sa.String(32), nullable=False, server_default='finalize'),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('phase', sa.String(32), nullable=False, server_default='queued'),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('payload_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('result_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('error', sa.Text(), server_default=''),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_ai_writing_job_session_id', 'ai_writing_job', ['session_id'])
    op.create_index('ix_ai_writing_job_author_id', 'ai_writing_job', ['author_id'])
    op.create_index('ix_ai_writing_job_status', 'ai_writing_job', ['status'])
    op.create_index('ix_ai_writing_job_updated_at', 'ai_writing_job', ['updated_at'])


def downgrade() -> None:
    op.drop_table('ai_writing_job')
