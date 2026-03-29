"""Add penalty and free kick to shot events

Revision ID: ab29f5de3412
Revises: c41f23d7ab9a
Create Date: 2026-02-12 14:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ab29f5de3412'
down_revision = 'c41f23d7ab9a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('penalty', sa.Boolean(), nullable=True, server_default=sa.false()))
        batch_op.add_column(sa.Column('free_kick', sa.Boolean(), nullable=True, server_default=sa.false()))

    op.execute("UPDATE shot_events SET penalty = false WHERE penalty IS NULL")
    op.execute("UPDATE shot_events SET free_kick = false WHERE free_kick IS NULL")

    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        batch_op.alter_column('penalty', existing_type=sa.Boolean(), nullable=False)
        batch_op.alter_column('free_kick', existing_type=sa.Boolean(), nullable=False)

    op.create_check_constraint(
        'ck_shot_events_not_penalty_and_free_kick',
        'shot_events',
        'NOT (penalty AND free_kick)'
    )


def downgrade():
    op.drop_constraint('ck_shot_events_not_penalty_and_free_kick', 'shot_events', type_='check')

    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        batch_op.drop_column('free_kick')
        batch_op.drop_column('penalty')
