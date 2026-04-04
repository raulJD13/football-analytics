/* All FastAPI calls go through the Next.js rewrite (/api/* → localhost:8000/*). */

// ── Types ──────────────────────────────────────────────────────────────────

export interface StandingEntry {
  position: number;
  team_id: number;
  team_name: string;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number | null;
  goals_against: number | null;
  goal_difference: number | null;
  points: number;
  form_last_5: string;
  projected_points: number;
}

export interface StandingsResponse {
  league: string;
  season: number;
  standings: StandingEntry[];
}

export interface HomeAwayStats {
  played: number;
  won: number;
  drawn: number;
  lost: number;
  points: number;
  goals_for: number | null;
  goals_against: number | null;
  avg_goals_scored: number | null;
  avg_goals_conceded: number | null;
  points_per_game: number;
  clean_sheets: number;
  defensive_variance: number | null;
}

export interface TeamStatsResponse {
  team_id: number;
  team_name: string;
  home: HomeAwayStats;
  away: HomeAwayStats;
  home_attack_strength: number | null;
  away_defence_weakness: number | null;
}

export interface FormMatch {
  match_id: number;
  match_date: string;
  is_home: boolean;
  opponent_team_id: number;
  team_goals: number | null;
  opponent_goals: number | null;
  outcome: "W" | "D" | "L";
  points: number;
}

export interface TeamFormResponse {
  team_id: number;
  matches: FormMatch[];
}

export interface PredictRequest {
  home_team_id: number;
  away_team_id: number;
}

export interface PredictResponse {
  home_team_id: number;
  away_team_id: number;
  home_win: number;
  draw: number;
  away_win: number;
  expected_home_goals: number;
  expected_away_goals: number;
  model_version: string;
}

// ── Fetchers ───────────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export function fetchStandings(
  league = "PD",
  season = 2024,
): Promise<StandingsResponse> {
  return get(`/api/standings?league=${league}&season=${season}`);
}

export function fetchTeamStats(teamId: number): Promise<TeamStatsResponse> {
  return get(`/api/teams/${teamId}/stats`);
}

export function fetchTeamForm(
  teamId: number,
  n = 10,
): Promise<TeamFormResponse> {
  return get(`/api/teams/${teamId}/form?n=${n}`);
}

export async function postPredict(
  body: PredictRequest,
): Promise<PredictResponse> {
  const res = await fetch("/api/predict", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST /api/predict failed: ${res.status}`);
  return res.json() as Promise<PredictResponse>;
}
