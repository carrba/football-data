"""Update NULL shots_blocked to 0

Revision ID: b7f3b250b08a
Revises: 4e63e1ab16ed
Create Date: 2026-02-09 09:18:59.941395

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7f3b250b08a'
down_revision = '4e63e1ab16ed'
branch_labels = None
depends_on = None


def upgrade():
    # Update NULL values to 0 for shots_blocked
    op.execute("""
        UPDATE player_match_stats 
        SET shots_blocked = 0 
        WHERE shots_blocked IS NULL
    """)
    
    # Set server default and make column non-nullable
    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.alter_column('shots_blocked',
                              existing_type=sa.Integer(),
                              nullable=False,
                              server_default='0')


def downgrade():
    # Remove server default and make column nullable again
    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.alter_column('shots_blocked',
                              existing_type=sa.Integer(),
                              nullable=True,
                              server_default=None)
