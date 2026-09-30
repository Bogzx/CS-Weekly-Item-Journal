"""Tests for Src/DB/create_database.py."""

import sqlite3

from Src.DB import create_database


def tables(path):
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def test_creates_schema_on_a_fresh_path(tmp_path):
    db = str(tmp_path / 'items.db')

    assert create_database.create_csgo_database(db) is True

    assert {'items', 'collections'} <= tables(db)
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(items)")}
    assert 'price_type' in cols


def test_refuses_to_touch_an_existing_database(tmp_path):
    db = str(tmp_path / 'items.db')
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (username) VALUES ('alice')")
    conn.commit()
    conn.close()

    assert create_database.main(['--db', db]) == 1

    assert sqlite3.connect(db).execute("SELECT username FROM users").fetchall() == [('alice',)]


def test_force_rebuilds_items_but_keeps_users_and_journals(tmp_path):
    """Re-running setup used to delete the file, and every account with it."""
    db = str(tmp_path / 'items.db')
    create_database.create_csgo_database(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO items (name, market_api_url) VALUES ('Old Item', '')")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("CREATE TABLE user_journals (id INTEGER PRIMARY KEY, user_id INTEGER, item_name TEXT)")
    conn.execute("INSERT INTO users (username) VALUES ('alice')")
    conn.execute("INSERT INTO user_journals (user_id, item_name) VALUES (1, 'Revolution Case')")
    conn.commit()
    conn.close()

    assert create_database.main(['--db', db, '--force']) == 0

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone() == (0,)
    assert conn.execute("SELECT username FROM users").fetchall() == [('alice',)]
    assert conn.execute("SELECT item_name FROM user_journals").fetchall() == [('Revolution Case',)]
