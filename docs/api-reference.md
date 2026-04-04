# API Reference

## football-data.org
Base URL: https://api.football-data.org/v4
Auth: X-Auth-Token header (FOOTBALL_API_KEY)
Rate limit: 10 req/min (free tier)

### Endpoints used
GET /competitions/PD/matches          # LaLiga partidos
GET /competitions/PD/standings        # Clasificación
GET /competitions/PD/scorers          # Goleadores
GET /matches/{id}                     # Partido específico

Competition codes: PD=LaLiga, PL=Premier, BL1=Bundesliga, SA=SerieA

## API-Football
Base URL: https://v3.football.api-sports.io
Auth: x-apisports-key header (API_FOOTBALL_KEY)
Rate limit: 100 req/day (free tier)

### Endpoints used
GET /fixtures?league=140&season=2024  # LaLiga fixtures
GET /fixtures/statistics?fixture={id} # Stats por partido
