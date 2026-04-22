from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from dotenv import load_dotenv
import sqlite3
import os

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))

from flask import Flask, request, jsonify
import requests

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# MODELS
MODEL_CHAT = "nvidia/nemotron-3-super-120b-a12b:free"
MODEL_EMBED = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
# ── Database setup ────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect("users.db", timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS onboarding (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            temp_history TEXT DEFAULT '[]',
            user_type TEXT DEFAULT '',
            dynamic_answer TEXT DEFAULT '',
            goal TEXT DEFAULT '',
            challenge TEXT DEFAULT '',
            ai_summary TEXT DEFAULT '',
            completed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()

init_db()

from flask import request, jsonify
from modules.ai_helper import ask_ai


def call_chat_ai(prompt):

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": MODEL_CHAT,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            }
        )

        data = response.json()
        print("CHAT RESPONSE:", data)

        if "choices" not in data:
            return "AI Error: " + str(data)

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        return str(e)

def get_embedding(text):

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/embeddings",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": MODEL_EMBED,
                "input": text
            }
        )

        data = response.json()
        print("EMBED RESPONSE:", data)

        return data["data"][0]["embedding"]

    except Exception as e:
        print("Embedding error:", e)
        return []

# ── Login required decorator ──────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"]    = user["id"]
            session["user_email"] = user["email"]
            session.permanent     = True
            return redirect(url_for("dashboard"))

        flash("Incorrect email or password.")
    return render_template("auth.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if len(password) < 4:
            flash("Password must be at least 8 characters.")
            return render_template("auth.html")

        password_hash = generate_password_hash(password)

        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, password_hash)
            )
            conn.commit()
            conn.close()
            flash("Account created! Please log in.")
            return redirect(url_for("login"))
        except Exception:
            flash("An account with that email already exists.")
            return render_template("auth.html")

    return render_template("auth.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

from modules.ai_helper import generate_next_question, generate_final_summary
import json

def has_completed_onboarding(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT completed FROM onboarding WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    return row and row["completed"] == 1


def get_history(user_id):
    """Read conversation history from DB."""
    conn = get_db()
    row = conn.execute(
        "SELECT temp_history FROM onboarding WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    if row and row["temp_history"]:
        try:
            return json.loads(row["temp_history"])
        except Exception:
            return []
    return []


def save_history(user_id, history):
    """Write conversation history to DB."""
    conn = get_db()
    conn.execute("""
        INSERT INTO onboarding (user_id, temp_history)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET temp_history = excluded.temp_history
    """, (user_id, json.dumps(history)))
    conn.commit()
    conn.close()


@app.route("/onboarding")
@login_required
def onboarding():
    if has_completed_onboarding(session["user_id"]):
        return redirect(url_for("dashboard"))
    # Reset any partial history
    save_history(session["user_id"], [])
    return render_template("onboarding.html")


@app.route("/onboarding/q1", methods=["POST"])
@login_required
def onboarding_q1():
    # Clear history for fresh start
    save_history(session["user_id"], [])
    first_question = (
        "Tell me about your current role or career situation "
        "— what are you working toward right now?"
    )
    return json.dumps({"question": first_question})


@app.route("/onboarding/answer", methods=["POST"])
@login_required
def onboarding_answer():
    try:
        data            = request.get_json(force=True)
        question_text   = data.get("question", "").strip()
        answer_text     = data.get("answer", "").strip()
        question_number = int(data.get("question_number", 1))

        print(f"\n--- Q{question_number} submitted ---")
        print(f"Q: {question_text}")
        print(f"A: {answer_text}")

        # Load history from DB, append this turn, save back
        history = get_history(session["user_id"])
        history.append({"q": question_text, "a": answer_text})
        save_history(session["user_id"], history)

        print(f"History now has {len(history)} turns")

        # After Q4 — signal frontend to request summary
        if question_number >= 4:
            return json.dumps({"status": "done"})

        # Generate next question using full history
        next_q_num    = question_number + 1
        next_question = generate_next_question(history, next_q_num)

        print(f"Generated Q{next_q_num}: {next_question}")

        return json.dumps({
            "status":          "next",
            "question":        next_question,
            "question_number": next_q_num
        })

    except Exception as e:
        import traceback
        print("ERROR in onboarding_answer:")
        traceback.print_exc()
        return json.dumps({"status": "error", "message": str(e)}), 500


@app.route("/onboarding/finish", methods=["POST"])
@login_required
def onboarding_finish():
    try:
        user_id = session["user_id"]
        history = get_history(user_id)

        print(f"\n--- Generating summary for {len(history)} turns ---")
        for i, t in enumerate(history):
            print(f"  Q{i+1}: {t['q'][:60]}")
            print(f"  A{i+1}: {t['a'][:60]}")

        if len(history) < 4:
            return json.dumps({
                "error": f"Only {len(history)} answers recorded. Please complete all 4 questions."
            }), 400

        summary = generate_final_summary(history)

        # Save completed profile
        conn = get_db()
        conn.execute("""
            INSERT INTO onboarding
                (user_id, temp_history, user_type, dynamic_answer,
                 goal, challenge, ai_summary, completed)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                temp_history   = excluded.temp_history,
                user_type      = excluded.user_type,
                dynamic_answer = excluded.dynamic_answer,
                goal           = excluded.goal,
                challenge      = excluded.challenge,
                ai_summary     = excluded.ai_summary,
                completed      = 1
        """, (
            user_id,
            json.dumps(history),
            history[0]["a"][:300],
            history[1]["a"][:300] if len(history) > 1 else "",
            history[2]["a"][:300] if len(history) > 2 else "",
            history[3]["a"][:300] if len(history) > 3 else "",
            summary
        ))
        conn.commit()
        conn.close()

        return json.dumps({"status": "done", "summary": summary})

    except Exception as e:
        import traceback
        print("ERROR in onboarding_finish:")
        traceback.print_exc()
        return json.dumps({"status": "error", "message": str(e)}), 500

@app.route("/next-question", methods=["POST"])
def next_question():

    data = request.get_json()
    answers = data.get("answers", {})
    slide = data.get("slide")

    prompt = f"""
You are an AI onboarding mentor.

User answers so far:
{answers}

Generate next question for onboarding.

Return ONLY JSON:
{{
 "question": "...",
 "placeholder": "..."
}}
"""

    reply = call_chat_ai(prompt)

    try:
        import json
        return jsonify(json.loads(reply))
    except:
        return jsonify({
            "question": "⚠️ Try again",
            "placeholder": "Something went wrong"
        })

@app.route("/generate-dashboard", methods=["POST"])
def generate_dashboard():

    data = request.get_json()
    answers = data.get("answers", {})

    # 🔹 Combine all answers
    combined_text = " ".join(answers.values())

    # 🔹 Generate embedding
    embedding_vector = get_embedding(combined_text)

    # 👉 You can store this in DB later
    print("USER VECTOR:", embedding_vector[:5])  # preview

    # 🔹 Generate dashboard
    prompt = f"""
User answers:
{answers}

Create a personalized goal dashboard.

Include:
- Goal summary
- Roadmap
- Skills
- Weekly plan
- Projects
- Motivation

Return clean HTML.
"""

    dashboard = call_chat_ai(prompt)

    return jsonify({
        "dashboard": dashboard
    })

@app.route("/test-chat")
def test_chat():
    return call_chat_ai("Say hello like a mentor")

@app.route("/test-embed")
def test_embed():
    return str(get_embedding("I am a student learning AI")[:5])

@app.route("/dashboard")
@login_required
def dashboard():
    if not has_completed_onboarding(session["user_id"]):
        return redirect(url_for("onboarding"))

    conn = get_db()
    profile = conn.execute(
        "SELECT * FROM onboarding WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()
    conn.close()

    return render_template("dashboard.html",
                           email=session["user_email"],
                           profile=profile)


'''@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", email=session["user_email"])'''

# ── Mentor Chat Page ──────────────────────────────────────────────────────────
@app.route("/mentor")
@login_required
def mentor():
    if not has_completed_onboarding(session["user_id"]):
        return redirect(url_for("onboarding"))

    user_id = session["user_id"]

    # Load user profile
    conn = get_db()
    profile = conn.execute(
        "SELECT * FROM onboarding WHERE user_id = ?", (user_id,)
    ).fetchone()

    # Load existing chat history
    messages = conn.execute(
        """SELECT role, content, created_at
           FROM chat_messages
           WHERE user_id = ?
           ORDER BY created_at ASC""",
        (user_id,)
    ).fetchall()
    conn.close()

    return render_template("mentor.html",
                           email=session["user_email"],
                           profile=profile,
                           messages=messages)

# ── Send Message API ──────────────────────────────────────────────────────────
@app.route("/mentor/send", methods=["POST"])
@login_required
def mentor_send():
    try:
        data        = request.get_json(force=True)
        user_msg    = data.get("message", "").strip()

        if not user_msg:
            return json.dumps({"error": "Empty message"}), 400

        if len(user_msg) > 2000:
            return json.dumps({"error": "Message too long"}), 400

        user_id = session["user_id"]
        conn    = get_db()

        # Load profile for context
        profile_row = conn.execute(
            "SELECT * FROM onboarding WHERE user_id = ?", (user_id,)
        ).fetchone()

        if not profile_row:
            return json.dumps({"error": "Profile not found"}), 400

        user_profile = {
            "user_type": profile_row["user_type"],
            "goal":      profile_row["goal"],
            "challenge": profile_row["challenge"],
            "ai_summary": profile_row["ai_summary"]
        }

        # Load recent chat history from DB
        history_rows = conn.execute(
            """SELECT role, content FROM chat_messages
               WHERE user_id = ?
               ORDER BY created_at ASC""",
            (user_id,)
        ).fetchall()

        chat_history = [{"role": r["role"], "content": r["content"]}
                        for r in history_rows]

        # Get AI reply
        from modules.ai_helper import get_mentor_reply
        reply = get_mentor_reply(user_profile, chat_history, user_msg)

        # Save both user message and AI reply to DB
        conn.execute(
            "INSERT INTO chat_messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, "user", user_msg)
        )
        conn.execute(
            "INSERT INTO chat_messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, "assistant", reply)
        )
        conn.commit()
        conn.close()

        return json.dumps({"reply": reply})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return json.dumps({"error": str(e)}), 500


# ── Clear Chat History ────────────────────────────────────────────────────────
@app.route("/mentor/clear", methods=["POST"])
@login_required
def mentor_clear():
    conn = get_db()
    conn.execute(
        "DELETE FROM chat_messages WHERE user_id = ?",
        (session["user_id"],)
    )
    conn.commit()
    conn.close()
    return json.dumps({"status": "cleared"})

@app.route("/reset-db")
def reset_db():
    conn = get_db()
    conn.execute("DROP TABLE IF EXISTS users")
    conn.execute("DROP TABLE IF EXISTS onboarding")
    conn.execute("DROP TABLE IF EXISTS chat_messages")
    conn.commit()
    conn.close()
    init_db()
    return "Database reset successfully. <a href='/'>Go home</a>"

if __name__ == "__main__":
    app.run(debug=True)


