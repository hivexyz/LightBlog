"""add author voice and humanized revision fields

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_writing_session') as batch_op:
        batch_op.add_column(sa.Column(
            'writing_mode', sa.String(32), nullable=False,
            server_default='personal_opinion'
        ))
        batch_op.add_column(sa.Column('style_notes', sa.Text(), server_default=''))
        batch_op.add_column(sa.Column('pre_humanized_title', sa.String(200), server_default=''))
        batch_op.add_column(sa.Column('pre_humanized_content', sa.Text(), server_default=''))
        batch_op.add_column(sa.Column('humanize_summary', sa.Text(), server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('ai_writing_session') as batch_op:
        batch_op.drop_column('humanize_summary')
        batch_op.drop_column('pre_humanized_content')
        batch_op.drop_column('pre_humanized_title')
        batch_op.drop_column('style_notes')
        batch_op.drop_column('writing_mode')
