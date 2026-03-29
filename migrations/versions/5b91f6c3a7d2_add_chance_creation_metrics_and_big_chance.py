"""Add chance creation metrics and big chance flag

Revision ID: 5b91f6c3a7d2
Revises: 3e95d88f6b42
Create Date: 2026-02-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5b91f6c3a7d2'
down_revision = '3e95d88f6b42'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    player_match_stats_columns = {column['name'] for column in inspector.get_columns('player_match_stats')}
    shot_event_columns = {column['name'] for column in inspector.get_columns('shot_events')}

    if 'chances_created' not in player_match_stats_columns:
        with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
            batch_op.add_column(sa.Column('chances_created', sa.Integer(), nullable=True, server_default='0'))

    if 'big_chances_created' not in player_match_stats_columns:
        with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
            batch_op.add_column(sa.Column('big_chances_created', sa.Integer(), nullable=True, server_default='0'))

    op.execute('UPDATE player_match_stats SET chances_created = 0 WHERE chances_created IS NULL')
    op.execute('UPDATE player_match_stats SET big_chances_created = 0 WHERE big_chances_created IS NULL')

    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.alter_column('chances_created', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('big_chances_created', existing_type=sa.Integer(), nullable=False)

    if 'big_chance' not in shot_event_columns:
        with op.batch_alter_table('shot_events', schema=None) as batch_op:
            batch_op.add_column(sa.Column('big_chance', sa.Boolean(), nullable=True, server_default=sa.false()))

    op.execute('UPDATE shot_events SET big_chance = FALSE WHERE big_chance IS NULL')

    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        batch_op.alter_column('big_chance', existing_type=sa.Boolean(), nullable=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    player_match_stats_columns = {column['name'] for column in inspector.get_columns('player_match_stats')}
    shot_event_columns = {column['name'] for column in inspector.get_columns('shot_events')}

    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        if 'big_chances_created' in player_match_stats_columns:
            batch_op.drop_column('big_chances_created')
        if 'chances_created' in player_match_stats_columns:
            batch_op.drop_column('chances_created')

    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        if 'big_chance' in shot_event_columns:
            batch_op.drop_column('big_chance')
