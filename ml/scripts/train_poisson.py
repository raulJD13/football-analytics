"""train_poisson.py — Poisson match outcome predictor for LaLiga.

Model logic
-----------
Goals scored by each side in a match are modelled as independent Poisson
random variables:

    H ~ Poisson(λ_home)
    A ~ Poisson(λ_away)

where:
    λ_home = attack_home × defence_away × HOME_ADVANTAGE × league_avg_goals
    λ_away = attack_away × defence_home × league_avg_goals

    attack_home    = team's home avg goals scored   / league_avg_goals
    defence_away   = opponent's away avg goals conceded / league_avg_goals
    attack_away    = team's away avg goals scored   / league_avg_goals
    defence_home   = opponent's home avg goals conceded / league_avg_goals

P(home wins), P(draw), P(away wins) are computed by summing the joint PMF
over a goal grid [0..MAX_GOALS] × [0..MAX_GOALS].

MLflow
------
Experiment : football-match-prediction
Registered : poisson-match-predictor  (alias: Production after training)

Usage
-----
    python ml/scripts/train_poisson.py [--mlflow-uri http://localhost:5000]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import poisson as scipy_poisson

import clickhouse_connect
import mlflow
import mlflow.pyfunc

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────
HOME_ADVANTAGE = 1.2          # historical home goal-scoring boost
MAX_GOALS = 10                # upper bound for PMF grid
REGISTERED_MODEL = "poisson-match-predictor"
EXPERIMENT_NAME = "football-match-prediction"


# ── Poisson predictor (MLflow pyfunc) ────────────────────────────────────────

class PoissonPredictor(mlflow.pyfunc.PythonModel):
    """Wraps team-strength parameters and Poisson prediction logic.

    Accepts a DataFrame with columns [home_team_id, away_team_id] and
    returns a DataFrame with [home_win, draw, away_win,
    expected_home_goals, expected_away_goals].
    """

    def load_context(self, context: mlflow.pyfunc.PythonModelContext) -> None:
        """Load the JSON artifact saved during training."""
        path = context.artifacts["team_params"]
        with open(path) as f:
            params = json.load(f)
        self._strengths: dict[str, dict[str, float]] = params["team_strengths"]
        self._league_avg: float = params["league_avg_goals"]
        self._home_advantage: float = params["home_advantage"]

    # called directly in training (before MLflow wraps the instance)
    def _init_from_params(self, params: dict) -> None:
        self._strengths = params["team_strengths"]
        self._league_avg = params["league_avg_goals"]
        self._home_advantage = params["home_advantage"]

    def _lambdas(self, home_id: int, away_id: int) -> tuple[float, float]:
        """Compute expected goal rates for both sides."""
        default = {"home_attack": 1.0, "home_defence": 1.0,
                   "away_attack": 1.0, "away_defence": 1.0}
        h = self._strengths.get(str(home_id), default)
        a = self._strengths.get(str(away_id), default)

        lam_home = (
            h["home_attack"] * a["away_defence"]
            * self._home_advantage * self._league_avg
        )
        lam_away = a["away_attack"] * h["home_defence"] * self._league_avg
        return lam_home, lam_away

    def _poisson_probs(
        self, lam_home: float, lam_away: float
    ) -> tuple[float, float, float]:
        """Sum PMF over goal grid → (P_home_win, P_draw, P_away_win)."""
        goals = np.arange(MAX_GOALS + 1)
        pmf_h = scipy_poisson.pmf(goals, lam_home)   # shape (11,)
        pmf_a = scipy_poisson.pmf(goals, lam_away)   # shape (11,)
        # outer product → (11, 11) joint probability matrix
        joint = np.outer(pmf_h, pmf_a)

        home_win = float(np.tril(joint, k=-1).sum())   # rows > cols
        draw = float(np.trace(joint))
        away_win = float(np.triu(joint, k=1).sum())    # rows < cols

        total = home_win + draw + away_win
        return home_win / total, draw / total, away_win / total

    def predict(
        self,
        context: mlflow.pyfunc.PythonModelContext | None,
        model_input: pd.DataFrame,
    ) -> pd.DataFrame:
        """Predict match outcome probabilities.

        Parameters
        ----------
        model_input : DataFrame with columns ``home_team_id``, ``away_team_id``

        Returns
        -------
        DataFrame with columns:
            home_win, draw, away_win  (probabilities summing to 1)
            expected_home_goals, expected_away_goals
        """
        rows = []
        for _, row in model_input.iterrows():
            lh, la = self._lambdas(int(row["home_team_id"]), int(row["away_team_id"]))
            ph, pd_, pa = self._poisson_probs(lh, la)
            rows.append({
                "home_win": round(ph, 4),
                "draw": round(pd_, 4),
                "away_win": round(pa, 4),
                "expected_home_goals": round(lh, 3),
                "expected_away_goals": round(la, 3),
            })
        return pd.DataFrame(rows)


# ── data loading ─────────────────────────────────────────────────────────────

def load_team_stats(client: clickhouse_connect.driver.Client) -> pd.DataFrame:
    """Load per-team home/away averages from mart_team_stats."""
    query = """
        SELECT
            team_id,
            home_avg_goals_scored,
            home_avg_goals_conceded,
            away_avg_goals_scored,
            away_avg_goals_conceded
        FROM football.mart_team_stats
    """
    return client.query_df(query)


def load_finished_matches(client: clickhouse_connect.driver.Client) -> pd.DataFrame:
    """Load finished matches with known outcomes from mart_match_features."""
    query = """
        SELECT
            match_id,
            home_team_id,
            away_team_id,
            home_goals,
            away_goals,
            result
        FROM football.mart_match_features
        WHERE result IN ('H', 'D', 'A')
          AND home_goals IS NOT NULL
          AND away_goals IS NOT NULL
    """
    return client.query_df(query)


# ── strength computation ──────────────────────────────────────────────────────

def build_team_params(stats: pd.DataFrame, league_avg: float) -> dict:
    """Build the team-strength lookup dict saved as a model artifact.

    Returns a JSON-serialisable dict:
        {
          "team_strengths": {
              "<team_id>": {
                  "home_attack":   float,  # home avg scored / league avg
                  "home_defence":  float,  # home avg conceded / league avg
                  "away_attack":   float,  # away avg scored / league avg
                  "away_defence":  float,  # away avg conceded / league avg
              }, ...
          },
          "league_avg_goals": float,
          "home_advantage":   float,
        }
    """
    strengths: dict[str, dict[str, float]] = {}
    for _, row in stats.iterrows():
        tid = str(int(row["team_id"]))
        # Fill NaN (teams with no home/away games yet) with 1.0 (league average)
        ha = float(row["home_avg_goals_scored"]) if pd.notna(row["home_avg_goals_scored"]) else league_avg
        hd = float(row["home_avg_goals_conceded"]) if pd.notna(row["home_avg_goals_conceded"]) else league_avg
        aa = float(row["away_avg_goals_scored"]) if pd.notna(row["away_avg_goals_scored"]) else league_avg
        ad = float(row["away_avg_goals_conceded"]) if pd.notna(row["away_avg_goals_conceded"]) else league_avg

        strengths[tid] = {
            "home_attack":  round(ha / league_avg, 4),
            "home_defence": round(hd / league_avg, 4),
            "away_attack":  round(aa / league_avg, 4),
            "away_defence": round(ad / league_avg, 4),
        }

    return {
        "team_strengths": strengths,
        "league_avg_goals": round(league_avg, 4),
        "home_advantage": HOME_ADVANTAGE,
    }


# ── evaluation ────────────────────────────────────────────────────────────────

def evaluate(
    matches: pd.DataFrame,
    predictor: PoissonPredictor,
) -> dict[str, float]:
    """Compute accuracy, log-loss, and Brier score vs two baselines.

    Returns a flat dict ready for ``mlflow.log_metrics``.
    """
    input_df = matches[["home_team_id", "away_team_id"]]
    preds = predictor.predict(None, input_df)

    actual = matches["result"].values                  # 'H', 'D', 'A'
    n = len(actual)

    # ── Poisson accuracy (argmax prediction) ─────────────────────────────────
    pred_labels = np.where(
        (preds["home_win"] >= preds["draw"]) & (preds["home_win"] >= preds["away_win"]),
        "H",
        np.where(preds["draw"] >= preds["away_win"], "D", "A"),
    )
    accuracy = float((pred_labels == actual).sum() / n)

    # ── Log-loss (cross-entropy) ──────────────────────────────────────────────
    eps = 1e-7
    log_loss = 0.0
    for i, res in enumerate(actual):
        p = {"H": preds.iloc[i]["home_win"],
             "D": preds.iloc[i]["draw"],
             "A": preds.iloc[i]["away_win"]}[res]
        log_loss -= np.log(np.clip(p, eps, 1 - eps))
    log_loss /= n

    # ── Brier score (mean squared error of probability vector) ───────────────
    brier = 0.0
    for i, res in enumerate(actual):
        y = {"H": np.array([1, 0, 0]),
             "D": np.array([0, 1, 0]),
             "A": np.array([0, 0, 1])}[res]
        p_vec = np.array([preds.iloc[i]["home_win"],
                          preds.iloc[i]["draw"],
                          preds.iloc[i]["away_win"]])
        brier += float(np.sum((p_vec - y) ** 2))
    brier /= n

    # ── Baseline 1: always predict home win ──────────────────────────────────
    baseline_home_acc = float((actual == "H").sum() / n)

    # ── Baseline 2: most frequent outcome ────────────────────────────────────
    most_common = pd.Series(actual).value_counts().idxmax()
    baseline_freq_acc = float((actual == most_common).sum() / n)

    log.info(
        "Poisson accuracy %.3f | baseline_home %.3f | baseline_freq %.3f (%s)",
        accuracy, baseline_home_acc, baseline_freq_acc, most_common,
    )

    return {
        "accuracy": accuracy,
        "log_loss": log_loss,
        "brier_score": brier,
        "baseline_always_home_win_accuracy": baseline_home_acc,
        "baseline_most_frequent_accuracy": baseline_freq_acc,
        "n_matches_evaluated": float(n),
        "home_win_rate_actual": float((actual == "H").sum() / n),
        "draw_rate_actual": float((actual == "D").sum() / n),
        "away_win_rate_actual": float((actual == "A").sum() / n),
    }


# ── training entry point ──────────────────────────────────────────────────────

def train(
    ch_host: str = "localhost",
    ch_port: int = 8124,
    ch_db: str = "football",
    mlflow_uri: str = "http://localhost:5000",
) -> str:
    """Run the full training pipeline and return the MLflow run ID."""
    # ── connect ───────────────────────────────────────────────────────────────
    log.info("Connecting to ClickHouse at %s:%d/%s", ch_host, ch_port, ch_db)
    client = clickhouse_connect.get_client(host=ch_host, port=ch_port, database=ch_db)

    # ── load data ─────────────────────────────────────────────────────────────
    log.info("Loading team stats …")
    stats = load_team_stats(client)
    log.info("  %d teams loaded", len(stats))

    log.info("Loading finished matches …")
    matches = load_finished_matches(client)
    log.info("  %d finished matches loaded", len(matches))

    # ── compute league average: total goals / total matches ───────────────────
    league_avg = float(
        (matches["home_goals"].astype(float) + matches["away_goals"].astype(float)).mean()
    )
    log.info("League average goals per match: %.4f", league_avg)

    # ── build team parameters ─────────────────────────────────────────────────
    params = build_team_params(stats, league_avg)

    # ── instantiate and evaluate predictor ───────────────────────────────────
    predictor = PoissonPredictor()
    predictor._init_from_params(params)
    metrics = evaluate(matches, predictor)

    # ── MLflow ────────────────────────────────────────────────────────────────
    mlflow.set_tracking_uri(mlflow_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)

    with mlflow.start_run(run_name="poisson_model") as run:
        # Parameters
        mlflow.log_params({
            "home_advantage": HOME_ADVANTAGE,
            "max_goals_grid": MAX_GOALS,
            "league_avg_goals": round(league_avg, 4),
            "n_teams": len(stats),
            "competition": "LaLiga (PD)",
        })

        # Metrics
        mlflow.log_metrics(metrics)

        # Artifact: team strength JSON
        # We use log_artifact (works with both MLflow 2.x and 3.x) rather than
        # pyfunc.log_model to avoid the v3 "logged-models" server endpoint that
        # does not exist in the MLflow 2.11 Docker image.
        with tempfile.TemporaryDirectory() as tmpdir:
            params_path = Path(tmpdir) / "team_params.json"
            params_path.write_text(json.dumps(params, indent=2))
            mlflow.log_artifact(str(params_path), artifact_path="model")

        run_id = run.info.run_id
        log.info("MLflow run %s logged to experiment '%s'", run_id, EXPERIMENT_NAME)

    # ── register as Production ────────────────────────────────────────────────
    model_uri = f"runs:/{run_id}/model"
    client_mlflow = mlflow.tracking.MlflowClient(mlflow_uri)

    # Create registered model if it doesn't exist yet
    try:
        client_mlflow.create_registered_model(REGISTERED_MODEL)
        log.info("Created registered model '%s'", REGISTERED_MODEL)
    except mlflow.exceptions.MlflowException:
        pass  # already exists

    mv = client_mlflow.create_model_version(
        name=REGISTERED_MODEL,
        source=model_uri,
        run_id=run_id,
    )
    client_mlflow.set_registered_model_alias(REGISTERED_MODEL, "Production", mv.version)
    log.info(
        "Registered '%s' version %s as Production", REGISTERED_MODEL, mv.version
    )

    return run_id


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train the Poisson match predictor.")
    # CLICKHOUSE_HOST in .env is the Docker service name; host-side scripts use localhost
    p.add_argument("--ch-host", default="localhost")
    p.add_argument("--ch-port", type=int, default=int(os.getenv("CLICKHOUSE_PORT", "8124")))
    p.add_argument("--ch-db", default=os.getenv("CLICKHOUSE_DB", "football"))
    # MLFLOW_TRACKING_URI in .env is the Docker service name; host-side scripts use localhost:5001
    # (port 5000 is occupied by macOS AirPlay Receiver)
    p.add_argument("--mlflow-uri", default="http://localhost:5001")
    return p.parse_args()


if __name__ == "__main__":
    # Load .env if python-dotenv is available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    args = _parse_args()
    run_id = train(
        ch_host=args.ch_host,
        ch_port=args.ch_port,
        ch_db=args.ch_db,
        mlflow_uri=args.mlflow_uri,
    )
    log.info("Done. Run ID: %s", run_id)
