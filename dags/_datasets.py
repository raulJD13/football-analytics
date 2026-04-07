"""Shared Airflow datasets used to trigger downstream automation DAGs."""

from __future__ import annotations

from airflow.datasets import Dataset


RAW_MATCHES_DATASET = Dataset("football://raw/matches")
RAW_STANDINGS_DATASET = Dataset("football://raw/standings")
RAW_SCORERS_DATASET = Dataset("football://raw/scorers")
RAW_ADVANCED_STATS_DATASET = Dataset("football://raw/advanced-stats")
