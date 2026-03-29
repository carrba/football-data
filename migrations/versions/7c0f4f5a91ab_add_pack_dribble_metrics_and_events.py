"""Add pack dribble metrics and events

Revision ID: 7c0f4f5a91ab
Revises: 2b6c9d7e4f11
Create Date: 2026-02-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c0f4f5a91ab'
down_revision = '2b6c9d7e4f11'
branch_labels = None
depends_on = None


DRIBBLE_COLUMNS = [
    'pack_dribbles',
    'pack_dribble_defenders',
    'pack_dribble_midfielders',
    'pack_dribble_attackers',
    'pack_dribble_score',
    'pack_dribbled_past',
    'pack_dribbled_past_defenders',
    'pack_dribbled_past_midfielders',
    'pack_dribbled_past_attackers',
    'pack_dribbled_past_score'
]


def _add_dribble_columns_to_stats_table(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column['name'] for column in inspector.get_columns(table_name)}

    missing_columns = [column for column in DRIBBLE_COLUMNS if column not in existing_columns]
    if not missing_columns:
        return

    with op.batch_alter_table(table_name, schema=None) as batch_op:
        for column in missing_columns:
            batch_op.add_column(sa.Column(column, sa.Integer(), nullable=True, server_default='0'))

    for column in missing_columns:
        op.execute(f"UPDATE {table_name} SET {column} = 0 WHERE {column} IS NULL")

    with op.batch_alter_table(table_name, schema=None) as batch_op:
        for column in missing_columns:
            batch_op.alter_column(column, existing_type=sa.Integer(), nullable=False)


def _drop_dribble_columns_from_stats_table(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column['name'] for column in inspector.get_columns(table_name)}
    removable_columns = [column for column in DRIBBLE_COLUMNS if column in existing_columns]

    if not removable_columns:
        return

    with op.batch_alter_table(table_name, schema=None) as batch_op:
        for column in reversed(removable_columns):
            batch_op.drop_column(column)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _add_dribble_columns_to_stats_table('player_match_stats')
    _add_dribble_columns_to_stats_table('goalkeeper_match_stats')

    if not inspector.has_table('pack_dribble_events'):
        op.create_table(
            'pack_dribble_events',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('match_id', sa.Integer(), sa.ForeignKey('matches.id'), nullable=False),
            sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id'), nullable=False),
            sa.Column('dribbler_id', sa.Integer(), sa.ForeignKey('players.id'), nullable=True),
            sa.Column('score', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('defenders', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('midfielders', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('attackers', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
        )

    if not inspector.has_table('pack_dribbled_past_players'):
        op.create_table(
            'pack_dribbled_past_players',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('event_id', sa.Integer(), sa.ForeignKey('pack_dribble_events.id'), nullable=False),
            sa.Column('player_id', sa.Integer(), sa.ForeignKey('players.id'), nullable=False),
            sa.Column('position_group', sa.String(length=20), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table('pack_dribbled_past_players'):
        op.drop_table('pack_dribbled_past_players')
    if inspector.has_table('pack_dribble_events'):
        op.drop_table('pack_dribble_events')

    _drop_dribble_columns_from_stats_table('goalkeeper_match_stats')
    _drop_dribble_columns_from_stats_table('player_match_stats')
