"""
fix_db.py  --  Run this whenever you get an SQLite OperationalError.
Usage:  python fix_db.py
"""
import pathlib, shutil, sqlite3
from datetime import datetime

DB = pathlib.Path(__file__).parent / "study_planner.db"

TABLES = {
    "users": "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, daily_study_hours REAL NOT NULL DEFAULT 4.0, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "subjects": "CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT NOT NULL, exam_date DATE NOT NULL, difficulty INTEGER NOT NULL DEFAULT 3, is_weak INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (id))",
    "timetable_entries": "CREATE TABLE IF NOT EXISTS timetable_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, subject_id INTEGER NOT NULL, plan_date DATE NOT NULL, allocated_hours REAL NOT NULL, priority_score REAL NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (id), FOREIGN KEY (subject_id) REFERENCES subjects (id))",
    "topics": "CREATE TABLE IF NOT EXISTS topics (id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id INTEGER NOT NULL, name TEXT NOT NULL, is_completed INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, completed_at TIMESTAMP, FOREIGN KEY (subject_id) REFERENCES subjects (id))",
    "notes": "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, subject_id INTEGER NOT NULL, filename TEXT NOT NULL, original_name TEXT NOT NULL, file_size INTEGER NOT NULL, mime_type TEXT NOT NULL DEFAULT 'application/octet-stream', uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (id), FOREIGN KEY (subject_id) REFERENCES subjects (id))",
    "chat_messages": "CREATE TABLE IF NOT EXISTS chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, subject_id INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (id), FOREIGN KEY (subject_id) REFERENCES subjects (id))",
}

print("=" * 52)
print("  Study Planner — Database Auto-Fix")
print("=" * 52)

if not DB.exists() or DB.stat().st_size == 0:
    print("\nDatabase missing or empty — creating fresh...")
    conn = sqlite3.connect(DB)
    for name, sql in TABLES.items():
        conn.execute(sql)
        print(f"  Created: {name}")
    conn.commit(); conn.close()
    print("\nDone. Register a new account and log in.")
else:
    backup = DB.parent / f"study_planner_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(DB, backup)
    print(f"\nBackup saved: {backup.name}")
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    fixed = 0
    print("\nChecking tables:")
    for name, sql in TABLES.items():
        if name in existing:
            print(f"  [  OK  ] {name}")
        else:
            conn.execute(sql)
            conn.commit()
            print(f"  [ FIXED] {name}  <-- added")
            fixed += 1
    # Also ensure mime_type column exists on notes
    cols = [r[1] for r in conn.execute("PRAGMA table_info(notes)").fetchall()]
    if "mime_type" not in cols and "notes" in existing:
        conn.execute("ALTER TABLE notes ADD COLUMN mime_type TEXT NOT NULL DEFAULT 'application/octet-stream'")
        conn.commit()
        print("  [ FIXED] notes.mime_type column added")
        fixed += 1
    conn.close()
    if fixed == 0:
        print("\nAll tables OK. If errors persist, delete study_planner.db and run: flask --app app init-db")
    else:
        print(f"\n{fixed} issue(s) fixed. Your existing data was preserved.")

print("\nNow run:  flask --app app run --debug")
print("=" * 52)
