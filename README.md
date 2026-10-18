# StudyAI — AI-Powered Study Planner (Phase 1-4)

A complete Flask web app: auth, timetable, progress tracking,
PDF notes (1 GB storage), and a full AI chatbot per subject.

---

## Quick start (first time)

  cd study_planner
  python -m venv venv
  source venv/bin/activate      (Windows: venv\Scripts\activate)
  pip install -r requirements.txt
  flask --app app init-db
  flask --app app run --debug

Open http://127.0.0.1:5000

## Upgrading (keep existing data)

  flask --app app migrate
  flask --app app run --debug

## SQLite error? (any time)

  python fix_db.py

---

## AI chatbot setup (Gemini, free)

1. Get a free key at https://aistudio.google.com/apikey
2. Copy .env.example to .env
3. Set GEMINI_API_KEY=your-key-here in .env
4. Restart the server

Without a key the app works fully -- only AI features show a friendly error.

---

## What is in each phase

Phase 1: Auth, subjects, timetable generation (priority formula)
Phase 2: Topics, progress tracking, tomorrow's focus recommendations
Phase 3: File uploads (PDF/Word/PPT/Excel/TXT/Image), 1 GB quota, secure serving
Phase 4: AI chatbot per subject + smart topic suggestions (Gemini)

---

## Phase 4 features

AI CHATBOT (per subject)
  - Full conversational chat interface on each subject's detail page
  - Context-aware: Gemini knows the subject name, difficulty, weak flag, and topics
  - 6 quick-prompt cards: Explain simply, What to focus on, Practice questions,
    Key summary, Common mistakes, Study plan
  - Conversation history stored per subject (last 20 turns sent as context)
  - Typing indicator with animated dots while Gemini responds
  - Clear chat button to start fresh

DASHBOARD TOKEN CARDS (6 cards)
  - Subjects tracked
  - Upcoming exams
  - Weak subjects
  - Files uploaded
  - AI questions asked
  - Storage used

---

## Accepted file types

PDF, Word (.doc/.docx), PowerPoint (.ppt/.pptx), Excel (.xls/.xlsx),
plain text (.txt), JPEG, PNG

Security: extension check + magic byte validation + UUID disk filename
+ ownership check on every download + 1 GB per-user quota
