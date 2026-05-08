from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Team(db.Model):
    """Team model"""
    __tablename__ = 'teams'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    city = db.Column(db.String(100))
    country = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    home_matches = db.relationship('Match', foreign_keys='Match.home_team_id', backref='home_team', lazy=True)
    away_matches = db.relationship('Match', foreign_keys='Match.away_team_id', backref='away_team', lazy=True)
    
    def __repr__(self):
        return f'<Team {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'city': self.city,
            'country': self.country,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Match(db.Model):
    """Match model"""
    __tablename__ = 'matches'
    
    id = db.Column(db.Integer, primary_key=True)
    home_team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    away_team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    main = db.Column(db.Boolean, nullable=False, default=True)
    home_score = db.Column(db.Integer, nullable=False, default=0)
    away_score = db.Column(db.Integer, nullable=False, default=0)
    match_date = db.Column(db.DateTime, nullable=False)
    venue = db.Column(db.String(200))
    surface = db.Column(db.String(20))  # Astro or Grass
    competition = db.Column(db.String(100))
    season = db.Column(db.String(20))
    home_formation = db.Column(db.String(20))  # e.g., 4-4-2, 4-3-3
    away_formation = db.Column(db.String(20))  # e.g., 4-4-2, 4-3-3
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    events = db.relationship('MatchEvent', backref='match', lazy=True, cascade='all, delete-orphan')
    shot_events = db.relationship('ShotEvent', backref='match', lazy=True, cascade='all, delete-orphan')
    corner_events = db.relationship('CornerEvent', backref='match', lazy=True, cascade='all, delete-orphan')
    player_stats = db.relationship('PlayerMatchStats', backref='match', lazy=True, cascade='all, delete-orphan')
    starting_lineups = db.relationship('MatchLineup', backref='match', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Match {self.home_team.name} vs {self.away_team.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'home_team': self.home_team.to_dict() if self.home_team else None,
            'away_team': self.away_team.to_dict() if self.away_team else None,
            'main': self.main,
            'home_score': self.home_score,
            'away_score': self.away_score,
            'match_date': self.match_date.isoformat() if self.match_date else None,
            'venue': self.venue,
            'surface': self.surface,
            'competition': self.competition,
            'season': self.season,
            'home_formation': self.home_formation,
            'away_formation': self.away_formation,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Player(db.Model):
    """Player model"""
    __tablename__ = 'players'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'))
    position = db.Column(db.String(50))
    jersey_number = db.Column(db.Integer)
    date_of_birth = db.Column(db.Date)
    nationality = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    team = db.relationship('Team', backref='players')
    events = db.relationship('MatchEvent', backref='player', lazy=True)
    shot_events = db.relationship('ShotEvent', foreign_keys='ShotEvent.player_id', backref='player', lazy=True)
    corner_events_taken = db.relationship('CornerEvent', foreign_keys='CornerEvent.taker_player_id', backref='taker_player', lazy=True)
    corner_events_won = db.relationship('CornerEvent', foreign_keys='CornerEvent.won_by_player_id', backref='won_by_player', lazy=True)
    match_stats = db.relationship('PlayerMatchStats', backref='player', lazy=True)
    
    def __repr__(self):
        return f'<Player {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'team': self.team.name if self.team else None,
            'position': self.position,
            'jersey_number': self.jersey_number,
            'date_of_birth': self.date_of_birth.isoformat() if self.date_of_birth else None,
            'nationality': self.nationality
        }


class MatchEvent(db.Model):
    """Match event model (goals, cards, substitutions, etc.)"""
    __tablename__ = 'match_events'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'))
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'))
    event_type = db.Column(db.String(50), nullable=False)  # yellow_card, red_card, substitution (goals tracked in PlayerMatchStats)
    minute = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    team = db.relationship('Team')
    
    def __repr__(self):
        return f'<MatchEvent {self.event_type} at {self.minute}\'>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'team_id': self.team_id,
            'player': self.player.to_dict() if self.player else None,
            'event_type': self.event_type,
            'minute': self.minute,
            'description': self.description
        }


class ShotEvent(db.Model):
    """Shot event for a specific match"""
    __tablename__ = 'shot_events'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    assist_player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    shot_on_target = db.Column(db.Boolean, nullable=False, default=False)
    shot_off_target = db.Column(db.Boolean, nullable=False, default=False)
    shot_blocked = db.Column(db.Boolean, nullable=False, default=False)
    penalty = db.Column(db.Boolean, nullable=False, default=False)
    free_kick = db.Column(db.Boolean, nullable=False, default=False)
    corner = db.Column(db.Boolean, nullable=False, default=False)
    xG = db.Column(db.Float, nullable=False, default=0.0)
    big_chance = db.Column(db.Boolean, nullable=False, default=False)
    inside_box = db.Column(db.Boolean, nullable=False, default=False)
    veo_seconds = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    team = db.relationship('Team')
    assist_player = db.relationship('Player', foreign_keys=[assist_player_id], backref='assisted_shot_events')

    __table_args__ = (
        db.CheckConstraint(
            '(CASE WHEN shot_on_target THEN 1 ELSE 0 END) + '
            '(CASE WHEN shot_off_target THEN 1 ELSE 0 END) + '
            '(CASE WHEN shot_blocked THEN 1 ELSE 0 END) = 1',
            name='ck_shot_events_exactly_one_outcome'
        ),
        db.CheckConstraint(
            '(CASE WHEN penalty THEN 1 ELSE 0 END) + '
            '(CASE WHEN free_kick THEN 1 ELSE 0 END) + '
            '(CASE WHEN corner THEN 1 ELSE 0 END) <= 1',
            name='ck_shot_events_max_one_set_piece_context'
        ),
    )

    def __repr__(self):
        return f'<ShotEvent Match:{self.match_id} Player:{self.player_id}>'

    def to_dict(self):
        formatted_veo_time = None
        if self.veo_seconds is not None and self.veo_seconds >= 0:
            formatted_veo_time = f"{self.veo_seconds // 60:02d}:{self.veo_seconds % 60:02d}"

        return {
            'id': self.id,
            'match_id': self.match_id,
            'team_id': self.team_id,
            'player': self.player.to_dict() if self.player else None,
            'assist_player_id': self.assist_player_id,
            'shot_on_target': self.shot_on_target,
            'shot_off_target': self.shot_off_target,
            'shot_blocked': self.shot_blocked,
            'penalty': self.penalty,
            'free_kick': self.free_kick,
            'corner': self.corner,
            'xG': self.xG,
            'big_chance': self.big_chance,
            'inside_box': self.inside_box,
            'veo_seconds': self.veo_seconds,
            'veo_time': formatted_veo_time,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class CornerEvent(db.Model):
    """Corner event for a specific match"""
    __tablename__ = 'corner_events'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    taker_player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    won_by_player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    delivery_type = db.Column(db.String(20), nullable=False)
    delivery_outcome = db.Column(db.String(20), nullable=False)
    delivery_length = db.Column(db.String(10), nullable=False)
    led_to_shot = db.Column(db.Boolean, nullable=False, default=False)
    big_chance_created = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    team = db.relationship('Team')

    __table_args__ = (
        db.CheckConstraint(
            "delivery_type IN ('inswing', 'outswing', 'straight')",
            name='ck_corner_events_delivery_type'
        ),
        db.CheckConstraint(
            "delivery_outcome IN ('successful', 'unsuccessful')",
            name='ck_corner_events_delivery_outcome'
        ),
        db.CheckConstraint(
            "delivery_length IN ('short', 'long')",
            name='ck_corner_events_delivery_length'
        ),
    )

    def __repr__(self):
        return f'<CornerEvent Match:{self.match_id} Taker:{self.taker_player_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'team_id': self.team_id,
            'taker_player_id': self.taker_player_id,
            'won_by_player_id': self.won_by_player_id,
            'delivery_type': self.delivery_type,
            'delivery_outcome': self.delivery_outcome,
            'delivery_length': self.delivery_length,
            'led_to_shot': self.led_to_shot,
            'big_chance_created': self.big_chance_created,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class PlayerMatchStats(db.Model):
    """Player statistics for a specific match"""
    __tablename__ = 'player_match_stats'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    
    # Passing stats
    short_completed_passes = db.Column(db.Integer, default=0)
    short_incomplete_passes = db.Column(db.Integer, default=0)
    long_completed_passes = db.Column(db.Integer, default=0)
    long_incomplete_passes = db.Column(db.Integer, default=0)
    
    # Duel stats
    duels_won = db.Column(db.Integer, default=0)
    duels_lost = db.Column(db.Integer, default=0)
    aerial_duels_won = db.Column(db.Integer, default=0)
    aerial_duels_lost = db.Column(db.Integer, default=0)
    ground_duels_won = db.Column(db.Integer, default=0)
    ground_duels_lost = db.Column(db.Integer, default=0)
    
    # Shooting stats
    shots_on_target = db.Column(db.Integer, default=0)
    shots_off_target = db.Column(db.Integer, default=0)
    shots_blocked = db.Column(db.Integer, default=0)
    shots_inside_box = db.Column(db.Integer, default=0)
    shots_outside_box = db.Column(db.Integer, default=0)
    
    # Defensive stats
    tackles_won = db.Column(db.Integer, default=0)
    tackles_lost = db.Column(db.Integer, default=0)
    interceptions = db.Column(db.Integer, default=0)
    clearances = db.Column(db.Integer, default=0)
    pressures = db.Column(db.Integer, default=0)
    
    # Other stats
    fouls_committed = db.Column(db.Integer, default=0)
    fouls_won = db.Column(db.Integer, default=0)
    offsides = db.Column(db.Integer, default=0)
    yellow_cards = db.Column(db.Integer, default=0, nullable=False)
    red_cards = db.Column(db.Integer, default=0, nullable=False)
    
    # Passing variations
    successful_crosses = db.Column(db.Integer, default=0)
    unsuccessful_crosses = db.Column(db.Integer, default=0)
    throw_in_retained = db.Column(db.Integer, default=0)
    throw_in_lost = db.Column(db.Integer, default=0)
    recoveries = db.Column(db.Integer, default=0)
    progressive_runs = db.Column(db.Integer, default=0)
    touches_in_opposition_box = db.Column(db.Integer, default=0)
    
    # Pack pass stats
    pack_passes = db.Column(db.Integer, default=0)
    pack_pass_defenders = db.Column(db.Integer, default=0)
    pack_pass_midfielders = db.Column(db.Integer, default=0)
    pack_pass_attackers = db.Column(db.Integer, default=0)
    pack_pass_score = db.Column(db.Integer, default=0)
    pack_pass_receive_score = db.Column(db.Integer, default=0)
    
    # Pack turnover stats
    pack_turnovers = db.Column(db.Integer, default=0)
    pack_turnover_defenders = db.Column(db.Integer, default=0)
    pack_turnover_midfielders = db.Column(db.Integer, default=0)
    pack_turnover_attackers = db.Column(db.Integer, default=0)
    pack_turnover_score = db.Column(db.Integer, default=0)

    # Pack dribble stats
    pack_dribbles = db.Column(db.Integer, default=0)
    pack_dribble_defenders = db.Column(db.Integer, default=0)
    pack_dribble_midfielders = db.Column(db.Integer, default=0)
    pack_dribble_attackers = db.Column(db.Integer, default=0)
    pack_dribble_score = db.Column(db.Integer, default=0)
    pack_dribbled_past = db.Column(db.Integer, default=0)
    pack_dribbled_past_defenders = db.Column(db.Integer, default=0)
    pack_dribbled_past_midfielders = db.Column(db.Integer, default=0)
    pack_dribbled_past_attackers = db.Column(db.Integer, default=0)
    pack_dribbled_past_score = db.Column(db.Integer, default=0)
    
    # Shooting stats (advanced)
    goals = db.Column(db.Integer, default=0, nullable=False)
    assists = db.Column(db.Integer, default=0, nullable=False)
    xG = db.Column(db.Float, default=0.0)  # Expected goals
    xG_inside_box = db.Column(db.Float, default=0.0)
    xG_outside_box = db.Column(db.Float, default=0.0)
    xA = db.Column(db.Float, default=0.0)  # Expected assists
    chances_created = db.Column(db.Integer, default=0, nullable=False)
    big_chances_created = db.Column(db.Integer, default=0, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint to prevent duplicate entries
    __table_args__ = (db.UniqueConstraint('match_id', 'player_id', name='_match_player_uc'),)
    
    def __repr__(self):
        return f'<PlayerMatchStats Match:{self.match_id} Player:{self.player_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'player': self.player.to_dict() if self.player else None,
            'short_completed_passes': self.short_completed_passes,
            'short_incomplete_passes': self.short_incomplete_passes,
            'long_completed_passes': self.long_completed_passes,
            'long_incomplete_passes': self.long_incomplete_passes,
            'duels_won': self.duels_won,
            'duels_lost': self.duels_lost,
            'aerial_duels_won': self.aerial_duels_won,
            'aerial_duels_lost': self.aerial_duels_lost,
            'ground_duels_won': self.ground_duels_won,
            'ground_duels_lost': self.ground_duels_lost,
            'shots_on_target': self.shots_on_target,
            'shots_off_target': self.shots_off_target,
            'shots_blocked': self.shots_blocked,
            'shots_inside_box': self.shots_inside_box,
            'shots_outside_box': self.shots_outside_box,
            'tackles_won': self.tackles_won,
            'tackles_lost': self.tackles_lost,
            'interceptions': self.interceptions,
            'clearances': self.clearances,
            'pressures': self.pressures,
            'fouls_committed': self.fouls_committed,
            'fouls_won': self.fouls_won,
            'offsides': self.offsides,
            'yellow_cards': self.yellow_cards,
            'red_cards': self.red_cards,
            'progressive_runs': self.progressive_runs,
            'touches_in_opposition_box': self.touches_in_opposition_box,
            'goals': self.goals,
            'assists': self.assists,
            'xG': self.xG,
            'xG_inside_box': self.xG_inside_box,
            'xG_outside_box': self.xG_outside_box,
            'xA': self.xA,
            'chances_created': self.chances_created,
            'big_chances_created': self.big_chances_created
        }


class PackPassEvent(db.Model):
    """Pack pass event for a specific match"""
    __tablename__ = 'pack_pass_events'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    passer_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    score = db.Column(db.Integer, default=0, nullable=False)
    defenders = db.Column(db.Integer, default=0, nullable=False)
    midfielders = db.Column(db.Integer, default=0, nullable=False)
    attackers = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    match = db.relationship('Match', backref='pack_pass_events')
    team = db.relationship('Team')
    passer = db.relationship('Player', foreign_keys=[passer_id], backref='pack_passes_made')
    receiver = db.relationship('Player', foreign_keys=[receiver_id], backref='pack_passes_received')

    def __repr__(self):
        return f'<PackPassEvent Match:{self.match_id} Passer:{self.passer_id} Receiver:{self.receiver_id}>'


class PackTurnoverEvent(db.Model):
    """Pack turnover event for a specific match"""
    __tablename__ = 'pack_turnover_events'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    score = db.Column(db.Integer, default=0, nullable=False)
    defenders = db.Column(db.Integer, default=0, nullable=False)
    midfielders = db.Column(db.Integer, default=0, nullable=False)
    attackers = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    match = db.relationship('Match', backref='pack_turnover_events')
    team = db.relationship('Team')
    player = db.relationship('Player', backref='pack_turnovers_made')

    def __repr__(self):
        return f'<PackTurnoverEvent Match:{self.match_id} Player:{self.player_id}>'


class PackDribbleEvent(db.Model):
    """Pack dribble event for a specific match"""
    __tablename__ = 'pack_dribble_events'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    dribbler_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    score = db.Column(db.Integer, default=0, nullable=False)
    defenders = db.Column(db.Integer, default=0, nullable=False)
    midfielders = db.Column(db.Integer, default=0, nullable=False)
    attackers = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    match = db.relationship('Match', backref='pack_dribble_events')
    team = db.relationship('Team')
    dribbler = db.relationship('Player', backref='pack_dribbles_made')

    def __repr__(self):
        return f'<PackDribbleEvent Match:{self.match_id} Dribbler:{self.dribbler_id}>'


class PackDribbledPastPlayer(db.Model):
    """Main-team players dribbled past in a pack dribble event"""
    __tablename__ = 'pack_dribbled_past_players'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('pack_dribble_events.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    position_group = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event = db.relationship('PackDribbleEvent', backref='dribbled_past_players')
    player = db.relationship('Player', backref='pack_dribbled_past_events')

    def __repr__(self):
        return f'<PackDribbledPastPlayer Event:{self.event_id} Player:{self.player_id} Group:{self.position_group}>'


class GoalKeeperMatchStats(db.Model):
    """Goalkeeper statistics for a specific match"""
    __tablename__ = 'goalkeeper_match_stats'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    
    # Passing stats
    short_completed_passes = db.Column(db.Integer, default=0)
    short_incomplete_passes = db.Column(db.Integer, default=0)
    long_completed_passes = db.Column(db.Integer, default=0)
    long_incomplete_passes = db.Column(db.Integer, default=0)
    
    # Duel stats
    duels_won = db.Column(db.Integer, default=0)
    duels_lost = db.Column(db.Integer, default=0)
    aerial_duels_won = db.Column(db.Integer, default=0)
    aerial_duels_lost = db.Column(db.Integer, default=0)
    ground_duels_won = db.Column(db.Integer, default=0)
    ground_duels_lost = db.Column(db.Integer, default=0)
    
    # Defensive stats
    tackles_won = db.Column(db.Integer, default=0)
    tackles_lost = db.Column(db.Integer, default=0)
    interceptions = db.Column(db.Integer, default=0)
    clearances = db.Column(db.Integer, default=0)
    
    # Other stats
    fouls_committed = db.Column(db.Integer, default=0)
    fouls_won = db.Column(db.Integer, default=0)
    offsides = db.Column(db.Integer, default=0)
    recoveries = db.Column(db.Integer, default=0)
    
    # Pack pass stats
    pack_passes = db.Column(db.Integer, default=0)
    pack_pass_defenders = db.Column(db.Integer, default=0)
    pack_pass_midfielders = db.Column(db.Integer, default=0)
    pack_pass_attackers = db.Column(db.Integer, default=0)
    pack_pass_score = db.Column(db.Integer, default=0)
    pack_pass_receive_score = db.Column(db.Integer, default=0)
    
    # Pack turnover stats
    pack_turnovers = db.Column(db.Integer, default=0)
    pack_turnover_defenders = db.Column(db.Integer, default=0)
    pack_turnover_midfielders = db.Column(db.Integer, default=0)
    pack_turnover_attackers = db.Column(db.Integer, default=0)
    pack_turnover_score = db.Column(db.Integer, default=0)

    # Pack dribble stats
    pack_dribbles = db.Column(db.Integer, default=0)
    pack_dribble_defenders = db.Column(db.Integer, default=0)
    pack_dribble_midfielders = db.Column(db.Integer, default=0)
    pack_dribble_attackers = db.Column(db.Integer, default=0)
    pack_dribble_score = db.Column(db.Integer, default=0)
    pack_dribbled_past = db.Column(db.Integer, default=0)
    pack_dribbled_past_defenders = db.Column(db.Integer, default=0)
    pack_dribbled_past_midfielders = db.Column(db.Integer, default=0)
    pack_dribbled_past_attackers = db.Column(db.Integer, default=0)
    pack_dribbled_past_score = db.Column(db.Integer, default=0)
    
    # Goalkeeper specific stats
    saves = db.Column(db.Integer, default=0, nullable=False)
    saves_held = db.Column(db.Integer, default=0, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint to prevent duplicate entries
    __table_args__ = (db.UniqueConstraint('match_id', 'player_id', name='_goalkeeper_match_player_uc'),)
    
    # Relationships
    match = db.relationship('Match', backref='goalkeeper_stats')
    player = db.relationship('Player', backref='goalkeeper_match_stats')
    
    def __repr__(self):
        return f'<GoalKeeperMatchStats Match:{self.match_id} Player:{self.player_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'player': self.player.to_dict() if self.player else None,
            'short_completed_passes': self.short_completed_passes,
            'short_incomplete_passes': self.short_incomplete_passes,
            'long_completed_passes': self.long_completed_passes,
            'long_incomplete_passes': self.long_incomplete_passes,
            'duels_won': self.duels_won,
            'duels_lost': self.duels_lost,
            'aerial_duels_won': self.aerial_duels_won,
            'aerial_duels_lost': self.aerial_duels_lost,
            'ground_duels_won': self.ground_duels_won,
            'ground_duels_lost': self.ground_duels_lost,
            'tackles_won': self.tackles_won,
            'tackles_lost': self.tackles_lost,
            'interceptions': self.interceptions,
            'clearances': self.clearances,
            'fouls_committed': self.fouls_committed,
            'fouls_won': self.fouls_won,
            'offsides': self.offsides,
            'recoveries': self.recoveries,
            'pack_passes': self.pack_passes,
            'pack_pass_defenders': self.pack_pass_defenders,
            'pack_pass_midfielders': self.pack_pass_midfielders,
            'pack_pass_attackers': self.pack_pass_attackers,
            'pack_pass_score': self.pack_pass_score,
            'pack_pass_receive_score': self.pack_pass_receive_score,
            'pack_turnovers': self.pack_turnovers,
            'pack_turnover_defenders': self.pack_turnover_defenders,
            'pack_turnover_midfielders': self.pack_turnover_midfielders,
            'pack_turnover_attackers': self.pack_turnover_attackers,
            'pack_turnover_score': self.pack_turnover_score,
            'pack_dribbles': self.pack_dribbles,
            'pack_dribble_defenders': self.pack_dribble_defenders,
            'pack_dribble_midfielders': self.pack_dribble_midfielders,
            'pack_dribble_attackers': self.pack_dribble_attackers,
            'pack_dribble_score': self.pack_dribble_score,
            'pack_dribbled_past': self.pack_dribbled_past,
            'pack_dribbled_past_defenders': self.pack_dribbled_past_defenders,
            'pack_dribbled_past_midfielders': self.pack_dribbled_past_midfielders,
            'pack_dribbled_past_attackers': self.pack_dribbled_past_attackers,
            'pack_dribbled_past_score': self.pack_dribbled_past_score,
            'saves': self.saves,
            'saves_held': self.saves_held
        }


class MatchLineup(db.Model):
    """Starting lineup for a match"""
    __tablename__ = 'match_lineups'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    position = db.Column(db.String(20))  # e.g., GK, CB, CM, ST
    shirt_number = db.Column(db.Integer)
    
    # Relationships
    player = db.relationship('Player', backref='lineup_appearances')
    team = db.relationship('Team')
    
    def __repr__(self):
        return f'<MatchLineup Match:{self.match_id} Player:{self.player_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'match_id': self.match_id,
            'player': self.player.to_dict() if self.player else None,
            'team': self.team.to_dict() if self.team else None,
            'position': self.position,
            'shirt_number': self.shirt_number
        }
