import os
import json
import logging
import time
from datetime import datetime

from flask import Flask, jsonify, render_template, redirect, url_for, flash, session, request, abort, send_from_directory
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional

import pyrebase
import firebase_admin
from firebase_admin import credentials, firestore, db
from jinja2.exceptions import TemplateNotFound

from dotenv import load_dotenv
from openai import OpenAI   # corrected import for OpenAI
import requests
from flask import request, jsonify


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# Load .env
load_dotenv()

# OpenRouter key
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

# AI client
chat_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_KEY
) if OPENROUTER_KEY else None

if not chat_client:
    logger.error("OPENROUTER_KEY missing – AI features disabled")
app = Flask(__name__)

# =============================================================================
#  Firebase Configuration
config = {
    'apiKey': "AIzaSyCnx9tSj5_bJk4qwdoHutv_73iUoGHINWE",
    'authDomain': "insighteval-e56af.firebaseapp.com",
    'projectId': "insighteval-e56af",
    'storageBucket': "insighteval-e56af.appspot.com",
    'messagingSenderId': "184739995469",
    'appId': "1:184739995469:web:9390b124eced0431ff6104",
    'measurementId': "G-S6KDMGXBP8",
    # ✅ Correct Realtime Database URL (replace this with yours from Firebase console)
    'databaseURL': "https://insighteval-e56af-default-rtdb.firebaseio.com/"
}

# ✅ Initialize Pyrebase (client SDK)
firebase = pyrebase.initialize_app(config)
auth = firebase.auth()

# ✅ Initialize Firebase Admin SDK (server SDK)
if not firebase_admin._apps:
    cred = credentials.Certificate("insighteval-e56af-firebase-adminsdk-fbsvc-3c042c68fa.json")
    firebase_admin.initialize_app(cred, {
        'databaseURL': config['databaseURL']   
    })

# ✅ Setup Firestore and Realtime DB clients
firestore_db = firestore.client()
realtime_db = db

# =============================================================================


app.config['SECRET_KEY'] = '1a2b3c4d5e6f7g8h9i0j'
app.config['TEMPLATES_AUTO_RELOAD'] = True

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# =============================================================================
#  Forms
# =============================================================================
class LoginForm(FlaskForm):
    """Form for user login."""
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    submit = SubmitField('Login')


class ProfileForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(min=2, max=50)])
    student_id = StringField('ID', validators=[DataRequired(), Length(min=2, max=20)])
    department = StringField('Department', validators=[DataRequired(), Length(min=2, max=100)])
    bio = TextAreaField('Bio', validators=[Optional(), Length(max=200)])
    submit = SubmitField('Save Profile')
# =============================================================================
#  Routes
# =============================================================================
QUESTION_CACHE = {}

def load_questions(course: str):
    """Load questions from templates/json/<course>_questions.json"""
    if course in QUESTION_CACHE:
        return QUESTION_CACHE[course]

    path = os.path.join("templates", "json", f"{course}_questions.json")
    if not os.path.exists(path):
        logger.warning(f"JSON not found: {path}")
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    QUESTION_CACHE[course] = data.get("questions", [])
    return QUESTION_CACHE[course]
def detect_weak_topics(wrong_questions: list) -> list:
    if not wrong_questions or not chat_client:
        return ["General Review"]

    prompt = "Analyze these wrong questions and return up to 3 main weak topics (comma-separated, short names):\n\n"
    for i, q in enumerate(wrong_questions[:8], 1):
        prompt += f"{i}. {q}\n"
    prompt += "\nWeak topics:"

    try:
        response = chat_client.chat.completions.create(
            model="mistralai/mistral-7b-instruct:free",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=50
        )
        resp = response.choices[0].message.content
        topics = [t.strip() for t in resp.strip().split(",") if t.strip()]
        return topics[:3] or ["General Review"]
    except Exception as e:
        logger.error(f"Topic detection error: {e}")
        return ["General Review"]
    
@app.route("/api/ai_feedback_quiz", methods=["POST"])
def ai_feedback_quiz():
    if not chat_client:
        return jsonify({"error": "AI not configured"}), 500

    data = request.get_json(silent=True) or {}
    course = data.get("course", "general").upper()
    answered = data.get("answered", [])

    if not answered:
        return jsonify({"error": "No answers provided"}), 400

    # === 1. AI-GRADE ALL SHORT_ANSWER QUESTIONS ===
    for q in answered:
        if q.get("type") == "short_answer":
            student = q.get("selected", "").strip()
            expected = q.get("answer", "").strip()
            question = q.get("question", "Short answer")

            if not student or student in ["Not answered", ""]:
                q["correct"] = False
                q["explanation"] = "No answer submitted"
                continue

            prompt = f"""Grade this student's short answer.

Question: {question}
Expected: {expected}
Student said: {student}

Is it essentially correct? Answer with ONLY this JSON:
{{"grade": "CORRECT" or "INCORRECT", "explanation": "1 short sentence"}}
"""

            try:
                resp = chat_client.chat.completions.create(
                    model="mistralai/mistral-7b-instruct:free",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=100
                )
                raw = resp.choices[0].message.content.strip()
                raw = raw.replace("```json", "").replace("```", "").strip()
                result = json.loads(raw)

                q["correct"] = result["grade"] == "CORRECT"
                q["explanation"] = result.get("explanation", "Graded by AI")
            except Exception as e:
                logger.error(f"LLM grading failed: {e}")
                q["correct"] = False
                q["explanation"] = "Auto-grading failed"

        elif q.get("type") == "coding":
            code = q.get("code", "")
            lang = q.get("lang", "71")
            test_cases = q.get("test_cases", [])
            hidden_cases = q.get("hidden_test_cases", [])
            all_cases = test_cases + hidden_cases
            total_marks = q.get("marks", 10)

            if not code.strip():
                q["correct"] = False
                q["explanation"] = "No code submitted"
                q["earned_marks"] = 0
                continue

            JUDGE0_URL = "https://judge0-ce.p.rapidapi.com"
            RAPIDAPI_KEY = "f106eb3bc9msh970dca68389f22dp18d538jsn9745aa68f4bf"

            total_cases = len(all_cases) if all_cases else 1
            passed = 0
            marks_per_case = total_marks / total_cases

            for case in all_cases:
                stdin = case.get("stdin", "")
                expected = case.get("expected", "")
                try:
                    payload = {
                        "source_code": code,
                        "language_id": lang,
                        "stdin": stdin,
                        "redirect_stderr_to_stdout": True
                    }
                    headers = {
                        "x-rapidapi-key": RAPIDAPI_KEY,
                        "x-rapidapi-host": "judge0-ce.p.rapidapi.com",
                        "Content-Type": "application/json"
                    }

                    submission = requests.post(
                        f"{JUDGE0_URL}/submissions?base64_encoded=false&wait=false",
                        json=payload, headers=headers
                    ).json()
                    token = submission.get('token')
                    if not token:
                        continue

                    time.sleep(2)
                    result = requests.get(
                        f"{JUDGE0_URL}/submissions/{token}", headers=headers
                    ).json()

                    actual_output = (result.get('stdout') or
                                    result.get('stderr') or
                                    result.get('compile_output') or
                                    "").strip()

                    def normalize(txt):
                        return txt.replace("\r", "").strip()

                    if normalize(actual_output) == normalize(expected):
                        passed += 1

                except Exception as e:
                    logger.error(f"Judge0 call failed: {e}")

            earned_marks = round(passed * marks_per_case, 2)

            q["passed_cases"] = passed
            q["total_cases"] = total_cases
            q["earned_marks"] = earned_marks
            q["correct"] = passed == total_cases
            q["explanation"] = (
                f"Passed {passed}/{total_cases} test cases → "
                f"Earned {earned_marks}/{total_marks} marks"
            )
    

        else:
            # For non-short-answer questions, just keep their existing correctness
            pass

    # === 2. RECALCULATE FINAL SCORE ===
    earned = 0
    total = 0

    for q in answered:
        q_marks = q.get("marks", 0)
        q_earned = q.get("earned_marks", None)

        # always add full marks to total
        total += q_marks

        # if partial marks exist → use them
        if q_earned is not None:
            earned += q_earned
        # otherwise, for MCQ/short answer: add full marks if correct
        elif q.get("correct"):
            earned += q_marks
            

    #    # === 3. GENERATE MICRO-QUIZ ON THE TEST TOPIC (ALWAYS) ===
    # Use wrong questions if any, otherwise use ALL questions from the test
    if any(not q.get("correct", True) for q in answered):
        topic_qs = [q.get("question", "concept") for q in answered if not q.get("correct")]
    else:
        topic_qs = [q.get("question", "concept") for q in answered]  # even perfect score → revise the topic

    # Take first 3 as focus topics
    weak = ", ".join([q[:70] + "..." if len(q) > 70 else q for q in topic_qs[:3]]) or course

    feedback_prompt = f"""You are a kind, expert tutor.

Student scored {earned}/{total} ({(earned/total*100):.1f}%) in {course}
Weak areas: {weak}

INSTRUCTIONS:
1. Write a 120–150 word feedback.
2. Tone MUST match the score percentage:
   - 0–20%: "You struggled significantly. Here's what went wrong..."
   - 21–45%: "You faced challenges. Let's fix the basics..."
   - 46–70%: "Good effort! You know some parts, but..."
   - 71–89%: "Strong performance! Just a few gaps..."
   - 90–100%: "Excellent! You're mastering this..."
   
3. Structure:
   - Start with tone-matched opener
   - 1 strength (even if score is 0)
   - 2–3 weaknesses (based on weak topics)
   - 3 numbered tips (actionable, 1-line each)
   - End with encouragement

4. Generate exactly 5 MCQs on weak topics only.

Output ONLY valid JSON:
{{
  "feedback": "…",
  "micro_quiz": {{
    "questions": [
      {{"question":"…","options":["a) …","b) …","c) …","d) …"],"answer":"b) …"}},
      {{"question":"…","options":["a) …","b) …","c) …","d) …"],"answer":"a) …"}},
      {{"question":"…","options":["a) …","b) …","c) …","d) …"],"answer":"c) …"}},
      {{"question":"…","options":["a) …","b) …","c) …","d) …"],"answer":"b) …"}},
      {{"question":"…","options":["a) …","b) …","c) …","d) …"],"answer":"b) …"}}
    ]
  }}
}}
"""

    try:
        resp = chat_client.chat.completions.create(
            model="mistralai/mistral-7b-instruct:free",
            messages=[{"role": "user", "content": feedback_prompt}],
            temperature=0.8,
            max_tokens=1000
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        # ROBUST JSON PARSING
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON")
        json_str = raw[start:end]
        result = json.loads(json_str)

    except Exception as e:
        logger.error(f"Feedback generation failed: {e}")
        result = {
            "feedback": "Great effort! Every attempt makes you stronger.",
            "micro_quiz": {"questions": []}
        }

    return jsonify({
        "feedback": result.get("feedback", "Keep learning!"),
        "micro_quiz": result.get("micro_quiz", {"questions": []}),
        "score": earned,
        "total_marks": total,
        "answers": answered
    })
# 4. NOW — add the /run_code route (AFTER app is created!)
@app.route('/run_code', methods=['POST'])
def run_code():
    data = request.json
    source_code = data.get('code')
    language_id = data.get('language_id', 71)  # 71 = Python
    stdin = data.get('input', '')
    expected_output = data.get('expected_output', '').strip()   # <--- ADD THIS

    JUDGE0_URL = "https://judge0-ce.p.rapidapi.com"
    RAPIDAPI_KEY = "f106eb3bc9msh970dca68389f22dp18d538jsn9745aa68f4bf"

    payload = {
        "source_code": source_code,
        "language_id": language_id,
        "stdin": stdin,
        "redirect_stderr_to_stdout": True
    }

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "judge0-ce.p.rapidapi.com",
        "Content-Type": "application/json"
    }

    try:
        # Submit code
        submission = requests.post(
            f"{JUDGE0_URL}/submissions?base64_encoded=false&wait=false",
            json=payload, headers=headers
        ).json()
        token = submission['token']

        # Wait then get result
        import time
        time.sleep(2)
        result = requests.get(f"{JUDGE0_URL}/submissions/{token}", headers=headers).json()

        actual_output = (result.get('stdout') or 
                         result.get('stderr') or 
                         result.get('compile_output') or 
                         "").strip()

        # -----------------------------
        # 🎯 MARKING LOGIC (ADD HERE)
        # -----------------------------
        def normalize(text):
            return text.replace("\r", "").strip()

        actual_clean = normalize(actual_output)
        expected_clean = normalize(expected_output)

        mark = 1 if actual_clean == expected_clean else 0

        return jsonify({
            "output": actual_output,
            "status": result['status']['description'],
            "time": result.get('time', '0'),
            "memory": result.get('memory', '0'),
            "expected_output": expected_output,
            "mark": mark   # <--- RETURN MARKING
        })

    except Exception as e:
        return jsonify({"output": f"Error: {str(e)}", "status": "Error"}), 500

@app.route("/micro_quiz")
def micro_quiz():
    return render_template("micro_quiz.html")

@app.route('/')
def home():
    """Redirects the root URL to the login page."""
    return redirect(url_for('login'))

# LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data

        try:
            # 1️⃣ Sign in user with Firebase Auth
            user = auth.sign_in_with_email_and_password(email, password)

            # 2️⃣ Firestore: check in 'users' collection
            safe_email = email.replace(".", "_")
            doc_ref = firestore_db.collection("users").document(safe_email)
            doc = doc_ref.get()

            if not doc.exists:
                flash("User not found in Firestore. Contact admin.", "error")
                return redirect(url_for('login'))

            user_data = doc.to_dict()
            user_role = user_data.get("role", "Unknown")

            # 3️⃣ Check if profile is complete
            profile_fields = ["name", "id"]  # fields to check in Firestore
            profile_complete = all(
                field in user_data and user_data[field] for field in profile_fields
            )

            # 4️⃣ Set session info
            session['user_email'] = email
            session['user_role'] = user_role

            # 5️⃣ Redirect based on completeness
            if profile_complete:
                flash(f"Welcome back, {email}!", "success")
                return redirect(url_for('dashboard'))
            else:
                flash("Please complete your profile setup.", "info")
                return redirect(url_for('setup_profile'))

        except Exception as e:
            error_msg = str(e)
            if "INVALID_LOGIN_CREDENTIALS" in error_msg:
                flash("Invalid email or password.", "error")
            elif "EMAIL_NOT_FOUND" in error_msg:
                flash("No account found with this email.", "error")
            elif "INVALID_PASSWORD" in error_msg:
                flash("Incorrect password.", "error")
            else:
                flash("Login failed. Please try again.", "error")

    return render_template('login.html', form=form)




# SETUP PROFILE
@app.route('/setup_profile', methods=['GET', 'POST'])
def setup_profile():
    if 'user_email' not in session:
        flash('You must be logged in to setup profile.', 'error')
        return redirect(url_for('login'))

    form = ProfileForm()

    if form.validate_on_submit():
        # Get data from form
        name = form.name.data
        student_id = form.student_id.data
        department = form.department.data
        bio = form.bio.data

        # Get session info
        email = session['user_email']
        role = session.get('user_role', 'Student')  # Default to Student if missing
        safe_email = email.replace('.', '_')

        # Reference to users collection
        user_doc = firestore_db.collection("users").document(safe_email)

        # Data to save
        user_data = {
            'name': name,
            'id': student_id,
            'department': department,
            'bio': bio,
            'role': role
        }

        # Save profile data to Firestore
        user_doc.set(user_data, merge=True)

        flash('Profile saved successfully!', 'success')
        return redirect(url_for('dashboard'))

    # On GET or failed POST, render the form
    return render_template('setup_profile.html', form=form)



#DASHBOARD
@app.route('/dashboard')
def dashboard():
    """Renders the main dashboard for any logged-in user."""
    if 'user_role' not in session:
        flash('You must be logged in to view the dashboard.', 'error')
        return redirect(url_for('login'))
    
    return render_template('dashboard.html')



@app.route('/reset_password', methods=['POST'])
def reset_password():
    if 'user_email' not in session:
        return {"status": "error", "message": "You must be logged in to reset your password."}, 403

    try:
        email = session['user_email']
        auth.send_password_reset_email(email)
        return {"status": "success", "message": f"A password reset link has been sent to {email}."}
    except Exception as e:
        return {"status": "error", "message": f"Error sending reset email: {str(e)}"}, 500




@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_email' not in session:
        return jsonify({'error': 'User not logged in'}), 401

    data = request.get_json()
    name = data.get('name')
    user_id = data.get('id')
    department = data.get('department')
    bio = data.get('bio')

    try:
        safe_email = session['user_email'].replace('.', '_')
        user_doc = firestore_db.collection("users").document(safe_email)

        user_data = {
            'name': name,
            'id': user_id,
            'department': department,
            'bio': bio
        }


        user_doc.set(user_data, merge=True)
        return jsonify({'message': 'Profile updated successfully'}), 200

    except Exception as e:
        print("Error updating profile:", e)
        return jsonify({'error': str(e)}), 500




@app.route('/get_profile_data')
def get_profile_data():
    if 'user_email' not in session:
        return {'error': 'User not logged in'}, 401

    user_email = session['user_email']
    safe_email = user_email.replace('.', '_')  # Firestore doc names can’t contain '.'

    try:
        user_doc = firestore_db.collection("users").document(safe_email).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            classroom_ids = user_data.get('classroom', [])  # list of ids (may be empty)

            classrooms = []
            for cid in classroom_ids:
                try:
                    class_ref = realtime_db.reference(f'classrooms/{cid}')
                    class_data = class_ref.get()
                    if class_data:
                        owner_email = class_data.get('owner', '')
                        owner_email = owner_email.replace('.', '_')
                        owner_doc = firestore_db.collection("users").document(owner_email).get()
                        if owner_doc.exists:
                            owner_name = owner_doc.to_dict().get('name', 'Unknown')    
                        classrooms.append({
                            'id': cid,
                            'name': class_data.get('classroomName', ''),
                            'owner': owner_name,
                            'ownerEmail': class_data.get('owner', ''),
                            'noOfStudents': class_data.get('noOfStudents',0),
                            'subjectCode': class_data.get('subjectCode', ''),
                            'createdDate': class_data.get('createdDate', ''),
                        })
                    else:
                        # If realtime entry was removed, skip or you can mark as missing
                        pass
                except Exception as e:
                    # log and continue
                    print(f"Error fetching classroom {cid} from RTDB:", e)

            return {
                'email': user_email,
                'role': user_data.get('role', ''),
                'name': user_data.get('name', ''),
                'userid': user_data.get('id', ''),
                'department': user_data.get('department', ''),
                'bio': user_data.get('bio', ''),
                'classrooms': classrooms
            }
        else:
            return {'error': 'User not found'}, 404
    except Exception as e:
        print("Error fetching user data:", e)
        return {'error': 'Failed to fetch user data'}, 500



@app.route('/search_users', methods=['GET'])
def search_users():
    # require login
    if 'user_email' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    raw_q = request.args.get('query', '').strip()
    if raw_q == '':
        return jsonify([])

    q = raw_q.lower()

    results = []

    try:
        students_col = firestore_db.collection('users')
        for doc in students_col.stream():
            data = doc.to_dict() or {}
            # normalize fields to avoid KeyErrors
            name = (data.get('name') or '').lower()
            userid = (data.get('userid') or data.get('id') or '').lower()

            if (q in name or q in userid) and doc.id.replace('_','.') != session.get('user_email',''):
                classroom_ids = data.get('classroom', [])  # list of ids (may be empty)
                classrooms = []
                for cid in classroom_ids:
                    try:
                        class_ref = realtime_db.reference(f'classrooms/{cid}')
                        class_data = class_ref.get()
                        if class_data:
                            if(class_data.get('owner')==doc.id.replace('_','.')):
                                classrooms.append({
                                    'id': cid,
                                    'name': class_data.get('classroomName', ''),
                                    'subjectCode': class_data.get('subjectCode', ''),
                                    'createdDate': class_data.get('createdDate', ''),
                                })
                        else:
                            # If realtime entry was removed, skip or you can mark as missing
                            pass
                    except Exception as e:
                        # log and continue
                        print(f"Error fetching classroom {cid} from RTDB:", e)
                        
                results.append({
                    'name': data.get('name', ''),
                    'email': data.get('email', ''),
                    'userid': data.get('userid') or data.get('id') or '',
                    'department': data.get('department', ''),
                    'bio': data.get('bio', ''),
                    'role': data.get('role',''),
                    'classrooms': classrooms
                })

        # optional: limit results
        # results = results[:50]

        return jsonify(results)

    except Exception as e:
        app.logger.exception("search_users failed")
        return jsonify({'error': 'Internal server error'}), 500



    

@app.route('/classroom/<classroom_id>')
def classroom_page(classroom_id):
    if 'user_role' not in session:
        return redirect(url_for('login'))
    return render_template('classroom.html', classroom_id=classroom_id)





@app.route('/courses/assessment')
def assessment():
    """Renders the assessment page."""
    try:
        return render_template('courses/assessment.html')
    except TemplateNotFound:
        abort(404)



@app.route('/courses/<course_name>')
def course(course_name):
    template_path = f'courses/{course_name}.html'
    try:
        return render_template(template_path)
    except TemplateNotFound:
        abort(404)






@app.route('/json/<path:filename>')
def serve_json(filename):
    """Serve JSON files from the templates/json directory."""
    return send_from_directory('templates/json', filename)



@app.route('/logout')
def logout():
    """Clears the user session."""
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))



@app.route('/create_classroom', methods=['POST'])
def create_classroom():
    try:
        data = request.get_json()
        name = data.get('name')
        subject = data.get('subject')
        user_email = session.get('user_email')

        if not user_email:
            return jsonify({'success': False, 'message': 'Not logged in'})

        ref = realtime_db.reference('classrooms')
        new_ref = ref.push({
            'classroomName': name,
            'subjectCode': subject,
            'owner': user_email,
            'createdDate': datetime.now().isoformat(),
            'noOfStudents': 0,
            'members': {},
            'joinRequests': {}
        })
        classroom={
            'id': new_ref.key,
            'name': name,
            'owner': "You",
            'ownerEmail': user_email,
            'noOfStudents': 0,
            'subjectCode': subject,
            'createdDate': datetime.now().strftime("%m/%d/%Y, %I:%M:%S %p")
        }
        classroom_id = new_ref.key    
        safe_email = user_email.replace('.', '_')
        user_classroom_ref = firestore_db.collection("users").document(safe_email)
        user_classroom_ref.set({
            'classroom': firestore.ArrayUnion([classroom_id])
        }, merge=True)
        

        return jsonify({'success': True, 'classroom': classroom})
    except Exception as e:
        return jsonify({'error': False, 'message': str(e)})
    
    

@app.route('/get_classroom/<classroom_id>')
def get_classroom(classroom_id):
    try:
        ref = realtime_db.reference(f'classrooms/{classroom_id}')
        data = ref.get()
        if not data:
            return jsonify({'error': 'Classroom not found'}), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@app.route('/delete_classroom', methods=['POST'])
def delete_classroom():
    if 'user_email' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    data = request.get_json() or {}
    classroom_id = data.get('id')
    if not classroom_id:
        return jsonify({'success': False, 'message': 'Missing classroom id'}), 400

    user_email = session['user_email']
    safe_email = user_email.replace('.', '_')

    try:
        # 1️⃣ Get classroom data from Realtime DB
        class_ref = realtime_db.reference(f'classrooms/{classroom_id}')
        classroom_data = class_ref.get()

        if not classroom_data:
            return jsonify({'success': False, 'message': 'Classroom not found'}), 404

        members = classroom_data.get('members', {})

        # 2️⃣ Remove classroom from each member's Firestore document
        fs = firestore.client()
        for member_email_key in members.keys():
            # Convert back to normal email if needed
            email = member_email_key
            user_doc_ref = fs.collection('users').document(email)
            doc_snapshot = user_doc_ref.get()
            if doc_snapshot.exists:
                user_doc_ref.update({
                    'classroom': firestore.ArrayRemove([classroom_id])
                })

        # 3️⃣ Delete classroom from Realtime Database
        class_ref.delete()

        # 4️⃣ Remove classroom id from Firestore (owner)
        user_doc_ref = firestore_db.collection("users").document(safe_email)
        user_doc_ref.update({
            'classroom': firestore.ArrayRemove([classroom_id])
        })

        return jsonify({'success': True, 'message': 'Classroom deleted'}), 200

    except Exception as e:
        print("Error deleting classroom:", e)
        return jsonify({'success': False, 'message': str(e)}), 500

    


@app.route('/join_classroom/<classroom_id>', methods=['POST'])
def join_classroom(classroom_id):
    try:
        # Get logged-in user's email
        user_email = session.get('user_email')
        if not user_email:
            return jsonify({'error': 'User not logged in'}), 401

        # Make email RTDB-safe
        safe_email = user_email.replace('.', '_')

        # Reference to classroom join requests
        join_ref = db.reference(f'classrooms/{classroom_id}/joinRequests/{safe_email}')

        # Set value to True
        join_ref.set(True)

        return jsonify({'message': f'Join request sent for classroom {classroom_id}'})
    
    except Exception as e:
        print("Error in join_classroom:", e)
        return jsonify({'error': 'Internal server error'}), 500
    


    
@app.route('/join_classroom_by_code/<code>', methods=['POST'])
def join_classroom_by_code(code):
    try:
        user_email = session.get('user_email')
        if not user_email:
            return jsonify({'error': 'User not logged in'}), 401

        ref = realtime_db.reference('classrooms')
        all_classrooms = ref.get()

        if not all_classrooms:
            return jsonify({'error': 'No classrooms found'}), 404

        # 🔍 Find classroom whose ID starts with given code
        matched_classroom_id = None
        for cid in all_classrooms.keys():
            if cid.startswith(code):
                matched_classroom_id = cid
                break

        if not matched_classroom_id:
            return jsonify({'error': 'No classroom found with that code'}), 404

        # 🔹 Add user email to joinRequests of matched classroom
        join_ref = realtime_db.reference(f'classrooms/{matched_classroom_id}/joinRequests')
        safe_email = user_email.replace('.', '_')
        join_ref = db.reference(f'classrooms/{matched_classroom_id}/joinRequests/{safe_email}')
        # Set value to True
        join_ref.set(True)

        return jsonify({'message': f'Join request sent to classroom {matched_classroom_id}'}), 200

    except Exception as e:
        print("Error in join_classroom_by_code:", e)
        return jsonify({'error': 'Failed to send join request'}), 500
    



#CLASSROOM
@app.route('/update_test_status', methods=['POST'])
def update_test_status():
    try:
        data = request.get_json()
        classroom_id = data.get('classroom_id')
        test_ref = data.get('test_ref')
        student_email = session.get('user_email')
        update_data = data.get('update_data')  # dict of fields to update (status, score, etc.)

        if not classroom_id or not test_ref or not student_email or not update_data:
            return jsonify({"success": False, "message": "Missing data"}), 400

        safe_email = student_email.replace('.', '_')

        # ✅ Firebase path
        result_ref = db.reference(
            f'classrooms/{classroom_id}/activities/{test_ref}/test/results/{safe_email}'
        )

        # ✅ Add timestamp automatically
        update_data["timestamp"] = datetime.now().isoformat()

        # ✅ Update or create entry
        result_ref.update(update_data)

        return jsonify({"success": True, "message": "Status updated successfully"})

    except Exception as e:
        print("Error in update_test_status:", e)
        return jsonify({"success": False, "message": str(e)}), 500
    

@app.route("/student_result.html")
def student_result():
    # Get query parameters from URL
    classroom_id = request.args.get("classroom")
    test_ref = request.args.get("test")

    # (Optional) Use these IDs to fetch student-specific test results from DB or Firestore
    # For now, you can just pass them to the template
    return render_template("student_result.html", classroom_id=classroom_id,test_ref=test_ref)


@app.route("/teacher_result.html")
def teacher_result():
    classroom_id = request.args.get("classroom")
    test_ref = request.args.get("test")

    # (Optional) You can later use classroom_id and test_ref 
    # to fetch test data or results from Firestore / Firebase / DB

    return render_template("teacher_result.html", classroom_id=classroom_id, test_ref=test_ref)



@app.route('/create_test/<classroom_id>')
def create_test(classroom_id):
    """
    Renders the create_test.html page for a specific classroom.
    """
    return render_template('create_test.html', classroom_id=classroom_id)
    

@app.route('/send_message', methods=['POST'])
def send_message():
    if 'user_email' not in session:
        return jsonify({'success': False, 'message': 'User not logged in'}), 401

    data = request.get_json() or {}
    classroom_id = data.get('classroom_id')
    message = data.get('message')

    if not classroom_id or not message:
        return jsonify({'success': False, 'message': 'Missing classroom_id or message'}), 400

    try:
        sender_email = session['user_email']
        activities_ref = realtime_db.reference(f'classrooms/{classroom_id}/activities')

        new_message_ref = activities_ref.push({
            'type': 1,
            'message': message.strip(),
            'sender': sender_email,
            'timestamp': datetime.now().isoformat()
        })

        return jsonify({'success': True, 'id': new_message_ref.key}), 200

    except Exception as e:
        print("Error sending message:", e)
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/get_join_requests/<classroom_id>', methods=['GET'])
def get_join_requests(classroom_id):
    try:
        # 1️⃣ Fetch join requests from Realtime DB
        join_req_ref = realtime_db.reference(f'classrooms/{classroom_id}/joinRequests')
        join_requests = join_req_ref.get() or {}

        if not join_requests:
            return jsonify([]), 200

        result = []

        # 2️⃣ Iterate through each email in joinRequests
        for email_key in join_requests.keys():
            # Convert email format back to normal if it’s stored as faculty1@insighteval_com
            email = email_key

            # 3️⃣ Search for this email in Firestore under User collection
            req_doc = firestore_db.collection("users").document(email).get()
            if req_doc.exists:
                req_name = req_doc.to_dict().get('name', 'Unknown')
            

            result.append({
                    'name':req_name ,
                    'email': email.replace('_', '.')
             })
           
        return jsonify(result), 200

    except Exception as e:
        print("Error fetching join requests:", str(e))
        return jsonify({'error': str(e)}), 500
    
    
    

@app.route('/reject_join_request', methods=['POST'])
def reject_join_request():
    try:
        data = request.get_json()
        classroom_id = data.get('classroom_id')
        email = data.get('email')

        if not classroom_id or not email:
            return jsonify({'error': 'Missing data'}), 400

        # Convert email to Firebase-safe key (replace '.' with '_')
        email_key = email.replace('.', '_')

        # Delete the join request from Realtime DB
        join_req_ref = realtime_db.reference(f'classrooms/{classroom_id}/joinRequests/{email_key}')
        join_req_ref.delete()

        return jsonify({'success': True, 'message': 'Join request rejected'}), 200

    except Exception as e:
        print("Error rejecting join request:", e)
        return jsonify({'error': str(e)}), 500



@app.route('/accept_join_request', methods=['POST'])
def accept_join_request():
    try:
        data = request.get_json()
        classroom_id = data.get('classroom_id')
        email = data.get('email')

        if not classroom_id or not email:
            return jsonify({'error': 'Missing data'}), 400

        email_key = email.replace('.', '_')
        classroom_ref = realtime_db.reference(f'classrooms/{classroom_id}')

        # 1️⃣ Move from joinRequests → members
        join_req_ref = classroom_ref.child(f'joinRequests/{email_key}')
        if join_req_ref.get() is None:
            return jsonify({'error': 'Join request not found'}), 404

        # Add to members node
        classroom_ref.child(f'members/{email_key}').set(True)

        # Delete from joinRequests
        join_req_ref.delete()

        # 2️⃣ Increment member count
        current_count = classroom_ref.child('noOfStudents').get() or 0
        classroom_ref.child('noOfStudents').set(current_count + 1)

        req_ref = firestore_db.collection("users").document(email_key)
        req_doc = req_ref.get()
        if req_doc.exists:
            req_ref.set({
            'classroom': firestore.ArrayUnion([classroom_id])
        }, merge=True)
        
        return jsonify({'success': True, 'message': 'Join request accepted'}), 200

    except Exception as e:
        print("Error accepting join request:", e)
        return jsonify({'error': str(e)}), 500
    



@app.route('/get_members/<classroom_id>', methods=['GET'])
def get_members(classroom_id):
    try:
        # 1️⃣ Fetch members from Realtime Database
        members_ref = realtime_db.reference(f'classrooms/{classroom_id}/members')
        members = members_ref.get() or {}

        if not members:
            return jsonify([]), 200

        firestore_db = firestore.client()
        result = []

        # 2️⃣ For each member email_key (stored as student1@insighteval_com)
        for email_key in members.keys():
            email = email_key.replace('_', '.')  # convert back to normal email format

            # 3️⃣ Check Firestore (faculty first, then students)
            doc_faculty = firestore_db.collection("users").document(email_key).get()
            if doc_faculty.exists:
                user_data = doc_faculty.to_dict()
                name = user_data.get('name', 'Unknown')
            
            result.append({
                'name': name,
                'email': email
            })

        return jsonify(result), 200

    except Exception as e:
        print("Error fetching members:", str(e))
        return jsonify({'error': str(e)}), 500
    

@app.route('/remove_member', methods=['POST'])
def remove_member():
    if 'user_email' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    data = request.get_json() or {}
    classroom_id = data.get('classroom_id')
    member_email = data.get('member_email')

    if not classroom_id or not member_email:
        return jsonify({'success': False, 'message': 'Missing data'}), 400

    safe_email = member_email.replace('.', '_')

    try:
        # 1️⃣ Remove member from Realtime Database
        class_ref = realtime_db.reference(f'classrooms/{classroom_id}/members/{safe_email}')
        class_ref.delete()

        # 2️⃣ Decrease number of students count
        class_meta_ref = realtime_db.reference(f'classrooms/{classroom_id}/noOfStudents')
        count = class_meta_ref.get() or 0
        if count > 0:
            class_meta_ref.set(count - 1)

        # 3️⃣ Remove classroom id from member's Firestore user doc
        fs = firestore.client()
        user_doc_ref = fs.collection('users').document(safe_email)
        if user_doc_ref.get().exists:
            user_doc_ref.update({
                'classroom': firestore.ArrayRemove([classroom_id])
            })

        return jsonify({'success': True, 'message': 'Member removed successfully'}), 200

    except Exception as e:
        print("Error removing member:", e)
        return jsonify({'success': False, 'message': str(e)}), 500

#CREATE_TEST
@app.route('/publish_test/<classroom_id>', methods=['POST'])
def publish_test(classroom_id):
    try:
        data = request.json
        sender_email = session['user_email']
        test_data = data.get('test')

        if not test_data:
            return jsonify({"success": False, "error": "No test data received"}), 400
        
        test_data['results'] = {"_init": True}

        activities_ref = db.reference(f'classrooms/{classroom_id}/activities')

        new_activity = activities_ref.push({
            'type': 3,
            'test': test_data,  # now contains marks
            'sender': sender_email,
            'timestamp': datetime.now().isoformat()
        })

        return jsonify({"success": True, "message": "Test published successfully!", "id": new_activity.key}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    
#ASSESMENT
@app.route('/get_test_data/<classroom_id>/<test_ref>', methods=['GET'])
def get_test_data(classroom_id, test_ref):
    """Fetch test details from Firebase Realtime DB"""
    try:
        test_path = f"classrooms/{classroom_id}/activities/{test_ref}"
        print(f"📡 Fetching test path: {test_path}")  # Debug log

        test_data = db.reference(test_path).get()

        if not test_data:
            return jsonify({"success": False, "error": "Test not found"}), 404
        
        return jsonify({"success": True, "test": test_data}), 200

    except Exception as e:
        print("🔥 Error fetching test data:", e)
        return jsonify({"success": False, "error": str(e)}), 500    




if __name__ == '__main__':
    app.run(debug=True)