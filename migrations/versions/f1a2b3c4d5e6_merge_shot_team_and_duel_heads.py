"""Merge shot team_id and duel split heads

Revision ID: f1a2b3c4d5e6
Revises: 91b2a4e5f7c1, e4b7c2a1d9f0
Create Date: 2026-04-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = ('91b2a4e5f7c1', 'e4b7c2a1d9f0')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass