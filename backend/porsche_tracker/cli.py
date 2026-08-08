"""Operator CLI: init the DB, run collectors, run ingest.

    uv run porsche db-init
    uv run porsche collect ebay          # run one collector -> ingest
    uv run porsche collect all
"""

from __future__ import annotations

import typer

from porsche_tracker.collectors.base import Collector
from porsche_tracker.collectors.ebay import EbayCollector
from porsche_tracker.collectors.sample import DEMO_DAYS, replay_days
from porsche_tracker.db.base import session_scope
from porsche_tracker.ingest.ingest import ingest

app = typer.Typer(add_completion=False, help="Porsche 981 market tracker")

# registry: source key -> collector factory
COLLECTORS: dict[str, type[Collector]] = {
    EbayCollector.key: EbayCollector,
}


@app.command("db-init")
def db_init() -> None:
    """Bring the database schema up to date by running Alembic migrations to head.
    Works on both Postgres (prod) and SQLite (local demo)."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")
    typer.echo("schema at head")


@app.command()
def collect(source: str = typer.Argument(..., help="source key or 'all'")) -> None:
    """Run collector(s) and ingest results."""
    keys = list(COLLECTORS) if source == "all" else [source]
    for key in keys:
        cls = COLLECTORS.get(key)
        if cls is None:
            typer.echo(f"unknown source: {key}", err=True)
            raise typer.Exit(1)
        collector = cls()
        typer.echo(f"[{key}] collecting…")
        result = collector.collect()
        for err in result.errors:
            typer.echo(f"[{key}] error: {err}", err=True)
        with session_scope() as session:
            stats = ingest(
                session,
                result,
                {collector.key: {"display_name": collector.display_name, "kind": collector.kind}},
            )
        typer.echo(
            f"[{key}] seen={stats.listings_seen} new_listings={stats.new_listings} "
            f"new_obs={stats.new_observations} raw={stats.raw_stored}"
        )


@app.command("purge-demo")
def purge_demo() -> None:
    """Remove all synthetic demo data (sources keyed `sample*`) and any vehicles
    left orphaned. Run this once before real data starts flowing."""
    from sqlalchemy import text

    stmts = [
        "delete from listing_observations where listing_id in "
        "(select l.id from listings l join sources s on s.id=l.source_id where s.key like 'sample%')",
        "delete from transactions where source_id in (select id from sources where key like 'sample%')",
        "delete from listings where source_id in (select id from sources where key like 'sample%')",
        "delete from vehicle_options where vehicle_id in "
        "(select v.id from vehicles v left join listings l on l.vehicle_id=v.id where l.id is null)",
        "delete from vehicles where id in "
        "(select v.id from vehicles v left join listings l on l.vehicle_id=v.id where l.id is null)",
        "delete from raw_ingestions where source_key like 'sample%'",
        "delete from sources where key like 'sample%'",
    ]
    with session_scope() as session:
        for stmt in stmts:
            session.execute(text(stmt))
    typer.echo("purged demo data")


@app.command("enrich-vins")
def enrich_vins(limit: int = typer.Option(200, help="max vehicles to decode this run")) -> None:
    """Decode VINs (NHTSA vPIC, free) for vehicles missing a decode; back-fills only
    empty/unknown fields. Idempotent — safe to run after every collection."""
    from porsche_tracker.enrich.vpic import enrich_vehicles

    with session_scope() as session:
        n = enrich_vehicles(session, limit=limit)
    typer.echo(f"enriched {n} vehicles via vPIC")


@app.command("seed-demo")
def seed_demo(days: int = typer.Option(DEMO_DAYS, help="days of synthetic history")) -> None:
    """Populate the DB with synthetic 981 listings across a date range so the API/
    dashboard have data before real API keys exist. Replays each day through the
    normal ingest path, producing real price-drop history and cross-source dedup."""
    meta = {
        "sample_dealer": {"display_name": "Sample Dealer", "kind": "dealer"},
        "sample_marketplace": {"display_name": "Sample Marketplace", "kind": "aggregator"},
    }
    total_obs = 0
    for collector in replay_days(days):
        result = collector.collect()
        with session_scope() as session:
            stats = ingest(session, result, meta)
        total_obs += stats.new_observations
    typer.echo(f"seeded {days} days of demo data; {total_obs} observations written")


if __name__ == "__main__":
    app()
