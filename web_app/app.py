from flask import Flask, request, redirect, url_for, send_file, render_template, flash, Response
import os
import sys
import subprocess
import uuid
from werkzeug.utils import secure_filename
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
import requests

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


def allowed_file(filename):
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS


def check_auth(username: str, password: str) -> bool:
    """Check username and password against environment variables."""
    env_user = os.environ.get('WEB_APP_USER')
    env_pass = os.environ.get('WEB_APP_PASS')
    if not env_user or not env_pass:
        # If no credentials are set, allow access (local use)
        return True
    return username == env_user and password == env_pass


def authenticate():
    """Sends a 401 response that enables basic auth in the browser."""
    return Response(
        'Authentication required', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # If credentials not configured, allow access
        if not os.environ.get('WEB_APP_USER'):
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


def run_pipeline():
    # Accept either a direct URL or a posted HTML file.
    url = request.form.get('url', '').strip()
    file = request.files.get('file')
    company = request.form.get('company', '').strip()
    use_llm_flags = request.form.getlist('use_llm_flag')
    use_external_news_flag = request.form.get("use_external_news")
    use_llm = None
    if use_llm_flags:
        use_llm = '1' in use_llm_flags
    else:
        use_llm = USE_LLM_DEFAULT

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
@requires_auth
def home():
    return render_template('home.html')


@app.route('/app', methods=['GET'])
@requires_auth
def app_page():
    use_external_default = os.environ.get("USE_EXTERNAL_OUTLOOK", "0").lower() in {"1", "true", "yes", "on"}
    return render_template('app.html', use_llm_default=USE_LLM_DEFAULT, use_external_default=use_external_default)


@app.route('/help', methods=['GET'])
@requires_auth
def help_page():
    return render_template('help.html')


@app.route('/settings', methods=['GET'])
@requires_auth
def settings_page():
    return render_template('settings.html', use_llm_default=USE_LLM_DEFAULT)


@app.route('/generate', methods=['POST'])
@requires_auth
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


if __name__ == '__main__':
    # Bind to host/port from environment for cloud deployment (Render/Heroku/Railway)
    port = int(os.environ.get('PORT', 8501))
    host = os.environ.get('HOST', '0.0.0.0')
    debug = os.environ.get('FLASK_DEBUG', '0') in ('1', 'true', 'True')
    app.run(host=host, port=port, debug=debug)
