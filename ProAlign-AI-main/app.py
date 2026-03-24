from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
import datetime
import base64
import numpy as np
import cv2
import mediapipe as mp
from deepface import DeepFace
app = Flask(__name__)
app.secret_key = "proalign_ai_secret"

DATABASE = "database.db"
UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ==============================
# DATABASE
# ==============================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    # USERS
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT UNIQUE,
        password TEXT,
        theme TEXT DEFAULT 'dark',
        profile_pic TEXT DEFAULT 'default.png',
        created_at TEXT
    )
    """)

    # QUESTIONS
    c.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        question TEXT,
        keywords TEXT
    )
    """)

    # INTERVIEWS
    c.execute("""
    CREATE TABLE IF NOT EXISTS interviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        role TEXT,
        started_at TEXT,
        ended_at TEXT,
        technical REAL,
        emotion REAL,
        posture REAL,
        overall REAL
    )
    """)

    # ANSWERS
    c.execute("""
    CREATE TABLE IF NOT EXISTS interview_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        interview_id INTEGER,
        question TEXT,
        answer TEXT,
        technical_score REAL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS posture_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        started_at TEXT,
        ended_at TEXT,
        avg_score REAL
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS emotion_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        dominant_emotion TEXT,
        confidence_score REAL,
        stability_score REAL,
        created_at TEXT
    )
    """)
    conn.commit()

    # Insert sample role-based questions if empty
    count = c.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    if count == 0:
        sample_questions = [
            # Software Developer
            ("Software Developer", "Explain OOP concepts.", "encapsulation,inheritance,polymorphism,abstraction"),
            ("Software Developer", "What is REST API?", "stateless,http,get,post"),
            ("Software Developer", "Explain JWT.", "token,authentication,payload,signature"),

            # Data Analyst
            ("Data Analyst", "What is normalization?", "redundancy,1nf,2nf,3nf"),
            ("Data Analyst", "Explain regression.", "prediction,linear,dependent,independent"),

            # Frontend Developer
            ("Frontend Developer", "What is DOM?", "document,html,structure"),
            ("Frontend Developer", "Explain CSS Flexbox.", "flex,layout,alignment"),

            # HR
            ("HR", "Tell me about yourself.", "background,skills,experience"),
            ("HR", "Why should we hire you?", "skills,value,strength")
        ]

        c.executemany(
            "INSERT INTO questions (role, question, keywords) VALUES (?, ?, ?)",
            sample_questions
        )
        conn.commit()

    conn.close()

init_db()

# ==============================
# POSTURE SMART SESSION GLOBALS
# ==============================

mp_pose = mp.solutions.pose
pose = mp_pose.Pose()

posture_scores = []
posture_session_running = False
current_posture_score = 0
# ==============================
# EMOTION SESSION GLOBALS
# ==============================

emotion_history = []
emotion_running = False
# ==============================
# LANDING & AUTH
# ==============================

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/signup")
def signup():
    return render_template("signup.html")


@app.route("/register", methods=["POST"])
def register():
    name = request.form["name"]
    email = request.form["email"]
    password = generate_password_hash(request.form["password"])
    created = datetime.datetime.utcnow().isoformat()

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (name, email, password, created_at) VALUES (?, ?, ?, ?)",
            (name, email, password, created)
        )
        conn.commit()
    except:
        conn.close()
        return "User already exists."

    conn.close()
    return redirect("/login")


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():
    email = request.form["email"]
    password = request.form["password"]

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close()

    if user and check_password_hash(user["password"], password):
        session["user_id"] = user["id"]
        session["name"] = user["name"]
        session["theme"] = user["theme"]
        session["profile_pic"] = user["profile_pic"]
        return redirect("/home")

    return "Invalid credentials."

# ==============================
# HOME
# ==============================

@app.route("/home")
def home():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    interviews = conn.execute(
        "SELECT * FROM interviews WHERE user_id=?",
        (session["user_id"],)
    ).fetchall()

    # Total interviews
    total_interviews = len(interviews)

    # Average confidence (overall score)
    overall_scores = [
        i["overall"] for i in interviews
        if i["overall"] is not None
    ]

    avg_confidence = round(
        sum(overall_scores) / len(overall_scores), 2
    ) if overall_scores else 0

    # Growth stage logic
    if avg_confidence >= 80:
        level = 5
    elif avg_confidence >= 65:
        level = 4
    elif avg_confidence >= 50:
        level = 3
    elif avg_confidence >= 30:
        level = 2
    else:
        level = 1

    conn.close()

    return render_template(
        "home.html",
        name=session.get("name"),
        interviews=interviews,
        total_interviews=total_interviews,
        avg_confidence=avg_confidence,
        level=level
    )

# ==============================
# ROLE SELECTION
# ==============================

@app.route("/select_role")
def select_role():
    if "user_id" not in session:
        return redirect("/login")

    roles = ["Software Developer", "Data Analyst", "Frontend Developer", "HR"]
    return render_template("select_role.html", roles=roles)


@app.route("/start_interview", methods=["POST"])
def start_interview():
    if "user_id" not in session:
        return redirect("/login")

    role = request.form.get("role")
    if not role:
        return redirect("/select_role")

    session["selected_role"] = role

    conn = get_db()
    questions = conn.execute(
        "SELECT * FROM questions WHERE role=? ORDER BY RANDOM() LIMIT 5",
        (role,)
    ).fetchall()
    conn.close()

    session["question_data"] = [
        {"question": q["question"], "keywords": q["keywords"]}
        for q in questions
    ]

    session["current_index"] = 0
    session["answers"] = []

    # Create interview record
    conn = get_db()
    started = datetime.datetime.utcnow().isoformat()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO interviews (user_id, role, started_at) VALUES (?, ?, ?)",
        (session["user_id"], role, started)
    )
    conn.commit()
    session["interview_id"] = cur.lastrowid
    conn.close()

    return redirect("/interview")

# ==============================
# INTERVIEW
# ==============================

emotion_scores = []
posture_scores = []

@app.route("/interview")
def interview():
    if "user_id" not in session:
        return redirect("/login")

    if "question_data" not in session:
        return redirect("/select_role")

    return render_template("interview.html")


@app.route("/get_question")
def get_question():
    index = session.get("current_index", 0)
    questions = session.get("question_data", [])

    if index < len(questions):
        return jsonify({"question": questions[index]["question"]})

    return jsonify({"question": None})


@app.route("/submit_answer", methods=["POST"])
def submit_answer():
    data = request.json
    answer = data.get("answer", "")

    index = session.get("current_index", 0)
    questions = session.get("question_data", [])

    if index >= len(questions):
        return jsonify({"status": "done"})

    current = questions[index]

    # Advanced Offline Technical Scoring
    keywords = [k.strip().lower() for k in current["keywords"].split(",")]
    answer_lower = answer.lower()
    match_count = sum(1 for k in keywords if k in answer_lower)

    length_bonus = min(len(answer.split()) / 10, 1)
    technical_score = round(((match_count / len(keywords)) * 7) + (length_bonus * 3), 2)

    session["answers"].append({
        "question": current["question"],
        "answer": answer,
        "technical_score": technical_score
    })

    conn = get_db()
    conn.execute("""
        INSERT INTO interview_answers (interview_id, question, answer, technical_score)
        VALUES (?, ?, ?, ?)
    """, (session["interview_id"], current["question"], answer, technical_score))
    conn.commit()
    conn.close()

    session["current_index"] += 1

    return jsonify({"status": "next"})


@app.route("/analyze_frame", methods=["POST"])
def analyze_frame():
    global emotion_scores, posture_scores

    try:
        data = request.json["image"]
        encoded_data = data.split(",")[1]
        np_arr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        result = DeepFace.analyze(frame, actions=['emotion'], enforce_detection=False)
        dominant = result[0]['dominant_emotion'] if isinstance(result, list) else result['dominant_emotion']

        emotion_scores.append(1 if dominant in ["happy", "neutral"] else 0)
        posture_scores.append(1)

        emotion_avg = round((sum(emotion_scores)/len(emotion_scores))*10,2)
        posture_avg = round((sum(posture_scores)/len(posture_scores))*10,2)

        return jsonify({"emotion_score": emotion_avg, "posture_score": posture_avg})

    except:
        return jsonify({"emotion_score": 0, "posture_score": 0})

@app.route("/posture")
def posture():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("posture.html")

@app.route("/start_posture_session", methods=["POST"])
def start_posture_session():

    global posture_session_running, posture_scores

    posture_scores = []
    posture_session_running = True

    started = datetime.datetime.utcnow().isoformat()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO posture_sessions (user_id, started_at)
        VALUES (?, ?)
    """, (session["user_id"], started))
    conn.commit()

    session["posture_session_id"] = cur.lastrowid
    conn.close()

    return {"status": "started"}

@app.route("/analyze_posture_frame", methods=["POST"])
def analyze_posture_frame():

    global current_posture_score, posture_scores, posture_session_running

    if not posture_session_running:
        return {"score": 0}

    data = request.json["image"]

    # Decode base64 image
    img_data = base64.b64decode(data.split(",")[1])
    np_arr = np.frombuffer(img_data, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = pose.process(rgb)

    score = 0

    if results.pose_landmarks:

        landmarks = results.pose_landmarks.landmark

        left_shoulder = landmarks[11]
        right_shoulder = landmarks[12]
        nose = landmarks[0]

        # Shoulder alignment check
        shoulder_diff = abs(left_shoulder.y - right_shoulder.y)

        # Head tilt check
        shoulder_mid_x = (left_shoulder.x + right_shoulder.x) / 2
        head_offset = abs(nose.x - shoulder_mid_x)

        if shoulder_diff < 0.05 and head_offset < 0.05:
            score = 10
        elif shoulder_diff < 0.08:
            score = 6
        else:
            score = 3

    current_posture_score = score
    posture_scores.append(score)

    return {"score": score}

@app.route("/stop_posture_session", methods=["POST"])
def stop_posture_session():

    global posture_session_running, posture_scores

    posture_session_running = False

    avg_score = 0
    if posture_scores:
        avg_score = round(sum(posture_scores) / len(posture_scores), 2)

    ended = datetime.datetime.utcnow().isoformat()

    conn = get_db()
    conn.execute("""
        UPDATE posture_sessions
        SET ended_at=?, avg_score=?
        WHERE id=?
    """, (ended, avg_score, session.get("posture_session_id")))
    conn.commit()
    conn.close()

    return {"status": "stopped", "avg_score": avg_score}

@app.route("/emotion")
def emotion():
    if "user_id" not in session:
        return redirect("/login")

    global emotion_history, emotion_running
    emotion_history = []
    emotion_running = True

    return render_template("emotion.html")

@app.route("/analyze_emotion_frame", methods=["POST"])
def analyze_emotion_frame():

    if not emotion_running:
        return {"status": "stopped"}

    data = request.json["image"]

    # Decode base64 image
    encoded_data = data.split(",")[1]
    nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    try:
        result = DeepFace.analyze(
            frame,
            actions=["emotion"],
            enforce_detection=False
        )

        dominant = result[0]["dominant_emotion"]
        confidence = result[0]["emotion"][dominant]

        emotion_history.append(dominant)

        return {
            "dominant": dominant,
            "confidence": round(confidence, 2)
        }

    except:
        return {"dominant": "neutral", "confidence": 0}
    
@app.route("/finish_emotion", methods=["POST"])
def finish_emotion():

    global emotion_running
    emotion_running = False

    if not emotion_history:
        return {"status": "no_data"}

    from collections import Counter

    counter = Counter(emotion_history)
    dominant = counter.most_common(1)[0][0]

    total = len(emotion_history)
    positive_emotions = ["happy", "neutral"]
    positive_count = sum(counter[e] for e in positive_emotions if e in counter)

    confidence_score = round((positive_count / total) * 100, 2)

    stability_score = round((counter[dominant] / total) * 100, 2)

    # Save to DB
    conn = get_db()
    conn.execute("""
        INSERT INTO emotion_sessions
        (user_id, dominant_emotion, confidence_score, stability_score, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        session["user_id"],
        dominant,
        confidence_score,
        stability_score,
        datetime.datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()

    return {
        "status": "completed",
        "dominant": dominant,
        "confidence_score": confidence_score,
        "stability_score": stability_score
    }
# ==============================
# REPORT
# ==============================

@app.route("/report")
def generate_report():

    if "user_id" not in session:
        return redirect("/login")

    interview_id = session.get("interview_id")
    if not interview_id:
        return redirect("/dashboard")

    conn = get_db()

    # ===============================
    # TECHNICAL SCORE (FROM DB)
    # ===============================
    answers = conn.execute("""
        SELECT technical_score
        FROM interview_answers
        WHERE interview_id=?
    """, (interview_id,)).fetchall()

    technical_scores = [
        a["technical_score"]
        for a in answers
        if a["technical_score"] is not None
    ]

    technical = round(
        sum(technical_scores) / len(technical_scores),
        2
    ) if technical_scores else 0

    # ===============================
    # EMOTION & POSTURE (SESSION)
    # ===============================
    emotion_scores = session.get("emotion_scores", [])
    posture_scores = session.get("posture_scores", [])

    emotion = round(
        (sum(emotion_scores) / len(emotion_scores)) * 10,
        2
    ) if emotion_scores else 0

    posture = round(
        (sum(posture_scores) / len(posture_scores)) * 10,
        2
    ) if posture_scores else 0

    # ===============================
    # OVERALL CALCULATION
    # ===============================
    overall = round(
        (technical * 0.6) +
        (emotion * 0.2) +
        (posture * 0.2),
        2
    )

    ended = datetime.datetime.utcnow().isoformat()

    conn.execute("""
        UPDATE interviews
        SET ended_at=?, technical=?, emotion=?, posture=?, overall=?
        WHERE id=?
    """, (ended, technical, emotion, posture, overall, interview_id))

    conn.commit()
    conn.close()

    # 🔥 Clear session metrics AFTER saving
    session.pop("emotion_scores", None)
    session.pop("posture_scores", None)

    return redirect(f"/report/{interview_id}")

@app.route("/report/<int:id>")
def report_by_id(id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    # ===============================
    # INTERVIEW DATA
    # ===============================
    interview = conn.execute("""
        SELECT *
        FROM interviews
        WHERE id=? AND user_id=?
    """, (id, session["user_id"])).fetchone()

    answers = conn.execute("""
        SELECT question, answer, technical_score
        FROM interview_answers
        WHERE interview_id=?
    """, (id,)).fetchall()

    if not interview:
        conn.close()
        return redirect("/dashboard")

    # ===============================
    # ATTACH LATEST POSTURE SESSION
    # ===============================
    posture_session = conn.execute("""
        SELECT avg_score
        FROM posture_sessions
        WHERE user_id=?
        ORDER BY started_at DESC
        LIMIT 1
    """, (session["user_id"],)).fetchone()

    # ===============================
    # ATTACH LATEST EMOTION SESSION
    # ===============================
    emotion_session = conn.execute("""
        SELECT confidence_score AS avg_score
        FROM emotion_sessions
        WHERE user_id=?
        ORDER BY created_at DESC
        LIMIT 1
    """, (session["user_id"],)).fetchone()

    conn.close()

    # ===============================
    # SAFE VALUE EXTRACTION
    # ===============================
    overall = interview["overall"] or 0
    technical = interview["technical"] or 0

    # If interview already saved emotion/posture use it
    emotion = interview["emotion"] or 0
    posture = interview["posture"] or 0

    # If interview emotion/posture is 0, use latest session values
    if emotion == 0 and emotion_session:
        emotion = emotion_session["avg_score"]

    if posture == 0 and posture_session:
        posture = posture_session["avg_score"]

    # ===============================
    # PROFESSIONAL INDEX (Improved Logic)
    # ===============================
    professional_score = round(
        (technical * 6) + 
        (emotion * 2) + 
        (posture * 2),
        2
    )

    # ===============================
    # PREMIUM BADGE SYSTEM
    # ===============================
    if professional_score >= 90:
        badge = "👑 Elite Performer"
    elif professional_score >= 80:
        badge = "🏆 Interview Ready"
    elif professional_score >= 70:
        badge = "🚀 Strong Candidate"
    elif professional_score >= 60:
        badge = "📈 Promising Talent"
    elif professional_score >= 50:
        badge = "⚡ Developing Professional"
    else:
        badge = "🌱 Beginner — Growth Phase"

    # ===============================
    # STRENGTH / IMPROVEMENT ANALYSIS
    # ===============================
    strengths = []
    improvements = []

    if technical >= 8:
        strengths.append("Excellent technical expertise")
    elif technical >= 6:
        strengths.append("Good technical foundation")
    else:
        improvements.append("Improve technical depth and clarity")

    if emotion >= 8:
        strengths.append("Confident and expressive communication")
    elif emotion >= 6:
        strengths.append("Stable emotional control")
    else:
        improvements.append("Work on facial confidence and tone")

    if posture >= 8:
        strengths.append("Professional body alignment")
    elif posture >= 6:
        strengths.append("Decent posture stability")
    else:
        improvements.append("Maintain upright posture consistently")

    # ===============================
    # SMART AI FEEDBACK (Dynamic)
    # ===============================
    feedback = f"Your professional performance score is {professional_score}%. "

    if strengths:
        feedback += "Key strengths include: " + ", ".join(strengths) + ". "

    if improvements:
        feedback += "Focus on improving: " + ", ".join(improvements) + "."

    # ===============================
    # RENDER
    # ===============================
    # Provide template with explicit report metadata so template conditionals work
    return render_template(
        "report.html",
        report_type="interview",
        created_at=interview["started_at"] or interview["ended_at"],
        avg_score=round(professional_score/10, 2),
        interview={
            **interview,
            "technical": technical,
            "emotion": emotion,
            "posture": posture,
            "overall": professional_score
        },
        answers=answers,
        badge=badge,
        strengths=strengths,
        improvements=improvements,
        feedback=feedback
    )

@app.route("/dashboard")
def performance_dashboard():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    # ===============================
    # INTERVIEW HISTORY
    # ===============================
    interviews = conn.execute("""
        SELECT id, role, overall, started_at
        FROM interviews
        WHERE user_id=?
        ORDER BY started_at DESC
    """, (session["user_id"],)).fetchall()

    # ===============================
    # POSTURE HISTORY
    # ===============================
    posture_sessions = conn.execute("""
        SELECT id, avg_score, started_at AS created_at
        FROM posture_sessions
        WHERE user_id=?
        ORDER BY started_at DESC
    """, (session["user_id"],)).fetchall()

    # ===============================
    # EMOTION HISTORY
    # ===============================
    emotion_sessions = conn.execute("""
        SELECT id, confidence_score AS avg_score, created_at
        FROM emotion_sessions
        WHERE user_id=?
        ORDER BY created_at DESC
    """, (session["user_id"],)).fetchall()

    conn.close()

    # ===============================
    # SAFE AVERAGES (FIXED PROPERLY)
    # ===============================

    valid_interviews = [i["overall"] for i in interviews if i["overall"] is not None]
    interview_avg = round(sum(valid_interviews) / len(valid_interviews), 2) if valid_interviews else 0

    valid_posture = [p["avg_score"] for p in posture_sessions if p["avg_score"] is not None]
    posture_avg = round(sum(valid_posture) / len(valid_posture), 2) if valid_posture else 0

    valid_emotion = [e["avg_score"] for e in emotion_sessions if e["avg_score"] is not None]
    emotion_avg = round(sum(valid_emotion) / len(valid_emotion), 2) if valid_emotion else 0

    # ===============================
    # PROFESSIONAL INDEX
    # ===============================
    professional_index = round(
        (interview_avg * 0.5) +
        (posture_avg * 2.5) +
        (emotion_avg * 2.5),
        2
    )

    # ===============================
    # LEVEL SYSTEM
    # ===============================
    if professional_index >= 85:
        level = "🏆 Interview Ready"
    elif professional_index >= 70:
        level = "🚀 Advanced"
    elif professional_index >= 50:
        level = "📈 Improving"
    else:
        level = "🌱 Beginner"

    return render_template(
        "dashboard.html",
        interviews=interviews,
        posture_sessions=posture_sessions,
        emotion_sessions=emotion_sessions,
        professional_index=professional_index,
        level=level
    )


@app.route("/history")
def history():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    interviews = conn.execute("""
        SELECT * FROM interviews
        WHERE user_id=?
        ORDER BY started_at DESC
    """, (session["user_id"],)).fetchall()

    conn.close()

    return render_template("history.html", interviews=interviews)
# ==============================
# ==============================
# PROFILE
# ==============================

@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (session["user_id"],)
    ).fetchone()
    conn.close()

    return render_template("profile.html", user=user)


@app.route("/update_profile", methods=["POST"])
def update_profile():
    if "user_id" not in session:
        return redirect("/login")

    theme = request.form.get("theme")
    selected_avatar = request.form.get("avatar")

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (session["user_id"],)
    ).fetchone()

    profile_pic = user["profile_pic"]

    # If default avatar selected
    if selected_avatar:
        profile_pic = selected_avatar

    # If uploaded image
    if "profile_pic" in request.files:
        file = request.files["profile_pic"]
        if file.filename != "":
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            profile_pic = "uploads/" + filename

    conn.execute("""
        UPDATE users
        SET theme=?, profile_pic=?
        WHERE id=?
    """, (theme, profile_pic, session["user_id"]))

    conn.commit()
    conn.close()

    # Update session
    session["theme"] = theme
    session["profile_pic"] = profile_pic

    return redirect("/profile")
 
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)