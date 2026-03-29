"""Split duels into aerial and ground

Revision ID: 91b2a4e5f7c1
Revises: 3e95d88f6b42
Create Date: 2026-02-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '91b2a4e5f7c1'
down_revision = '3e95d88f6b42'
branch_labels = None
depends_on = None


DUEL_SPLIT_COLUMNS = [
    'aerial_duels_won',
    'aerial_duels_lost',
    'ground_duels_won',
    'ground_duels_lost'
]


def _add_split_columns(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column['name'] for column in inspector.get_columns(table_name)}

    missing_columns = [column for column in DUEL_SPLIT_COLUMNS if column not in existing_columns]
    if not missing_columns:
        return

    with op.batch_alter_table(table_name, schema=None) as batch_op:
        for column in missing_columns:
            batch_op.add_column(sa.Column(column, sa.Integer(), nullable=True, server_default='0'))

    if {'duels_won', 'duels_lost'}.issubset(existing_columns):
        op.execute(f"UPDATE {table_name} SET ground_duels_won = COALESCE(duels_won, 0) WHERE ground_duels_won IS NULL OR ground_duels_won = 0")
        op.execute(f"UPDATE {table_name} SET ground_duels_lost = COALESCE(duels_lost, 0) WHERE ground_duels_lost IS NULL OR ground_duels_lost = 0")

    for column in missing_columns:
        op.execute(f"UPDATE {table_name} SET {column} = 0 WHERE {column} IS NULL")

    with op.batch_alter_table(table_name, schema=None) as batch_op:
        for column in missing_columns:
            batch_op.alter_column(column, existing_type=sa.Integer(), nullable=False)


def _drop_split_columns(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column['name'] for column in inspector.get_columns(table_name)}

    removable_columns = [column for column in DUEL_SPLIT_COLUMNS if column in existing_columns]
    if not removable_columns:
        return

    with op.batch_alter_table(table_name, schema=None) as batch_op:
        for column in reversed(removable_columns):
            batch_op.drop_column(column)


def upgrade():
    _add_split_columns('player_match_stats')
    _add_split_columns('goalkeeper_match_stats')


def downgrade():
    _drop_split_columns('goalkeeper_match_stats')
    _drop_split_columns('player_match_stats')
