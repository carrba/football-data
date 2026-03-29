"""Add corner context to shot events

Revision ID: c6d1a9f4e2b3
Revises: f3c92b7a1d44
Create Date: 2026-03-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'c6d1a9f4e2b3'
down_revision = 'f3c92b7a1d44'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = {column['name'] for column in inspector.get_columns('shot_events')}
    check_constraints = {constraint['name'] for constraint in inspector.get_check_constraints('shot_events') if constraint.get('name')}

    if 'corner' not in columns:
        with op.batch_alter_table('shot_events', schema=None) as batch_op:
            batch_op.add_column(sa.Column('corner', sa.Boolean(), nullable=True, server_default=sa.false()))

        op.execute('UPDATE shot_events SET corner = false WHERE corner IS NULL')

        with op.batch_alter_table('shot_events', schema=None) as batch_op:
            batch_op.alter_column('corner', existing_type=sa.Boolean(), nullable=False, server_default=None)

    if 'ck_shot_events_not_penalty_and_free_kick' in check_constraints:
        op.drop_constraint('ck_shot_events_not_penalty_and_free_kick', 'shot_events', type_='check')

    if 'ck_shot_events_max_one_set_piece_context' not in check_constraints:
        op.create_check_constraint(
            'ck_shot_events_max_one_set_piece_context',
            'shot_events',
            '(CASE WHEN penalty THEN 1 ELSE 0 END) + '
            '(CASE WHEN free_kick THEN 1 ELSE 0 END) + '
            '(CASE WHEN corner THEN 1 ELSE 0 END) <= 1'
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = {column['name'] for column in inspector.get_columns('shot_events')}
    check_constraints = {constraint['name'] for constraint in inspector.get_check_constraints('shot_events') if constraint.get('name')}

    if 'ck_shot_events_max_one_set_piece_context' in check_constraints:
        op.drop_constraint('ck_shot_events_max_one_set_piece_context', 'shot_events', type_='check')

    if 'ck_shot_events_not_penalty_and_free_kick' not in check_constraints:
        op.create_check_constraint(
            'ck_shot_events_not_penalty_and_free_kick',
            'shot_events',
            'NOT (penalty AND free_kick)'
        )

    if 'corner' in columns:
        with op.batch_alter_table('shot_events', schema=None) as batch_op:
            batch_op.drop_column('corner')
