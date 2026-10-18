"""
app.py  --  AI Study Planner (Phase 1-4)
Phase 1: Auth + Subjects + Timetable
Phase 2: Topics + Progress + Recommendations
Phase 3: PDF/File upload system (1 GB quota, multi-type)
Phase 4: AI Chatbot per subject + Topic suggestions (Gemini)
"""
import os
import pathlib
import uuid
from datetime import date, datetime
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, flash, g, jsonify, redirect,
                   render_template, request, send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import db as db_module
from ai_client import AIConfigError, AIRequestError, chat_with_subject, suggest_important_topics
from planner import build_recommendations, build_timetable

load_dotenv()

_HERE = pathlib.Path(__file__).parent

app = Flask(__name__)
app.config.from_mapping(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-this"),
    DATABASE=str(_HERE / "study_planner.db"),
    UPLOAD_FOLDER=str(_HERE / "uploads"),
    MAX_CONTENT_LENGTH=100 * 1024 * 1024,        # 100 MB per file
    USER_STORAGE_QUOTA=1 * 1024 * 1024 * 1024,  # 1 GB per user
    ALLOWED_EXTENSIONS={"pdf","doc","docx","ppt","pptx","xls","xlsx","txt","jpg","jpeg","png"},
)
db_module.init_app(app)


@app.errorhandler(413)
def file_too_large(e):
    flash("File too large. Maximum is 100 MB per file.", "error")
    return redirect(request.referrer or url_for("subjects"))


# ── File type helpers ────────────────────────────────────────────────────────

MIME_MAP = {
    ".pdf":  "application/pdf",
    ".doc":  "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt":  "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls":  "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt":  "text/plain",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
}

TYPE_LABEL = {
    ".pdf":"PDF", ".doc":"Word", ".docx":"Word",
    ".ppt":"PPT", ".pptx":"PPT",
    ".xls":"Excel", ".xlsx":"Excel",
    ".txt":"Text", ".jpg":"Image", ".jpeg":"Image", ".png":"Image",
}

MAGIC = {
    ".pdf": [(0, b"%PDF")],
    ".png": [(0, b"\x89PNG")],
    ".jpg": [(0, b"\xff\xd8\xff")],
    ".jpeg":[(0, b"\xff\xd8\xff")],
    ".docx":[(0, b"PK\x03\x04")],
    ".pptx":[(0, b"PK\x03\x04")],
    ".xlsx":[(0, b"PK\x03\x04")],
    ".doc": [(0, b"\xd0\xcf\x11\xe0")],
    ".ppt": [(0, b"\xd0\xcf\x11\xe0")],
    ".xls": [(0, b"\xd0\xcf\x11\xe0")],
}

def _allowed(filename):
    return pathlib.Path(filename).suffix.lower().lstrip(".") in app.config["ALLOWED_EXTENSIONS"]

def _magic_ok(fs, ext):
    if ext == ".txt": return True
    sigs = MAGIC.get(ext)
    if not sigs: return False
    hdr = fs.read(12); fs.seek(0)
    return all(hdr[o:o+len(s)] == s for o,s in sigs)

def _human(b):
    if b < 1024: return f"{b} B"
    if b < 1024**2: return f"{b/1024:.1f} KB"
    if b < 1024**3: return f"{b/1024**2:.1f} MB"
    return f"{b/1024**3:.2f} GB"

def _storage_used(db, uid):
    return db.execute("SELECT COALESCE(SUM(file_size),0) AS t FROM notes WHERE user_id=?", (uid,)).fetchone()["t"]


# ── Auth helpers ─────────────────────────────────────────────────────────────

@app.before_request
def load_user():
    uid = session.get("user_id")
    g.user = db_module.get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None

def login_required(view):
    @wraps(view)
    def wrapped(**kw):
        if g.user is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(**kw)
    return wrapped


# ── Auth routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("dashboard") if g.user else url_for("login"))

@app.route("/register", methods=["GET","POST"])
def register():
    if g.user: return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form["username"].strip()
        email    = request.form["email"].strip().lower()
        password = request.form["password"]
        err = None
        if not username: err = "Username required."
        elif not email:  err = "Email required."
        elif len(password) < 6: err = "Password must be at least 6 characters."
        if not err:
            try:
                db_module.get_db().execute(
                    "INSERT INTO users (username,email,password_hash) VALUES (?,?,?)",
                    (username, email, generate_password_hash(password)))
                db_module.get_db().commit()
                flash("Account created! Please log in.", "success")
                return redirect(url_for("login"))
            except db_module.sqlite3.IntegrityError:
                err = "Username or email already taken."
        flash(err, "error")
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if g.user: return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        user = db_module.get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Incorrect username or password.", "error")
        else:
            session.clear(); session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))


# ── Shared helpers ────────────────────────────────────────────────────────────

def _subjects_with_progress(db, user_id):
    return db.execute(
        "SELECT s.*, COUNT(t.id) AS total_topics, "
        "SUM(CASE WHEN t.is_completed=1 THEN 1 ELSE 0 END) AS completed_topics "
        "FROM subjects s LEFT JOIN topics t ON t.subject_id=s.id "
        "WHERE s.user_id=? GROUP BY s.id ORDER BY s.exam_date ASC",
        (user_id,),
    ).fetchall()


# ── Dashboard ────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    db  = db_module.get_db()
    today = date.today()
    sp  = _subjects_with_progress(db, g.user["id"])
    upcoming   = [s for s in sp if date.fromisoformat(s["exam_date"]) >= today]
    weak_count = sum(1 for s in upcoming if s["is_weak"])
    plan = db.execute(
        "SELECT t.*, s.name AS subject_name FROM timetable_entries t "
        "JOIN subjects s ON s.id=t.subject_id "
        "WHERE t.user_id=? AND t.plan_date=? ORDER BY t.priority_score DESC",
        (g.user["id"], today.isoformat())).fetchall()
    recos = build_recommendations(sp, today, top_n=3)

    # Stats for token/activity cards
    notes_count = db.execute("SELECT COUNT(*) AS c FROM notes WHERE user_id=?", (g.user["id"],)).fetchone()["c"]
    chat_count  = db.execute("SELECT COUNT(*) AS c FROM chat_messages WHERE user_id=? AND role='user'", (g.user["id"],)).fetchone()["c"]
    used_bytes  = _storage_used(db, g.user["id"])

    return render_template("dashboard.html",
        today=today, upcoming_count=len(upcoming),
        subject_count=len(sp), weak_count=weak_count,
        next_exam=upcoming[0] if upcoming else None,
        todays_plan=plan, recommendations=recos,
        notes_count=notes_count, chat_count=chat_count,
        used_storage=_human(used_bytes),
    )


# ── Subjects ─────────────────────────────────────────────────────────────────

@app.route("/subjects", methods=["GET","POST"])
@login_required
def subjects():
    db = db_module.get_db()
    if request.method == "POST":
        name       = request.form["name"].strip()
        exam_date  = request.form["exam_date"]
        difficulty = int(request.form.get("difficulty", 3))
        is_weak    = 1 if request.form.get("is_weak") == "on" else 0
        if not name or not exam_date:
            flash("Name and exam date are required.", "error")
        else:
            db.execute("INSERT INTO subjects (user_id,name,exam_date,difficulty,is_weak) VALUES (?,?,?,?,?)",
                       (g.user["id"], name, exam_date, difficulty, is_weak))
            db.commit()
            flash(f'"{name}" added.', "success")
            return redirect(url_for("subjects"))
    all_subjects = _subjects_with_progress(db, g.user["id"])
    return render_template("subjects.html", subjects=all_subjects, today=date.today())

@app.route("/subjects/<int:sid>/delete", methods=["POST"])
@login_required
def delete_subject(sid):
    db = db_module.get_db()
    owned = db.execute("SELECT id FROM subjects WHERE id=? AND user_id=?", (sid, g.user["id"])).fetchone()
    if not owned:
        flash("Subject not found.", "error")
        return redirect(url_for("subjects"))
    # cascade: topics, notes (files+rows), chat, timetable
    for note in db.execute("SELECT filename FROM notes WHERE subject_id=?", (sid,)).fetchall():
        fp = pathlib.Path(app.config["UPLOAD_FOLDER"]) / note["filename"]
        if fp.exists(): fp.unlink()
    for tbl in ("topics","notes","chat_messages","timetable_entries"):
        col = "subject_id" if tbl != "timetable_entries" else "subject_id"
        db.execute(f"DELETE FROM {tbl} WHERE {col}=?", (sid,))
    db.execute("DELETE FROM subjects WHERE id=?", (sid,))
    db.commit()
    flash("Subject removed.", "success")
    return redirect(url_for("subjects"))


# ── Subject detail ────────────────────────────────────────────────────────────

@app.route("/subjects/<int:sid>", methods=["GET","POST"])
@login_required
def subject_detail(sid):
    db = db_module.get_db()
    subject = db.execute("SELECT * FROM subjects WHERE id=? AND user_id=?", (sid, g.user["id"])).fetchone()
    if not subject:
        flash("Subject not found.", "error")
        return redirect(url_for("subjects"))
    if request.method == "POST":
        name = request.form.get("name","").strip()
        if not name:
            flash("Topic name required.", "error")
        else:
            db.execute("INSERT INTO topics (subject_id, name) VALUES (?,?)", (sid, name))
            db.commit()
            flash(f'Topic "{name}" added.', "success")
        return redirect(url_for("subject_detail", sid=sid))

    topics = db.execute("SELECT * FROM topics WHERE subject_id=? ORDER BY created_at ASC", (sid,)).fetchall()
    notes  = db.execute("SELECT * FROM notes WHERE subject_id=? AND user_id=? ORDER BY uploaded_at DESC", (sid, g.user["id"])).fetchall()
    chat_history = db.execute(
        "SELECT * FROM chat_messages WHERE subject_id=? AND user_id=? ORDER BY created_at ASC LIMIT 50",
        (sid, g.user["id"])).fetchall()

    total = len(topics); done = sum(1 for t in topics if t["is_completed"])
    pct   = round((done/total)*100) if total else 0
    return render_template("subject_detail.html",
        subject=subject, topics=topics, notes=notes,
        chat_history=chat_history,
        total=total, completed=done, completion_percent=pct,
        today=date.today(), human_size=_human, type_label=TYPE_LABEL,
    )


# ── Topics ────────────────────────────────────────────────────────────────────

@app.route("/topics/<int:tid>/toggle", methods=["POST"])
@login_required
def toggle_topic(tid):
    db = db_module.get_db()
    topic = db.execute(
        "SELECT topics.* FROM topics JOIN subjects ON subjects.id=topics.subject_id "
        "WHERE topics.id=? AND subjects.user_id=?", (tid, g.user["id"])).fetchone()
    if not topic: return jsonify({"error": "Not found"}), 404
    new_state   = 0 if topic["is_completed"] else 1
    completed_at = datetime.now().isoformat(timespec="seconds") if new_state else None
    db.execute("UPDATE topics SET is_completed=?, completed_at=? WHERE id=?", (new_state, completed_at, tid))
    db.commit()
    counts = db.execute(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN is_completed=1 THEN 1 ELSE 0 END) AS done "
        "FROM topics WHERE subject_id=?", (topic["subject_id"],)).fetchone()
    t, d = counts["total"] or 0, counts["done"] or 0
    return jsonify({"is_completed": bool(new_state), "subject_completion_percent": round((d/t)*100) if t else 0})

@app.route("/topics/<int:tid>/delete", methods=["POST"])
@login_required
def delete_topic(tid):
    db = db_module.get_db()
    topic = db.execute(
        "SELECT topics.subject_id FROM topics JOIN subjects ON subjects.id=topics.subject_id "
        "WHERE topics.id=? AND subjects.user_id=?", (tid, g.user["id"])).fetchone()
    if not topic:
        flash("Topic not found.", "error")
        return redirect(url_for("subjects"))
    db.execute("DELETE FROM topics WHERE id=?", (tid,))
    db.commit()
    flash("Topic removed.", "success")
    return redirect(url_for("subject_detail", sid=topic["subject_id"]))

@app.route("/subjects/<int:sid>/topics/quick-add", methods=["POST"])
@login_required
def quick_add_topic(sid):
    db = db_module.get_db()
    if not db.execute("SELECT id FROM subjects WHERE id=? AND user_id=?", (sid, g.user["id"])).fetchone():
        return jsonify({"error": "Not found"}), 404
    name = (request.get_json(silent=True) or {}).get("name","").strip()
    if not name: return jsonify({"error": "Name required"}), 400
    db.execute("INSERT INTO topics (subject_id, name) VALUES (?,?)", (sid, name))
    db.commit()
    new = db.execute("SELECT id FROM topics WHERE subject_id=? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    counts = db.execute(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN is_completed=1 THEN 1 ELSE 0 END) AS done "
        "FROM topics WHERE subject_id=?", (sid,)).fetchone()
    t, d = counts["total"] or 0, counts["done"] or 0
    return jsonify({"topic_id": new["id"], "name": name, "total_topics": t,
                    "completion_percent": round((d/t)*100) if t else 0})

@app.route("/subjects/<int:sid>/suggest-topics", methods=["POST"])
@login_required
def suggest_topics(sid):
    db = db_module.get_db()
    subject = db.execute("SELECT * FROM subjects WHERE id=? AND user_id=?", (sid, g.user["id"])).fetchone()
    if not subject: return jsonify({"error": "Not found"}), 404
    existing = {r["name"].strip().lower() for r in db.execute("SELECT name FROM topics WHERE subject_id=?", (sid,)).fetchall()}
    try:
        suggestions = suggest_important_topics(subject["name"], subject["difficulty"])
    except AIConfigError as e: return jsonify({"error": str(e), "error_type": "config"}), 400
    except AIRequestError as e: return jsonify({"error": str(e), "error_type": "request"}), 502
    return jsonify({"topics": [s for s in suggestions if s.strip().lower() not in existing]})


# ── AI Chat ───────────────────────────────────────────────────────────────────

@app.route("/subjects/<int:sid>/chat", methods=["POST"])
@login_required
def chat(sid):
    """
    JSON endpoint for the chatbot. Receives {"message": "..."} and returns
    {"reply": "..."}.  Stores both sides in chat_messages for history.
    """
    db = db_module.get_db()
    subject = db.execute("SELECT * FROM subjects WHERE id=? AND user_id=?", (sid, g.user["id"])).fetchone()
    if not subject: return jsonify({"error": "Subject not found"}), 404

    data    = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message: return jsonify({"error": "Message is empty"}), 400

    # Fetch topic names for context
    topic_names = [r["name"] for r in db.execute(
        "SELECT name FROM topics WHERE subject_id=?", (sid,)).fetchall()]

    # Last 10 turns for conversation context
    history = [{"role": r["role"], "content": r["content"]} for r in db.execute(
        "SELECT role, content FROM chat_messages WHERE subject_id=? AND user_id=? "
        "ORDER BY created_at ASC LIMIT 20", (sid, g.user["id"])).fetchall()]

    try:
        reply = chat_with_subject(
            subject_name=subject["name"],
            difficulty=subject["difficulty"],
            is_weak=bool(subject["is_weak"]),
            topics=topic_names,
            history=history,
            user_message=message,
        )
    except AIConfigError as e: return jsonify({"error": str(e), "error_type": "config"}), 400
    except AIRequestError as e: return jsonify({"error": str(e), "error_type": "request"}), 502

    # Persist both messages
    for role, content in [("user", message), ("assistant", reply)]:
        db.execute("INSERT INTO chat_messages (user_id, subject_id, role, content) VALUES (?,?,?,?)",
                   (g.user["id"], sid, role, content))
    db.commit()
    return jsonify({"reply": reply})

@app.route("/subjects/<int:sid>/chat/clear", methods=["POST"])
@login_required
def clear_chat(sid):
    db = db_module.get_db()
    db.execute("DELETE FROM chat_messages WHERE subject_id=? AND user_id=?", (sid, g.user["id"]))
    db.commit()
    flash("Chat history cleared.", "success")
    return redirect(url_for("subject_detail", sid=sid))


# ── Notes ─────────────────────────────────────────────────────────────────────

@app.route("/subjects/<int:sid>/notes", methods=["POST"])
@login_required
def upload_note(sid):
    db = db_module.get_db()
    if not db.execute("SELECT id FROM subjects WHERE id=? AND user_id=?", (sid, g.user["id"])).fetchone():
        flash("Subject not found.", "error"); return redirect(url_for("subjects"))
    file = request.files.get("note_file")
    if not file or file.filename == "":
        flash("No file selected.", "error"); return redirect(url_for("subject_detail", sid=sid))
    original = secure_filename(file.filename)
    ext      = pathlib.Path(original).suffix.lower()
    if not _allowed(original):
        flash("File type not accepted. Allowed: PDF, Word, PPT, Excel, TXT, JPG, PNG.", "error")
        return redirect(url_for("subject_detail", sid=sid))
    if not _magic_ok(file, ext):
        flash(f"File content doesn't match its extension ({ext}).", "error")
        return redirect(url_for("subject_detail", sid=sid))
    used  = _storage_used(db, g.user["id"])
    quota = app.config["USER_STORAGE_QUOTA"]
    if used >= quota:
        flash(f"Storage quota full ({_human(quota)}). Delete some files first.", "error")
        return redirect(url_for("subject_detail", sid=sid))
    disk_name = f"{uuid.uuid4().hex}{ext}"
    upload_folder = pathlib.Path(app.config["UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)
    save_path = upload_folder / disk_name
    file.save(save_path)
    fsize = save_path.stat().st_size
    if used + fsize > quota:
        save_path.unlink()
        flash(f"File too large for remaining quota ({_human(quota-used)} left).", "error")
        return redirect(url_for("subject_detail", sid=sid))
    db.execute("INSERT INTO notes (user_id,subject_id,filename,original_name,file_size,mime_type) VALUES (?,?,?,?,?,?)",
               (g.user["id"], sid, disk_name, original, fsize, MIME_MAP.get(ext,"application/octet-stream")))
    db.commit()
    flash(f'"{original}" uploaded ({_human(fsize)}).', "success")
    return redirect(url_for("subject_detail", sid=sid))

@app.route("/notes")
@login_required
def notes_overview():
    db = db_module.get_db()
    all_subjects = db.execute("SELECT * FROM subjects WHERE user_id=? ORDER BY exam_date ASC", (g.user["id"],)).fetchall()
    grouped = []
    for s in all_subjects:
        notes = db.execute("SELECT * FROM notes WHERE subject_id=? AND user_id=? ORDER BY uploaded_at DESC", (s["id"], g.user["id"])).fetchall()
        if notes: grouped.append({"subject": s, "notes": notes})
    used = _storage_used(db, g.user["id"])
    quota = app.config["USER_STORAGE_QUOTA"]
    return render_template("notes.html", grouped=grouped,
        total_notes=sum(len(g["notes"]) for g in grouped),
        used_bytes=used, quota_bytes=quota,
        used_pct=round((used/quota)*100) if quota else 0,
        human_size=_human, type_label=TYPE_LABEL)

@app.route("/notes/<int:nid>/download")
@login_required
def download_note(nid):
    db = db_module.get_db()
    note = db.execute("SELECT * FROM notes WHERE id=? AND user_id=?", (nid, g.user["id"])).fetchone()
    if not note: flash("Note not found.", "error"); return redirect(url_for("notes_overview"))
    fp = pathlib.Path(app.config["UPLOAD_FOLDER"]) / note["filename"]
    if not fp.exists(): flash("File missing from server.", "error"); return redirect(url_for("notes_overview"))
    mime = note["mime_type"] or MIME_MAP.get(fp.suffix.lower(), "application/octet-stream")
    return send_file(fp, mimetype=mime,
                     as_attachment=mime not in {"application/pdf","image/jpeg","image/png","text/plain"},
                     download_name=note["original_name"])

@app.route("/notes/<int:nid>/delete", methods=["POST"])
@login_required
def delete_note(nid):
    db = db_module.get_db()
    note = db.execute("SELECT * FROM notes WHERE id=? AND user_id=?", (nid, g.user["id"])).fetchone()
    if not note: flash("Note not found.", "error"); return redirect(url_for("notes_overview"))
    fp = pathlib.Path(app.config["UPLOAD_FOLDER"]) / note["filename"]
    if fp.exists(): fp.unlink()
    db.execute("DELETE FROM notes WHERE id=?", (nid,))
    db.commit()
    flash(f'"{note["original_name"]}" deleted.', "success")
    ref = request.referrer or ""
    return redirect(url_for("notes_overview") if "notes" in ref and "subjects" not in ref
                    else url_for("subject_detail", sid=note["subject_id"]))


# ── Settings ──────────────────────────────────────────────────────────────────

@app.route("/settings", methods=["GET","POST"])
@login_required
def settings():
    db = db_module.get_db()
    if request.method == "POST":
        try:
            hours = float(request.form["daily_study_hours"])
            assert 0.5 <= hours <= 18
        except (ValueError, AssertionError):
            flash("Enter a number between 0.5 and 18.", "error")
        else:
            db.execute("UPDATE users SET daily_study_hours=? WHERE id=?", (hours, g.user["id"]))
            db.commit(); flash("Study hours updated.", "success")
            return redirect(url_for("settings"))
    return render_template("settings.html")


# ── Timetable ─────────────────────────────────────────────────────────────────

@app.route("/timetable")
@login_required
def timetable():
    db  = db_module.get_db(); today = date.today()
    plan = db.execute(
        "SELECT t.*, s.name AS subject_name FROM timetable_entries t "
        "JOIN subjects s ON s.id=t.subject_id "
        "WHERE t.user_id=? AND t.plan_date=? ORDER BY t.priority_score DESC",
        (g.user["id"], today.isoformat())).fetchall()
    has_subjects = db.execute("SELECT COUNT(*) AS c FROM subjects WHERE user_id=?", (g.user["id"],)).fetchone()["c"] > 0
    return render_template("timetable.html", plan=plan, today=today,
                           has_subjects=has_subjects, daily_hours=g.user["daily_study_hours"])

@app.route("/timetable/generate", methods=["POST"])
@login_required
def generate_timetable():
    db = db_module.get_db(); today = date.today()
    rows = db.execute("SELECT * FROM subjects WHERE user_id=?", (g.user["id"],)).fetchall()
    if not rows: flash("Add at least one subject first.", "error"); return redirect(url_for("subjects"))
    plan = build_timetable(rows, g.user["daily_study_hours"], today)
    if not plan: flash("All exam dates are in the past. Update your subjects.", "error"); return redirect(url_for("subjects"))
    db.execute("DELETE FROM timetable_entries WHERE user_id=? AND plan_date=?", (g.user["id"], today.isoformat()))
    for row in plan:
        db.execute("INSERT INTO timetable_entries (user_id,subject_id,plan_date,allocated_hours,priority_score) VALUES (?,?,?,?,?)",
                   (g.user["id"], row["subject_id"], today.isoformat(), row["allocated_hours"], row["priority_score"]))
    db.commit(); flash("Today's timetable generated.", "success")
    return redirect(url_for("timetable"))
