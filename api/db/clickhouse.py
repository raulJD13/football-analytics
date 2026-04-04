"""Shared ClickHouse client factory."""

from __future__ import annotations

import os

import clickhouse_connect
import clickhouse_connect.driver


def get_client() -> clickhouse_connect.driver.Client:
    """Return a ClickHouse client using environment variables.

    Inside Docker: CLICKHOUSE_HOST=clickhouse, port 8123.
    From the host: CLICKHOUSE_HOST defaults to localhost, port 8124.
    """
    host = os.getenv("CLICKHOUSE_HOST", "localhost")
    port = int(os.getenv("CLICKHOUSE_PORT", "8124"))
    database = os.getenv("CLICKHOUSE_DB", "football")
    return clickhouse_connect.get_client(host=host, port=port, database=database)
