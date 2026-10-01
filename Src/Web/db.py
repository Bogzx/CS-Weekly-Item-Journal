"""SQLite connections, schema upgrades, and user and journal queries."""

import logging
import sqlite3

from flask import current_app, g, session

logger = logging.getLogger(__name__)


def get_db():
    """This request's connection to the SQLite database (rows as dicts)."""
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        # Set row_factory to return dictionaries instead of Row objects
        g.db.row_factory = lambda cursor, row: {
            column[0]: row[idx] for idx, column in enumerate(cursor.description)
        }
    return g.db


def close_db(error):
    """Close database connection at the end of request."""
    if 'db' in g:
        g.db.close()


def initialize_database(path):
    """Add the tables and columns the app needs to the database at `path`."""
    conn = sqlite3.connect(path)
    cursor = conn.cursor()

    # Check and add price_type column if needed
    try:
        cursor.execute("ALTER TABLE items ADD COLUMN price_type TEXT")
        logger.info("Added price_type column to items table")
    except sqlite3.OperationalError:
        # Column already exists, which is fine
        pass

    # tradable = 0 marks items that cannot be sold (Charm Detachment Pack)
    try:
        cursor.execute("ALTER TABLE items ADD COLUMN tradable INTEGER NOT NULL DEFAULT 1")
        logger.info("Added tradable column to items table")
    except sqlite3.OperationalError:
        # Column already exists (or no item table yet), which is fine
        pass

    # Create users table if it doesn't exist
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Create user_journals table if it doesn't exist
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_journals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        item_name TEXT NOT NULL,
        item_collection TEXT,
        item_price REAL,
        item_price_type TEXT,
        item_type TEXT,
        screenshot_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    )
    ''')

    # Add indexes for better performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_journals_user_id ON user_journals (user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_journals_item_id ON user_journals (item_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_journals_screenshot_id ON user_journals (screenshot_id)")

    conn.commit()
    conn.close()
    logger.info("Database initialized: %s", path)


def get_current_user():
    """The logged-in user (id, username, email), or None."""
    if 'user_id' in session:
        conn = get_db()
        user = conn.execute(
            "SELECT id, username, email FROM users WHERE id = ?",
            (session['user_id'],)
        ).fetchone()
        return user
    return None


def get_user_journal(user_id):
    """Get a user's journal items from the database."""
    conn = get_db()
    journal_items = conn.execute(
        "SELECT * FROM user_journals WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    return journal_items


def get_journal_total(journal_items):
    """Calculate total value of items in a journal."""
    return sum(float(item.get('item_price', 0) or 0) for item in journal_items)


def get_journal_price_rows(user_id):
    """(created_at, item_price) for every journal entry of a user."""
    conn = get_db()
    rows = conn.execute(
        "SELECT created_at, item_price FROM user_journals WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    return [(row['created_at'], row['item_price']) for row in rows]
