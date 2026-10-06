"""Collect -> deduplicate -> store in BigQuery -> summarise with Gemini.

Runs as a Cloud Run Job. Any unhandled exception exits non-zero, which marks
the execution failed and trips the Cloud Monitoring log alert.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

from google import genai
from google.cloud import bigquery
from google.genai import types

from app.sources import Item, fetch_rss, fetch_youtube

log = logging.getLogger("digest")

DEFAULT_FEEDS = (
    "https://cloud.google.com/feeds/gcp-release-notes.xml,"
    "https://cloudblog.withgoogle.com/rss/"
)
DEFAULT_YT_QUERIES = "Google Cloud Vertex AI agents,Terraform Google Cloud"

SYSTEM_PROMPT = (
    "You write a weekly digest for a cloud/AI engineer. Group items by theme, "
    "one line each with the URL, and finish with 3 concrete things worth "
    "learning or building this week. Use only the items provided."
)


def _csv(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


def dedupe(items: list[Item]) -> list[Item]:
    seen: dict[str, Item] = {}
    for item in items:
        seen.setdefault(item.id, item)
    return list(seen.values())


def new_only(client: bigquery.Client, table: str, items: list[Item]) -> list[Item]:
    if not items:
        return []
    query = f"SELECT id FROM `{table}` WHERE id IN UNNEST(@ids)"
    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("ids", "STRING", [i.id for i in items])
            ]
        ),
    )
    existing = {row["id"] for row in job.result()}
    return [i for i in items if i.id not in existing]


def insert(client: bigquery.Client, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    errors = client.insert_rows_json(table, rows, row_ids=[r.get("id") for r in rows])
    if errors:
        raise RuntimeError(f"BigQuery insert failed: {errors}")


def build_prompt(items: list[Item]) -> str:
    lines = [f"- [{i.kind}] {i.title} — {i.url}" for i in items]
    return "New items this run:\n" + "\n".join(lines)


def summarise(project: str, items: list[Item]) -> str:
    client = genai.Client(
        enterprise=True,
        project=project,
        location=os.environ.get("GENAI_LOCATION", "global"),
    )
    response = client.models.generate_content(
        model=os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
        contents=build_prompt(items),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT, temperature=0.3, max_output_tokens=2048
        ),
    )
    return response.text or ""


def run() -> int:
    project = os.environ["PROJECT_ID"]
    dataset = os.environ["BQ_DATASET"]
    items_table = f"{project}.{dataset}.items"
    digests_table = f"{project}.{dataset}.digests"

    collected = dedupe(
        fetch_rss(_csv("FEEDS", DEFAULT_FEEDS))
        + fetch_youtube(_csv("YT_QUERIES", DEFAULT_YT_QUERIES))
    )
    bq = bigquery.Client(project=project)
    fresh = new_only(bq, items_table, collected)
    log.info("collected=%d new=%d", len(collected), len(fresh))
    if not fresh:
        return 0

    insert(bq, items_table, [i.to_row() for i in fresh])

    digest = summarise(project, fresh)
    insert(
        bq,
        digests_table,
        [
            {
                "run_at": datetime.now(timezone.utc).isoformat(),
                "item_count": len(fresh),
                "digest": digest,
            }
        ],
    )
    log.info("digest stored (%d chars)", len(digest))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    sys.exit(run())
