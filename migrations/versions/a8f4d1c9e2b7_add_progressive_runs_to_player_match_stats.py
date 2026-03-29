"""add progressive runs to player_match_stats

Revision ID: a8f4d1c9e2b7
Revises: de7c4b18a2f1
Create Date: 2026-02-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a8f4d1c9e2b7'
down_revision = 'de7c4b18a2f1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.add_column(sa.Column('progressive_runs', sa.Integer(), nullable=True, server_default='0'))

    op.execute("UPDATE player_match_stats SET progressive_runs = 0 WHERE progressive_runs IS NULL")

    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.alter_column('progressive_runs', existing_type=sa.Integer(), nullable=False)


def downgrade():
    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.drop_column('progressive_runs')
