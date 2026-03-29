"""add touches in opposition box to player_match_stats

Revision ID: f8a1c3d9e4b2
Revises: fe2a7c4d9b31
Create Date: 2026-02-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f8a1c3d9e4b2'
down_revision = 'fe2a7c4d9b31'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.add_column(sa.Column('touches_in_opposition_box', sa.Integer(), nullable=True, server_default='0'))

    op.execute("UPDATE player_match_stats SET touches_in_opposition_box = 0 WHERE touches_in_opposition_box IS NULL")

    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.alter_column('touches_in_opposition_box', existing_type=sa.Integer(), nullable=False)


def downgrade():
    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.drop_column('touches_in_opposition_box')
