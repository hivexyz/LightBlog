"""add controlled web research sources

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_writing_session') as batch_op:
        batch_op.add_column(sa.Column('research_queries', sa.Text(), default='[]'))
        batch_op.add_column(sa.Column('citation_warnings', sa.Text(), default='[]'))

    op.create_table(
        'ai_research_source',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'session_id', sa.Integer(),
            sa.ForeignKey('ai_writing_session.id', ondelete='CASCADE'), nullable=False
        ),
        sa.Column('query', sa.String(1000), nullable=False),
        sa.Column('purpose', sa.String(500), default=''),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('url', sa.String(2000), nullable=False),
        sa.Column('snippet', sa.Text(), default=''),
        sa.Column('source_content', sa.Text(), default=''),
        sa.Column('source_name', sa.String(200), default=''),
        sa.Column('published_at', sa.String(100), default=''),
        sa.Column('retrieved_at', sa.DateTime(), nullable=False, default=sa.func.now()),
        sa.Column('selected', sa.Boolean(), nullable=False, default=False),
        sa.Column('content_hash', sa.String(64), default=''),
        sa.Column('fetch_status', sa.String(20), nullable=False, default='ready'),
    )
    op.create_index('ix_ai_research_source_session_id', 'ai_research_source', ['session_id'])
    op.create_index('ix_ai_research_source_selected', 'ai_research_source', ['selected'])
    op.create_index(
        'ix_ai_research_source_session_url', 'ai_research_source',
        ['session_id', 'url'], unique=True
    )


def downgrade() -> None:
    op.drop_table('ai_research_source')
    with op.batch_alter_table('ai_writing_session') as batch_op:
        batch_op.drop_column('citation_warnings')
        batch_op.drop_column('research_queries')
