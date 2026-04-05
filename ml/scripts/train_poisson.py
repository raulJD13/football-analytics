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

def load_finished_matches(client: clickhouse_connect.driver.Client) -> pd.DataFrame:
    """Load finished matches with known outcomes from mart_match_features."""
    query = """
        SELECT
            match_id,
            match_date,
            home_team_id,
            away_team_id,
            home_goals,
            away_goals,
            result
        FROM football.mart_match_features
        WHERE result IN ('H', 'D', 'A')
          AND home_goals IS NOT NULL
          AND away_goals IS NOT NULL
        ORDER BY match_date
    """
    return client.query_df(query)


# ── train / holdout split ─────────────────────────────────────────────────────

def _season_year(date: pd.Timestamp) -> int:
    """August-anchored season year: Aug 2024 → 2024, May 2025 → 2024."""
    ts = pd.Timestamp(date)
    return ts.year if ts.month >= 8 else ts.year - 1


def split_train_holdout(
    matches: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split into train (all seasons except last) and holdout (last season only).

    The holdout set is never seen during parameter fitting, giving a true
    out-of-sample accuracy estimate.
    """
    seasons = matches["match_date"].apply(_season_year)
    latest_season = int(seasons.max())
    train = matches[seasons < latest_season].copy()
    holdout = matches[seasons == latest_season].copy()

    n_train_seasons = seasons[seasons < latest_season].nunique()
    log.info(
        "Season split — train: %d matches (%d seasons) | holdout: %d matches "
        "(season %d/%d)",
        len(train), n_train_seasons,
        len(holdout), latest_season, latest_season + 1,
    )
    return train, holdout


# ── strength computation ──────────────────────────────────────────────────────

def build_team_params(matches: pd.DataFrame, league_avg: float) -> dict:
    """Compute team-strength params from *match rows* (not from mart_team_stats).

    This allows calling it with train-only data so holdout matches never
    influence the fitted parameters.

    Unpivots each match into two per-team rows (home + away), then computes
    per-team averages.  Teams absent from ``matches`` fall back to league avg
    (neutral strength = 1.0 ratio).

    Returns a JSON-serialisable dict:
        {
          "team_strengths": {
              "<team_id>": {
                  "home_attack":   float,   # home avg scored  / league avg
                  "home_defence":  float,   # home avg conceded / league avg
                  "away_attack":   float,   # away avg scored  / league avg
                  "away_defence":  float,   # away avg conceded / league avg
              }, ...
          },
          "league_avg_goals": float,
          "home_advantage":   float,
        }
    """
    # Unpivot: one row per (team, match) perspective
    home_rows = matches[["home_team_id", "home_goals", "away_goals"]].rename(
        columns={"home_team_id": "team_id", "home_goals": "scored", "away_goals": "conceded"}
    ).assign(is_home=True)
    away_rows = matches[["away_team_id", "away_goals", "home_goals"]].rename(
        columns={"away_team_id": "team_id", "away_goals": "scored", "home_goals": "conceded"}
    ).assign(is_home=False)
    df = pd.concat([home_rows, away_rows], ignore_index=True)
    df["scored"] = pd.to_numeric(df["scored"], errors="coerce")
    df["conceded"] = pd.to_numeric(df["conceded"], errors="coerce")

    strengths: dict[str, dict[str, float]] = {}
    for team_id, grp in df.groupby("team_id"):
        home = grp[grp["is_home"]]
        away = grp[~grp["is_home"]]

        def _avg(series: pd.Series) -> float:
            v = series.mean()
            return float(v) if pd.notna(v) else league_avg

        strengths[str(int(team_id))] = {
            "home_attack":  round(_avg(home["scored"])   / league_avg, 4),
            "home_defence": round(_avg(home["conceded"]) / league_avg, 4),
            "away_attack":  round(_avg(away["scored"])   / league_avg, 4),
            "away_defence": round(_avg(away["conceded"]) / league_avg, 4),
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

    # ── load all finished matches ─────────────────────────────────────────────
    log.info("Loading finished matches …")
    all_matches = load_finished_matches(client)
    log.info("  %d finished matches loaded", len(all_matches))

    # ── train / holdout split by season ──────────────────────────────────────
    # Team params are fit on train only → holdout is truly out-of-sample.
    train_matches, holdout_matches = split_train_holdout(all_matches)

    one_season_only = len(train_matches) == 0
    if one_season_only:
        log.warning(
            "Only one season available — falling back to in-sample evaluation."
        )
        train_matches = all_matches

    # ── league average from TRAIN only ───────────────────────────────────────
    league_avg = float(
        (train_matches["home_goals"].astype(float)
         + train_matches["away_goals"].astype(float)).mean()
    )
    log.info("League average goals per match (train): %.4f", league_avg)

    # ── build team parameters from TRAIN only ────────────────────────────────
    params = build_team_params(train_matches, league_avg)

    # ── instantiate predictor ─────────────────────────────────────────────────
    predictor = PoissonPredictor()
    predictor._init_from_params(params)

    # ── out-of-sample evaluation (primary) ───────────────────────────────────
    eval_set = holdout_matches if not one_season_only else all_matches
    oos_metrics = evaluate(eval_set, predictor)

    # ── in-sample evaluation (for overfitting diagnosis) ─────────────────────
    is_metrics = evaluate(train_matches, predictor)

    improvement = oos_metrics["accuracy"] - oos_metrics["baseline_always_home_win_accuracy"]
    log.info(
        "OUT-OF-SAMPLE → accuracy=%.3f | baseline_home=%.3f | improvement=%+.3f pp | "
        "brier=%.4f | log_loss=%.4f",
        oos_metrics["accuracy"],
        oos_metrics["baseline_always_home_win_accuracy"],
        improvement,
        oos_metrics["brier_score"],
        oos_metrics["log_loss"],
    )

    # ── MLflow ────────────────────────────────────────────────────────────────
    mlflow.set_tracking_uri(mlflow_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)

    with mlflow.start_run(run_name="poisson_model") as run:
        # Parameters
        mlflow.log_params({
            "home_advantage": HOME_ADVANTAGE,
            "max_goals_grid": MAX_GOALS,
            "league_avg_goals": round(league_avg, 4),
            "n_teams": len(params["team_strengths"]),
            "competition": "LaLiga (PD)",
            "eval_strategy": "last_season_holdout",
        })

        # Out-of-sample metrics (the real numbers)
        mlflow.log_metrics({
            "accuracy_out_of_sample":    oos_metrics["accuracy"],
            "brier_score_out_of_sample": oos_metrics["brier_score"],
            "log_loss_out_of_sample":    oos_metrics["log_loss"],
            "baseline_home_win":         oos_metrics["baseline_always_home_win_accuracy"],
            "baseline_most_frequent":    oos_metrics["baseline_most_frequent_accuracy"],
            "improvement_vs_baseline":   improvement,
            "n_holdout_matches":         float(len(eval_set)),
            # In-sample for comparison / overfitting check
            "accuracy_in_sample":        is_metrics["accuracy"],
            "n_train_matches":           float(len(train_matches)),
        })

        # Artifact: team strength JSON fitted on train data
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
    # Load .env — but remove Docker-internal URIs so the CLI defaults (localhost)
    # are used when running from the host.
    try:
        import os as _os
        from dotenv import load_dotenv
        load_dotenv()
        # .env sets MLFLOW_TRACKING_URI=http://mlflow:5000 (Docker-internal).
        # Host scripts must use localhost:5001 instead; let --mlflow-uri control it.
        _os.environ.pop("MLFLOW_TRACKING_URI", None)
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
