import os
import sys
import sqlite3
import secrets
import smtplib
import subprocess
from email.message import EmailMessage
from datetime import datetime, timedelta
from functools import wraps

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    request,
    redirect,
    url_for,
    send_file,
    render_template,
    flash,
    session,
    Response,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Load environment variables
load_dotenv()

# Paths and configuration
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(BASE_DIR, "users.db")
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
OUTPUT_FOLDER = os.path.join(os.path.dirname(__file__), "outputs")
ALLOWED_EXTENSIONS = {".html", ".htm"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB uploads
app.secret_key = os.environ.get("WEB_APP_SECRET", "dev-secret")

# -----------------------------------------------------------------------------
# Database helpers
# -----------------------------------------------------------------------------


def init_db():
    """Create required tables if they do not exist."""
    conn = sqlite3.connect(DB_PATH)
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

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            company_name TEXT,
            source_type TEXT,
            url_used TEXT,
            base_growth REAL,
            combined_score INTEGER,
            growth_bump REAL,
            external_used INTEGER,
            ai_sentiment_label TEXT,
            ai_sentiment_note TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    conn.commit()
    conn.close()


with app.app_context():
    init_db()


def get_db():
    return sqlite3.connect(DB_PATH)


# -----------------------------------------------------------------------------
# Auth helpers
# -----------------------------------------------------------------------------


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapper


# Alias to avoid NameError if older references remain
requires_auth = login_required


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------


def allowed_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS


def send_reset_email(to_email: str, reset_link: str):
    """Send reset email using smtplib; log link if email not configured."""
    mail_server = os.environ.get("MAIL_SERVER")
    mail_port = os.environ.get("MAIL_PORT")
    mail_username = os.environ.get("MAIL_USERNAME")
    mail_password = os.environ.get("MAIL_PASSWORD")
    mail_use_tls = os.environ.get("MAIL_USE_TLS", "0") == "1"
    mail_sender = os.environ.get("MAIL_SENDER", "no-reply@example.com")

    if not (mail_server and mail_port and mail_username and mail_password):
        app.logger.warning(
            "PASSWORD RESET LINK (email not configured): %s", reset_link
        )
        return

    msg = EmailMessage()
    msg["Subject"] = "Password reset instructions"
    msg["From"] = mail_sender
    msg["To"] = to_email
    msg.set_content(
        "You requested a password reset. Click this link to set a new password:\n\n"
        f"{reset_link}\n\n"
        "If you did not request this, you can ignore this email."
    )

    try:
        with smtplib.SMTP(mail_server, int(mail_port), timeout=10) as server:
            if mail_use_tls:
                server.starttls()
            server.login(mail_username, mail_password)
            server.send_message(msg)
    except Exception as e:
        app.logger.warning("Failed to send reset email: %s", e)
        app.logger.warning("PASSWORD RESET LINK (fallback): %s", reset_link)


# -----------------------------------------------------------------------------
# Auth routes
# -----------------------------------------------------------------------------


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not email or not password:
            flash("Email and password are required.")
            return render_template("signup.html")
        if password != confirm:
            flash("Passwords do not match.")
            return render_template("signup.html")

        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT id FROM users WHERE email = ?", (email,))
            if cur.fetchone():
                flash("An account with this email already exists.")
                conn.close()
                return render_template("signup.html")

            pw_hash = generate_password_hash(password)
            cur.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, pw_hash),
            )
            conn.commit()
            conn.close()
            flash("Account created. Please log in.")
            return redirect(url_for("login"))
        except Exception as e:
            app.logger.error("Signup failed: %s", e)
            flash("Signup failed. Please try again.")
            return render_template("signup.html")

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        conn.close()

        if row and check_password_hash(row[1], password):
            session["user_id"] = row[0]
            session["email"] = email
            return redirect(url_for("index"))

        flash("Invalid email/password.")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if email:
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT id FROM users WHERE email = ?", (email,))
                row = cur.fetchone()
                if row:
                    token = secrets.token_urlsafe(32)
                    expires_at = datetime.utcnow() + timedelta(hours=1)
                    cur.execute(
                        """
                        INSERT INTO password_reset_tokens (user_id, token, expires_at, used)
                        VALUES (?, ?, ?, 0)
                        """,
                        (row[0], token, expires_at.isoformat()),
                    )
                    conn.commit()
                    reset_link = url_for("reset_password", token=token, _external=True)
                    send_reset_email(email, reset_link)
                conn.close()
            except Exception as e:
                app.logger.warning("Failed to issue reset token: %s", e)
        flash("If an account with that email exists, reset instructions have been sent.")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT prt.id, prt.user_id, prt.expires_at, prt.used, u.email
        FROM password_reset_tokens prt
        JOIN users u ON u.id = prt.user_id
        WHERE prt.token = ?
        """,
        (token,),
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        return render_template("reset_password_invalid.html")

    token_id, user_id, expires_at, used, email = row
    try:
        expires_dt = datetime.fromisoformat(expires_at)
    except Exception:
        expires_dt = datetime.utcnow() - timedelta(seconds=1)

    if used or expires_dt < datetime.utcnow():
        conn.close()
        return render_template("reset_password_invalid.html")

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not password or password != confirm:
            flash("Passwords do not match.")
            conn.close()
            return render_template("reset_password.html", email=email)
        try:
            pw_hash = generate_password_hash(password)
            cur.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, user_id)
            )
            cur.execute(
                "UPDATE password_reset_tokens SET used = 1 WHERE id = ?", (token_id,)
            )
            conn.commit()
            conn.close()
            flash("Password reset. You can now log in.")
            return redirect(url_for("login"))
        except Exception as e:
            app.logger.error("Failed to reset password: %s", e)
            flash("Could not reset password. Try again.")
            conn.close()
            return render_template("reset_password.html", email=email)

    conn.close()
    return render_template("reset_password.html", email=email)


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        url = request.form.get("url", "").strip()
        file = request.files.get("file")
        company = request.form.get("company", "").strip()

        use_llm_flags = request.form.getlist("use_llm_flag")
        use_llm = "1" in use_llm_flags if use_llm_flags else True

        if not company:
            flash("Please provide a company name")
            return redirect(request.url)

        unique_suffix = (
            datetime.utcnow().strftime("%Y%m%d%H%M%S") + "_" + secrets.token_hex(4)
        )

        if url:
            try:
                headers = {"User-Agent": "Mozilla/5.0 (automated)"}
                resp = requests.get(url, headers=headers, timeout=20)
                resp.raise_for_status()
            except Exception as e:
                flash(f"Failed to fetch URL: {e}")
                return redirect(request.url)

            saved_name = f"url_{unique_suffix}.html"
            saved_path = os.path.join(UPLOAD_FOLDER, saved_name)
            try:
                with open(saved_path, "wb") as fh:
                    fh.write(resp.content)
            except Exception as e:
                flash(f"Failed to save fetched HTML: {e}")
                return redirect(request.url)
        else:
            if not file or file.filename == "":
                flash("No file selected and no URL provided")
                return redirect(request.url)
            if not allowed_file(file.filename):
                flash("Unsupported file type. Upload HTML file.")
                return redirect(request.url)

            filename = secure_filename(file.filename)
            saved_name = (
                f"{os.path.splitext(filename)[0]}_{unique_suffix}"
                f"{os.path.splitext(filename)[1]}"
            )
            saved_path = os.path.join(UPLOAD_FOLDER, saved_name)
            file.save(saved_path)

        mid_name = f"mid_product_{unique_suffix}.xlsx"
        safe_company = secure_filename(company) or "output"
        final_download_name = f"{safe_company}_financial_modeling.xlsx"
        final_name = f"final_{unique_suffix}.xlsx"
        mid_path = os.path.join(OUTPUT_FOLDER, mid_name)
        final_path = os.path.join(OUTPUT_FOLDER, final_name)

        python_exec = sys.executable
        script_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "unified_pipeline.py")
        )

        cmd = [
            python_exec,
            script_path,
            "--html",
            saved_path,
            "--company",
            company,
            "--mid-product",
            mid_path,
            "--final",
            final_path,
        ]
        if use_llm:
            cmd.append("--use-llm")

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except Exception as e:
            flash(f"Failed to run pipeline: {e}")
            return redirect(request.url)

        stdout = proc.stdout
        stderr = proc.stderr
        returncode = proc.returncode
        if use_llm and "LLM mapping failed" in stdout + stderr:
            flash("LLM was requested but unavailable; fell back to non-LLM mapping.")

        if returncode != 0:
            error_msg = f"Pipeline failed (exit {returncode}). See logs below."
            if request.form.get("ajax") == "1":
                body = f"{error_msg}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
                return Response(body, status=500, mimetype="text/plain")
            flash(error_msg)
            return render_template(
                "result.html", stdout=stdout, stderr=stderr, final_filename=None
            )

        # Log the run (non-fatal if it fails)
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO runs (
                    user_id, company_name, source_type, url_used,
                    base_growth, combined_score, growth_bump,
                    external_used, ai_sentiment_label, ai_sentiment_note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.get("user_id"),
                    company,
                    "url" if url else "file",
                    url if url else None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            app.logger.warning("Failed to log run: %s", e)

        if request.form.get("ajax") == "1":
            if os.path.exists(final_path) and os.path.getsize(final_path) > 0:
                return send_file(final_path, as_attachment=True, download_name=final_download_name)
            body = f"Final file not found after processing.\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
            return Response(body, status=500, mimetype="text/plain")

        if not os.path.exists(final_path) or os.path.getsize(final_path) == 0:
            flash("Final file not found after processing")
            final_for_template = None
        else:
            final_for_template = final_download_name

        return render_template(
            "result.html", stdout=stdout, stderr=stderr, final_filename=final_for_template
        )

    return render_template("index.html")


@app.route("/app")
@login_required
def app_page():
    return render_template("index.html")


@app.route("/help")
@login_required
def help_page():
    return render_template("help.html")


@app.route("/settings")
@login_required
def settings_page():
    return render_template("settings.html")


@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT company_name, source_type, url_used, base_growth, combined_score,
               growth_bump, external_used, ai_sentiment_label, ai_sentiment_note, created_at
        FROM runs
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 50
        """,
        (session.get("user_id"),),
    )
    runs = cur.fetchall()
    conn.close()
    return render_template("dashboard.html", runs=runs)


@app.route("/download/<filename>")
@login_required
def download(filename):
    fpath = os.path.join(OUTPUT_FOLDER, filename)
    if not os.path.exists(fpath):
        flash("File not found")
        return redirect(url_for("index"))
    return send_file(fpath, as_attachment=True, download_name=filename)


# -----------------------------------------------------------------------------
# Entry
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8501))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("FLASK_DEBUG", "0") in ("1", "true", "True")
    app.run(host=host, port=port, debug=debug)
