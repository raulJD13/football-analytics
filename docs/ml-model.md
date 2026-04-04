# ML Model

## Level 1 — Poisson model (no sklearn)
Input features (from dbt marts):
  - attack_strength  = avg_goals_scored / league_avg
  - defence_weakness = avg_goals_conceded / league_avg
  - home_advantage   = historical home factor (~1.2)
Output: P(home wins), P(draw), P(away wins)
Script: ml/scripts/train_poisson.py

## Level 2 — XGBoost classifier
Target: result ∈ {H, D, A}
Features (from mart_match_features):
  - home_form_5, away_form_5
  - home_attack_strength, away_defence_weakness
  - h2h_home_win_rate
  - home_rest_days, away_rest_days
  - position_diff
Script: ml/scripts/train_classifier.py

## MLflow
Tracking URI: http://localhost:5000
Experiment: football-match-prediction
Model registry: production / staging tags
Retrain DAG: dags/retrain_model.py (every Monday 03:00)

## Evaluation
Baselines to beat:
  - "always predict home win" → ~45% accuracy LaLiga
  - "predict most frequent result" → ~48% accuracy
Target: > 52% accuracy on held-out last season
