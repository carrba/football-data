"""Add pack pass and turnover events

Revision ID: e1c8f6a2b9d3
Revises: 04c3d7f2f031
Create Date: 2026-02-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e1c8f6a2b9d3'
down_revision = '04c3d7f2f031'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('pack_pass_events'):
        op.create_table(
            'pack_pass_events',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('match_id', sa.Integer(), sa.ForeignKey('matches.id'), nullable=False),
            sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id'), nullable=False),
            sa.Column('passer_id', sa.Integer(), sa.ForeignKey('players.id'), nullable=False),
            sa.Column('receiver_id', sa.Integer(), sa.ForeignKey('players.id'), nullable=False),
            sa.Column('score', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('defenders', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('midfielders', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('attackers', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
        )
    else:
        existing_columns = {col['name'] for col in inspector.get_columns('pack_pass_events')}
        with op.batch_alter_table('pack_pass_events', schema=None) as batch_op:
            if 'defenders' not in existing_columns:
                batch_op.add_column(sa.Column('defenders', sa.Integer(), nullable=True, server_default='0'))
            if 'midfielders' not in existing_columns:
                batch_op.add_column(sa.Column('midfielders', sa.Integer(), nullable=True, server_default='0'))
            if 'attackers' not in existing_columns:
                batch_op.add_column(sa.Column('attackers', sa.Integer(), nullable=True, server_default='0'))
            if 'created_at' not in existing_columns:
                batch_op.add_column(sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')))

        op.execute("UPDATE pack_pass_events SET defenders = 0 WHERE defenders IS NULL")
        op.execute("UPDATE pack_pass_events SET midfielders = 0 WHERE midfielders IS NULL")
        op.execute("UPDATE pack_pass_events SET attackers = 0 WHERE attackers IS NULL")
        op.execute("UPDATE pack_pass_events SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")

        with op.batch_alter_table('pack_pass_events', schema=None) as batch_op:
            if 'defenders' not in existing_columns:
                batch_op.alter_column('defenders', existing_type=sa.Integer(), nullable=False)
            if 'midfielders' not in existing_columns:
                batch_op.alter_column('midfielders', existing_type=sa.Integer(), nullable=False)
            if 'attackers' not in existing_columns:
                batch_op.alter_column('attackers', existing_type=sa.Integer(), nullable=False)
            if 'created_at' not in existing_columns:
                batch_op.alter_column('created_at', existing_type=sa.DateTime(), nullable=False)

    if not inspector.has_table('pack_turnover_events'):
        op.create_table(
            'pack_turnover_events',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('match_id', sa.Integer(), sa.ForeignKey('matches.id'), nullable=False),
            sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id'), nullable=False),
            sa.Column('player_id', sa.Integer(), sa.ForeignKey('players.id'), nullable=False),
            sa.Column('score', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('defenders', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('midfielders', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('attackers', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
        )
    else:
        existing_columns = {col['name'] for col in inspector.get_columns('pack_turnover_events')}
        with op.batch_alter_table('pack_turnover_events', schema=None) as batch_op:
            if 'defenders' not in existing_columns:
                batch_op.add_column(sa.Column('defenders', sa.Integer(), nullable=True, server_default='0'))
            if 'midfielders' not in existing_columns:
                batch_op.add_column(sa.Column('midfielders', sa.Integer(), nullable=True, server_default='0'))
            if 'attackers' not in existing_columns:
                batch_op.add_column(sa.Column('attackers', sa.Integer(), nullable=True, server_default='0'))
            if 'created_at' not in existing_columns:
                batch_op.add_column(sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')))

        op.execute("UPDATE pack_turnover_events SET defenders = 0 WHERE defenders IS NULL")
        op.execute("UPDATE pack_turnover_events SET midfielders = 0 WHERE midfielders IS NULL")
        op.execute("UPDATE pack_turnover_events SET attackers = 0 WHERE attackers IS NULL")
        op.execute("UPDATE pack_turnover_events SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")

        with op.batch_alter_table('pack_turnover_events', schema=None) as batch_op:
            if 'defenders' not in existing_columns:
                batch_op.alter_column('defenders', existing_type=sa.Integer(), nullable=False)
            if 'midfielders' not in existing_columns:
                batch_op.alter_column('midfielders', existing_type=sa.Integer(), nullable=False)
            if 'attackers' not in existing_columns:
                batch_op.alter_column('attackers', existing_type=sa.Integer(), nullable=False)
            if 'created_at' not in existing_columns:
                batch_op.alter_column('created_at', existing_type=sa.DateTime(), nullable=False)


def downgrade():
    op.drop_table('pack_turnover_events')
    op.drop_table('pack_pass_events')
