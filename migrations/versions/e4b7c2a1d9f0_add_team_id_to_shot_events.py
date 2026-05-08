"""Add team_id to shot events

Revision ID: e4b7c2a1d9f0
Revises: c6d1a9f4e2b3
Create Date: 2026-04-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'e4b7c2a1d9f0'
down_revision = 'c6d1a9f4e2b3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = {column['name'] for column in inspector.get_columns('shot_events')}
    foreign_keys = {foreign_key['name'] for foreign_key in inspector.get_foreign_keys('shot_events') if foreign_key.get('name')}

    if 'team_id' not in columns:
        with op.batch_alter_table('shot_events', schema=None) as batch_op:
            batch_op.add_column(sa.Column('team_id', sa.Integer(), nullable=True))

    if 'fk_shot_events_team_id_teams' not in foreign_keys:
        with op.batch_alter_table('shot_events', schema=None) as batch_op:
            batch_op.create_foreign_key('fk_shot_events_team_id_teams', 'teams', ['team_id'], ['id'])

    op.execute(
        sa.text(
            """
            UPDATE shot_events
            SET team_id = (
                SELECT match_lineups.team_id
                FROM match_lineups
                WHERE match_lineups.match_id = shot_events.match_id
                  AND match_lineups.player_id = shot_events.player_id
                  AND match_lineups.team_id IS NOT NULL
                LIMIT 1
            )
            WHERE team_id IS NULL
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE shot_events
            SET team_id = (
                SELECT players.team_id
                FROM players
                WHERE players.id = shot_events.player_id
            )
            WHERE team_id IS NULL
            """
        )
    )

    remaining_null_team_ids = bind.execute(
        sa.text('SELECT COUNT(*) FROM shot_events WHERE team_id IS NULL')
    ).scalar()
    if remaining_null_team_ids:
        raise RuntimeError('Unable to backfill shot_events.team_id for all existing rows')

    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        batch_op.alter_column('team_id', existing_type=sa.Integer(), nullable=False)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = {column['name'] for column in inspector.get_columns('shot_events')}
    foreign_keys = {foreign_key['name'] for foreign_key in inspector.get_foreign_keys('shot_events') if foreign_key.get('name')}

    if 'fk_shot_events_team_id_teams' in foreign_keys:
        with op.batch_alter_table('shot_events', schema=None) as batch_op:
            batch_op.drop_constraint('fk_shot_events_team_id_teams', type_='foreignkey')

    if 'team_id' in columns:
        with op.batch_alter_table('shot_events', schema=None) as batch_op:
            batch_op.drop_column('team_id')