"""Add shot events table

Revision ID: 9b7c2d1a4fef
Revises: e1c8f6a2b9d3
Create Date: 2026-02-12 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9b7c2d1a4fef'
down_revision = 'e1c8f6a2b9d3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'shot_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('match_id', sa.Integer(), sa.ForeignKey('matches.id'), nullable=False),
        sa.Column('player_id', sa.Integer(), sa.ForeignKey('players.id'), nullable=False),
        sa.Column('shot_on_target', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('shot_off_target', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('shot_blocked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('xG', sa.Float(), nullable=False, server_default='0'),
        sa.Column('inside_box', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.CheckConstraint(
            "(CASE WHEN shot_on_target THEN 1 ELSE 0 END) + "
            "(CASE WHEN shot_off_target THEN 1 ELSE 0 END) + "
            "(CASE WHEN shot_blocked THEN 1 ELSE 0 END) = 1",
            name='ck_shot_events_exactly_one_outcome'
        )
    )

    op.create_index('ix_shot_events_match_id', 'shot_events', ['match_id'])
    op.create_index('ix_shot_events_player_id', 'shot_events', ['player_id'])


def downgrade():
    op.drop_index('ix_shot_events_player_id', table_name='shot_events')
    op.drop_index('ix_shot_events_match_id', table_name='shot_events')
    op.drop_table('shot_events')
