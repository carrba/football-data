"""Add corner events table

Revision ID: fe2a7c4d9b31
Revises: 5b91f6c3a7d2
Create Date: 2026-02-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fe2a7c4d9b31'
down_revision = '5b91f6c3a7d2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'corner_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('match_id', sa.Integer(), sa.ForeignKey('matches.id'), nullable=False),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id'), nullable=False),
        sa.Column('taker_player_id', sa.Integer(), sa.ForeignKey('players.id'), nullable=False),
        sa.Column('won_by_player_id', sa.Integer(), sa.ForeignKey('players.id'), nullable=True),
        sa.Column('delivery_type', sa.String(length=20), nullable=False),
        sa.Column('delivery_outcome', sa.String(length=20), nullable=False),
        sa.Column('delivery_length', sa.String(length=10), nullable=False),
        sa.Column('led_to_shot', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('big_chance_created', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.CheckConstraint(
            "delivery_type IN ('inswing', 'outswing', 'straight')",
            name='ck_corner_events_delivery_type'
        ),
        sa.CheckConstraint(
            "delivery_outcome IN ('successful', 'unsuccessful')",
            name='ck_corner_events_delivery_outcome'
        ),
        sa.CheckConstraint(
            "delivery_length IN ('short', 'long')",
            name='ck_corner_events_delivery_length'
        )
    )

    op.create_index('ix_corner_events_match_id', 'corner_events', ['match_id'])
    op.create_index('ix_corner_events_team_id', 'corner_events', ['team_id'])
    op.create_index('ix_corner_events_taker_player_id', 'corner_events', ['taker_player_id'])
    op.create_index('ix_corner_events_won_by_player_id', 'corner_events', ['won_by_player_id'])


def downgrade():
    op.drop_index('ix_corner_events_won_by_player_id', table_name='corner_events')
    op.drop_index('ix_corner_events_taker_player_id', table_name='corner_events')
    op.drop_index('ix_corner_events_team_id', table_name='corner_events')
    op.drop_index('ix_corner_events_match_id', table_name='corner_events')
    op.drop_table('corner_events')
