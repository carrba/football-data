"""Add assist player id to shot events

Revision ID: c41f23d7ab9a
Revises: d2c4a97b8e11
Create Date: 2026-02-12 13:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c41f23d7ab9a'
down_revision = 'd2c4a97b8e11'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('assist_player_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_shot_events_assist_player_id_players', 'players', ['assist_player_id'], ['id'])

    op.create_index('ix_shot_events_assist_player_id', 'shot_events', ['assist_player_id'])


def downgrade():
    op.drop_index('ix_shot_events_assist_player_id', table_name='shot_events')

    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        batch_op.drop_constraint('fk_shot_events_assist_player_id_players', type_='foreignkey')
        batch_op.drop_column('assist_player_id')
