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

export interface FeatureContribution {
  feature: string;
  value: number;
  contribution: number;
}

export interface PredictExplainResponse extends PredictResponse {
  top_contributions: FeatureContribution[];
  explanation_label: string;
}

export interface FeatureImportanceEntry {
  name: string;
  importance: number;
}

export interface ModelMetricsResponse {
  model_name: string;
  model_version: string;
  accuracy: number;
  brier_score: number;
  log_loss: number | null;
  baseline_accuracy: number;
  feature_importance: FeatureImportanceEntry[];
}

export interface FixtureEntry {
  match_id: number;
  match_date: string;
  status: string;
  matchday: number | null;
  home_team_id: number;
  home_team_name: string;
  away_team_id: number;
  away_team_name: string;
  home_goals: number | null;
  away_goals: number | null;
  home_win: number | null;
  draw: number | null;
  away_win: number | null;
  expected_home_goals: number | null;
  expected_away_goals: number | null;
}

export interface FixturesResponse {
  season: number;
  fixtures: FixtureEntry[];
}

export interface HeadToHeadMatch {
  match_id: number;
  match_date: string;
  home_team_name: string;
  away_team_name: string;
  home_goals: number | null;
  away_goals: number | null;
  result: string;
}

export interface MatchDetailResponse {
  fixture: FixtureEntry;
  home_form: FormMatch[];
  away_form: FormMatch[];
  head_to_head: HeadToHeadMatch[];
  top_contributions: FeatureContribution[];
  explanation_label: string | null;
}

export interface TeamXgPoint {
  match_id: number;
  match_date: string;
  opponent_team_id: number;
  is_home: boolean;
  expected_goals_for: number;
  expected_goals_against: number;
  cumulative_expected_goals_for: number;
  cumulative_expected_goals_against: number;
}

export interface TeamXgResponse {
  team_id: number;
  points: TeamXgPoint[];
}

// ── Fetchers ───────────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export function currentSeasonStartYear(today = new Date()): number {
  const month = today.getUTCMonth() + 1;
  const year = today.getUTCFullYear();
  return month >= 8 ? year : year - 1;
}

export function fetchStandings(
  league = "PD",
  season = currentSeasonStartYear(),
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

export function fetchTeamXg(teamId: number): Promise<TeamXgResponse> {
  return get(`/api/teams/${teamId}/xg`);
}

export function fetchModelMetrics(): Promise<ModelMetricsResponse> {
  return get("/api/model/metrics");
}

export function fetchFixtures(limit = 12): Promise<FixturesResponse> {
  return get(`/api/fixtures?limit=${limit}`);
}

export function fetchMatchDetail(matchId: number): Promise<MatchDetailResponse> {
  return get(`/api/fixtures/${matchId}`);
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

export async function postPredictExplain(
  body: PredictRequest,
): Promise<PredictExplainResponse> {
  const res = await fetch("/api/predict/explain", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST /api/predict/explain failed: ${res.status}`);
  return res.json() as Promise<PredictExplainResponse>;
}
