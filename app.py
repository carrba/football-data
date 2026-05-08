from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from config import Config
from models import db, Team, Match, Player, MatchEvent, PlayerMatchStats, MatchLineup, GoalKeeperMatchStats, PackPassEvent, PackTurnoverEvent, PackDribbleEvent, PackDribbledPastPlayer, ShotEvent, CornerEvent
from datetime import datetime
from flask_migrate import Migrate
from sqlalchemy import func, case
import os
import csv
import io
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.lineplots import LinePlot
import math

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
migrate = Migrate(app, db)

DEFENDER_POSITIONS = {
    'GK', 'GOALKEEPER',
    'RB', 'RWB', 'LB', 'LWB',
    'CB', 'LCB', 'RCB',
    'SW', 'SWEEPER'
}

MIDFIELDER_POSITIONS = {
    'CDM', 'LDM', 'RDM',
    'CM', 'LCM', 'RCM',
    'CAM', 'LAM', 'RAM',
    'LM', 'RM'
}

ATTACKER_POSITIONS = {
    'LW', 'RW', 'LF', 'RF',
    'SS', 'CF', 'ST'
}

# Create tables
with app.app_context():
    db.create_all()


def is_goalkeeper_for_match(match_id, player):
    lineup = MatchLineup.query.filter_by(match_id=match_id, player_id=player.id).first()
    if lineup and lineup.position:
        return lineup.position.upper() == 'GK', lineup
    if player.position:
        return player.position.upper() in ('GK', 'GOALKEEPER'), lineup
    return False, lineup


def get_team_id_for_match(match_id, player):
    lineup = MatchLineup.query.filter_by(match_id=match_id, player_id=player.id).first()
    if lineup and lineup.team_id:
        return lineup.team_id
    return player.team_id


def get_stats_model(match_id, player):
    is_goalkeeper, _ = is_goalkeeper_for_match(match_id, player)
    return GoalKeeperMatchStats if is_goalkeeper else PlayerMatchStats


def get_position_group(position_value):
    normalized = (position_value or '').strip().upper()

    if normalized in DEFENDER_POSITIONS:
        return 'defender'
    if normalized in MIDFIELDER_POSITIONS:
        return 'midfielder'
    if normalized in ATTACKER_POSITIONS:
        return 'attacker'

    if 'BACK' in normalized or normalized.startswith('CB'):
        return 'defender'
    if normalized.endswith('DM') or normalized.endswith('CM') or normalized.endswith('AM') or normalized in {'MIDFIELD', 'MIDFIELDER'}:
        return 'midfielder'
    if normalized in {'FORWARD', 'ATTACKER', 'STRIKER', 'WINGER'}:
        return 'attacker'

    return 'midfielder'


def get_player_position_group_for_match(match_id, player):
    lineup = MatchLineup.query.filter_by(match_id=match_id, player_id=player.id).first()
    position_value = lineup.position if lineup and lineup.position else player.position
    return get_position_group(position_value)


def get_or_create_stats(match_id, player, stats_model):
    stats = stats_model.query.filter_by(match_id=match_id, player_id=player.id).first()
    if not stats:
        stats = stats_model(match_id=match_id, player_id=player.id)
        db.session.add(stats)
    return stats


def sync_duel_totals(stats):
    if not hasattr(stats, 'aerial_duels_won') or not hasattr(stats, 'ground_duels_won'):
        return

    stats.duels_won = int((stats.aerial_duels_won or 0) + (stats.ground_duels_won or 0))
    stats.duels_lost = int((stats.aerial_duels_lost or 0) + (stats.ground_duels_lost or 0))


def mirror_duel_to_non_main_outfield(match_id, acting_player, stat_name, increment=True):
    """Mirror main-team duel events to the non-main outfield aggregate player."""
    opposite_duel_stat = {
        'aerial_duels_won': 'aerial_duels_lost',
        'aerial_duels_lost': 'aerial_duels_won',
        'ground_duels_won': 'ground_duels_lost',
        'ground_duels_lost': 'ground_duels_won',
        'tackles_won': 'ground_duels_lost'
    }.get(stat_name)

    if not opposite_duel_stat:
        return None

    match = Match.query.get(match_id)
    if not match:
        return None

    main_team_id = match.home_team_id if match.main else match.away_team_id
    acting_team_id = get_team_id_for_match(match_id, acting_player)
    if acting_team_id != main_team_id:
        return None

    non_main_team_id = match.away_team_id if match.main else match.home_team_id
    non_main_outfield_player = Player.query.filter(
        Player.team_id == non_main_team_id,
        func.lower(Player.name).like('%outfield%')
    ).order_by(Player.id.asc()).first()

    if not non_main_outfield_player:
        return None

    outfield_stats_model = get_stats_model(match_id, non_main_outfield_player)
    if not hasattr(outfield_stats_model, opposite_duel_stat):
        return None

    outfield_stats = get_or_create_stats(match_id, non_main_outfield_player, outfield_stats_model)
    current_value = getattr(outfield_stats, opposite_duel_stat) or 0

    if increment:
        setattr(outfield_stats, opposite_duel_stat, current_value + 1)
    else:
        setattr(outfield_stats, opposite_duel_stat, max(0, current_value - 1))

    if opposite_duel_stat in ['aerial_duels_won', 'aerial_duels_lost', 'ground_duels_won', 'ground_duels_lost']:
        sync_duel_totals(outfield_stats)

    return {
        'player_id': non_main_outfield_player.id,
        'stat_name': opposite_duel_stat,
        'new_value': getattr(outfield_stats, opposite_duel_stat),
        'duels_won': getattr(outfield_stats, 'duels_won', 0),
        'duels_lost': getattr(outfield_stats, 'duels_lost', 0)
    }


def recalc_pack_pass_stats(match_id, player_id, stats_model):
    stats = stats_model.query.filter_by(match_id=match_id, player_id=player_id).first()
    if not stats:
        return

    pass_counts = db.session.query(
        func.count(PackPassEvent.id),
        func.coalesce(func.sum(PackPassEvent.score), 0),
        func.coalesce(func.sum(PackPassEvent.defenders), 0),
        func.coalesce(func.sum(PackPassEvent.midfielders), 0),
        func.coalesce(func.sum(PackPassEvent.attackers), 0)
    ).filter_by(match_id=match_id, passer_id=player_id).one()

    receive_score = db.session.query(
        func.coalesce(func.sum(PackPassEvent.score), 0)
    ).filter_by(match_id=match_id, receiver_id=player_id).scalar()

    stats.pack_passes = int(pass_counts[0])
    stats.pack_pass_score = int(pass_counts[1])
    stats.pack_pass_defenders = int(pass_counts[2])
    stats.pack_pass_midfielders = int(pass_counts[3])
    stats.pack_pass_attackers = int(pass_counts[4])
    stats.pack_pass_receive_score = int(receive_score or 0)


def recalc_pack_turnover_stats(match_id, player_id, stats_model):
    stats = stats_model.query.filter_by(match_id=match_id, player_id=player_id).first()
    if not stats:
        return

    turnover_counts = db.session.query(
        func.count(PackTurnoverEvent.id),
        func.coalesce(func.sum(PackTurnoverEvent.score), 0),
        func.coalesce(func.sum(PackTurnoverEvent.defenders), 0),
        func.coalesce(func.sum(PackTurnoverEvent.midfielders), 0),
        func.coalesce(func.sum(PackTurnoverEvent.attackers), 0)
    ).filter_by(match_id=match_id, player_id=player_id).one()

    stats.pack_turnovers = int(turnover_counts[0])
    stats.pack_turnover_score = int(turnover_counts[1])
    stats.pack_turnover_defenders = int(turnover_counts[2])
    stats.pack_turnover_midfielders = int(turnover_counts[3])
    stats.pack_turnover_attackers = int(turnover_counts[4])


def recalc_pack_dribble_stats(match_id, player_id, stats_model):
    stats = stats_model.query.filter_by(match_id=match_id, player_id=player_id).first()
    if not stats:
        return

    dribble_counts = db.session.query(
        func.count(PackDribbleEvent.id),
        func.coalesce(func.sum(PackDribbleEvent.score), 0),
        func.coalesce(func.sum(PackDribbleEvent.defenders), 0),
        func.coalesce(func.sum(PackDribbleEvent.midfielders), 0),
        func.coalesce(func.sum(PackDribbleEvent.attackers), 0)
    ).filter_by(match_id=match_id, dribbler_id=player_id).one()

    stats.pack_dribbles = int(dribble_counts[0])
    stats.pack_dribble_score = int(dribble_counts[1])
    stats.pack_dribble_defenders = int(dribble_counts[2])
    stats.pack_dribble_midfielders = int(dribble_counts[3])
    stats.pack_dribble_attackers = int(dribble_counts[4])


def recalc_pack_dribbled_past_stats(match_id, player_id, stats_model):
    stats = stats_model.query.filter_by(match_id=match_id, player_id=player_id).first()
    if not stats:
        return

    dribbled_past_counts = db.session.query(
        func.count(PackDribbledPastPlayer.id),
        func.coalesce(func.sum(case((PackDribbledPastPlayer.position_group == 'defender', 1), else_=0)), 0),
        func.coalesce(func.sum(case((PackDribbledPastPlayer.position_group == 'midfielder', 1), else_=0)), 0),
        func.coalesce(func.sum(case((PackDribbledPastPlayer.position_group == 'attacker', 1), else_=0)), 0)
    ).join(
        PackDribbleEvent,
        PackDribbleEvent.id == PackDribbledPastPlayer.event_id
    ).filter(
        PackDribbleEvent.match_id == match_id,
        PackDribbledPastPlayer.player_id == player_id
    ).one()

    defenders = int(dribbled_past_counts[1])
    midfielders = int(dribbled_past_counts[2])
    attackers = int(dribbled_past_counts[3])

    stats.pack_dribbled_past = int(dribbled_past_counts[0])
    stats.pack_dribbled_past_defenders = defenders
    stats.pack_dribbled_past_midfielders = midfielders
    stats.pack_dribbled_past_attackers = attackers
    stats.pack_dribbled_past_score = (defenders * 3) + (midfielders * 2) + attackers


def calculate_chances_created(match_id, player_id):
    """Count shots created by a player via assists in a specific match."""
    chances_created = db.session.query(func.count(ShotEvent.id)).filter(
        ShotEvent.match_id == match_id,
        ShotEvent.assist_player_id == player_id
    ).scalar()
    return int(chances_created or 0)


def calculate_big_chances_created(match_id, player_id):
    """Count big chances created by a player via assists in a specific match."""
    big_chances_created = db.session.query(func.count(ShotEvent.id)).filter(
        ShotEvent.match_id == match_id,
        ShotEvent.assist_player_id == player_id,
        ShotEvent.big_chance.is_(True)
    ).scalar()
    return int(big_chances_created or 0)


def format_veo_time(veo_seconds):
    if veo_seconds is None or veo_seconds < 0:
        return None
    return f"{veo_seconds // 60:02d}:{veo_seconds % 60:02d}"


def build_summary_export_filename(match, summary_type):
    non_main_team_name = match.away_team.name if match.main else match.home_team.name
    team_slug = re.sub(r'[^a-z0-9]+', '_', non_main_team_name.lower()).strip('_') or 'team'
    date_suffix = match.match_date.strftime('%d%m%y')
    return f"{team_slug}_{summary_type}_{date_suffix}.pdf"


def build_match_summary_pdf_response(match, summary_rows, goal_threat_rows, summary_type, summary_heading='Match Summary', player_rows=None):
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(KeepTogether([
        Paragraph(f"{match.home_team.name} vs {match.away_team.name}", styles['Title']),
        Paragraph(match.match_date.strftime('%Y-%m-%d %H:%M'), styles['Normal'])
    ]))
    elements.append(Spacer(1, 14))

    table_data = [['Metric', match.home_team.name, match.away_team.name]]
    for row in summary_rows:
        home_value = row['home_value']
        away_value = row['away_value']
        if row['value_type'] == 'float':
            home_display = f"{home_value:.2f}"
            away_display = f"{away_value:.2f}"
        else:
            home_display = str(home_value)
            away_display = str(away_value)

        table_data.append([row['metric'], home_display, away_display])

    summary_table = Table(table_data, colWidths=[220, 140, 140])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(KeepTogether([
        Paragraph(summary_heading, styles['Heading2']),
        summary_table
    ]))
    elements.append(Spacer(1, 16))

    goal_threat_table_data = [['Metric', match.home_team.name, match.away_team.name]]
    for row in goal_threat_rows:
        home_value = row['home_value']
        away_value = row['away_value']
        if row['value_type'] == 'float':
            home_display = f"{home_value:.2f}"
            away_display = f"{away_value:.2f}"
        elif row['value_type'] == 'pct':
            home_display = f"{home_value:.1f}%"
            away_display = f"{away_value:.1f}%"
        else:
            home_display = str(home_value)
            away_display = str(away_value)

        goal_threat_table_data.append([row['metric'], home_display, away_display])

    goal_threat_table = Table(goal_threat_table_data, colWidths=[220, 140, 140])
    goal_threat_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(KeepTogether([
        Paragraph('Goal Threat', styles['Heading2']),
        goal_threat_table
    ]))
    elements.append(Spacer(1, 16))

    main_team_id = match.home_team_id if match.main else match.away_team_id
    non_main_team_id = match.away_team_id if match.main else match.home_team_id
    main_team_name = match.home_team.name if match.main else match.away_team.name
    non_main_team_name = match.away_team.name if match.main else match.home_team.name

    shot_events = ShotEvent.query.filter(
        ShotEvent.match_id == match.id,
        ShotEvent.veo_seconds.isnot(None),
        ShotEvent.veo_seconds >= 0
    ).order_by(ShotEvent.veo_seconds.asc(), ShotEvent.id.asc()).all()

    main_points = [(0.0, 0.0)]
    non_main_points = [(0.0, 0.0)]
    main_cumulative_xg = 0.0
    non_main_cumulative_xg = 0.0

    for event in shot_events:
        shot_minute = float(event.veo_seconds) / 60.0
        shot_xg = float(event.xG or 0.0)
        shooter_team_id = event.team_id

        if shooter_team_id == main_team_id:
            main_points.append((shot_minute, main_cumulative_xg))
            main_cumulative_xg += shot_xg
            main_points.append((shot_minute, main_cumulative_xg))
        elif shooter_team_id == non_main_team_id:
            non_main_points.append((shot_minute, non_main_cumulative_xg))
            non_main_cumulative_xg += shot_xg
            non_main_points.append((shot_minute, non_main_cumulative_xg))
        else:
            continue

    timeline_elements = [Paragraph('xG Timeline', styles['Heading2'])]

    if len(main_points) > 1 or len(non_main_points) > 1:
        drawing = Drawing(520, 220)
        line_plot = LinePlot()
        line_plot.x = 45
        line_plot.y = 40
        line_plot.height = 150
        line_plot.width = 445
        line_plot.data = [main_points, non_main_points]
        line_plot.joinedLines = 1

        line_plot.lines[0].strokeColor = colors.HexColor('#1f77b4')
        line_plot.lines[0].strokeWidth = 2
        line_plot.lines[1].strokeColor = colors.HexColor('#d62728')
        line_plot.lines[1].strokeWidth = 2

        max_minute = max(point[0] for point in main_points + non_main_points)
        max_cumulative_xg = max(point[1] for point in main_points + non_main_points)

        x_max = max(5.0, math.ceil(max_minute / 5.0) * 5.0)
        y_max = max(0.5, math.ceil(max_cumulative_xg * 2) / 2)

        line_plot.xValueAxis.valueMin = 0
        line_plot.xValueAxis.valueMax = x_max
        line_plot.xValueAxis.valueStep = 5
        line_plot.yValueAxis.valueMin = 0
        line_plot.yValueAxis.valueMax = y_max
        line_plot.yValueAxis.valueStep = max(0.1, round(y_max / 5, 1))
        line_plot.xValueAxis.labelTextFormat = '%.0f'
        line_plot.yValueAxis.labelTextFormat = '%.1f'

        drawing.add(line_plot)
        timeline_elements.append(drawing)
        timeline_elements.append(Paragraph(f"Blue: {main_team_name}", styles['Normal']))
        timeline_elements.append(Paragraph(f"Red: {non_main_team_name}", styles['Normal']))
    else:
        timeline_elements.append(Paragraph('No timed shot data available to plot cumulative xG timeline.', styles['Normal']))

    elements.append(KeepTogether(timeline_elements))

    if player_rows:
        elements.append(Spacer(1, 16))
        header_style = ParagraphStyle(
            'ShotSummaryPlayerHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=8,
            leading=9,
            textColor=colors.whitesmoke,
            alignment=1,
        )
        body_style = ParagraphStyle(
            'ShotSummaryPlayerBody',
            parent=styles['Normal'],
            fontSize=8,
            leading=9,
            alignment=1,
        )
        name_style = ParagraphStyle(
            'ShotSummaryPlayerName',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=8,
            leading=9,
            alignment=0,
        )
        player_table_data = [[
            Paragraph('Player', header_style),
            Paragraph('Goals', header_style),
            Paragraph('Assists', header_style),
            Paragraph('xG', header_style),
            Paragraph('xA', header_style),
            Paragraph('xSC', header_style),
            Paragraph('Shots On Target', header_style),
            Paragraph('Shots Off Target', header_style),
            Paragraph('Shots Blocked', header_style),
        ]]
        for row in player_rows:
            player_table_data.append([
                Paragraph(row['player_name'], name_style),
                Paragraph(str(row['goals']), body_style),
                Paragraph(str(row['assists']), body_style),
                Paragraph(f"{row['xg']:.2f}", body_style),
                Paragraph(f"{row['xa']:.2f}", body_style),
                Paragraph(f"{row['xg'] + row['xa']:.2f}", body_style),
                Paragraph(str(row['shots_on_target']), body_style),
                Paragraph(str(row['shots_off_target']), body_style),
                Paragraph(str(row['shots_blocked']), body_style),
            ])
        player_table = Table(
            player_table_data,
            colWidths=[130, 36, 40, 32, 32, 34, 54, 58, 54],
            repeatRows=1
        )
        player_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        main_team_name = match.home_team.name if match.main else match.away_team.name
        elements.append(KeepTogether([
            Paragraph(f'Player Shot Summary — {main_team_name}', styles['Heading2']),
            player_table
        ]))

    document.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    filename = build_summary_export_filename(match, summary_type)
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


def get_match_goal_totals(match):
    lineup_team_by_player = {
        player_id: team_id
        for player_id, team_id in db.session.query(
            MatchLineup.player_id,
            MatchLineup.team_id
        ).filter(MatchLineup.match_id == match.id).all()
    }

    player_ids = {player_id for player_id in lineup_team_by_player if player_id}

    stat_rows = db.session.query(
        PlayerMatchStats.player_id,
        PlayerMatchStats.goals,
        Player.team_id
    ).join(
        Player, Player.id == PlayerMatchStats.player_id
    ).filter(
        PlayerMatchStats.match_id == match.id
    ).all()

    for player_id, _, _ in stat_rows:
        if player_id:
            player_ids.add(player_id)

    own_goal_rows = db.session.query(
        MatchEvent.team_id,
        MatchEvent.player_id
    ).filter(
        MatchEvent.match_id == match.id,
        MatchEvent.event_type == 'own_goal'
    ).all()

    for _, player_id in own_goal_rows:
        if player_id:
            player_ids.add(player_id)

    player_team_by_id = {
        player_id: team_id
        for player_id, team_id in db.session.query(Player.id, Player.team_id).filter(Player.id.in_(player_ids)).all()
    } if player_ids else {}

    totals = {
        match.home_team_id: 0,
        match.away_team_id: 0
    }

    for player_id, goals, player_team_id in stat_rows:
        team_id = lineup_team_by_player.get(player_id) or player_team_id
        if team_id in totals:
            totals[team_id] += int(goals or 0)

    for benefiting_team_id, player_id in own_goal_rows:
        credited_team_id = benefiting_team_id

        if credited_team_id not in totals and player_id:
            player_team_id = lineup_team_by_player.get(player_id) or player_team_by_id.get(player_id)
            if player_team_id == match.home_team_id:
                credited_team_id = match.away_team_id
            elif player_team_id == match.away_team_id:
                credited_team_id = match.home_team_id

        if credited_team_id in totals:
            totals[credited_team_id] += 1

    return totals


def recalc_match_score(match_id):
    """Recalculate match score from player goal stats for that match."""
    match = Match.query.get(match_id)
    if not match:
        return False

    goal_totals = get_match_goal_totals(match)
    home_goals = goal_totals[match.home_team_id]
    away_goals = goal_totals[match.away_team_id]

    score_changed = (match.home_score != home_goals) or (match.away_score != away_goals)
    match.home_score = home_goals
    match.away_score = away_goals
    return score_changed


def sync_match_scores(match_ids):
    """Sync scores for many matches and persist only if anything changed."""
    changed = False
    for match_id in match_ids:
        changed = recalc_match_score(match_id) or changed

    if changed:
        db.session.commit()


@app.route('/')
def index():
    """Home page showing recent matches"""
    matches = Match.query.order_by(Match.match_date.desc()).limit(10).all()
    sync_match_scores([match.id for match in matches])
    return render_template('index.html', matches=matches)


@app.route('/teams')
def teams():
    """List all teams"""
    all_teams = Team.query.order_by(Team.name).all()
    return render_template('teams.html', teams=all_teams)


@app.route('/teams/new', methods=['GET', 'POST'])
def new_team():
    """Create a new team"""
    if request.method == 'POST':
        team = Team(
            name=request.form['name'],
            city=request.form.get('city'),
            country=request.form.get('country')
        )
        db.session.add(team)
        db.session.commit()
        flash('Team created successfully!', 'success')
        return redirect(url_for('teams'))
    return render_template('team_form.html')


@app.route('/teams/<int:team_id>')
def team_detail(team_id):
    """View team details"""
    team = Team.query.get_or_404(team_id)
    home_matches = Match.query.filter_by(home_team_id=team_id).order_by(Match.match_date.desc()).all()
    away_matches = Match.query.filter_by(away_team_id=team_id).order_by(Match.match_date.desc()).all()
    sync_match_scores([match.id for match in home_matches + away_matches])
    players = Player.query.filter_by(team_id=team_id).all()
    return render_template('team_detail.html', team=team, home_matches=home_matches, 
                         away_matches=away_matches, players=players)


@app.route('/matches')
def matches():
    """List all matches"""
    all_matches = Match.query.order_by(Match.match_date.desc()).all()
    sync_match_scores([match.id for match in all_matches])
    return render_template('matches.html', matches=all_matches)


@app.route('/matches/new', methods=['GET', 'POST'])
def new_match():
    """Create a new match"""
    if request.method == 'POST':
        main_team = request.form.get('main_team', 'home')
        is_home_main = (main_team != 'away')

        match = Match(
            home_team_id=request.form['home_team_id'],
            away_team_id=request.form['away_team_id'],
            main=is_home_main,
            home_score=0,
            away_score=0,
            match_date=datetime.strptime(request.form['match_date'], '%Y-%m-%dT%H:%M'),
            venue=request.form.get('venue'),
            surface=request.form.get('surface'),
            competition=request.form.get('competition'),
            season=request.form.get('season'),
            home_formation=request.form.get('home_formation'),
            away_formation=request.form.get('away_formation'),
            notes=request.form.get('notes')
        )
        db.session.add(match)
        db.session.commit()
        flash('Match created successfully! Now add the starting lineup.', 'success')
        return redirect(url_for('match_lineup', match_id=match.id))
    
    teams = Team.query.order_by(Team.name).all()
    return render_template('match_form.html', teams=teams)


@app.route('/matches/<int:match_id>/lineup', methods=['GET', 'POST'])
def match_lineup(match_id):
    """Add starting lineup for a match (11 players with positions for both teams)"""
    match = Match.query.get_or_404(match_id)
    
    if request.method == 'POST':
        # Clear existing lineup
        MatchLineup.query.filter_by(match_id=match_id).delete()
        
        # Process home team lineup
        for i in range(1, 12):  # 11 players
            player_id = request.form.get(f'home_player_{i}')
            position = request.form.get(f'home_position_{i}')
            
            if player_id and position:
                player_id = int(player_id)  # Convert to integer
                player = Player.query.get(player_id)
                lineup = MatchLineup(
                    match_id=match_id,
                    player_id=player_id,
                    team_id=match.home_team_id,
                    position=position,
                    shirt_number=player.jersey_number
                )
                db.session.add(lineup)
                
                # Create appropriate stats entry based on position
                if position.upper() == 'GK':
                    # Create GoalKeeperMatchStats for goalkeepers
                    gk_stats = GoalKeeperMatchStats.query.filter_by(match_id=match_id, player_id=player_id).first()
                    if not gk_stats:
                        gk_stats = GoalKeeperMatchStats(match_id=match_id, player_id=player_id)
                        db.session.add(gk_stats)
                else:
                    # Create PlayerMatchStats for other positions
                    stats = PlayerMatchStats.query.filter_by(match_id=match_id, player_id=player_id).first()
                    if not stats:
                        stats = PlayerMatchStats(match_id=match_id, player_id=player_id)
                        db.session.add(stats)
        
        # Process away team lineup
        for i in range(1, 12):  # 11 players
            player_id = request.form.get(f'away_player_{i}')
            position = request.form.get(f'away_position_{i}')
            
            if player_id and position:
                player_id = int(player_id)  # Convert to integer
                player = Player.query.get(player_id)
                lineup = MatchLineup(
                    match_id=match_id,
                    player_id=player_id,
                    team_id=match.away_team_id,
                    position=position,
                    shirt_number=player.jersey_number
                )
                db.session.add(lineup)
                
                # Create appropriate stats entry based on position
                if position.upper() == 'GK':
                    # Create GoalKeeperMatchStats for goalkeepers
                    gk_stats = GoalKeeperMatchStats.query.filter_by(match_id=match_id, player_id=player_id).first()
                    if not gk_stats:
                        gk_stats = GoalKeeperMatchStats(match_id=match_id, player_id=player_id)
                        db.session.add(gk_stats)
                else:
                    # Create PlayerMatchStats for other positions
                    stats = PlayerMatchStats.query.filter_by(match_id=match_id, player_id=player_id).first()
                    if not stats:
                        stats = PlayerMatchStats(match_id=match_id, player_id=player_id)
                        db.session.add(stats)
        
        recalc_match_score(match_id)
        db.session.commit()
        flash('Starting lineups added successfully!', 'success')
        return redirect(url_for('match_stats', match_id=match.id))
    
    # GET request - get existing lineup if any
    home_lineup = MatchLineup.query.filter_by(match_id=match_id, team_id=match.home_team_id).all()
    away_lineup = MatchLineup.query.filter_by(match_id=match_id, team_id=match.away_team_id).all()
    
    # If no lineup exists for this match, try to get the most recent lineup for each team
    if not home_lineup:
        # Find the most recent match involving the home team (excluding current match)
        recent_home_match = Match.query.filter(
            db.or_(Match.home_team_id == match.home_team_id, Match.away_team_id == match.home_team_id),
            Match.id != match_id,
            Match.match_date < match.match_date
        ).order_by(Match.match_date.desc()).first()
        
        if recent_home_match:
            # Get lineup from that match for this team
            home_lineup = MatchLineup.query.filter_by(
                match_id=recent_home_match.id,
                team_id=match.home_team_id
            ).all()
    
    if not away_lineup:
        # Find the most recent match involving the away team (excluding current match)
        recent_away_match = Match.query.filter(
            db.or_(Match.home_team_id == match.away_team_id, Match.away_team_id == match.away_team_id),
            Match.id != match_id,
            Match.match_date < match.match_date
        ).order_by(Match.match_date.desc()).first()
        
        if recent_away_match:
            # Get lineup from that match for this team
            away_lineup = MatchLineup.query.filter_by(
                match_id=recent_away_match.id,
                team_id=match.away_team_id
            ).all()
    
    # Get all players for both teams
    home_players = Player.query.filter_by(team_id=match.home_team_id).order_by(Player.name).all()
    away_players = Player.query.filter_by(team_id=match.away_team_id).order_by(Player.name).all()
    
    return render_template('match_lineup.html', match=match, 
                         home_lineup=home_lineup, away_lineup=away_lineup,
                         home_players=home_players, away_players=away_players)


@app.route('/matches/<int:match_id>/lineup/stats')
def match_lineup_stats(match_id):
    """Track statistics for the starting lineup"""
    match = Match.query.get_or_404(match_id)
    
    # Get all players with stats for this match
    player_stats = PlayerMatchStats.query.filter_by(match_id=match_id).all()
    
    return render_template('match_lineup_stats.html', match=match, player_stats=player_stats)


@app.route('/matches/<int:match_id>')
def match_detail(match_id):
    """View match details"""
    match = Match.query.get_or_404(match_id)
    sync_match_scores([match_id])
    events = MatchEvent.query.filter_by(match_id=match_id).order_by(MatchEvent.minute).all()
    
    # Calculate minutes played from Veo timing events
    veo_events = {}
    for event in events:
        if event.event_type.startswith('veo_'):
            veo_events[event.event_type] = event.minute
    
    # Calculate total match minutes
    total_match_minutes = None
    half_minutes = None
    if all(k in veo_events for k in ['veo_1st_half_start', 'veo_1st_half_stop', 
                                       'veo_2nd_half_start', 'veo_2nd_half_stop']):
        first_half = veo_events['veo_1st_half_stop'] - veo_events['veo_1st_half_start']
        second_half = veo_events['veo_2nd_half_stop'] - veo_events['veo_2nd_half_start']
        total_match_minutes = first_half + second_half
        half_minutes = {'first': first_half, 'second': second_half}
    
    # Get substitution events
    sub_off_events = {}  # {player_id: minute}
    sub_on_events = {}   # {player_id: minute}
    for event in events:
        if event.event_type == 'substitute_off' and event.player_id:
            sub_off_events[event.player_id] = event.minute
        elif event.event_type == 'substitute_on' and event.player_id:
            sub_on_events[event.player_id] = event.minute
    
    # Get lineup and assign minutes
    home_lineup = MatchLineup.query.filter_by(match_id=match_id, team_id=match.home_team_id).all()
    away_lineup = MatchLineup.query.filter_by(match_id=match_id, team_id=match.away_team_id).all()
    
    lineup_minutes = None
    if home_lineup or away_lineup:
        lineup_minutes = {'home': [], 'away': []}
        
        # Calculate minutes for home team
        for lineup_player in home_lineup:
            player_id = lineup_player.player_id
            
            # Check if player was substituted off
            if player_id in sub_off_events:
                minutes = sub_off_events[player_id]
            else:
                minutes = total_match_minutes if total_match_minutes else 0
            
            lineup_minutes['home'].append({
                'position': lineup_player.position,
                'shirt_number': lineup_player.shirt_number,
                'player_name': lineup_player.player.name,
                'minutes': minutes
            })
        
        # Calculate minutes for away team
        for lineup_player in away_lineup:
            player_id = lineup_player.player_id
            
            # Check if player was substituted off
            if player_id in sub_off_events:
                minutes = sub_off_events[player_id]
            else:
                minutes = total_match_minutes if total_match_minutes else 0
            
            lineup_minutes['away'].append({
                'position': lineup_player.position,
                'shirt_number': lineup_player.shirt_number,
                'player_name': lineup_player.player.name,
                'minutes': minutes
            })
        
        # Add substitute players who came on
        for player_id, sub_minute in sub_on_events.items():
            player = Player.query.get(player_id)
            if player and total_match_minutes:
                minutes = total_match_minutes - sub_minute
                player_data = {
                    'position': 'SUB',
                    'shirt_number': player.jersey_number,
                    'player_name': player.name,
                    'minutes': minutes
                }
                
                # Add to appropriate team
                if player.team_id == match.home_team_id:
                    lineup_minutes['home'].append(player_data)
                elif player.team_id == match.away_team_id:
                    lineup_minutes['away'].append(player_data)
    
    return render_template('match_detail.html', match=match, events=events,
                         lineup_minutes=lineup_minutes, total_match_minutes=total_match_minutes,
                         half_minutes=half_minutes,
                         home_players=Player.query.filter_by(team_id=match.home_team_id).order_by(Player.jersey_number).all(),
                         away_players=Player.query.filter_by(team_id=match.away_team_id).order_by(Player.jersey_number).all())


@app.route('/matches/<int:match_id>/main-team', methods=['POST'])
def set_main_team(match_id):
    """Set which team is the main team for a match."""
    match = Match.query.get_or_404(match_id)
    selected_team = request.form.get('main_team')

    if selected_team not in ('home', 'away'):
        flash('Invalid main team selection.', 'error')
        return redirect(url_for('match_detail', match_id=match_id))

    match.main = (selected_team == 'home')
    db.session.commit()
    flash('Main team updated successfully!', 'success')
    return redirect(url_for('match_detail', match_id=match_id))


@app.route('/matches/<int:match_id>/stats')
def match_stats(match_id):
    """View and record player statistics for a match"""
    match = Match.query.get_or_404(match_id)

    is_goalkeeper_map = {}

    class CombinedGoalkeeperStats:
        def __init__(self, gk_stats, player_stats):
            self._gk_stats = gk_stats
            self._player_stats = player_stats

        def __getattr__(self, name):
            if hasattr(self._gk_stats, name):
                return getattr(self._gk_stats, name)
            if self._player_stats and hasattr(self._player_stats, name):
                return getattr(self._player_stats, name)
            return 0

    class OutfieldStatsWrapper:
        def __init__(self, player_stats):
            self._stats = player_stats
            self.saves = 0
            self.saves_held = 0

        def __getattr__(self, name):
            return getattr(self._stats, name)

    def build_stats_for_player(player):
        is_goalkeeper, _ = is_goalkeeper_for_match(match_id, player)
        is_goalkeeper_map[player.id] = is_goalkeeper
        if is_goalkeeper:
            gk_stats = GoalKeeperMatchStats.query.filter_by(match_id=match_id, player_id=player.id).first()
            if not gk_stats:
                gk_stats = GoalKeeperMatchStats(match_id=match_id, player_id=player.id)
                db.session.add(gk_stats)

            player_stats = PlayerMatchStats.query.filter_by(match_id=match_id, player_id=player.id).first()
            if not player_stats:
                player_stats = PlayerMatchStats(match_id=match_id, player_id=player.id)
                db.session.add(player_stats)

            return CombinedGoalkeeperStats(gk_stats, player_stats)

        stats = PlayerMatchStats.query.filter_by(match_id=match_id, player_id=player.id).first()
        if not stats:
            stats = PlayerMatchStats(match_id=match_id, player_id=player.id)
            db.session.add(stats)
        return OutfieldStatsWrapper(stats)
    
    # Define position ordering
    def position_sort_key(player):
        position_order = {
            'GK': 1, 'Goalkeeper': 1,
            'RB': 2, 'CB': 2, 'LB': 2, 'RWB': 2, 'LWB': 2, 'Defender': 2,
            'CDM': 3, 'CM': 3, 'CAM': 3, 'RM': 3, 'LM': 3, 'RW': 3, 'LW': 3, 'Midfielder': 3,
            'ST': 4, 'CF': 4, 'Forward': 4
        }
        return position_order.get(player.position, 5)
    
    # Get all players from both teams with their stats, ordered by position
    home_players = sorted(
        Player.query.filter_by(team_id=match.home_team_id).all(),
        key=position_sort_key
    )
    away_players = sorted(
        Player.query.filter_by(team_id=match.away_team_id).all(),
        key=position_sort_key
    )

    lineup_rows = MatchLineup.query.filter_by(match_id=match_id).all()
    position_by_player_id = {
        lineup.player_id: lineup.position
        for lineup in lineup_rows
        if lineup.position
    }

    main_team_id = match.home_team_id if match.main else match.away_team_id
    main_team_players = home_players if main_team_id == match.home_team_id else away_players
    corner_events = CornerEvent.query.filter_by(match_id=match_id).order_by(CornerEvent.created_at.desc()).all()
    
    # Get or create stats for each player
    home_player_stats = []
    for player in home_players:
        home_player_stats.append(build_stats_for_player(player))
    
    away_player_stats = []
    for player in away_players:
        away_player_stats.append(build_stats_for_player(player))
    
    db.session.commit()
    
    return render_template('match_stats.html', match=match,
                         home_players=home_players, away_players=away_players,
                         home_player_stats=home_player_stats, away_player_stats=away_player_stats,
                         is_goalkeeper_map=is_goalkeeper_map,
                         main_team_players=main_team_players,
                         position_by_player_id=position_by_player_id,
                         corner_events=corner_events)


@app.route('/matches/<int:match_id>/players/<int:player_id>/stats')
def player_match_stats(match_id, player_id):
    """View statistics for a specific player in a match"""
    match = Match.query.get_or_404(match_id)
    player = Player.query.get_or_404(player_id)
    
    # Check if player is a goalkeeper by checking lineup position for this match
    is_goalkeeper, lineup = is_goalkeeper_for_match(match_id, player)
    
    # DEBUG LOGGING
    print(f"\n=== DEBUG player_match_stats ===")
    print(f"Player: {player.name} (ID: {player_id})")
    print(f"Player.position: {player.position}")
    print(f"Lineup found: {lineup is not None}")
    if lineup:
        print(f"Lineup.position: '{lineup.position}'")
    
    if lineup and lineup.position:
        print(f"Checking lineup position: {lineup.position.upper()} == 'GK' = {is_goalkeeper}")
    elif player.position:
        print(f"Checking player position: {player.position.upper()} = {is_goalkeeper}")
    
    print(f"Final is_goalkeeper: {is_goalkeeper}")
    print(f"================================\n")
    
    # If goalkeeper, try to get goalkeeper stats first
    if is_goalkeeper:
        gk_stats = GoalKeeperMatchStats.query.filter_by(match_id=match_id, player_id=player_id).first()
        if gk_stats:
            # Calculate goalkeeper metrics
            total_completed = gk_stats.short_completed_passes + gk_stats.long_completed_passes
            total_incomplete = gk_stats.short_incomplete_passes + gk_stats.long_incomplete_passes
            total_passes = total_completed + total_incomplete
            pass_accuracy = (total_completed / total_passes * 100) if total_passes > 0 else 0
            
            total_duels = gk_stats.duels_won + gk_stats.duels_lost
            duel_success_rate = (gk_stats.duels_won / total_duels * 100) if total_duels > 0 else 0
            
            save_hold_percentage = (gk_stats.saves_held / gk_stats.saves * 100) if gk_stats.saves > 0 else 0
            
            metrics = {
                'total_passes': total_passes,
                'pass_accuracy': pass_accuracy,
                'total_duels': total_duels,
                'duel_success_rate': duel_success_rate,
                'save_hold_percentage': save_hold_percentage
            }
            
            print(f"RENDERING: goalkeeper_match_stats.html (GoalKeeperMatchStats found)")
            return render_template('goalkeeper_match_stats.html', match=match, player=player, stats=gk_stats, metrics=metrics)
        else:
            # Goalkeeper but no GoalKeeperMatchStats - check for PlayerMatchStats
            stats = PlayerMatchStats.query.filter_by(match_id=match_id, player_id=player_id).first()
            if stats:
                # Create a wrapper object that adds saves/saves_held attributes to PlayerMatchStats
                class GKStatsWrapper:
                    def __init__(self, player_stats):
                        self._stats = player_stats
                        # Add goalkeeper-specific fields that don't exist in PlayerMatchStats
                        self.saves = 0
                        self.saves_held = 0
                    
                    def __getattr__(self, name):
                        return getattr(self._stats, name)
                
                wrapped_stats = GKStatsWrapper(stats)
                
                # Calculate goalkeeper metrics
                total_completed = stats.short_completed_passes + stats.long_completed_passes
                total_incomplete = stats.short_incomplete_passes + stats.long_incomplete_passes
                total_passes = total_completed + total_incomplete
                pass_accuracy = (total_completed / total_passes * 100) if total_passes > 0 else 0
                
                total_duels = stats.duels_won + stats.duels_lost
                duel_success_rate = (stats.duels_won / total_duels * 100) if total_duels > 0 else 0
                
                metrics = {
                    'total_passes': total_passes,
                    'pass_accuracy': pass_accuracy,
                    'total_duels': total_duels,
                    'duel_success_rate': duel_success_rate,
                    'save_hold_percentage': 0
                }
                
                print(f"RENDERING: goalkeeper_match_stats.html (PlayerMatchStats wrapped)")
                return render_template('goalkeeper_match_stats.html', match=match, player=player, stats=wrapped_stats, metrics=metrics)
    
    # Get regular player stats
    stats = PlayerMatchStats.query.filter_by(match_id=match_id, player_id=player_id).first_or_404()
    
    # Calculate some useful metrics
    total_completed = stats.short_completed_passes + stats.long_completed_passes
    total_incomplete = stats.short_incomplete_passes + stats.long_incomplete_passes
    total_passes = total_completed + total_incomplete
    pass_accuracy = (total_completed / total_passes * 100) if total_passes > 0 else 0
    
    total_duels = stats.duels_won + stats.duels_lost
    duel_success_rate = (stats.duels_won / total_duels * 100) if total_duels > 0 else 0
    
    total_shots = stats.shots_on_target + stats.shots_off_target
    shot_accuracy = (stats.shots_on_target / total_shots * 100) if total_shots > 0 else 0
    
    metrics = {
        'total_passes': total_passes,
        'pass_accuracy': pass_accuracy,
        'total_duels': total_duels,
        'duel_success_rate': duel_success_rate,
        'total_shots': total_shots,
        'shot_accuracy': shot_accuracy,
        'chances_created': stats.chances_created,
        'big_chances_created': stats.big_chances_created
    }
    
    print(f"RENDERING: player_match_stats.html (regular player)")
    print(f"=== END DEBUG ===\n")
    return render_template('player_match_stats.html', match=match, player=player, stats=stats, metrics=metrics)


@app.route('/matches/<int:match_id>/goalkeepers/<int:player_id>/stats')
def goalkeeper_match_stats(match_id, player_id):
    """View statistics for a specific goalkeeper in a match"""
    match = Match.query.get_or_404(match_id)
    player = Player.query.get_or_404(player_id)
    stats = GoalKeeperMatchStats.query.filter_by(match_id=match_id, player_id=player_id).first_or_404()
    
    # Calculate some useful metrics
    total_completed = stats.short_completed_passes + stats.long_completed_passes
    total_incomplete = stats.short_incomplete_passes + stats.long_incomplete_passes
    total_passes = total_completed + total_incomplete
    pass_accuracy = (total_completed / total_passes * 100) if total_passes > 0 else 0
    
    total_duels = stats.duels_won + stats.duels_lost
    duel_success_rate = (stats.duels_won / total_duels * 100) if total_duels > 0 else 0
    
    # Goalkeeper specific metrics
    save_hold_percentage = (stats.saves_held / stats.saves * 100) if stats.saves > 0 else 0
    
    metrics = {
        'total_passes': total_passes,
        'pass_accuracy': pass_accuracy,
        'total_duels': total_duels,
        'duel_success_rate': duel_success_rate,
        'save_hold_percentage': save_hold_percentage
    }
    
    return render_template('goalkeeper_match_stats.html', match=match, player=player, stats=stats, metrics=metrics)


@app.route('/matches/<int:match_id>/spreadsheet')
def match_spreadsheet(match_id):
    """View match statistics in spreadsheet format with team aggregates"""
    match, home_data, home_aggregates, away_data, away_aggregates = build_match_spreadsheet_payload(match_id)

    return render_template('match_spreadsheet.html', match=match,
                         home_data=home_data, home_aggregates=home_aggregates,
                         away_data=away_data, away_aggregates=away_aggregates)


def build_match_spreadsheet_payload(match_id):
    match = Match.query.get_or_404(match_id)

    xa_rows = db.session.query(
        ShotEvent.assist_player_id,
        func.coalesce(func.sum(ShotEvent.xG), 0.0)
    ).filter(
        ShotEvent.match_id == match_id,
        ShotEvent.assist_player_id.isnot(None)
    ).group_by(ShotEvent.assist_player_id).all()
    xa_by_player = {player_id: float(total_xa or 0) for player_id, total_xa in xa_rows}

    def position_sort_key(player):
        position_order = {
            'GK': 1, 'Goalkeeper': 1,
            'RB': 2, 'CB': 2, 'LB': 2, 'RWB': 2, 'LWB': 2, 'Defender': 2,
            'CDM': 3, 'CM': 3, 'CAM': 3, 'RM': 3, 'LM': 3, 'RW': 3, 'LW': 3, 'Midfielder': 3,
            'ST': 4, 'CF': 4, 'Forward': 4
        }
        return position_order.get(player.position, 5)

    home_players = sorted(
        Player.query.filter_by(team_id=match.home_team_id).all(),
        key=position_sort_key
    )
    away_players = sorted(
        Player.query.filter_by(team_id=match.away_team_id).all(),
        key=position_sort_key
    )

    base_aggregates = {
        'short_completed_passes': 0,
        'short_incomplete_passes': 0,
        'long_completed_passes': 0,
        'long_incomplete_passes': 0,
        'pack_passes': 0,
        'pack_pass_score': 0,
        'pack_pass_receive_score': 0,
        'pack_turnovers': 0,
        'pack_turnover_score': 0,
        'duels_won': 0,
        'duels_lost': 0,
        'aerial_duels_won': 0,
        'aerial_duels_lost': 0,
        'ground_duels_won': 0,
        'ground_duels_lost': 0,
        'xA': 0.0,
        'assists': 0,
        'chances_created': 0,
        'big_chances_created': 0,
        'xG': 0,
        'goals': 0,
        'shots_on_target': 0,
        'shots_off_target': 0,
        'shots_blocked': 0,
        'shots_inside_box': 0,
        'shots_outside_box': 0,
        'xG_inside_box': 0,
        'xG_outside_box': 0,
        'tackles_won': 0,
        'tackles_lost': 0,
        'interceptions': 0,
        'clearances': 0,
        'pressures': 0,
        'fouls_committed': 0,
        'fouls_won': 0,
        'offsides': 0,
        'progressive_runs': 0,
        'touches_in_opposition_box': 0
    }

    def build_team_data(players):
        team_data = []
        team_aggregates = dict(base_aggregates)

        for player in players:
            stats = PlayerMatchStats.query.filter_by(match_id=match_id, player_id=player.id).first()
            if not stats:
                continue

            player_xa = float(xa_by_player.get(player.id, 0) or 0)
            team_data.append({
                'player': player,
                'stats': stats,
                'xA': player_xa
            })

            for key in team_aggregates:
                if key == 'xA':
                    team_aggregates[key] += player_xa
                else:
                    team_aggregates[key] += (getattr(stats, key, 0) or 0)

        return team_data, team_aggregates

    home_data, home_aggregates = build_team_data(home_players)
    away_data, away_aggregates = build_team_data(away_players)

    return match, home_data, home_aggregates, away_data, away_aggregates


def build_match_team_summary_payload(match_id):
    match = Match.query.get_or_404(match_id)

    lineup_rows = MatchLineup.query.filter_by(match_id=match_id).all()
    lineup_position_by_player = {
        row.player_id: (row.position.upper() if row.position else '')
        for row in lineup_rows
    }
    lineup_team_by_player = {
        row.player_id: row.team_id
        for row in lineup_rows
        if row.team_id
    }

    player_stats_rows = PlayerMatchStats.query.filter_by(match_id=match_id).all()
    gk_stats_rows = GoalKeeperMatchStats.query.filter_by(match_id=match_id).all()

    player_stats_by_player = {row.player_id: row for row in player_stats_rows}
    gk_stats_by_player = {row.player_id: row for row in gk_stats_rows}

    player_ids = {
        row.player_id for row in lineup_rows if row.player_id
    }
    player_ids.update(row.player_id for row in player_stats_rows if row.player_id)
    player_ids.update(row.player_id for row in gk_stats_rows if row.player_id)

    players = Player.query.filter(Player.id.in_(player_ids)).all() if player_ids else []

    def is_goalkeeper(player):
        lineup_position = lineup_position_by_player.get(player.id)
        if lineup_position:
            return lineup_position == 'GK'
        return bool(player.position and player.position.upper() in ('GK', 'GOALKEEPER'))

    totals = {
        match.home_team_id: {
            'completed_passes': 0,
            'xg': 0.0,
            'non_penalty_xg': 0.0,
            'goals': 0,
            'shots_on_target': 0,
            'shots_off_target': 0,
            'shots_blocked': 0,
            'total_shots': 0,
            'shots_inside_box': 0,
            'shots_outside_box': 0,
            'chances_created': 0,
            'team_pacing_score': 0,
            'goalkeeper_saves': 0
        },
        match.away_team_id: {
            'completed_passes': 0,
            'xg': 0.0,
            'non_penalty_xg': 0.0,
            'goals': 0,
            'shots_on_target': 0,
            'shots_off_target': 0,
            'shots_blocked': 0,
            'total_shots': 0,
            'shots_inside_box': 0,
            'shots_outside_box': 0,
            'chances_created': 0,
            'team_pacing_score': 0,
            'goalkeeper_saves': 0
        }
    }

    for player in players:
        team_id = lineup_team_by_player.get(player.id) or player.team_id
        team_totals = totals.get(team_id)
        if not team_totals:
            continue

        outfield_stats = player_stats_by_player.get(player.id)
        goalkeeper_stats = gk_stats_by_player.get(player.id)

        passing_stats = outfield_stats
        if is_goalkeeper(player) and goalkeeper_stats:
            passing_stats = goalkeeper_stats

        if passing_stats:
            team_totals['completed_passes'] += int(
                (passing_stats.short_completed_passes or 0) +
                (passing_stats.long_completed_passes or 0) +
                (passing_stats.pack_passes or 0)
            )
            team_totals['team_pacing_score'] += int(passing_stats.pack_pass_score or 0)

        if outfield_stats:
            team_totals['goals'] += int(outfield_stats.goals or 0)
            team_totals['shots_on_target'] += int(outfield_stats.shots_on_target or 0)
            team_totals['shots_off_target'] += int(outfield_stats.shots_off_target or 0)
            team_totals['shots_blocked'] += int(outfield_stats.shots_blocked or 0)
            team_totals['total_shots'] += int((outfield_stats.shots_on_target or 0) + (outfield_stats.shots_off_target or 0) + (outfield_stats.shots_blocked or 0))
            team_totals['shots_inside_box'] += int(outfield_stats.shots_inside_box or 0)
            team_totals['shots_outside_box'] += int(outfield_stats.shots_outside_box or 0)
            team_totals['chances_created'] += int(outfield_stats.chances_created or 0)

        if goalkeeper_stats:
            team_totals['goalkeeper_saves'] += int((goalkeeper_stats.saves or 0) + (goalkeeper_stats.saves_held or 0))

    shot_events = ShotEvent.query.filter_by(match_id=match_id).all()
    for shot_event in shot_events:
        team_totals = totals.get(shot_event.team_id)
        if not team_totals:
            continue

        team_totals['xg'] += float(shot_event.xG or 0)

        if not shot_event.penalty:
            team_totals['non_penalty_xg'] += float(shot_event.xG or 0)

    goal_totals = get_match_goal_totals(match)
    totals[match.home_team_id]['goals'] = goal_totals[match.home_team_id]
    totals[match.away_team_id]['goals'] = goal_totals[match.away_team_id]

    def safe_pct(numerator, denominator):
        if denominator <= 0:
            return 0.0
        return (numerator / denominator) * 100

    home_totals = totals[match.home_team_id]
    away_totals = totals[match.away_team_id]

    summary_rows = [
        {
            'metric': 'Completed Passes',
            'home_value': totals[match.home_team_id]['completed_passes'],
            'away_value': totals[match.away_team_id]['completed_passes'],
            'value_type': 'int'
        },
        {
            'metric': 'xG',
            'home_value': totals[match.home_team_id]['xg'],
            'away_value': totals[match.away_team_id]['xg'],
            'value_type': 'float'
        },
        {
            'metric': 'Total Shots',
            'home_value': totals[match.home_team_id]['total_shots'],
            'away_value': totals[match.away_team_id]['total_shots'],
            'value_type': 'int'
        },
        {
            'metric': 'Chances Created',
            'home_value': totals[match.home_team_id]['chances_created'],
            'away_value': totals[match.away_team_id]['chances_created'],
            'value_type': 'int'
        },
        {
            'metric': 'Team Packing Score',
            'home_value': totals[match.home_team_id]['team_pacing_score'],
            'away_value': totals[match.away_team_id]['team_pacing_score'],
            'value_type': 'int'
        },
        {
            'metric': 'Goalkeeper Saves',
            'home_value': totals[match.home_team_id]['goalkeeper_saves'],
            'away_value': totals[match.away_team_id]['goalkeeper_saves'],
            'value_type': 'int'
        }
    ]

    goal_threat_rows = [
        {
            'metric': 'Goals',
            'home_value': home_totals['goals'],
            'away_value': away_totals['goals'],
            'value_type': 'int'
        },
        {
            'metric': 'xG',
            'home_value': home_totals['xg'],
            'away_value': away_totals['xg'],
            'value_type': 'float'
        },
        {
            'metric': 'Non Penalty xG',
            'home_value': home_totals['non_penalty_xg'],
            'away_value': away_totals['non_penalty_xg'],
            'value_type': 'float'
        },
        {
            'metric': 'Shots on Target Ratio',
            'home_value': safe_pct(home_totals['shots_on_target'], home_totals['shots_on_target'] + away_totals['shots_on_target']),
            'away_value': safe_pct(away_totals['shots_on_target'], home_totals['shots_on_target'] + away_totals['shots_on_target']),
            'value_type': 'pct'
        },
        {
            'metric': 'Shots on Target',
            'home_value': home_totals['shots_on_target'],
            'away_value': away_totals['shots_on_target'],
            'value_type': 'int'
        },
        {
            'metric': 'Shots off Target',
            'home_value': home_totals['shots_off_target'],
            'away_value': away_totals['shots_off_target'],
            'value_type': 'int'
        },
        {
            'metric': 'Shots Blocked',
            'home_value': home_totals['shots_blocked'],
            'away_value': away_totals['shots_blocked'],
            'value_type': 'int'
        },
        {
            'metric': 'Total Shot Accuracy',
            'home_value': safe_pct(home_totals['shots_on_target'], home_totals['total_shots']),
            'away_value': safe_pct(away_totals['shots_on_target'], away_totals['total_shots']),
            'value_type': 'pct'
        },
        {
            'metric': 'On Target Conversion Ratio',
            'home_value': safe_pct(home_totals['goals'], home_totals['shots_on_target']),
            'away_value': safe_pct(away_totals['goals'], away_totals['shots_on_target']),
            'value_type': 'pct'
        },
        {
            'metric': 'All Shot Conversion Ratio',
            'home_value': safe_pct(home_totals['goals'], home_totals['total_shots']),
            'away_value': safe_pct(away_totals['goals'], away_totals['total_shots']),
            'value_type': 'pct'
        },
        {
            'metric': 'Shots Inside Box',
            'home_value': home_totals['shots_inside_box'],
            'away_value': away_totals['shots_inside_box'],
            'value_type': 'int'
        },
        {
            'metric': 'Shots Outside Box',
            'home_value': home_totals['shots_outside_box'],
            'away_value': away_totals['shots_outside_box'],
            'value_type': 'int'
        }
    ]

    return match, summary_rows, goal_threat_rows


@app.route('/matches/<int:match_id>/summary/export.pdf')
def export_match_team_summary_pdf(match_id):
    """Export key team summary metrics as a PDF."""
    match, summary_rows, goal_threat_rows = build_match_team_summary_payload(match_id)

    return build_match_summary_pdf_response(
        match,
        summary_rows,
        goal_threat_rows,
        'match_summary',
        summary_heading='Match Summary'
    )


@app.route('/matches/<int:match_id>/shot-summary/export.pdf')
def export_match_shot_summary_pdf(match_id):
    """Export a shot-focused team summary as a PDF."""
    match, summary_rows, goal_threat_rows = build_match_team_summary_payload(match_id)
    shot_summary_rows = [
        row for row in summary_rows
        if row['metric'] not in {'Completed Passes', 'Team Packing Score'}
    ]
    _, _, player_rows, _ = build_player_match_summary_payload(match_id)

    return build_match_summary_pdf_response(
        match,
        shot_summary_rows,
        goal_threat_rows,
        'shot_summary',
        summary_heading='Shot Summary',
        player_rows=player_rows
    )


def build_player_match_summary_payload(match_id):
    match = Match.query.get_or_404(match_id)

    main_team_id = match.home_team_id if match.main else match.away_team_id
    main_team_name = match.home_team.name if match.main else match.away_team.name

    lineup_rows = MatchLineup.query.filter_by(match_id=match_id, team_id=main_team_id).all()
    lineup_position_by_player = {
        row.player_id: (row.position or '').upper()
        for row in lineup_rows
    }

    all_match_events = MatchEvent.query.filter_by(match_id=match_id).all()

    sub_on_player_ids = {
        event.player_id
        for event in all_match_events
        if event.event_type == 'substitute_on' and event.player_id
    }

    played_player_ids = set(lineup_position_by_player.keys()) | sub_on_player_ids
    if not played_player_ids:
        return match, main_team_name, [], []

    players = Player.query.filter(
        Player.team_id == main_team_id,
        Player.id.in_(played_player_ids)
    ).all()

    players_by_id = {player.id: player for player in players}

    def to_int_minute(value):
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    veo_events = {}
    all_event_minutes = []
    sub_off_minutes = {}
    sub_on_minutes = {}

    for event in all_match_events:
        minute_value = to_int_minute(event.minute)
        if minute_value is not None and minute_value >= 0:
            all_event_minutes.append(minute_value)

        if event.event_type.startswith('veo_') and minute_value is not None:
            veo_events[event.event_type] = minute_value

        if event.event_type == 'substitute_off' and event.player_id and minute_value is not None:
            player = players_by_id.get(event.player_id)
            if player and get_team_id_for_match(match_id, player) == main_team_id:
                sub_off_minutes[event.player_id] = minute_value

        if event.event_type == 'substitute_on' and event.player_id and minute_value is not None:
            player = players_by_id.get(event.player_id)
            if player and get_team_id_for_match(match_id, player) == main_team_id:
                sub_on_minutes[event.player_id] = minute_value

    total_match_minutes = None
    if all(k in veo_events for k in ['veo_1st_half_start', 'veo_1st_half_stop', 'veo_2nd_half_start', 'veo_2nd_half_stop']):
        first_half = veo_events['veo_1st_half_stop'] - veo_events['veo_1st_half_start']
        second_half = veo_events['veo_2nd_half_stop'] - veo_events['veo_2nd_half_start']
        total_match_minutes = max(0, first_half + second_half)
    elif all_event_minutes:
        total_match_minutes = max(all_event_minutes)

    minutes_rows = []

    for player in players:
        if player.id in lineup_position_by_player:
            minutes_played = sub_off_minutes.get(player.id, total_match_minutes or 0)
        elif player.id in sub_on_minutes:
            match_total = total_match_minutes or 0
            minutes_played = max(0, match_total - sub_on_minutes[player.id])
        else:
            minutes_played = 0

        if minutes_played > 0:
            minutes_rows.append({
                'player_name': player.name,
                'minutes_played': int(minutes_played)
            })

    minutes_rows.sort(key=lambda row: (-row['minutes_played'], row['player_name'].lower()))

    def position_sort_bucket(position_value):
        normalized = (position_value or '').strip().upper()
        if normalized in ('GK', 'GOALKEEPER'):
            return 0
        if normalized in {'RB', 'RWB', 'LB', 'LWB', 'CB', 'LCB', 'RCB', 'SW', 'SWEEPER'}:
            return 1
        if normalized in {'CDM', 'LDM', 'RDM', 'CM', 'LCM', 'RCM', 'CAM', 'LAM', 'RAM', 'LM', 'RM'}:
            return 2
        if normalized in {'LW', 'RW', 'LF', 'RF', 'SS', 'CF', 'ST', 'FORWARD', 'ATTACKER', 'STRIKER', 'WINGER'}:
            return 3
        if 'BACK' in normalized or normalized.startswith('CB'):
            return 1
        if normalized.endswith('DM') or normalized.endswith('CM') or normalized.endswith('AM') or normalized in {'MIDFIELD', 'MIDFIELDER'}:
            return 2
        return 3

    def player_position_for_sort(player):
        lineup_position = lineup_position_by_player.get(player.id)
        if lineup_position:
            return lineup_position
        return player.position or ''

    players.sort(key=lambda player: (position_sort_bucket(player_position_for_sort(player)), player.name.lower()))

    player_ids = [player.id for player in players]

    stats_rows = PlayerMatchStats.query.filter(
        PlayerMatchStats.match_id == match_id,
        PlayerMatchStats.player_id.in_(player_ids)
    ).all() if player_ids else []
    stats_by_player = {row.player_id: row for row in stats_rows}

    gk_stats_rows = GoalKeeperMatchStats.query.filter(
        GoalKeeperMatchStats.match_id == match_id,
        GoalKeeperMatchStats.player_id.in_(player_ids)
    ).all() if player_ids else []
    gk_stats_by_player = {row.player_id: row for row in gk_stats_rows}

    xa_rows = db.session.query(
        ShotEvent.assist_player_id,
        func.coalesce(func.sum(ShotEvent.xG), 0.0)
    ).filter(
        ShotEvent.match_id == match_id,
        ShotEvent.assist_player_id.isnot(None)
    ).group_by(ShotEvent.assist_player_id).all()
    xa_by_player = {player_id: float(total_xa or 0) for player_id, total_xa in xa_rows}

    big_chance_rows = db.session.query(
        ShotEvent.player_id,
        func.count(ShotEvent.id)
    ).filter(
        ShotEvent.match_id == match_id,
        ShotEvent.big_chance.is_(True)
    ).group_by(ShotEvent.player_id).all()
    big_chances_by_player = {player_id: int(total or 0) for player_id, total in big_chance_rows}

    big_chances_created_rows = db.session.query(
        ShotEvent.assist_player_id,
        func.count(ShotEvent.id)
    ).filter(
        ShotEvent.match_id == match_id,
        ShotEvent.assist_player_id.isnot(None),
        ShotEvent.big_chance.is_(True)
    ).group_by(ShotEvent.assist_player_id).all()
    big_chances_created_by_player = {
        player_id: int(total or 0)
        for player_id, total in big_chances_created_rows
    }

    chances_created_rows = db.session.query(
        ShotEvent.assist_player_id,
        func.count(ShotEvent.id)
    ).filter(
        ShotEvent.match_id == match_id,
        ShotEvent.assist_player_id.isnot(None)
    ).group_by(ShotEvent.assist_player_id).all()
    chances_created_by_player = {
        player_id: int(total or 0)
        for player_id, total in chances_created_rows
    }

    pack_receive_rows = db.session.query(
        PackPassEvent.receiver_id,
        func.count(PackPassEvent.id)
    ).filter(
        PackPassEvent.match_id == match_id,
        PackPassEvent.receiver_id.isnot(None)
    ).group_by(PackPassEvent.receiver_id).all()
    pack_receives_by_player = {player_id: int(total or 0) for player_id, total in pack_receive_rows}

    rows = []
    for player in players:
        stats = stats_by_player.get(player.id)
        gk_stats = gk_stats_by_player.get(player.id)

        lineup_position = (lineup_position_by_player.get(player.id) or '').upper()
        is_goalkeeper = lineup_position == 'GK' or (not lineup_position and bool(player.position and player.position.upper() in ('GK', 'GOALKEEPER')))
        passing_stats = gk_stats if (is_goalkeeper and gk_stats) else stats

        rows.append({
            'player_name': player.name,
            'goals': int(getattr(stats, 'goals', 0) or 0),
            'assists': int(getattr(stats, 'assists', 0) or 0),
            'big_chances': int(big_chances_by_player.get(player.id, 0) or 0),
            'big_chances_created': int(big_chances_created_by_player.get(player.id, 0) or 0),
            'chances_created': int(chances_created_by_player.get(player.id, 0) or 0),
            'shots_on_target': int(getattr(stats, 'shots_on_target', 0) or 0),
            'shots_off_target': int(getattr(stats, 'shots_off_target', 0) or 0),
            'shots_blocked': int(getattr(stats, 'shots_blocked', 0) or 0),
            'shots_in_box': int(getattr(stats, 'shots_inside_box', 0) or 0),
            'shots_outside_box': int(getattr(stats, 'shots_outside_box', 0) or 0),
            'posession_in_box': int(getattr(stats, 'touches_in_opposition_box', 0) or 0),
            'progressive_runs': int(getattr(stats, 'progressive_runs', 0) or 0),
            'short_completed_passes': int(getattr(passing_stats, 'short_completed_passes', 0) or 0),
            'long_completed_passes': int(getattr(passing_stats, 'long_completed_passes', 0) or 0),
            'short_incomplete_passes': int(getattr(passing_stats, 'short_incomplete_passes', 0) or 0),
            'long_incomplete_passes': int(getattr(passing_stats, 'long_incomplete_passes', 0) or 0),
            'pack_passes': int(getattr(passing_stats, 'pack_passes', 0) or 0),
            'pack_pass_score': int(getattr(passing_stats, 'pack_pass_score', 0) or 0),
            'pack_dribbles': int(getattr(passing_stats, 'pack_dribbles', 0) or 0),
            'pack_dribble_score': int(getattr(passing_stats, 'pack_dribble_score', 0) or 0),
            'pack_turnovers': int(getattr(passing_stats, 'pack_turnovers', 0) or 0),
            'pack_turnover_score': int(getattr(passing_stats, 'pack_turnover_score', 0) or 0),
            'pack_recieves': int(pack_receives_by_player.get(player.id, 0) or 0),
            'pack_recieves_score': int(getattr(passing_stats, 'pack_pass_receive_score', 0) or 0),
            'xg': float(getattr(stats, 'xG', 0.0) or 0.0),
            'xa': float(xa_by_player.get(player.id, 0.0) or 0.0),
            'dribbled_past': int(getattr(passing_stats, 'pack_dribbled_past', 0) or 0),
            'ground_duels_won': int(getattr(passing_stats, 'ground_duels_won', 0) or 0),
            'ground_duels_lost': int(getattr(passing_stats, 'ground_duels_lost', 0) or 0),
            'aerial_duels_won': int(getattr(passing_stats, 'aerial_duels_won', 0) or 0),
            'aerial_duels_lost': int(getattr(passing_stats, 'aerial_duels_lost', 0) or 0),
            'tackles_won': int(getattr(passing_stats, 'tackles_won', 0) or 0),
            'recoveries': int(getattr(passing_stats, 'recoveries', 0) or 0),
            'clearances': int(getattr(passing_stats, 'clearances', 0) or 0),
            'pressures': int(getattr(stats, 'pressures', 0) or 0)
        })

    return match, main_team_name, rows, minutes_rows


@app.route('/matches/<int:match_id>/players-summary/export.pdf')
def export_player_match_summary_pdf(match_id):
    """Export player match summary metrics as a PDF."""
    match, main_team_name, player_rows, _minutes_rows = build_player_match_summary_payload(match_id)

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=28,
        rightMargin=28,
        topMargin=24,
        bottomMargin=24
    )
    styles = getSampleStyleSheet()
    header_cell_style = ParagraphStyle(
        'PlayerSummaryHeaderCell',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7,
        leading=8,
        textColor=colors.whitesmoke,
        alignment=1,
        wordWrap='LTR',
        splitLongWords=False
    )
    body_cell_style = ParagraphStyle(
        'PlayerSummaryBodyCell',
        parent=styles['Normal'],
        fontSize=7,
        leading=8,
        alignment=1,
        wordWrap='LTR',
        splitLongWords=False
    )
    player_name_cell_style = ParagraphStyle(
        'PlayerSummaryPlayerNameCell',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7,
        leading=8,
        alignment=0,
        wordWrap='LTR',
        splitLongWords=False
    )
    elements = []

    elements.append(KeepTogether([
        Paragraph(f"Player Match Summary — {main_team_name}", styles['Title']),
        Paragraph(match.match_date.strftime('%Y-%m-%d %H:%M'), styles['Normal']),
        Paragraph(f"Match: {match.home_team.name} vs {match.away_team.name} | Score: {match.home_score} - {match.away_score}", styles['Normal'])
    ]))
    elements.append(Spacer(1, 10))

    table_data = [[
        Paragraph('Player', header_cell_style),
        Paragraph('Goals', header_cell_style),
        Paragraph('Assists', header_cell_style),
        Paragraph('Big Chances', header_cell_style),
        Paragraph('Big Chances Created', header_cell_style),
        Paragraph('Chances Created', header_cell_style),
        Paragraph('Shots On Target', header_cell_style),
        Paragraph('Shots Off Target', header_cell_style),
        Paragraph('Shots Blocked', header_cell_style),
        Paragraph('Shots In Box', header_cell_style),
        Paragraph('Shots Outside Box', header_cell_style),
        Paragraph('Touches in Box', header_cell_style),
        Paragraph('Progressive Runs', header_cell_style),
        Paragraph('Pack Recieves', header_cell_style),
        Paragraph('Pack Recieves Score', header_cell_style),
        Paragraph('xG', header_cell_style),
        Paragraph('xA', header_cell_style),
        Paragraph('xGC', header_cell_style)
    ]]

    for row in player_rows:
        xgc = (row['xg'] or 0.0) + (row['xa'] or 0.0)
        table_data.append([
            Paragraph(row['player_name'], player_name_cell_style),
            Paragraph(str(row['goals']), body_cell_style),
            Paragraph(str(row['assists']), body_cell_style),
            Paragraph(str(row['big_chances']), body_cell_style),
            Paragraph(str(row['big_chances_created']), body_cell_style),
            Paragraph(str(row['chances_created']), body_cell_style),
            Paragraph(str(row['shots_on_target']), body_cell_style),
            Paragraph(str(row['shots_off_target']), body_cell_style),
            Paragraph(str(row['shots_blocked']), body_cell_style),
            Paragraph(str(row['shots_in_box']), body_cell_style),
            Paragraph(str(row['shots_outside_box']), body_cell_style),
            Paragraph(str(row['posession_in_box']), body_cell_style),
            Paragraph(str(row['progressive_runs']), body_cell_style),
            Paragraph(str(row['pack_recieves']), body_cell_style),
            Paragraph(str(row['pack_recieves_score']), body_cell_style),
            Paragraph(f"{row['xg']:.2f}", body_cell_style),
            Paragraph(f"{row['xa']:.2f}", body_cell_style),
            Paragraph(f"{xgc:.2f}", body_cell_style)
        ])

    player_table = Table(
        table_data,
        colWidths=[52, 30, 32, 40, 48, 44, 40, 40, 40, 40, 44, 44, 48, 40, 48, 28, 28, 30],
        repeatRows=1
    )
    player_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
    ]))

    elements.append(KeepTogether([
        Paragraph("Attacking", styles['Heading2']),
        player_table
    ]))

    elements.append(Spacer(1, 12))

    possession_header_cell_style = ParagraphStyle(
        'PlayerSummaryPossessionHeaderCell',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=9,
        textColor=colors.whitesmoke,
        alignment=1,
        wordWrap='LTR',
        splitLongWords=False
    )
    possession_body_cell_style = ParagraphStyle(
        'PlayerSummaryPossessionBodyCell',
        parent=styles['Normal'],
        fontSize=8,
        leading=9,
        alignment=1,
        wordWrap='LTR',
        splitLongWords=False
    )
    possession_player_name_cell_style = ParagraphStyle(
        'PlayerSummaryPossessionPlayerNameCell',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=9,
        alignment=0,
        wordWrap='LTR',
        splitLongWords=False
    )

    possession_table_data = [[
        Paragraph('Player', possession_header_cell_style),
        Paragraph('Passes Completed', possession_header_cell_style),
        Paragraph('Pass Complete %', possession_header_cell_style),
        Paragraph('% Pack Passes', possession_header_cell_style),
        Paragraph('Pack Passes', possession_header_cell_style),
        Paragraph('Pack Pass Score', possession_header_cell_style),
        Paragraph('Pack Dribbles', possession_header_cell_style),
        Paragraph('Pack Dribble Score', possession_header_cell_style),
        Paragraph('Pack Turnovers', possession_header_cell_style),
        Paragraph('Pack Turnover Score', possession_header_cell_style)
    ]]

    for row in player_rows:
        passes_completed = row['short_completed_passes'] + row['long_completed_passes'] + row['pack_passes']
        pass_attempts = passes_completed + row['short_incomplete_passes'] + row['long_incomplete_passes']
        pass_complete_pct = ((passes_completed / pass_attempts) * 100) if pass_attempts > 0 else 0.0
        pack_pass_pct = ((row['pack_passes'] / pass_attempts) * 100) if pass_attempts > 0 else 0.0

        possession_table_data.append([
            Paragraph(row['player_name'], possession_player_name_cell_style),
            Paragraph(str(passes_completed), possession_body_cell_style),
            Paragraph(f"{pass_complete_pct:.1f}%", possession_body_cell_style),
            Paragraph(f"{pack_pass_pct:.1f}%", possession_body_cell_style),
            Paragraph(str(row['pack_passes']), possession_body_cell_style),
            Paragraph(str(row['pack_pass_score']), possession_body_cell_style),
            Paragraph(str(row['pack_dribbles']), possession_body_cell_style),
            Paragraph(str(row['pack_dribble_score']), possession_body_cell_style),
            Paragraph(str(row['pack_turnovers']), possession_body_cell_style),
            Paragraph(str(row['pack_turnover_score']), possession_body_cell_style),
        ])

    possession_table = Table(
        possession_table_data,
        colWidths=[88, 56, 52, 52, 48, 56, 56, 62, 56, 64],
        repeatRows=1
    )
    possession_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
    ]))

    elements.append(KeepTogether([
        Paragraph("Possession", styles['Heading2']),
        possession_table
    ]))

    elements.append(Spacer(1, 12))

    defensive_header_cell_style = ParagraphStyle(
        'PlayerSummaryDefensiveHeaderCell',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=9,
        textColor=colors.whitesmoke,
        alignment=1,
        wordWrap='LTR',
        splitLongWords=False
    )
    defensive_body_cell_style = ParagraphStyle(
        'PlayerSummaryDefensiveBodyCell',
        parent=styles['Normal'],
        fontSize=8,
        leading=9,
        alignment=1,
        wordWrap='LTR',
        splitLongWords=False
    )
    defensive_player_name_cell_style = ParagraphStyle(
        'PlayerSummaryDefensivePlayerNameCell',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=9,
        alignment=0,
        wordWrap='LTR',
        splitLongWords=False
    )

    defensive_table_data = [[
        Paragraph('Player', defensive_header_cell_style),
        Paragraph('Ground Duels Won', defensive_header_cell_style),
        Paragraph('Ground Duels Lost', defensive_header_cell_style),
        Paragraph('Aerial Duels Won', defensive_header_cell_style),
        Paragraph('Aerial Duels Lost', defensive_header_cell_style),
        Paragraph('Dribbled Passed', defensive_header_cell_style),
        Paragraph('Tackles Won', defensive_header_cell_style),
        Paragraph('Recoveries', defensive_header_cell_style),
        Paragraph('Clearances', defensive_header_cell_style),
        Paragraph('Pressures', defensive_header_cell_style)
    ]]

    for row in player_rows:
        defensive_table_data.append([
            Paragraph(row['player_name'], defensive_player_name_cell_style),
            Paragraph(str(row['ground_duels_won']), defensive_body_cell_style),
            Paragraph(str(row['ground_duels_lost']), defensive_body_cell_style),
            Paragraph(str(row['aerial_duels_won']), defensive_body_cell_style),
            Paragraph(str(row['aerial_duels_lost']), defensive_body_cell_style),
            Paragraph(str(row['dribbled_past']), defensive_body_cell_style),
            Paragraph(str(row['tackles_won']), defensive_body_cell_style),
            Paragraph(str(row['recoveries']), defensive_body_cell_style),
            Paragraph(str(row['clearances']), defensive_body_cell_style),
            Paragraph(str(row['pressures']), defensive_body_cell_style),
        ])

    defensive_table = Table(
        defensive_table_data,
        colWidths=[90, 56, 56, 56, 56, 60, 56, 56, 56, 52],
        repeatRows=1
    )
    defensive_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
    ]))

    elements.append(KeepTogether([
        Paragraph("Defensive", styles['Heading2']),
        defensive_table
    ]))
    # Minutes Played table temporarily disabled while minutes logic is reviewed.
    
    # Add Metric Definitions page
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("Metric Definitions", styles['Heading1']))
    elements.append(Spacer(1, 12))
    
    # Read and parse the METRIC-DEFINITIONS.md file
    import os
    metrics_file = os.path.join(os.path.dirname(__file__), 'METRIC-DEFINITIONS.md')
    try:
        with open(metrics_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Skip the title line and process the rest
        for line in lines[1:]:
            line = line.rstrip('\n')
            if not line.strip():
                continue
            
            # Check indentation to determine formatting
            if line.startswith('    - '):
                # Sub-bullet (indented)
                text = line[6:].strip()
                # Replace bold markers for ReportLab
                text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
                elements.append(Paragraph(f"• {text}", ParagraphStyle(
                    'MetricSubBullet',
                    parent=styles['Normal'],
                    fontSize=9,
                    leftIndent=30,
                    leading=11,
                    spaceAfter=6
                )))
            elif line.startswith('- '):
                # Main bullet
                text = line[2:].strip()
                # Replace bold markers for ReportLab
                text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
                elements.append(Paragraph(text, ParagraphStyle(
                    'MetricBullet',
                    parent=styles['Normal'],
                    fontSize=9,
                    leftIndent=12,
                    leading=12,
                    spaceAfter=8
                )))
    except Exception as e:
        elements.append(Paragraph(f"Error loading metric definitions: {str(e)}", styles['Normal']))
    
    document.build(elements)

    pdf_bytes = buffer.getvalue()
    buffer.close()

    filename = build_summary_export_filename(match, 'player_summary')
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route('/matches/<int:match_id>/spreadsheet/export.csv')
def export_match_spreadsheet_csv(match_id):
    """Export spreadsheet statistics as CSV."""
    match, home_data, home_aggregates, away_data, away_aggregates = build_match_spreadsheet_payload(match_id)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        'team', 'player_name', 'jersey',
        'short_completed', 'short_incomplete', 'short_completion_pct',
        'long_completed', 'long_incomplete', 'long_completion_pct',
        'pack_passes', 'pack_pass_score', 'overall_pass_pct', 'pack_receive_score', 'pack_turnovers', 'pack_turnover_score',
        'shots_on_target', 'shots_off_target', 'shots_blocked',
        'xA', 'assists', 'chances_created', 'big_chances_created', 'xG', 'goals',
        'aerial_duels_won', 'aerial_duels_lost', 'ground_duels_won', 'ground_duels_lost',
        'tackles_won', 'interceptions', 'clearances', 'pressures',
        'fouls_committed', 'fouls_won', 'offsides', 'progressive_runs', 'touches_in_opposition_box'
    ])

    def pct(completed, incomplete):
        attempts = completed + incomplete
        return round((completed / attempts) * 100, 1) if attempts > 0 else ''

    def overall_pct(stats):
        total_completed = (stats.pack_passes or 0) + (stats.short_completed_passes or 0) + (stats.long_completed_passes or 0)
        total_attempts = total_completed + (stats.short_incomplete_passes or 0) + (stats.long_incomplete_passes or 0)
        return round((total_completed / total_attempts) * 100, 1) if total_attempts > 0 else ''

    def write_team_rows(team_name, rows, aggregates):
        for row in rows:
            stats = row['stats']
            is_goalkeeper = bool(row['player'].position and row['player'].position.upper() in ['GK', 'GOALKEEPER'])
            writer.writerow([
                team_name,
                row['player'].name,
                row['player'].jersey_number or '-',
                stats.short_completed_passes,
                stats.short_incomplete_passes,
                pct(stats.short_completed_passes or 0, stats.short_incomplete_passes or 0),
                stats.long_completed_passes,
                stats.long_incomplete_passes,
                pct(stats.long_completed_passes or 0, stats.long_incomplete_passes or 0),
                stats.pack_passes,
                stats.pack_pass_score,
                overall_pct(stats),
                stats.pack_pass_receive_score,
                stats.pack_turnovers,
                stats.pack_turnover_score,
                stats.shots_on_target,
                stats.shots_off_target,
                stats.shots_blocked,
                round(row['xA'] or 0, 2),
                stats.assists,
                stats.chances_created,
                stats.big_chances_created,
                round(stats.xG or 0, 2),
                stats.goals,
                stats.aerial_duels_won,
                stats.aerial_duels_lost,
                stats.ground_duels_won,
                stats.ground_duels_lost,
                stats.tackles_won,
                stats.interceptions,
                stats.clearances,
                '' if is_goalkeeper else stats.pressures,
                stats.fouls_committed,
                stats.fouls_won,
                stats.offsides,
                stats.progressive_runs,
                stats.touches_in_opposition_box
            ])

        writer.writerow([
            f'{team_name} TOTAL', '', '',
            aggregates['short_completed_passes'],
            aggregates['short_incomplete_passes'],
            pct(aggregates['short_completed_passes'], aggregates['short_incomplete_passes']),
            aggregates['long_completed_passes'],
            aggregates['long_incomplete_passes'],
            pct(aggregates['long_completed_passes'], aggregates['long_incomplete_passes']),
            aggregates['pack_passes'],
            aggregates['pack_pass_score'],
            '',
            aggregates['pack_pass_receive_score'],
            aggregates['pack_turnovers'],
            aggregates['pack_turnover_score'],
            aggregates['shots_on_target'],
            aggregates['shots_off_target'],
            aggregates['shots_blocked'],
            round(aggregates['xA'] or 0, 2),
            aggregates['assists'],
            aggregates['chances_created'],
            aggregates['big_chances_created'],
            round(aggregates['xG'] or 0, 2),
            aggregates['goals'],
            aggregates['aerial_duels_won'],
            aggregates['aerial_duels_lost'],
            aggregates['ground_duels_won'],
            aggregates['ground_duels_lost'],
            aggregates['tackles_won'],
            aggregates['interceptions'],
            aggregates['clearances'],
            aggregates['pressures'],
            aggregates['fouls_committed'],
            aggregates['fouls_won'],
            aggregates['offsides'],
            aggregates['progressive_runs'],
            aggregates['touches_in_opposition_box']
        ])

    write_team_rows(match.home_team.name, home_data, home_aggregates)
    writer.writerow([])
    write_team_rows(match.away_team.name, away_data, away_aggregates)

    csv_content = output.getvalue()
    output.close()

    filename = f"match_{match.id}_spreadsheet.csv"
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route('/matches/<int:match_id>/edit', methods=['GET', 'POST'])
def edit_match(match_id):
    """Edit a match"""
    match = Match.query.get_or_404(match_id)
    
    if request.method == 'POST':
        main_team = request.form.get('main_team', 'home')
        match.home_team_id = request.form['home_team_id']
        match.away_team_id = request.form['away_team_id']
        match.main = (main_team != 'away')
        match.match_date = datetime.strptime(request.form['match_date'], '%Y-%m-%dT%H:%M')
        match.venue = request.form.get('venue')
        match.surface = request.form.get('surface')
        match.competition = request.form.get('competition')
        match.season = request.form.get('season')
        match.home_formation = request.form.get('home_formation')
        match.away_formation = request.form.get('away_formation')
        match.notes = request.form.get('notes')

        recalc_match_score(match_id)
        
        db.session.commit()
        flash('Match updated successfully!', 'success')
        return redirect(url_for('match_detail', match_id=match.id))
    
    teams = Team.query.order_by(Team.name).all()
    return render_template('match_form.html', match=match, teams=teams)


@app.route('/matches/<int:match_id>/delete', methods=['POST'])
def delete_match(match_id):
    """Delete a match and all associated data"""
    match = Match.query.get_or_404(match_id)
    match_title = f"{match.home_team.name} vs {match.away_team.name}"

    MatchEvent.query.filter_by(match_id=match_id).delete(synchronize_session=False)
    ShotEvent.query.filter_by(match_id=match_id).delete(synchronize_session=False)
    PlayerMatchStats.query.filter_by(match_id=match_id).delete(synchronize_session=False)
    GoalKeeperMatchStats.query.filter_by(match_id=match_id).delete(synchronize_session=False)
    MatchLineup.query.filter_by(match_id=match_id).delete(synchronize_session=False)
    PackPassEvent.query.filter_by(match_id=match_id).delete(synchronize_session=False)
    PackTurnoverEvent.query.filter_by(match_id=match_id).delete(synchronize_session=False)
    CornerEvent.query.filter_by(match_id=match_id).delete(synchronize_session=False)
    pack_dribble_event_ids = [row.id for row in PackDribbleEvent.query.with_entities(PackDribbleEvent.id).filter_by(match_id=match_id).all()]
    if pack_dribble_event_ids:
        PackDribbledPastPlayer.query.filter(PackDribbledPastPlayer.event_id.in_(pack_dribble_event_ids)).delete(synchronize_session=False)
    PackDribbleEvent.query.filter_by(match_id=match_id).delete(synchronize_session=False)
    
    db.session.delete(match)
    db.session.commit()
    
    flash(f'Match "{match_title}" and all associated data have been deleted successfully!', 'success')
    return redirect(url_for('matches'))


@app.route('/matches/<int:match_id>/events/new', methods=['POST'])
def add_match_event(match_id):
    """Add an event to a match"""
    match = Match.query.get_or_404(match_id)

    def resolve_match_player_id(raw_player_id, raw_player_name):
        if raw_player_id:
            try:
                return int(raw_player_id)
            except ValueError:
                return None

        player_name = (raw_player_name or '').strip().lower()
        if not player_name:
            return None

        player = Player.query.filter(
            Player.team_id.in_([match.home_team_id, match.away_team_id]),
            func.lower(Player.name) == player_name
        ).first()

        return player.id if player else None

    def apply_card_to_player_stats(player_id, card_type, increment=True):
        if not player_id or card_type not in ('yellow_card', 'red_card'):
            return

        stats = PlayerMatchStats.query.filter_by(match_id=match_id, player_id=player_id).first()
        if not stats:
            stats = PlayerMatchStats(match_id=match_id, player_id=player_id)
            db.session.add(stats)

        field_name = 'yellow_cards' if card_type == 'yellow_card' else 'red_cards'
        current_value = getattr(stats, field_name) or 0
        if increment:
            setattr(stats, field_name, current_value + 1)
        else:
            setattr(stats, field_name, max(0, current_value - 1))
    
    event_type = request.form['event_type']
    
    # Handle substitution events
    if event_type == 'substitution':
        player_off_id = request.form.get('player_off_id')
        player_on_id = request.form.get('player_on_id')
        minute = request.form['minute']
        
        if player_off_id and player_on_id:
            # Create substitute_off event
            event_off = MatchEvent(
                match_id=match_id,
                player_id=int(player_off_id),
                event_type='substitute_off',
                minute=minute,
                description=f"Substituted off"
            )
            db.session.add(event_off)
            
            # Create substitute_on event
            event_on = MatchEvent(
                match_id=match_id,
                player_id=int(player_on_id),
                event_type='substitute_on',
                minute=minute,
                description=f"Substituted on"
            )
            db.session.add(event_on)
            
            # Also add the visible substitution event
            event = MatchEvent(
                match_id=match_id,
                player_id=None,
                event_type='substitution',
                minute=minute,
                description=f"Off: {Player.query.get(int(player_off_id)).name} | On: {Player.query.get(int(player_on_id)).name}"
            )
            db.session.add(event)
    else:
        # Card and own-goal events can be linked by selected ID or typed player name.
        player_id = request.form.get('player_id')
        player_name = request.form.get('player_name')
        team_id = None

        if event_type in ('yellow_card', 'red_card', 'own_goal'):
            player_id = resolve_match_player_id(player_id, player_name)
            if not player_id:
                flash('Select or enter a valid player name for this event.', 'error')
                return redirect(url_for('match_detail', match_id=match_id))
        else:
            player_id = int(player_id) if player_id else None

        if event_type == 'own_goal':
            raw_team_id = request.form.get('team_id')
            try:
                team_id = int(raw_team_id)
            except (TypeError, ValueError):
                team_id = None

            if team_id not in (match.home_team_id, match.away_team_id):
                flash('Select the team benefiting from the own goal.', 'error')
                return redirect(url_for('match_detail', match_id=match_id))

            player = Player.query.get_or_404(player_id)
            player_team_id = get_team_id_for_match(match_id, player)
            if player_team_id not in (match.home_team_id, match.away_team_id):
                flash('Unable to determine the own-goal player team for this match.', 'error')
                return redirect(url_for('match_detail', match_id=match_id))

            if player_team_id == team_id:
                flash('An own goal must benefit the opposing team.', 'error')
                return redirect(url_for('match_detail', match_id=match_id))

            if not request.form.get('description'):
                benefiting_team = match.home_team if team_id == match.home_team_id else match.away_team
                description = f'Benefits: {benefiting_team.name}'
            else:
                description = request.form.get('description')
        else:
            description = request.form.get('description')
        
        event = MatchEvent(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            event_type=event_type,
            minute=request.form['minute'],
            description=description
        )
        db.session.add(event)

        if event_type in ('yellow_card', 'red_card'):
            apply_card_to_player_stats(player_id, event_type, increment=True)
    
    db.session.commit()
    
    flash('Event added successfully!', 'success')
    return redirect(url_for('match_detail', match_id=match_id))


@app.route('/matches/<int:match_id>/events/<int:event_id>/delete', methods=['POST'])
def delete_match_event(match_id, event_id):
    """Delete a match event"""
    event = MatchEvent.query.filter_by(id=event_id, match_id=match_id).first_or_404()

    if event.event_type in ('yellow_card', 'red_card') and event.player_id:
        stats = PlayerMatchStats.query.filter_by(match_id=match_id, player_id=event.player_id).first()
        if stats:
            if event.event_type == 'yellow_card':
                stats.yellow_cards = max(0, (stats.yellow_cards or 0) - 1)
            else:
                stats.red_cards = max(0, (stats.red_cards or 0) - 1)

    db.session.delete(event)
    db.session.commit()
    flash('Event deleted successfully!', 'success')
    return redirect(url_for('match_detail', match_id=match_id))


@app.route('/players')
def players():
    """List all players"""
    all_players = Player.query.order_by(Player.name).all()
    return render_template('players.html', players=all_players)


@app.route('/players/new', methods=['GET', 'POST'])
def new_player():
    """Create a new player"""
    if request.method == 'POST':
        dob = None
        if request.form.get('date_of_birth'):
            dob = datetime.strptime(request.form['date_of_birth'], '%Y-%m-%d').date()
        
        # Convert empty string to None for integer field
        jersey_num = request.form.get('jersey_number')
        jersey_num = int(jersey_num) if jersey_num else None
        
        player = Player(
            name=request.form['name'],
            team_id=request.form.get('team_id'),
            position=request.form.get('position'),
            jersey_number=jersey_num,
            date_of_birth=dob,
            nationality=request.form.get('nationality')
        )
        db.session.add(player)
        db.session.commit()
        flash('Player created successfully!', 'success')
        return redirect(url_for('players'))
    
    teams = Team.query.order_by(Team.name).all()
    return render_template('player_form.html', teams=teams)


@app.route('/players/<int:player_id>/edit', methods=['GET', 'POST'])
def edit_player(player_id):
    """Edit a player"""
    player = Player.query.get_or_404(player_id)
    
    if request.method == 'POST':
        player.name = request.form['name']
        player.team_id = request.form.get('team_id')
        player.position = request.form.get('position')
        
        # Convert empty string to None for integer field
        jersey_num = request.form.get('jersey_number')
        player.jersey_number = int(jersey_num) if jersey_num else None
        
        dob = None
        if request.form.get('date_of_birth'):
            dob = datetime.strptime(request.form['date_of_birth'], '%Y-%m-%d').date()
        player.date_of_birth = dob
        
        player.nationality = request.form.get('nationality')
        db.session.commit()
        flash('Player updated successfully!', 'success')
        return redirect(url_for('players'))
    
    teams = Team.query.order_by(Team.name).all()
    return render_template('player_form.html', player=player, teams=teams)


# API Endpoints
@app.route('/api/matches')
def api_matches():
    """API endpoint for matches"""
    matches = Match.query.order_by(Match.match_date.desc()).all()
    return jsonify([match.to_dict() for match in matches])


@app.route('/api/teams')
def api_teams():
    """API endpoint for teams"""
    teams = Team.query.order_by(Team.name).all()
    return jsonify([team.to_dict() for team in teams])


@app.route('/api/matches/<int:match_id>/stats/<int:player_id>', methods=['GET'])
def get_player_stats(match_id, player_id):
    """Fetch the latest stats for a player in a match"""
    player = Player.query.get_or_404(player_id)
    stats_model = get_stats_model(match_id, player)

    stats = stats_model.query.filter_by(match_id=match_id, player_id=player_id).first()
    if not stats:
        stats = stats_model(match_id=match_id, player_id=player_id)
        db.session.add(stats)
        db.session.commit()

    stats_data = {
        column.name: getattr(stats, column.name)
        for column in stats_model.__table__.columns
    }

    return jsonify({
        'success': True,
        'is_goalkeeper': stats_model == GoalKeeperMatchStats,
        'stats': stats_data
    })


@app.route('/api/matches/<int:match_id>/stats/<int:player_id>/increment', methods=['POST'])
def increment_player_stat(match_id, player_id):
    """Increment a specific stat for a player in a match"""
    data = request.get_json()
    stat_name = data.get('stat_name')
    
    if not stat_name:
        return jsonify({'error': 'stat_name is required'}), 400
    
    player = Player.query.get_or_404(player_id)
    is_goalkeeper, _ = is_goalkeeper_for_match(match_id, player)

    if is_goalkeeper and hasattr(GoalKeeperMatchStats, stat_name):
        stats_model = GoalKeeperMatchStats
    else:
        stats_model = PlayerMatchStats

    if not hasattr(stats_model, stat_name):
        return jsonify({'error': f'Invalid stat name: {stat_name}'}), 400

    stats = stats_model.query.filter_by(match_id=match_id, player_id=player_id).first()
    if not stats:
        stats = stats_model(match_id=match_id, player_id=player_id)
        db.session.add(stats)
    
    current_value = getattr(stats, stat_name)
    setattr(stats, stat_name, current_value + 1)

    linked_updates = {}
    if stat_name == 'tackles_won' and hasattr(stats, 'ground_duels_won'):
        stats.ground_duels_won = (stats.ground_duels_won or 0) + 1
        linked_updates['ground_duels_won'] = stats.ground_duels_won

    if stat_name in ['aerial_duels_won', 'aerial_duels_lost', 'ground_duels_won', 'ground_duels_lost', 'tackles_won']:
        sync_duel_totals(stats)
        if stat_name == 'tackles_won':
            linked_updates['duels_won'] = stats.duels_won
            linked_updates['duels_lost'] = stats.duels_lost

    opponent_outfield_update = mirror_duel_to_non_main_outfield(
        match_id=match_id,
        acting_player=player,
        stat_name=stat_name,
        increment=True
    )

    # Auto-calculate pack_pass_score if updating pack pass components
    if stat_name in ['pack_pass_defenders', 'pack_pass_midfielders', 'pack_pass_attackers']:
        stats.pack_pass_score = (stats.pack_pass_defenders * 3) + (stats.pack_pass_midfielders * 2) + (stats.pack_pass_attackers * 1)

    if stat_name == 'goals':
        recalc_match_score(match_id)

    db.session.commit()

    response = {
        'success': True,
        'stat_name': stat_name,
        'new_value': getattr(stats, stat_name)
    }

    if linked_updates:
        response['linked_updates'] = linked_updates

    if opponent_outfield_update:
        response['opponent_outfield_update'] = opponent_outfield_update

    # Include pack_pass_score in response if it was updated
    if stat_name in ['pack_pass_defenders', 'pack_pass_midfielders', 'pack_pass_attackers']:
        response['pack_pass_score'] = stats.pack_pass_score

    return jsonify(response)


@app.route('/api/matches/<int:match_id>/stats/<int:player_id>/decrement', methods=['POST'])
def decrement_player_stat(match_id, player_id):
    """Decrement a specific stat for a player in a match"""
    data = request.get_json()
    stat_name = data.get('stat_name')
    
    if not stat_name:
        return jsonify({'error': 'stat_name is required'}), 400
    
    player = Player.query.get_or_404(player_id)
    is_goalkeeper, _ = is_goalkeeper_for_match(match_id, player)

    if is_goalkeeper and hasattr(GoalKeeperMatchStats, stat_name):
        stats_model = GoalKeeperMatchStats
    else:
        stats_model = PlayerMatchStats

    if not hasattr(stats_model, stat_name):
        return jsonify({'error': f'Invalid stat name: {stat_name}'}), 400

    stats = stats_model.query.filter_by(match_id=match_id, player_id=player_id).first()
    if not stats:
        return jsonify({'error': 'Stats not found'}), 404
    
    # Decrement the specified stat (but not below 0)
    current_value = getattr(stats, stat_name)
    setattr(stats, stat_name, max(0, current_value - 1))

    linked_updates = {}
    if stat_name == 'tackles_won' and hasattr(stats, 'ground_duels_won'):
        stats.ground_duels_won = max(0, (stats.ground_duels_won or 0) - 1)
        linked_updates['ground_duels_won'] = stats.ground_duels_won

    if stat_name in ['aerial_duels_won', 'aerial_duels_lost', 'ground_duels_won', 'ground_duels_lost', 'tackles_won']:
        sync_duel_totals(stats)
        if stat_name == 'tackles_won':
            linked_updates['duels_won'] = stats.duels_won
            linked_updates['duels_lost'] = stats.duels_lost

    opponent_outfield_update = mirror_duel_to_non_main_outfield(
        match_id=match_id,
        acting_player=player,
        stat_name=stat_name,
        increment=False
    )

    # Auto-calculate pack_pass_score if updating pack pass components
    if stat_name in ['pack_pass_defenders', 'pack_pass_midfielders', 'pack_pass_attackers']:
        stats.pack_pass_score = (stats.pack_pass_defenders * 3) + (stats.pack_pass_midfielders * 2) + (stats.pack_pass_attackers * 1)

    if stat_name == 'goals':
        recalc_match_score(match_id)

    db.session.commit()

    response = {
        'success': True,
        'stat_name': stat_name,
        'new_value': getattr(stats, stat_name)
    }

    if linked_updates:
        response['linked_updates'] = linked_updates

    if opponent_outfield_update:
        response['opponent_outfield_update'] = opponent_outfield_update

    # Include pack_pass_score in response if it was updated
    if stat_name in ['pack_pass_defenders', 'pack_pass_midfielders', 'pack_pass_attackers']:
        response['pack_pass_score'] = stats.pack_pass_score

    return jsonify(response)


@app.route('/api/matches/<int:match_id>/record-pack-pass', methods=['POST'])
def record_pack_pass(match_id):
    """Record a pack pass event - updates both passer and receiver stats atomically"""
    data = request.get_json()
    match = Match.query.get_or_404(match_id)
    
    passer_id = data.get('passer_id')
    receiver_id = data.get('receiver_id')
    team_id = data.get('team_id')
    defenders = int(data.get('defenders', 0))
    midfielders = int(data.get('midfielders', 0))
    attackers = int(data.get('attackers', 0))

    if not team_id and passer_id:
        passer_player = Player.query.get_or_404(passer_id)
        team_id = get_team_id_for_match(match_id, passer_player)

    if not team_id:
        return jsonify({'error': 'team_id required'}), 400

    team_id = int(team_id)
    main_team_id = match.home_team_id if match.main else match.away_team_id
    is_main_team_event = team_id == main_team_id

    if team_id not in (match.home_team_id, match.away_team_id):
        return jsonify({'error': 'Invalid team for this match'}), 400

    if not passer_id:
        return jsonify({'error': 'passer_id required'}), 400

    if is_main_team_event and not receiver_id:
        return jsonify({'error': 'receiver_id required for main team'}), 400

    passer_id = int(passer_id)
    receiver_id = int(receiver_id) if receiver_id else None

    passer = Player.query.get_or_404(passer_id)
    passer_team_id = get_team_id_for_match(match_id, passer)
    if passer_team_id != team_id:
        return jsonify({'error': 'passer_id is not in the selected team for this match'}), 400

    receiver = None
    if receiver_id is not None:
        receiver = Player.query.get_or_404(receiver_id)
    
    # Calculate score
    score = (defenders * 3) + (midfielders * 2) + (attackers * 1)

    pack_event = PackPassEvent(
        match_id=match_id,
        team_id=team_id,
        passer_id=passer_id,
        receiver_id=receiver_id,
        score=score,
        defenders=defenders,
        midfielders=midfielders,
        attackers=attackers
    )
    db.session.add(pack_event)
    db.session.flush()

    passer_model = get_stats_model(match_id, passer)
    get_or_create_stats(match_id, passer, passer_model)
    recalc_pack_pass_stats(match_id, passer_id, passer_model)
    passer_stats = passer_model.query.filter_by(match_id=match_id, player_id=passer_id).first()

    if not is_main_team_event:
        try:
            db.session.commit()
            return jsonify({
                'success': True,
                'score': score,
                'team_only': True,
                'passer_pack_passes': passer_stats.pack_passes,
                'passer_pack_pass_score': passer_stats.pack_pass_score
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    receiver_model = get_stats_model(match_id, receiver)

    get_or_create_stats(match_id, receiver, receiver_model)

    recalc_pack_pass_stats(match_id, receiver_id, receiver_model)

    receiver_stats = receiver_model.query.filter_by(match_id=match_id, player_id=receiver_id).first()
    
    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'score': score,
            'passer_pack_passes': passer_stats.pack_passes,
            'passer_pack_pass_score': passer_stats.pack_pass_score,
            'receiver_pack_pass_receive_score': receiver_stats.pack_pass_receive_score
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/matches/<int:match_id>/record-pack-turnover', methods=['POST'])
def record_pack_turnover(match_id):
    """Record a pack turnover event - updates the player's turnover stats atomically"""
    data = request.get_json()
    
    player_id = data.get('player_id')
    defenders = int(data.get('defenders', 0))
    midfielders = int(data.get('midfielders', 0))
    attackers = int(data.get('attackers', 0))
    
    # Validate
    if not player_id:
        return jsonify({'error': 'player_id required'}), 400
    
    # Calculate score
    score = (defenders * 3) + (midfielders * 2) + (attackers * 1)
    
    player = Player.query.get_or_404(player_id)
    stats_model = get_stats_model(match_id, player)
    get_or_create_stats(match_id, player, stats_model)

    player_team_id = get_team_id_for_match(match_id, player)
    if not player_team_id:
        return jsonify({'error': 'Team not found for player'}), 400

    turnover_event = PackTurnoverEvent(
        match_id=match_id,
        team_id=player_team_id,
        player_id=player_id,
        score=score,
        defenders=defenders,
        midfielders=midfielders,
        attackers=attackers
    )
    db.session.add(turnover_event)
    db.session.flush()

    recalc_pack_turnover_stats(match_id, player_id, stats_model)

    player_stats = stats_model.query.filter_by(match_id=match_id, player_id=player_id).first()
    
    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'score': score,
            'pack_turnovers': player_stats.pack_turnovers,
            'pack_turnover_score': player_stats.pack_turnover_score
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/matches/<int:match_id>/record-pack-dribble', methods=['POST'])
def record_pack_dribble(match_id):
    """Record a pack dribble event for main/non-main team rules."""
    data = request.get_json()
    match = Match.query.get_or_404(match_id)

    dribbler_id = data.get('dribbler_id')
    team_id = data.get('team_id')

    if not dribbler_id or not team_id:
        return jsonify({'error': 'dribbler_id and team_id are required'}), 400

    team_id = int(team_id)
    dribbler_id = int(dribbler_id)

    if team_id not in (match.home_team_id, match.away_team_id):
        return jsonify({'error': 'Invalid team for this match'}), 400

    dribbler = Player.query.get_or_404(dribbler_id)
    dribbler_team_id = get_team_id_for_match(match_id, dribbler)
    if dribbler_team_id != team_id:
        return jsonify({'error': 'dribbler_id is not in the selected team for this match'}), 400

    main_team_id = match.home_team_id if match.main else match.away_team_id
    is_main_team_event = team_id == main_team_id

    defenders = 0
    midfielders = 0
    attackers = 0
    dribbled_past_player_ids = []

    if is_main_team_event:
        defenders = int(data.get('defenders', 0) or 0)
        midfielders = int(data.get('midfielders', 0) or 0)
        attackers = int(data.get('attackers', 0) or 0)

        if defenders < 0 or midfielders < 0 or attackers < 0:
            return jsonify({'error': 'defenders, midfielders and attackers must be >= 0'}), 400
    else:
        raw_player_ids = data.get('dribbled_past_player_ids') or []
        if not isinstance(raw_player_ids, list) or not raw_player_ids:
            return jsonify({'error': 'dribbled_past_player_ids required for non-main team dribbles'}), 400

        for raw_id in raw_player_ids:
            try:
                player_id = int(raw_id)
            except (TypeError, ValueError):
                return jsonify({'error': f'Invalid player id in dribbled_past_player_ids: {raw_id}'}), 400

            player = Player.query.get_or_404(player_id)
            player_team_id = get_team_id_for_match(match_id, player)
            if player_team_id != main_team_id:
                return jsonify({'error': f'Player {player_id} is not in the main team for this match'}), 400

            dribbled_past_player_ids.append(player_id)
            position_group = get_player_position_group_for_match(match_id, player)
            if position_group == 'defender':
                defenders += 1
            elif position_group == 'midfielder':
                midfielders += 1
            else:
                attackers += 1

    score = (defenders * 3) + (midfielders * 2) + attackers

    dribble_event = PackDribbleEvent(
        match_id=match_id,
        team_id=team_id,
        dribbler_id=dribbler_id,
        score=score,
        defenders=defenders,
        midfielders=midfielders,
        attackers=attackers
    )
    db.session.add(dribble_event)
    db.session.flush()

    dribbler_stats_model = get_stats_model(match_id, dribbler)
    get_or_create_stats(match_id, dribbler, dribbler_stats_model)
    recalc_pack_dribble_stats(match_id, dribbler_id, dribbler_stats_model)

    if not is_main_team_event:
        for player_id in dribbled_past_player_ids:
            dribbled_player = Player.query.get_or_404(player_id)
            position_group = get_player_position_group_for_match(match_id, dribbled_player)
            db.session.add(PackDribbledPastPlayer(
                event_id=dribble_event.id,
                player_id=player_id,
                position_group=position_group
            ))

            stats_model = get_stats_model(match_id, dribbled_player)
            get_or_create_stats(match_id, dribbled_player, stats_model)
            recalc_pack_dribbled_past_stats(match_id, player_id, stats_model)

    dribbler_stats = dribbler_stats_model.query.filter_by(match_id=match_id, player_id=dribbler_id).first()

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'score': score,
            'defenders': defenders,
            'midfielders': midfielders,
            'attackers': attackers,
            'pack_dribbles': dribbler_stats.pack_dribbles,
            'pack_dribble_score': dribbler_stats.pack_dribble_score,
            'is_main_team_event': is_main_team_event
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/matches/<int:match_id>/record-shot', methods=['POST'])
def record_shot(match_id):
    """Record a shot with xG, assist info, and goal status"""
    data = request.get_json()
    match = Match.query.get_or_404(match_id)
    
    player_id = int(data.get('player_id'))
    shot_type = data.get('shot_type')  # on_target, off_target, blocked
    xG = float(data.get('xG', 0))
    inside_box_raw = data.get('inside_box', False)
    assist_player_id_raw = data.get('assist_player_id')  # Optional
    shot_context = (data.get('shot_context') or 'open_play').strip().lower()
    valid_shot_contexts = {'open_play', 'penalty', 'free_kick', 'corner'}
    if shot_context not in valid_shot_contexts:
        return jsonify({'error': 'shot_context must be one of: open_play, penalty, free_kick, corner'}), 400
    is_goal = data.get('is_goal', False)
    big_chance_raw = data.get('big_chance', False)
    veo_seconds_raw = data.get('veo_seconds')
    veo_time_raw = (data.get('veo_time') or '').strip()

    veo_seconds = None
    if veo_seconds_raw is not None and str(veo_seconds_raw).strip() != '':
        try:
            veo_seconds = int(veo_seconds_raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'veo_seconds must be an integer'}), 400

        if veo_seconds < 0:
            return jsonify({'error': 'veo_seconds must be >= 0'}), 400
    elif veo_time_raw:
        parts = veo_time_raw.split(':')
        if len(parts) != 2:
            return jsonify({'error': 'veo_time must be in MM:SS format'}), 400

        minutes_part, seconds_part = parts
        if not (minutes_part.isdigit() and seconds_part.isdigit()):
            return jsonify({'error': 'veo_time must contain numeric minutes and seconds'}), 400

        minutes = int(minutes_part)
        seconds = int(seconds_part)
        if minutes < 0 or seconds < 0 or seconds > 59:
            return jsonify({'error': 'veo_time must have minutes >= 0 and seconds between 0 and 59'}), 400

        veo_seconds = (minutes * 60) + seconds
    else:
        return jsonify({'error': 'veo_seconds is required'}), 400

    assist_player_id = int(assist_player_id_raw) if assist_player_id_raw else None

    if isinstance(inside_box_raw, str):
        inside_box = inside_box_raw.strip().lower() in ('1', 'true', 'yes', 'on')
    else:
        inside_box = bool(inside_box_raw)

    is_penalty = shot_context == 'penalty'
    is_free_kick = shot_context == 'free_kick'
    is_corner = shot_context == 'corner'

    lineup_team_id = db.session.query(MatchLineup.team_id).filter(
        MatchLineup.match_id == match_id,
        MatchLineup.player_id == player_id,
        MatchLineup.team_id.isnot(None)
    ).scalar()
    player = Player.query.get_or_404(player_id)
    shot_team_id = lineup_team_id or player.team_id
    if shot_team_id not in {match.home_team_id, match.away_team_id}:
        return jsonify({'error': 'Unable to determine team for shot event'}), 400

    if isinstance(big_chance_raw, str):
        is_big_chance = big_chance_raw.strip().lower() in ('1', 'true', 'yes', 'on')
    else:
        is_big_chance = bool(big_chance_raw)
    
    # Validate
    if not player_id or not shot_type:
        return jsonify({'error': 'player_id and shot_type required'}), 400
    
    # Get or create player stats
    player_stats = PlayerMatchStats.query.filter_by(match_id=match_id, player_id=player_id).first()
    if not player_stats:
        player_stats = PlayerMatchStats(
            match_id=match_id,
            player_id=player_id
        )
        db.session.add(player_stats)
    
    # Update shot type
    if shot_type == 'on_target':
        player_stats.shots_on_target = (player_stats.shots_on_target or 0) + 1
    elif shot_type == 'off_target':
        player_stats.shots_off_target = (player_stats.shots_off_target or 0) + 1
    elif shot_type == 'blocked':
        player_stats.shots_blocked = (player_stats.shots_blocked or 0) + 1
    
    # Update xG
    player_stats.xG = (player_stats.xG or 0) + xG

    # Update inside/outside box shot metrics
    if inside_box:
        player_stats.shots_inside_box = (player_stats.shots_inside_box or 0) + 1
        player_stats.xG_inside_box = (player_stats.xG_inside_box or 0) + xG
    else:
        player_stats.shots_outside_box = (player_stats.shots_outside_box or 0) + 1
        player_stats.xG_outside_box = (player_stats.xG_outside_box or 0) + xG
    
    # Update goals if applicable
    if is_goal:
        player_stats.goals = (player_stats.goals or 0) + 1

    recalc_match_score(match_id)
    
    shot_event = ShotEvent(
        match_id=match_id,
        team_id=shot_team_id,
        player_id=player_id,
        assist_player_id=assist_player_id,
        shot_on_target=(shot_type == 'on_target'),
        shot_off_target=(shot_type == 'off_target'),
        shot_blocked=(shot_type == 'blocked'),
        penalty=is_penalty,
        free_kick=is_free_kick,
        corner=is_corner,
        xG=xG,
        big_chance=is_big_chance,
        inside_box=inside_box,
        veo_seconds=veo_seconds
    )
    db.session.add(shot_event)

    # Handle assist
    assist_player_stats = None
    assist_chances_created = 0
    assist_big_chances_created = 0
    if assist_player_id:
        assist_player_stats = PlayerMatchStats.query.filter_by(match_id=match_id, player_id=assist_player_id).first()
        if not assist_player_stats:
            assist_player = Player.query.get_or_404(assist_player_id)
            assist_player_stats = PlayerMatchStats(
                match_id=match_id,
                player_id=assist_player_id
            )
            db.session.add(assist_player_stats)
        
        # Record xA (xG becomes xA for the assister)
        assist_player_stats.xA = (assist_player_stats.xA or 0) + xG

        # Keep creation metrics derived from assisted shots so attribution stays on the assister.
        db.session.flush()
        assist_player_stats.chances_created = calculate_chances_created(match_id, assist_player_id)
        assist_player_stats.big_chances_created = calculate_big_chances_created(match_id, assist_player_id)
        
        # If goal, increment assists
        if is_goal:
            assist_player_stats.assists = (assist_player_stats.assists or 0) + 1

        assist_chances_created = assist_player_stats.chances_created
        assist_big_chances_created = assist_player_stats.big_chances_created
    
    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'shot_type': shot_type,
            'xG': xG,
            'veo_seconds': veo_seconds,
            'veo_time': format_veo_time(veo_seconds),
            'inside_box': inside_box,
            'shot_context': (
                'penalty' if is_penalty else (
                    'free_kick' if is_free_kick else (
                        'corner' if is_corner else 'open_play'
                    )
                )
            ),
            'big_chance': is_big_chance,
            'is_goal': is_goal,
            'goals': player_stats.goals,
            'shots': {
                'on_target': player_stats.shots_on_target,
                'off_target': player_stats.shots_off_target,
                'blocked': player_stats.shots_blocked,
                'inside_box': player_stats.shots_inside_box,
                'outside_box': player_stats.shots_outside_box
            },
            'xG_breakdown': {
                'inside_box': player_stats.xG_inside_box,
                'outside_box': player_stats.xG_outside_box
            },
            'assist': {
                'assists': assist_player_stats.assists if assist_player_stats else 0,
                'xA': assist_player_stats.xA if assist_player_stats else 0,
                'chances_created': assist_chances_created,
                'big_chances_created': assist_big_chances_created
            } if assist_player_id else None
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/matches/<int:match_id>/record-corner', methods=['POST'])
def record_corner(match_id):
    """Record a corner event with different requirements for main vs non-main teams."""
    data = request.get_json() or {}
    match = Match.query.get_or_404(match_id)

    parsed_payload, error_response = parse_corner_payload(match_id, match, data)
    if error_response:
        return error_response

    corner_event = CornerEvent(**parsed_payload)
    db.session.add(corner_event)

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'id': corner_event.id,
            'team_id': corner_event.team_id,
            'taker_player_id': corner_event.taker_player_id,
            'won_by_player_id': corner_event.won_by_player_id,
            'delivery_type': corner_event.delivery_type,
            'delivery_outcome': corner_event.delivery_outcome,
            'delivery_length': corner_event.delivery_length,
            'led_to_shot': corner_event.led_to_shot,
            'big_chance_created': corner_event.big_chance_created,
            'is_main_team_event': corner_event.team_id == (match.home_team_id if match.main else match.away_team_id)
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


def _parse_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def parse_corner_payload(match_id, match, data, existing_event=None):
    team_id_raw = data.get('team_id', existing_event.team_id if existing_event else None)
    taker_player_id_raw = data.get('taker_player_id', existing_event.taker_player_id if existing_event else None)
    won_by_player_id_raw = data.get('won_by_player_id', existing_event.won_by_player_id if existing_event else None)
    delivery_type = (data.get('delivery_type', existing_event.delivery_type if existing_event else '') or '').strip().lower()
    delivery_outcome = (data.get('delivery_outcome', existing_event.delivery_outcome if existing_event else '') or '').strip().lower()
    delivery_length = (data.get('delivery_length', existing_event.delivery_length if existing_event else '') or '').strip().lower()
    led_to_shot_raw = data.get('led_to_shot', existing_event.led_to_shot if existing_event else False)
    big_chance_created_raw = data.get('big_chance_created', existing_event.big_chance_created if existing_event else False)

    if not team_id_raw or not taker_player_id_raw:
        return None, (jsonify({'error': 'team_id and taker_player_id are required'}), 400)

    try:
        team_id = int(team_id_raw)
        taker_player_id = int(taker_player_id_raw)
    except (TypeError, ValueError):
        return None, (jsonify({'error': 'team_id and taker_player_id must be integers'}), 400)

    if team_id not in (match.home_team_id, match.away_team_id):
        return None, (jsonify({'error': 'Invalid team for this match'}), 400)

    if delivery_type not in ('inswing', 'outswing', 'straight'):
        return None, (jsonify({'error': 'delivery_type must be inswing, outswing, or straight'}), 400)

    if delivery_outcome not in ('successful', 'unsuccessful'):
        return None, (jsonify({'error': 'delivery_outcome must be successful or unsuccessful'}), 400)

    if delivery_length not in ('short', 'long'):
        return None, (jsonify({'error': 'delivery_length must be short or long'}), 400)

    led_to_shot = _parse_bool(led_to_shot_raw)
    big_chance_created = _parse_bool(big_chance_created_raw)

    taker = Player.query.get_or_404(taker_player_id)
    taker_team_id = get_team_id_for_match(match_id, taker)
    if taker_team_id != team_id:
        return None, (jsonify({'error': 'taker_player_id is not in the selected team for this match'}), 400)

    main_team_id = match.home_team_id if match.main else match.away_team_id
    is_main_team_event = team_id == main_team_id

    won_by_player_id = None
    if is_main_team_event:
        if not won_by_player_id_raw:
            return None, (jsonify({'error': 'won_by_player_id is required for main-team corners'}), 400)

        try:
            won_by_player_id = int(won_by_player_id_raw)
        except (TypeError, ValueError):
            return None, (jsonify({'error': 'won_by_player_id must be an integer'}), 400)

        won_by_player = Player.query.get_or_404(won_by_player_id)
        won_by_team_id = get_team_id_for_match(match_id, won_by_player)
        if won_by_team_id != team_id:
            return None, (jsonify({'error': 'won_by_player_id is not in the selected team for this match'}), 400)

    return {
        'match_id': match_id,
        'team_id': team_id,
        'taker_player_id': taker_player_id,
        'won_by_player_id': won_by_player_id,
        'delivery_type': delivery_type,
        'delivery_outcome': delivery_outcome,
        'delivery_length': delivery_length,
        'led_to_shot': led_to_shot,
        'big_chance_created': big_chance_created
    }, None


@app.route('/api/matches/<int:match_id>/corner-events/<int:event_id>', methods=['PUT'])
def update_corner_event(match_id, event_id):
    """Update an existing corner event."""
    data = request.get_json() or {}
    match = Match.query.get_or_404(match_id)
    corner_event = CornerEvent.query.filter_by(id=event_id, match_id=match_id).first_or_404()

    parsed_payload, error_response = parse_corner_payload(match_id, match, data, existing_event=corner_event)
    if error_response:
        return error_response

    corner_event.team_id = parsed_payload['team_id']
    corner_event.taker_player_id = parsed_payload['taker_player_id']
    corner_event.won_by_player_id = parsed_payload['won_by_player_id']
    corner_event.delivery_type = parsed_payload['delivery_type']
    corner_event.delivery_outcome = parsed_payload['delivery_outcome']
    corner_event.delivery_length = parsed_payload['delivery_length']
    corner_event.led_to_shot = parsed_payload['led_to_shot']
    corner_event.big_chance_created = parsed_payload['big_chance_created']

    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/matches/<int:match_id>/corner-events/<int:event_id>', methods=['DELETE'])
def delete_corner_event(match_id, event_id):
    """Delete a corner event."""
    corner_event = CornerEvent.query.filter_by(id=event_id, match_id=match_id).first_or_404()

    try:
        db.session.delete(corner_event)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(
        host=os.getenv('FLASK_HOST', '0.0.0.0'),
        port=int(os.getenv('FLASK_PORT', '5000')),
        debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    )
