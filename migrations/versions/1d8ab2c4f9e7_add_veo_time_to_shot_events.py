"""Add veo_time to shot events

Revision ID: 1d8ab2c4f9e7
Revises: ab29f5de3412
Create Date: 2026-02-13 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1d8ab2c4f9e7'
down_revision = 'ab29f5de3412'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('veo_time', sa.String(length=5), nullable=True))


def downgrade():
    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        batch_op.drop_column('veo_time')
