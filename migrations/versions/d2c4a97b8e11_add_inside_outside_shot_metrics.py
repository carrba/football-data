"""Add inside/outside shot metrics to player match stats

Revision ID: d2c4a97b8e11
Revises: 9b7c2d1a4fef
Create Date: 2026-02-12 12:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2c4a97b8e11'
down_revision = '9b7c2d1a4fef'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.add_column(sa.Column('shots_inside_box', sa.Integer(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('shots_outside_box', sa.Integer(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('xG_inside_box', sa.Float(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('xG_outside_box', sa.Float(), nullable=True, server_default='0'))

    op.execute("UPDATE player_match_stats SET shots_inside_box = 0 WHERE shots_inside_box IS NULL")
    op.execute("UPDATE player_match_stats SET shots_outside_box = 0 WHERE shots_outside_box IS NULL")
    op.execute("UPDATE player_match_stats SET \"xG_inside_box\" = 0 WHERE \"xG_inside_box\" IS NULL")
    op.execute("UPDATE player_match_stats SET \"xG_outside_box\" = 0 WHERE \"xG_outside_box\" IS NULL")

    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.alter_column('shots_inside_box', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('shots_outside_box', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('xG_inside_box', existing_type=sa.Float(), nullable=False)
        batch_op.alter_column('xG_outside_box', existing_type=sa.Float(), nullable=False)


def downgrade():
    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.drop_column('xG_outside_box')
        batch_op.drop_column('xG_inside_box')
        batch_op.drop_column('shots_outside_box')
        batch_op.drop_column('shots_inside_box')
