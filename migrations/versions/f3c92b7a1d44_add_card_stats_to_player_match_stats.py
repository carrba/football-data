"""Add yellow and red card stats to player_match_stats

Revision ID: f3c92b7a1d44
Revises: f8a1c3d9e4b2
Create Date: 2026-03-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'f3c92b7a1d44'
down_revision = 'f8a1c3d9e4b2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('player_match_stats')}

    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        if 'yellow_cards' not in columns:
            batch_op.add_column(sa.Column('yellow_cards', sa.Integer(), nullable=True, server_default='0'))
        if 'red_cards' not in columns:
            batch_op.add_column(sa.Column('red_cards', sa.Integer(), nullable=True, server_default='0'))

    op.execute('UPDATE player_match_stats SET yellow_cards = 0 WHERE yellow_cards IS NULL')
    op.execute('UPDATE player_match_stats SET red_cards = 0 WHERE red_cards IS NULL')

    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        if 'yellow_cards' not in columns:
            batch_op.alter_column('yellow_cards', existing_type=sa.Integer(), nullable=False, server_default=None)
        if 'red_cards' not in columns:
            batch_op.alter_column('red_cards', existing_type=sa.Integer(), nullable=False, server_default=None)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('player_match_stats')}

    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        if 'red_cards' in columns:
            batch_op.drop_column('red_cards')
        if 'yellow_cards' in columns:
            batch_op.drop_column('yellow_cards')
