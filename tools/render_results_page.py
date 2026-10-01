"""
render_results_page.py

Screenshot the app's results page for one screenshot (docs/results.png in the
README). It registers a throwaway user in a copy of the database, uploads the
image through the real /upload route, saves the HTML the app returns and has a
headless Chromium render it.

Usage (from the repository root):
    python tools/render_results_page.py --db build/demo.db --chrome /path/to/chrome

--db must be a built item database with prices for the items in the image
(e.g. `python Src/DB/bulk_scraper.py --db build/demo.db --query "Revolution Case"`
for each of them). It is copied; the original is not modified. --chrome is any
Chromium or Chrome binary that supports --headless and --screenshot.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def results_html(image_path, db_path):
    os.environ['DATABASE_PATH'] = db_path
    os.environ.setdefault('SECRET_KEY', 'render-results-not-a-real-key')
    import app

    client = app.app.test_client()
    token = 'render-results-token'
    password = 'render-results-password'
    with client.session_transaction() as sess:
        sess[app.CSRF_SESSION_KEY] = token
    client.post('/register', data={app.CSRF_FIELD: token, 'username': 'demo', 'email': 'demo@example.com',
                                   'password': password, 'confirm_password': password})
    client.post('/login', data={app.CSRF_FIELD: token, 'username': 'demo', 'password': password})
    with client.session_transaction() as sess:  # logging in starts a new session
        sess[app.CSRF_SESSION_KEY] = token
    with open(image_path, 'rb') as f:
        response = client.post('/upload', data={app.CSRF_FIELD: token, 'file': (f, os.path.basename(image_path))},
                               content_type='multipart/form-data')
    if response.status_code != 200:
        raise RuntimeError(f'/upload returned {response.status_code}')
    return response.get_data(as_text=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Screenshot the results page for one upload')
    parser.add_argument('image', nargs='?', default=os.path.join(REPO_ROOT, 'Training_Images', 'image.png'))
    parser.add_argument('--db', required=True, help='Item database with prices (copied, not modified)')
    parser.add_argument('--chrome', required=True, help='Chromium/Chrome binary')
    parser.add_argument('--out', default=os.path.join(REPO_ROOT, 'docs', 'results.png'))
    parser.add_argument('--size', default='1280,1500', help='Window width,height in CSS pixels')
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        db_copy = os.path.join(tmp, 'items.db')
        shutil.copyfile(args.db, db_copy)
        html_path = os.path.join(tmp, 'results.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(results_html(args.image, db_copy))
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        subprocess.run([args.chrome, '--headless', '--no-sandbox', '--hide-scrollbars',
                        f'--window-size={args.size}', f'--screenshot={os.path.abspath(args.out)}',
                        'file://' + html_path], check=True, capture_output=True, timeout=120)
    print(f'Wrote {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
