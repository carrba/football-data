"""Add team_id to match events

Revision ID: a6d4e8b1c2f3
Revises: f1a2b3c4d5e6
Create Date: 2026-04-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'a6d4e8b1c2f3'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = {column['name'] for column in inspector.get_columns('match_events')}
    foreign_keys = {foreign_key['name'] for foreign_key in inspector.get_foreign_keys('match_events') if foreign_key.get('name')}

    if 'team_id' not in columns:
        with op.batch_alter_table('match_events', schema=None) as batch_op:
            batch_op.add_column(sa.Column('team_id', sa.Integer(), nullable=True))

    if 'fk_match_events_team_id_teams' not in foreign_keys:
        with op.batch_alter_table('match_events', schema=None) as batch_op:
            batch_op.create_foreign_key('fk_match_events_team_id_teams', 'teams', ['team_id'], ['id'])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = {column['name'] for column in inspector.get_columns('match_events')}
    foreign_keys = {foreign_key['name'] for foreign_key in inspector.get_foreign_keys('match_events') if foreign_key.get('name')}

    if 'fk_match_events_team_id_teams' in foreign_keys:
        with op.batch_alter_table('match_events', schema=None) as batch_op:
            batch_op.drop_constraint('fk_match_events_team_id_teams', type_='foreignkey')

    if 'team_id' in columns:
        with op.batch_alter_table('match_events', schema=None) as batch_op:
            batch_op.drop_column('team_id')