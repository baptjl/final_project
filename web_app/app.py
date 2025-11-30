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


@app.route('/', methods=['GET', 'POST'])
@requires_auth
def index():
    if request.method == 'POST':
        # Accept either a direct URL or a posted HTML file.
        url = request.form.get('url', '').strip()
        file = request.files.get('file')
        company = request.form.get('company', '').strip()

        if not company:
            flash('Please provide a company name')
            return redirect(request.url)

        unique_suffix = datetime.utcnow().strftime('%Y%m%d%H%M%S') + '_' + uuid.uuid4().hex[:8]

        # If a URL was provided, fetch and save it as an HTML file
        if url:
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (automated)'}
                resp = requests.get(url, headers=headers, timeout=20)
                resp.raise_for_status()
            except Exception as e:
                flash(f'Failed to fetch URL: {e}')
                return redirect(request.url)

            saved_name = f"url_{unique_suffix}.html"
            saved_path = os.path.join(UPLOAD_FOLDER, saved_name)
            try:
                with open(saved_path, 'wb') as fh:
                    fh.write(resp.content)
            except Exception as e:
                flash(f'Failed to save fetched HTML: {e}')
                return redirect(request.url)

        else:
            # file handling path
            if not file or file.filename == '':
                flash('No file selected and no URL provided')
                return redirect(request.url)
            if not allowed_file(file.filename):
                flash('Unsupported file type. Upload HTML file.')
                return redirect(request.url)

            filename = secure_filename(file.filename)
            saved_name = f"{os.path.splitext(filename)[0]}_{unique_suffix}{os.path.splitext(filename)[1]}"
            saved_path = os.path.join(UPLOAD_FOLDER, saved_name)
            file.save(saved_path)

        # create output paths
        mid_name = f"mid_product_{unique_suffix}.xlsx"
        final_name = f"final_{unique_suffix}.xlsx"
        mid_path = os.path.join(OUTPUT_FOLDER, mid_name)
        final_path = os.path.join(OUTPUT_FOLDER, final_name)

        # Build command: use same Python interpreter running the app (respects venv)
        python_exec = sys.executable
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'unified_pipeline.py'))

        cmd = [python_exec, script_path, '--html', saved_path, '--company', company, '--mid-product', mid_path, '--final', final_path]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except Exception as e:
            flash(f'Failed to run pipeline: {e}')
            return redirect(request.url)

        stdout = proc.stdout
        stderr = proc.stderr
        returncode = proc.returncode

        # If pipeline failed, return an error (so the browser doesn't download HTML as .xlsx)
        if returncode != 0:
            error_msg = f"Pipeline failed (exit {returncode}). See logs below."
            if request.form.get('ajax') == '1':
                body = f"{error_msg}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
                return Response(body, status=500, mimetype='text/plain')
            flash(error_msg)
            return render_template('result.html', stdout=stdout, stderr=stderr, final_filename=None)

        # If this was an AJAX POST (from the JS UI), return the final Excel file directly
        if request.form.get('ajax') == '1':
            if os.path.exists(final_path) and os.path.getsize(final_path) > 0:
                # send file as attachment so the browser downloads it
                return send_file(final_path, as_attachment=True, download_name=final_name)
            else:
                body = f"Final file not found after processing.\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
                return Response(body, status=500, mimetype='text/plain')

        if not os.path.exists(final_path) or os.path.getsize(final_path) == 0:
            flash('Final file not found after processing')
            final_for_template = None
        else:
            final_for_template = final_name

        return render_template('result.html', stdout=stdout, stderr=stderr, final_filename=final_for_template)

    return render_template('index.html')


@app.route('/download/<filename>')
@requires_auth
def download(filename):
    fpath = os.path.join(OUTPUT_FOLDER, filename)
    if not os.path.exists(fpath):
        flash('File not found')
        return redirect(url_for('index'))
    return send_file(fpath, as_attachment=True, download_name=filename)


if __name__ == '__main__':
    # Bind to host/port from environment for cloud deployment (Render/Heroku/Railway)
    port = int(os.environ.get('PORT', 8501))
    host = os.environ.get('HOST', '0.0.0.0')
    debug = os.environ.get('FLASK_DEBUG', '0') in ('1', 'true', 'True')
    app.run(host=host, port=port, debug=debug)
