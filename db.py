import pathlib
import sqlite3

import click
from flask import current_app, g


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))


def apply_migrations():
    db = get_db()
    migrations_dir = pathlib.Path(current_app.root_path) / "migrations"
    if not migrations_dir.exists():
        click.echo("No migrations folder found.")
        return
    for path in sorted(migrations_dir.glob("*.sql")):
        sql = path.read_text()
        try:
            db.executescript(sql)
            click.echo(f"Applied {path.name}")
        except sqlite3.OperationalError as e:
            # ALTER TABLE ADD COLUMN fails silently if column already exists
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                click.echo(f"Skipped {path.name} (already applied)")
            else:
                click.echo(f"Warning in {path.name}: {e}")
    db.commit()


@click.command("init-db")
def init_db_command():
    init_db()
    click.echo("Database initialized.")


@click.command("migrate")
def migrate_command():
    apply_migrations()
    click.echo("Migrations applied.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(migrate_command)
