"""Add pressures to player_match_stats

Revision ID: 3e95d88f6b42
Revises: d8e616f13db1
Create Date: 2026-02-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3e95d88f6b42'
down_revision = 'd8e616f13db1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column['name'] for column in inspector.get_columns('player_match_stats')}

    if 'pressures' not in existing_columns:
        with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
            batch_op.add_column(sa.Column('pressures', sa.Integer(), nullable=True, server_default='0'))

        op.execute("UPDATE player_match_stats SET pressures = 0 WHERE pressures IS NULL")

        with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
            batch_op.alter_column('pressures', existing_type=sa.Integer(), nullable=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column['name'] for column in inspector.get_columns('player_match_stats')}

    if 'pressures' in existing_columns:
        with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
            batch_op.drop_column('pressures')
