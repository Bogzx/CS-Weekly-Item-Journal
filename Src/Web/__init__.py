"""The web app's building blocks. app.py creates the Flask app and its routes
from these; nothing here registers routes itself.

    settings    paths and environment parsing
    auth        sessions, CSRF tokens, the login throttle, safe redirects
    db          SQLite connections, schema upgrades, user and journal queries
    uploads     validating and storing uploaded or pasted screenshots
    matching    OCR text -> candidate items for each of the four slots
    valuation   what each slot is worth and which two to claim
    history     weekly drop history and its chart
    prices      the scheduled Steam price update
"""
