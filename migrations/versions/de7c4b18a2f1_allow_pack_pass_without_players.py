"""allow pack pass without players

Revision ID: de7c4b18a2f1
Revises: c9b2f1d7aa10
Create Date: 2026-02-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'de7c4b18a2f1'
down_revision = 'c9b2f1d7aa10'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pack_pass_events', schema=None) as batch_op:
        batch_op.alter_column('passer_id', existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column('receiver_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    op.execute("DELETE FROM pack_pass_events WHERE passer_id IS NULL OR receiver_id IS NULL")
    with op.batch_alter_table('pack_pass_events', schema=None) as batch_op:
        batch_op.alter_column('passer_id', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('receiver_id', existing_type=sa.Integer(), nullable=False)
