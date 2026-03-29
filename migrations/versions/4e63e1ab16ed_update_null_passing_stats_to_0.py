"""Update NULL passing stats to 0

Revision ID: 4e63e1ab16ed
Revises: 4fc74a475eb2
Create Date: 2026-02-09 09:05:54.755905

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4e63e1ab16ed'
down_revision = '4fc74a475eb2'
branch_labels = None
depends_on = None


def upgrade():
    # Update NULL values to 0 for all passing stat columns
    op.execute("""
        UPDATE player_match_stats 
        SET short_completed_passes = 0 
        WHERE short_completed_passes IS NULL
    """)
    op.execute("""
        UPDATE player_match_stats 
        SET short_incomplete_passes = 0 
        WHERE short_incomplete_passes IS NULL
    """)
    op.execute("""
        UPDATE player_match_stats 
        SET long_completed_passes = 0 
        WHERE long_completed_passes IS NULL
    """)
    op.execute("""
        UPDATE player_match_stats 
        SET long_incomplete_passes = 0 
        WHERE long_incomplete_passes IS NULL
    """)
    
    # Set server defaults and make columns non-nullable
    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.alter_column('short_completed_passes',
                              existing_type=sa.Integer(),
                              nullable=False,
                              server_default='0')
        batch_op.alter_column('short_incomplete_passes',
                              existing_type=sa.Integer(),
                              nullable=False,
                              server_default='0')
        batch_op.alter_column('long_completed_passes',
                              existing_type=sa.Integer(),
                              nullable=False,
                              server_default='0')
        batch_op.alter_column('long_incomplete_passes',
                              existing_type=sa.Integer(),
                              nullable=False,
                              server_default='0')


def downgrade():
    # Remove server defaults and make columns nullable again
    with op.batch_alter_table('player_match_stats', schema=None) as batch_op:
        batch_op.alter_column('short_completed_passes',
                              existing_type=sa.Integer(),
                              nullable=True,
                              server_default=None)
        batch_op.alter_column('short_incomplete_passes',
                              existing_type=sa.Integer(),
                              nullable=True,
                              server_default=None)
        batch_op.alter_column('long_completed_passes',
                              existing_type=sa.Integer(),
                              nullable=True,
                              server_default=None)
        batch_op.alter_column('long_incomplete_passes',
                              existing_type=sa.Integer(),
                              nullable=True,
                              server_default=None)
