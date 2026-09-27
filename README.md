# Football Match Data Recorder

A web application for recording and managing football match data built with Python Flask and PostgreSQL.

## Features

- **Team Management**: Add and view teams with details like city and country
- **Match Recording**: Record match details including scores, venue, competition, and season
- **Player Management**: Track players with positions, jersey numbers, and personal details
- **Match Events**: Record match events like goals, cards, and substitutions
- **Player Statistics Tracking**: Record detailed player stats during matches with easy click buttons:
  - Passing: Completed/Incomplete passes
  - Duels: Won/Lost
  - Shooting: On/Off target
  - Defense: Tackles, Interceptions, Clearances
  - Other: Fouls, Offsides
- **Real-time Stat Updates**: Click buttons to increment/decrement stats while watching matches
- **PDF Export (Team Summary / Shot Summary)**: Export key team metrics for a match, including a shot-focused summary without Completed Passes and Team Packing Score
- **Clean UI**: Modern, responsive interface for easy data entry
- **API Endpoints**: RESTful API for programmatic access to match and team data

## Database Models

- **Teams**: Store team information
- **Matches**: Record match details and scores
- **Players**: Track player information
- **Match Events**: Record goals, cards, substitutions during matches
- **Player Match Stats**: Detailed player statistics for each match

## Prerequisites

- Python 3.8+
- PostgreSQL database
- pip (Python package manager)

## Installation

1. **Clone or navigate to the repository**:
   ```bash
   cd football-data
   ```

2. **Install dependencies**:
   ```bash
   python -m pip install -r requirements.txt
   ```

3. **Set up PostgreSQL database**:
   - Create a new PostgreSQL database named `football_data`
   - Update the database connection string in `.env` file

4. **Configure environment variables**:
   - Copy `.env.example` to `.env`
   - Update the `DATABASE_URL` with your PostgreSQL credentials:
     ```
     DATABASE_URL=postgresql://username:password@localhost:5432/football_data
     ```

5. **Initialize the database**:
   ```bash
   python app.py
   ```
   The application will automatically create the necessary tables on first run.

## Running the Application

Start the Flask development server:

```bash
python app.py
```

The application will be available at `http://localhost:5000`

## CI/CD: Build and Push to Amazon ECR

This repository includes a GitHub Actions workflow at `.github/workflows/build-and-push-ecr.yml`.
It runs only when triggered manually (Actions → Run workflow, or `gh workflow run build-and-push-ecr.yml`). It:

1. Builds the Docker image from `Dockerfile`
2. Authenticates to AWS using GitHub OIDC
3. Creates the ECR repository if it does not exist
4. Pushes image tags:
    - `<ecr-registry>/<repository>:<git-sha>`
    - `<ecr-registry>/<repository>:latest`

Set the following in your GitHub repository settings before running the workflow:

- **Actions Secret**
   - `AWS_ROLE_TO_ASSUME`: IAM role ARN trusted for GitHub OIDC and allowed to push to ECR

- **Actions Variables**
   - `AWS_REGION`: AWS region for ECR (for example, `eu-west-1`)
   - `ECR_REPOSITORY`: ECR repository name (for example, `football-data`)

Minimum IAM permissions for the role should include ECR push permissions, such as:

- `ecr:GetAuthorizationToken`
- `ecr:BatchCheckLayerAvailability`
- `ecr:InitiateLayerUpload`
- `ecr:UploadLayerPart`
- `ecr:CompleteLayerUpload`
- `ecr:PutImage`
- `ecr:DescribeRepositories`
- `ecr:CreateRepository`

## Usage

1. **Add Teams**: Navigate to the Teams section and add the teams you want to track
2. **Record Matches**: Go to Matches and click "Record New Match" to add match details
3. **Add Players**: Add players and associate them with teams
4. **Track Events**: On the match detail page, add events like goals and cards
5. **View Statistics**: Browse through team histories and match records

## API Endpoints

- `GET /api/matches` - Get all matches as JSON
- `GET /api/teams` - Get all teams as JSON

## Project Structure

```
football-data/
├── app.py              # Main Flask application
├── models.py           # Database models
├── config.py           # Configuration settings
├── requirements.txt    # Python dependencies
├── templates/          # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── matches.html
│   ├── match_form.html
│   ├── match_detail.html
│   ├── teams.html
│   ├── team_form.html
│   ├── team_detail.html
│   ├── players.html
│   └── player_form.html
└── .env               # Environment variables (create from .env.example)
```

## Technologies Used

- **Flask**: Web framework
- **Flask-SQLAlchemy**: ORM for database operations
- **Flask-Migrate**: Database migrations
- **PostgreSQL**: Database
- **psycopg2**: PostgreSQL adapter for Python
- **python-dotenv**: Environment variable management

## Future Enhancements

- User authentication and authorization
- Advanced statistics and analytics
- Export data to CSV/Excel
- Player statistics tracking
- Match highlights and videos
- Mobile responsive design improvements
- Search and filter functionality

## License

This project is open source and available for personal and educational use.
