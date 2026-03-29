"""Convert veo_time to veo_seconds on shot events

Revision ID: 2b6c9d7e4f11
Revises: 1d8ab2c4f9e7
Create Date: 2026-02-13 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2b6c9d7e4f11'
down_revision = '1d8ab2c4f9e7'
branch_labels = None
depends_on = None


def _parse_veo_time(value):
    if not value or not isinstance(value, str):
        return None

    parts = value.split(':')
    if len(parts) != 2:
        return None

    minutes_part, seconds_part = parts
    if not (minutes_part.isdigit() and seconds_part.isdigit()):
        return None

    minutes = int(minutes_part)
    seconds = int(seconds_part)
    if minutes < 0 or seconds < 0 or seconds > 59:
        return None

    return (minutes * 60) + seconds


def upgrade():
    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('veo_seconds', sa.Integer(), nullable=True))

    bind = op.get_bind()
    shot_events = sa.table(
        'shot_events',
        sa.column('id', sa.Integer()),
        sa.column('veo_time', sa.String()),
        sa.column('veo_seconds', sa.Integer())
    )

    rows = bind.execute(
        sa.select(shot_events.c.id, shot_events.c.veo_time).where(shot_events.c.veo_time.isnot(None))
    ).fetchall()

    for row in rows:
        parsed_seconds = _parse_veo_time(row.veo_time)
        if parsed_seconds is None:
            continue

        bind.execute(
            sa.update(shot_events)
            .where(shot_events.c.id == row.id)
            .values(veo_seconds=parsed_seconds)
        )

    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        batch_op.drop_column('veo_time')


def downgrade():
    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('veo_time', sa.String(length=5), nullable=True))

    bind = op.get_bind()
    shot_events = sa.table(
        'shot_events',
        sa.column('id', sa.Integer()),
        sa.column('veo_time', sa.String()),
        sa.column('veo_seconds', sa.Integer())
    )

    rows = bind.execute(
        sa.select(shot_events.c.id, shot_events.c.veo_seconds).where(shot_events.c.veo_seconds.isnot(None))
    ).fetchall()

    for row in rows:
        if row.veo_seconds is None or row.veo_seconds < 0:
            continue

        formatted_time = f"{row.veo_seconds // 60:02d}:{row.veo_seconds % 60:02d}"
        bind.execute(
            sa.update(shot_events)
            .where(shot_events.c.id == row.id)
            .values(veo_time=formatted_time)
        )

    with op.batch_alter_table('shot_events', schema=None) as batch_op:
        batch_op.drop_column('veo_seconds')
