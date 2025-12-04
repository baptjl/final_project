from flask import Flask, request, redirect, url_for, send_file, render_template, flash, Response, session
import os
import sys
import subprocess
import uuid
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
import requests
import sqlite3

# Load environment variables from .env if present
load_dotenv()

# Configuration
BASE_DIR = os.path.abspath(os.path.dirname(__file__)) + os.sep + ".."
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
OUTPUT_FOLDER = os.path.join(os.path.dirname(__file__), 'outputs')
ALLOWED_EXTENSIONS = {'.html', '.htm'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Toggle LLM-based label mapping (Ollama). Default via env.
USE_LLM_DEFAULT = os.environ.get('USE_LLM_DEFAULT', '0').lower() in {'1', 'true', 'yes', 'on'}

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB uploads
app.secret_key = os.environ.get('WEB_APP_SECRET', 'dev-secret')
init_db()


def allowed_file(filename):
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS


def get_db():
    db_path = os.path.join(os.path.dirname(__file__), "users.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def run_pipeline():
    # Accept either a direct URL or a posted HTML file.
    url = request.form.get('url', '').strip()
    file = request.files.get('file')
    company = request.form.get('company', '').strip()
    use_llm_flag_raw = request.form.get('use_llm_flag')
    use_external_news_flag = request.form.get("use_external_news")
    if use_llm_flag_raw is None:
        use_llm = True  # safe default: always use OpenAI mapping
    else:
        use_llm = (use_llm_flag_raw == '1')

    if not company:
        return None, None, None, "Please provide a company name"

    unique_suffix = datetime.utcnow().strftime('%Y%m%d%H%M%S') + '_' + uuid.uuid4().hex[:8]

    # If a URL was provided, fetch and save it as an HTML file
    if url:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (automated)'}
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            return None, None, None, f'Failed to fetch URL: {e}'

        saved_name = f"url_{unique_suffix}.html"
        saved_path = os.path.join(UPLOAD_FOLDER, saved_name)
        try:
            with open(saved_path, 'wb') as fh:
                fh.write(resp.content)
        except Exception as e:
            return None, None, None, f'Failed to save fetched HTML: {e}'

    else:
        # file handling path
        if not file or file.filename == '':
            return None, None, None, 'No file selected and no URL provided'
        if not allowed_file(file.filename):
            return None, None, None, 'Unsupported file type. Upload HTML file.'

        filename = secure_filename(file.filename)
        saved_name = f"{os.path.splitext(filename)[0]}_{unique_suffix}{os.path.splitext(filename)[1]}"
        saved_path = os.path.join(UPLOAD_FOLDER, saved_name)
        file.save(saved_path)

    # create output paths
    mid_name = f"mid_product_{unique_suffix}.xlsx"
    safe_company = secure_filename(company) or "output"
    final_download_name = f"{safe_company}_financial_modeling.xlsx"
    final_name = f"final_{unique_suffix}.xlsx"
    mid_path = os.path.join(OUTPUT_FOLDER, mid_name)
    final_path = os.path.join(OUTPUT_FOLDER, final_name)
    # Build environment for subprocess with per-run external news flag
    env = os.environ.copy()
    env_default_ext = env.get("USE_EXTERNAL_OUTLOOK", "0").lower() in {"1", "true", "yes", "on"}
    ui_flag = use_external_news_flag == "1"
    if use_external_news_flag is not None:
        env["USE_EXTERNAL_OUTLOOK"] = "1" if ui_flag else "0"
    else:
        env["USE_EXTERNAL_OUTLOOK"] = "1" if env_default_ext else "0"
    if env.get("USE_EXTERNAL_OUTLOOK") != "1":
        env["USE_EXTERNAL_OUTLOOK"] = "0"

    # Build command: use same Python interpreter running the app (respects venv)
    python_exec = sys.executable
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'unified_pipeline.py'))

    cmd = [python_exec, script_path, '--html', saved_path, '--company', company, '--mid-product', mid_path, '--final', final_path]
    if use_llm:
        cmd.append('--use-llm')

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    except Exception as e:
        return None, None, None, f'Failed to run pipeline: {e}'

    stdout = proc.stdout
    stderr = proc.stderr
    returncode = proc.returncode
    if use_llm and "LLM mapping failed" in stdout + stderr:
        flash("LLM was requested but unavailable; fell back to non-LLM mapping.")

    if returncode != 0:
        return None, stdout, stderr, f"Pipeline failed (exit {returncode}). See logs below."

    if not os.path.exists(final_path) or os.path.getsize(final_path) == 0:
        return None, stdout, stderr, "Final file not found after processing."

    return {"final_path": final_path, "final_download_name": final_download_name}, stdout, stderr, None


@app.route('/', methods=['GET'])
@login_required
def home():
    return render_template('home.html')


@app.route('/app', methods=['GET'])
@login_required
def app_page():
    use_external_default = os.environ.get("USE_EXTERNAL_OUTLOOK", "0").lower() in {"1", "true", "yes", "on"}
    return render_template('app.html', use_llm_default=USE_LLM_DEFAULT, use_external_default=use_external_default)


@app.route('/help', methods=['GET'])
@login_required
def help_page():
    return render_template('help.html')


@app.route('/settings', methods=['GET'])
@login_required
def settings_page():
    return render_template('settings.html', use_llm_default=USE_LLM_DEFAULT)


@app.route('/generate', methods=['POST'])
@login_required
def generate():
    result, stdout, stderr, err = run_pipeline()
    if err:
        if request.form.get('ajax') == '1':
            body = f"{err}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
            return Response(body, status=500, mimetype='text/plain')
        flash(err)
        return render_template('result.html', stdout=stdout, stderr=stderr, final_filename=None)

    final_path = result["final_path"]
    final_download_name = result["final_download_name"]

    if request.form.get('ajax') == '1':
        return send_file(final_path, as_attachment=True, download_name=final_download_name)

    return render_template('result.html', stdout=stdout, stderr=stderr, final_filename=final_download_name)


@app.route('/download/<filename>')
@requires_auth
def download(filename):
    fpath = os.path.join(OUTPUT_FOLDER, filename)
    if not os.path.exists(fpath):
        flash('File not found')
        return redirect(url_for('app_page'))
    return send_file(fpath, as_attachment=True, download_name=filename)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, email, password_hash FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        conn.close()
        if row and check_password_hash(row["password_hash"], password):
            session["user_id"] = row["id"]
            session["email"] = row["email"]
            return redirect(url_for('home'))
        flash("Invalid email/password")
    return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if not email or '@' not in email:
            flash("Please enter a valid email.")
            return render_template('signup.html')
        if password != confirm:
            flash("Passwords do not match.")
            return render_template('signup.html')
        pw_hash = generate_password_hash(password)
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)", (email, pw_hash))
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("That email is already registered.")
        except Exception:
            flash("Could not create account. Please try again.")
    return render_template('signup.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    # Bind to host/port from environment for cloud deployment (Render/Heroku/Railway)
    port = int(os.environ.get('PORT', 8501))
    host = os.environ.get('HOST', '0.0.0.0')
    debug = os.environ.get('FLASK_DEBUG', '0') in ('1', 'true', 'True')
    app.run(host=host, port=port, debug=debug)
