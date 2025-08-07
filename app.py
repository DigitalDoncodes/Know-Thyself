# app.py
import os
import random
import io
import pandas as pd
import filetype
from datetime import datetime, timedelta, timezone
from werkzeug.security import check_password_hash

import pytz
from functools import wraps
from bson.objectid import ObjectId
from werkzeug.utils import secure_filename
from flask import (
    Flask, render_template, redirect, url_for, request,
    flash, send_from_directory, send_file, session, abort, current_app
)
from flask_login import login_user, logout_user, login_required, current_user
from dotenv import load_dotenv

load_dotenv()

from db import mongo, login_manager, scheduler, IST, User, init_extensions
from schemas import LoginForm, RegisterForm, JobForm, EditProfileForm, hash_pw, check_pw, SelfAssessmentForm

# Import SMTP functions from the new smtp.py file
import smtp

# Initialize Flask app
app = Flask(__name__, template_folder="templates", static_folder="static")

# Configure your SMTP settings
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] =587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = ('Psychology Job Portal', 'no-reply@psychportal.com')

# Set UPLOAD_FOLDER and MAX_CONTENT_LENGTH from environment variables
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', 7 * 1024 * 1024))

# Initialize Flask extensions
init_extensions(app)

# Initialize Flask-Mail and set it in the smtp module for cross-module usage
mail_instance = smtp.init_mail_app(app)
smtp.set_mail_instance(mail_instance)

# Load MongoDB URI from environment variables
app.config['MONGO_URI'] = os.environ.get('MONGO_URI')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

# Enable Flask-Mail Debugging for detailed output
app.config['MAIL_DEBUG'] = True


def teacher_required(f):
    """Decorator to restrict access to teachers only."""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "teacher":
            flash("You must be a teacher to access this page.", "warning")
            return redirect(url_for("startpage"))
        return f(*args, **kwargs)
    return decorated_function


def generate_growth_modules():
    """Generates a list of growth activity modules for the Growth Hub."""
    titles = [
        "How are you feeling emotionally today?",
        "Describe one positive thing that happened today.",
        "Rate your energy level on a scale from 1 to 10.",
        "What's your intention for today?",
        "Write a message to your future self.",
        "What are you grateful for this week?",
        "Unscramble the word: LPAEP",
        "Complete the pattern: 3, 6, 9, 12, ___",
        "Solve: What is 25 + 17?",
        "Write a compliment you'd give yourself.",
        "If emotions could speak, what would yours say?",
        "What's something challenging you overcame recently?",
        "Write a short poem or haiku.",
        "What’s your happiest memory as a child?",
        "How would you describe yourself in 3 words?",
        "Have you helped anyone today? How?",
        "What is one hobby you'd love to try?",
        "List 3 people you admire and why.",
        "What motivates you each morning?",
        "Draw or describe your mood as an animal (e.g., sloth = tired)",
        "Word association: Ocean : Water :: Forest : ___",
        "How do you express creativity?",
        "If you could learn anything instantly, what would it be?",
        "What does 'success' mean to you?",
        "How calm or anxious do you feel? (1–10)",
        "What do you need less of in your life?",
        "Rapid journal: Write whatever’s on your mind (no filter).",
        "What's your biggest win from this month?",
        "Draw/write your superpower!",
        "What's something you're proud of recently?",
        "How do you recharge?",
        "Who do you look up to, and what lesson did they teach you?",
        "Write 3 affirmations starting with: I am...",
        "Design your dream day.",
        "What makes you feel confident?",
        "What would your ideal future look like in 5 years?",
        "If today had a theme song, what would it be?",
        "Describe a safe space in your imagination.",
        "Write a thank-you note (to self or others).",
        "Have you laughed today? What made you laugh?",
        "How do you want to grow emotionally?",
        "Describe a time you overcame fear.",
        "List 3 small things you can do to feel better instantly.",
        "If you could only keep one value (e.g., honesty, joy), what would it be?",
        "Design a personal logo — describe/visualize it.",
        "Finish this sentence: 'I trust that...'",
        "What's something beautiful you witnessed recently?",
        "Write a dream you had or want to have.",
        "What’s one thing that surprises people about you?",
        "Complete the sentence: 'Right now, I feel ___ because ___'."
    ]

    modules = []
    for i, title in enumerate(titles, start=1):
        field = f"q{i}"
        html = f'<textarea name="{field}" placeholder="Write here..." rows="3" required></textarea>'
        modules.append({"title": title, "html": html})
    return modules

def cleanup_deadlines():
    """Mark applications with expired upload window as rejected_auto"""
    now_utc = datetime.now(timezone.utc)
    expired = mongo.db.applications.find({
        "resume_filename": {"$exists": False},
        "resume_deadline": {"$lt": now_utc},
    })
    for doc in expired:
        mongo.db.applications.update_one(
            {"_id": doc["_id"]}, {"$set": {"status": "rejected_auto"}}
        )

scheduler.add_job(cleanup_deadlines, "interval", hours=12)

def generate_otp():
    """Generate a 6-digit OTP"""
    return str(random.randint(100000, 999999))


# ---------- Routes ----------

@app.route("/")
def startpage():
     return render_template("startpage.html")

# Top of app.py or a separate file (growth_config.py)
GROWTH_ACTIVITIES = [
    {"id": 1, "title": "Daily Mood Check-in", "desc": "How are you feeling right now?", "icon": "😊"},
    {"id": 2, "title": "Gratitude Journal", "desc": "List three things you're thankful for today.", "icon": "🌟"},
    {"id": 3, "title": "Describe Your Day in One Word", "desc": "Summarize your day using just one word.", "icon": "🔤"},
    {"id": 4, "title": "Positive Affirmation", "desc": "Write a phrase to empower your day.", "icon": "💪"},
    {"id": 5, "title": "Today's Big Win", "desc": "What is one thing you accomplished today?", "icon": "🏆"},
    {"id": 6, "title": "Challenge Reflection", "desc": "Describe a difficulty you managed today.", "icon": "🎯"},
    {"id": 7, "title": "Letter to Future Self", "desc": "Write a note to yourself in one year.", "icon": "✉️"},
    {"id": 8, "title": "Self-Compassion Check", "desc": "List two ways you showed yourself kindness.", "icon": "🤗"},
    {"id": 9, "title": "One Act of Kindness", "desc": "What did you do for someone else today?", "icon": "🤝"},
    {"id": 10, "title": "Goal for Tomorrow", "desc": "Set a small goal for the next day.", "icon": "🎯"},
    {"id": 11, "title": "Stress Level Meter", "desc": "Rate your stress today (1–10) and why.", "icon": "📊"},
    {"id": 12, "title": "Best Memory This Week", "desc": "Describe a highlight of your week so far.", "icon": "📸"},
    {"id": 13, "title": "A Favorite Song", "desc": "Share a song that lifts your mood.", "icon": "🎵"},
    {"id": 14, "title": "Random Act of Joy", "desc": "What random thing brought you joy today?", "icon": "😂"},
    {"id": 15, "title": "Compliment Yourself", "desc": "Write a genuine compliment to yourself.", "icon": "🪞"},
    {"id": 16, "title": "Draw Your Emotion", "desc": "Use emoji or words to express your mood.", "icon": "🎨"},
    {"id": 17, "title": "Family Reflection", "desc": "Share one positive family interaction.", "icon": "👨‍👩‍👦"},
    {"id": 18, "title": "Teacher Thanks", "desc": "Thank a teacher or mentor in writing.", "icon": "🍎"},
    {"id": 19, "title": "Hobby Time", "desc": "What did you do just for fun today?", "icon": "🏓"},
    {"id": 20, "title": "Mini Meditation", "desc": "Take 2 minutes to breathe and reflect.", "icon": "🧘"},
    {"id": 21, "title": "Quick Brain Teaser", "desc": "Solve a logic or puzzle question.", "icon": "🧩"},
    {"id": 22, "title": "Word Scramble", "desc": "Unscramble a positive word of the day.", "icon": "🔄"},
    {"id": 23, "title": "Picture This!", "desc": "Upload (or describe) a photo that makes you smile.", "icon": "📷"},
    {"id": 24, "title": "Meaningful Quote", "desc": "Share a quote that resonates with you.", "icon": "💬"},
    {"id": 25, "title": "My Role Model", "desc": "Who inspires you and why?", "icon": "🕴️"},
    {"id": 26, "title": "Superpower Imagination", "desc": "Invent your own superpower and explain it.", "icon": "🦸‍♂️"},
    {"id": 27, "title": "Three-Word Self", "desc": "Describe yourself in as few words as possible.", "icon": "📝"},
    {"id": 28, "title": "Something New", "desc": "Did you try anything new today?", "icon": "✨"},
    {"id": 29, "title": "Kind Thought", "desc": "Share a kind thought for someone else.", "icon": "💭"},
    {"id": 30, "title": "Doodle Pad", "desc": "Draw something that represents your mood.", "icon": "🖌️"},
    {"id": 31, "title": "Friend Check-in", "desc": "Send a message to a friend and reflect on their reply.", "icon": "📱"},
    {"id": 32, "title": "Gratitude Photo", "desc": "Upload a photo of something you're grateful for.", "icon": "📷"},
    {"id": 33, "title": "Describe a Dream", "desc": "Recall the most recent dream you remember.", "icon": "🌙"},
    {"id": 34, "title": "Advice to Younger You", "desc": "What would you tell your 8-year-old self?", "icon": "👶"},
    {"id": 35, "title": "One Small Win", "desc": "Something you did well today, no matter how small.", "icon": "👏"},
    {"id": 36, "title": "Emotion Wheel", "desc": "Pick today’s main feeling from a wheel of emotions.", "icon": "🌀"},
    {"id": 37, "title": "Quick Survey", "desc": "Rank your sleep, nutrition, exercise (1–5)", "icon": "☑️"},
    {"id": 38, "title": "Picture Poem", "desc": "Write a quick poem about how you feel.", "icon": "🖋️"},
    {"id": 39, "title": "Future Vision", "desc": "Describe your ideal day 5 years from now.", "icon": "🔮"},
    {"id": 40, "title": "Peer Compliment", "desc": "Say something nice to a classmate.", "icon": "🏅"},
    {"id": 41, "title": "PERMA Profiler", "desc": "How much do you experience positivity, engagement, relationships, meaning, achievement?", "icon": "📈"},
    {"id": 42, "title": "Growth Mindset", "desc": "Describe a way you learned from a setback.", "icon": "📚"},
    {"id": 43, "title": "Motivation Meter", "desc": "Rate your motivation today (1–10) and why.", "icon": "🕹️"},
    {"id": 44, "title": "Strengths List", "desc": "Write three of your personal strengths.", "icon": "💪"},
    {"id": 45, "title": "Best Recent Habit", "desc": "What healthy habit did you practice today?", "icon": "🍎"},
    {"id": 46, "title": "Belief Update", "desc": "Write about changing a belief or opinion recently.", "icon": "🔁"},
    {"id": 47, "title": "Values Ranking", "desc": "What’s most important: Honesty, Kindness, or Ambition?", "icon": "🔢"},
    {"id": 48, "title": "Goal Progress", "desc": "What step did you take toward a current goal?", "icon": "🚀"},
    {"id": 49, "title": "Mini Habit Tracker", "desc": "Did you drink enough water today?", "icon": "💧"},
    {"id": 50, "title": "Stress Relief Strategy", "desc": "How did you unwind or relax today?", "icon": "🚿"},
    {"id": 51, "title": "Best Friend Story", "desc": "Share a memory with your closest friend.", "icon": "👫"},
    {"id": 52, "title": "Artist for a Day", "desc": "Draw or describe something creative you made.", "icon": "🎭"},
    {"id": 53, "title": "Positive Message Board", "desc": "Leave a kind note for others to see.", "icon": "📢"},
    {"id": 54, "title": "Energy Level", "desc": "How much energy do you have right now? Why?", "icon": "⚡"},
    {"id": 55, "title": "Kindness Wheel", "desc": "Spin for a random way to be kind today.", "icon": "🎡"},
    {"id": 56, "title": "Nature Pause", "desc": "Spend 3 minutes outside and reflect.", "icon": "🌳"},
    {"id": 57, "title": "Micro-Story", "desc": "Write your day as a 6-word story.", "icon": "📖"},
    {"id": 58, "title": "Purpose Check", "desc": "What makes you feel most alive?", "icon": "🌈"},
    {"id": 59, "title": "Mini Quiz: Who Inspires You?", "desc": "Choose a role model and explain why.", "icon": "🗣️"},
    {"id": 60, "title": "Today’s Lesson", "desc": "What did you learn today?", "icon": "📗"},
    {"id": 61, "title": "Dream Job Reflection", "desc": "What’s your dream career? Why?", "icon": "💼"},
    {"id": 62, "title": "Mood Calendar", "desc": "What color would you give today?", "icon": "🗓️"},
    {"id": 63, "title": "Playlist Maker", "desc": "List three songs for your mood.", "icon": "🎶"},
    {"id": 64, "title": "Describe a Place You Love", "desc": "What space helps you feel calm?", "icon": "🏞️"},
    {"id": 65, "title": "Mini Logic Puzzle", "desc": "Answer a quick riddle!", "icon": "🧠"},
    {"id": 66, "title": "Daily Affirmation Picker", "desc": "Choose or write today’s affirmation.", "icon": "💫"},
    {"id": 67, "title": "Body Scan", "desc": "Notice and write about physical sensations.", "icon": "🦶"},
    {"id": 68, "title": "Surprise Challenge", "desc": "Do something unexpected for yourself or another.", "icon": "🎁"},
    {"id": 69, "title": "Social Butterfly", "desc": "How did you connect with others today?", "icon": "🦋"},
    {"id": 70, "title": "Appreciation Post", "desc": "Recognize something or someone you appreciate.", "icon": "🎉"},
    {"id": 71, "title": "Describe a Problem", "desc": "What’s one challenge you’d like advice on?", "icon": "🔍"},
    {"id": 72, "title": "Energy Booster", "desc": "What gives you an instant energy boost?", "icon": "💥"},
    {"id": 73, "title": "Funny Memory", "desc": "Share something that made you laugh recently.", "icon": "🤣"},
    {"id": 74, "title": "Today’s Inspiration", "desc": "Quote or lesson that inspired you.", "icon": "🌠"},
    {"id": 75, "title": "Digital Declutter", "desc": "Did you tidy up your device or workspace?", "icon": "🧹"},
    {"id": 76, "title": "Check on a Friend", "desc": "Reach out to check in on someone.", "icon": "📞"},
    {"id": 77, "title": "Gratitude Letter", "desc": "Write a thank-you note to someone who helped you.", "icon": "✍️"},
    {"id": 78, "title": "Micro-Habit", "desc": "What small healthy habit did you practice?", "icon": "🦶"},
    {"id": 79, "title": "Sunshine Soak", "desc": "Spend a moment in sunshine and write your thoughts.", "icon": "☀️"},
    {"id": 80, "title": "Describe Your Safe Space", "desc": "Where do you feel most secure or at peace?", "icon": "🏡"},
    {"id": 81, "title": "Cheer Up a Peer", "desc": "Send an encouraging message to a friend.", "icon": "👋"},
    {"id": 82, "title": "Motivational Image", "desc": "Find or draw a motivational image.", "icon": "🖼️"},
    {"id": 83, "title": "Play a Short Game", "desc": "Solve a mini game or riddle here!", "icon": "🎲"},
    {"id": 84, "title": "Who Do You Admire?", "desc": "Name a person you admire and explain why.", "icon": "⭐"},
    {"id": 85, "title": "Grit & Perseverance", "desc": "Share a time you kept going despite difficulty.", "icon": "🚴"},
    {"id": 86, "title": "Breathe and Notice", "desc": "Take 5 slow breaths, then describe how you feel.", "icon": "🌬️"},
    {"id": 87, "title": "What Are You Curious About?", "desc": "Describe something you want to learn or try.", "icon": "❓"},
    {"id": 88, "title": "List Your Favorites", "desc": "Book, movie, and meal you love best!", "icon": "🥇"},
    {"id": 89, "title": "Ideal Day", "desc": "Describe what would make today ideal for you.", "icon": "🎈"},
    {"id": 90, "title": "Mini Bucket List", "desc": "List three things you want to try this year.", "icon": "📝"},
    {"id": 91, "title": "Mood Check-Out", "desc": "How do you feel after today's activities?", "icon": "😌"},
    {"id": 92, "title": "Describe a Surprise", "desc": "Share a recent pleasant surprise.", "icon": "🎊"},
    {"id": 93, "title": "Self-Reflection Moment", "desc": "What have you learned about yourself recently?", "icon": "👤"},
    {"id": 94, "title": "Offer Someone Help", "desc": "How did you help someone else today?", "icon": "🤲"},
    {"id": 95, "title": "Share a Short Story", "desc": "Write a mini story about a real or imagined event.", "icon": "📘"},
    {"id": 96, "title": "Daily Intention", "desc": "What’s your main intention for tomorrow?", "icon": "📅"},
    {"id": 97, "title": "Your Best Trait", "desc": "What personal trait are you proudest of?", "icon": "💖"},
    {"id": 98, "desc": "Sit in silence and write your first thought after.", "icon": "🤫"},
    {"id": 99, "title": "Shoutout Someone", "desc": "Give a shoutout to a peer or teacher.", "icon": "📣"},
    {"id": 100, "title": "Virtual Garden", "desc": "Imagine growing a quality (like resilience or kindness). Write how you’ll nurture it!", "icon": "🌿"},
]
import random
# Extend to 100 if not done manually:
for i in range(len(GROWTH_ACTIVITIES) + 1, 101):
    GROWTH_ACTIVITIES.append(
        {"id": i, "title": f"Reflection Prompt #{i}", "desc": f"", "icon": "📝"}
    )

from bson.objectid import ObjectId
from flask import redirect, request, url_for, flash

@app.route('/teacher/delete_growth_response/<response_id>', methods=["POST"])
@teacher_required
def delete_growth_response(response_id):
    try:
        mongo.db.growth_responses.delete_one({ "_id": ObjectId(response_id) })
        flash("✅ Reflection successfully deleted.", "success")
    except Exception as e:
        flash("❌ Failed to delete reflection.", "danger")
        print(f"Delete error: {e}")
    return redirect(url_for('view_growthhub_reflections'))

@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user_doc = mongo.db.users.find_one({
            "$or": [
                {"email": form.email_or_sid.data.lower()},
                {"student_id": form.email_or_sid.data.upper()}
            ]
        })
        print(f"--- Login Attempt for: {form.email_or_sid.data} ---")
        print(f"User Document from DB: {user_doc}")
        
        if user_doc and check_pw(form.password.data, user_doc.get("pw_hash", "")):
            login_user(User(user_doc))
            print(f"Login successful! User role from DB: {user_doc['role']}")
            print(f"Current_user after login_user: {current_user.is_authenticated}, Role: {current_user.role}")
            
            flash("Welcome !", "success")
            return redirect(url_for("student_dashboard")) 
        
        flash("Invalid credentials.", "danger")
        print(f"Login Failed for: {form.email_or_sid.data}")
    return render_template("login.html", form=form)

@app.route("/growth_menu")
@login_required
def growth_menu():
    # Allow both students and teachers to access Growth Hub
    responses = mongo.db.growth_responses.find({"student_id": current_user.student_id})
    completed_ids = {r["question_id"] for r in responses}

    activities = []
    for activity in GROWTH_ACTIVITIES:
        item = activity.copy()
        item["done"] = item["id"] in completed_ids
        activities.append(item)

    return render_template("growth_menu.html", activities=activities)


@app.route("/growth/<int:qid>", methods=["GET", "POST"])
@login_required
def growth_question(qid):
    if not (1 <= qid <= len(GROWTH_ACTIVITIES)):
        abort(404)

    activity = GROWTH_ACTIVITIES[qid - 1]

    if request.method == "POST":
        answer = request.form.get("answer", "").strip()
        if answer:
            mongo.db.growth_responses.insert_one({
                "student_id": current_user.student_id,
                "name": current_user.name,
                "question_id": qid,
                "question": activity["title"],
                "answer": answer,
                "submitted_at": datetime.utcnow()
            })
            flash("✅ Reflection saved!", "success")
            return redirect(url_for("growth_menu"))
        else:
            flash("Please write your answer before submitting.", "warning")

    return render_template("growth_question.html", qid=qid, activity=activity)

@app.route("/growth/random")
@login_required
def growth_random():
    import random
    qid = random.randint(1, len(GROWTH_ACTIVITIES))
    return redirect(url_for("growth_question", qid=qid))

@app.route("/teacher/growth_reflections")
@teacher_required
def view_growthhub_reflections():
    growth_responses = list(
        mongo.db.growth_responses.find().sort("submitted_at", -1)
    )
    return render_template("growthhub_table.html", growth_responses=growth_responses)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('student_dashboard'))

@app.route("/register", methods=["GET", "POST"])
def register():
    """Student registration page"""
    form = RegisterForm()
    if form.validate_on_submit():
        exists = mongo.db.users.find_one({
            "$or": [
                {"email": form.email.data.lower()},
                {"student_id": form.student_id.data.upper()}
            ]})
        if exists:
            flash("Account already exists", "warning")
        else:
            try:
                mongo.db.users.insert_one({
                    "role": "student",
                    "student_id": form.student_id.data.upper(),
                    "name": form.name.data,
                    "email": form.email.data.lower(),
                    "phone": form.phone.data,
                    "pw_hash": hash_pw(form.password.data),
                    "created_at": datetime.now(timezone.utc),
                })
                print(f"Successfully registered new user: {form.email.data}")
                flash("Account created—please sign in", "success")
                return redirect(url_for("login"))
            except Exception as e:
                print(f"Error during user registration: {e}")
                flash("An error occurred during registration. Please try again.", "danger")
    return render_template("register.html", form=form)


# --- Student & Public Routes ---
@app.route("/jobs")
def job_list():
    jobs = list(mongo.db.jobs.find({"status": "open"}))
    applied_ids = set()
    if current_user.is_authenticated and current_user.role == 'student':
        student_applications = mongo.db.applications.find({"user_id": ObjectId(current_user.id)})
        applied_ids = {app["job_id"] for app in student_applications}

    return render_template("job_list.html", jobs=jobs, applied_ids=applied_ids)

@app.route('/job/<job_id>')
def job_detail(job_id):
    job = mongo.db.jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        flash("Job not found", "danger")
        return redirect(url_for('student_dashboard'))
    return render_template("job_detail.html", job=job)



@app.route('/resources')
def resources():
    return render_template('resources.html')

@app.route('/advice')
def advice():
    return render_template("advice.html")

@app.route("/upload_resume/<job_id>", methods=["POST"])
@login_required
def upload_resume(job_id):
    resume_file = request.files.get("resume")
    photo_file = request.files.get("photo")

    if not resume_file or not photo_file or not resume_file.filename.strip() or not photo_file.filename.strip():
        flash("Please upload both resume and photo.", "warning")
        return redirect(url_for("student_dashboard"))

    application = mongo.db.applications.find_one({
        "student_id": current_user.student_id,
        "job_id": ObjectId(job_id)
    })

    if not application:
        flash("No matching application found. Please apply first.", "danger")
        return redirect(url_for("student_dashboard"))

    if application.get("status") not in ["pending_resume", "corrections_needed"]:
        flash("This application cannot be modified right now.", "danger")
        return redirect(url_for("student_dashboard"))

    # Save files
    filename_resume = secure_filename(resume_file.filename)
    filename_photo = secure_filename(photo_file.filename)
    resume_folder = os.path.join(current_app.root_path, "uploads", "resumes")
    photo_folder = os.path.join(current_app.root_path, "uploads", "photos")
    os.makedirs(resume_folder, exist_ok=True)
    os.makedirs(photo_folder, exist_ok=True)

    resume_path = os.path.join(resume_folder, filename_resume)
    photo_path = os.path.join(photo_folder, filename_photo)
    resume_file.save(resume_path)
    photo_file.save(photo_path)

    mongo.db.applications.update_one(
        {"_id": application["_id"]},
        {"$set": {
                "status": "submitted",
                "resume_uploaded_at": datetime.utcnow(),
                "resume_filename": filename_resume,
                "photo_filename": filename_photo
            }
        }
    )

    job = mongo.db.jobs.find_one({"_id": ObjectId(job_id)})
    job_title = job.get("title", "Untitled Job")

    try:
        smtp.send_confirmation_mail(current_user.email, current_user.name, application["_id"], job_title)
        flash("✅ Resume submitted and confirmation email sent.", "success")
    except Exception as e: # Catch specific exception for better debugging
        flash("Resume saved, but email failed to send.", "warning")
        print(f"Error sending confirmation email: {e}") # Log the error

    return redirect(url_for("student_dashboard"))


@app.route("/guidelines")
def guidelines():
    return render_template("guidelines_modal.html")

@app.route("/student/")
@login_required
def student_dashboard():
    if current_user.role != "student":
        return redirect(url_for("teacher_dashboard"))

    pipeline = [
        {"$match": {"user_id": ObjectId(current_user.id)}},
        {"$lookup": {
            "from": "jobs",
            "localField": "job_id",
            "foreignField": "_id",
            "as": "job"
        }},
        {"$unwind": "$job"},
        {"$sort": {"applied_at": -1}},
    ]
    apps = list(mongo.db.applications.aggregate(pipeline))

    jobs = list(mongo.db.jobs.find({"status": "open"}).sort("created_at", -1))

    applied_ids = set()
    if current_user.is_authenticated and current_user.role == 'student':
        student_applications = mongo.db.applications.find({"user_id": ObjectId(current_user.id)})
        applied_ids = {app["job_id"] for app in student_applications}


    has_active_application = any(
        app.get("status") in ("pending_resume", "submitted", "approved") for app in apps
    )

    now_ist = datetime.now(IST) 
    for app in apps:
        status = app.get("status", "")
        if status == "approved":
            app["status_message"] = "🎉 Yay! Your application is approved."
        elif status == "rejected":
            app["status_message"] = "😞 Unfortunately, your application was rejected."
        elif status == "corrections_needed":
            app["status_message"] = "✍️ Your application needs corrections. Please check feedback."
        else:
            app["status_message"] = ""

        deadline = app.get("resume_deadline")
        if deadline and deadline.tzinfo is None:
            app["resume_deadline"] = pytz.utc.localize(deadline).astimezone(IST)
        else:
            app["resume_deadline"] = deadline.astimezone(IST) if deadline else None

    return render_template(
        "student_dashboard.html",
        apps=apps,
        jobs=jobs,
        applied_ids=applied_ids,
        has_active=has_active_application,
        now=now_ist
    )

@app.route("/apply/<job_id>", methods=["POST"])
@login_required
def apply(job_id):
    if current_user.role != "student":
        flash("Only students can apply for jobs.", "danger")
        return redirect(url_for("startpage"))

    try:
        job_obj_id = ObjectId(job_id)
    except Exception:
        flash("Invalid job ID.", "danger")
        return redirect(url_for("student_dashboard"))

    active_statuses = ["pending_resume", "submitted", "approved"]
    existing_application = mongo.db.applications.find_one({
        "user_id": ObjectId(current_user.id),
        "status": {"$in": active_statuses}
    })

    if existing_application:
        flash("You already have an active application. You can only apply for one job at a time.", "warning")
        return redirect(url_for("student_dashboard"))

    job = mongo.db.jobs.find_one({"_id": job_obj_id, "status": "open"})
    if not job:
        flash("This job is no longer available.", "danger")
        return redirect(url_for("student_dashboard"))

    applications_count = mongo.db.applications.count_documents({
        "job_id": job_obj_id,
        "status": {"$in": ["pending_resume", "submitted", "approved"]}
    })

    if applications_count >= job.get("vacancies", 0):
        flash("Sorry, no vacancies are available for this job.", "danger")
        return redirect(url_for("student_dashboard"))

    now_utc = datetime.now(timezone.utc)
    deadline_utc = now_utc + timedelta(hours=48)

    mongo.db.applications.insert_one({
        "job_id": job_obj_id,
        "user_id": ObjectId(current_user.id),
        "applied_at": now_utc,
        "resume_deadline": deadline_utc,
        "status": "pending_resume",
    })

    mongo.db.jobs.update_one(
        {"_id": job_obj_id, "vacancies": {"$gt": 0}},
        {"$inc": {"vacancies": -1}}
    )

    flash("Application successful! Please upload your résumé within 48 hours.", "success")
    return redirect(url_for("student_dashboard"))


@app.route("/upload/<app_id>", methods=["POST"])
@login_required
def upload(app_id):
    # 📌 1. Verify application ownership
    app_doc = mongo.db.applications.find_one({"_id": ObjectId(app_id)})
    if not app_doc or app_doc.get("user_id") != ObjectId(current_user.id):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("student_dashboard"))

    if app_doc.get("status") not in ["pending_resume", "corrections_needed"]:
        flash("This application cannot be modified.", "danger")
        return redirect(url_for("student_dashboard"))

    # 📌 2. Get uploaded files
    resume = request.files.get("resume")
    photo = request.files.get("photo")
    if not resume or not photo or not resume.filename.strip() or not photo.filename.strip():
        flash("Please upload both résumé and photo.", "warning")
        return redirect(url_for("student_dashboard"))

    # 📌 3. Validate file types and extensions
    allowed_resume = {".pdf", ".doc", ".docx"}
    allowed_photo = {".jpg", ".jpeg", ".png"}

    resume_ext = os.path.splitext(resume.filename)[1].lower()
    photo_ext = os.path.splitext(photo.filename)[1].lower()

    if resume_ext not in allowed_resume:
        flash("Résumé must be a PDF or Word file.", "danger")
        return redirect(url_for("student_dashboard"))

    if photo_ext not in allowed_photo:
        flash("Photo must be JPG or PNG.", "danger")
        return redirect(url_for("student_dashboard"))

    # 📌 4. Generate secure filenames
    basename = f"{current_user.student_id}_{app_id}"
    resume_filename = secure_filename(f"{basename}{resume_ext}")
    photo_filename = secure_filename(f"{basename}_photo{photo_ext}")

    upload_dir = app.config.get("UPLOAD_FOLDER", "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    resume_path = os.path.join(upload_dir, resume_filename)
    photo_path = os.path.join(upload_dir, photo_filename)

    # 📌 5. Save files
    resume.save(resume_path)
    photo.save(photo_path)

    # 📌 6. Update application in DB
    mongo.db.applications.update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {
                "resume_filename": resume_filename,
                "photo_filename": photo_filename,
                "resume_uploaded_at": datetime.now(timezone.utc),
                "status": "submitted",
                "teacher_feedback": ""  # optional: clear feedback upon resubmission
            }
        }
    )

    # 📌 7. Send confirmation and admin emails
    job = mongo.db.jobs.find_one({"_id": app_doc["job_id"]})
    job_title = job.get("title", "Untitled Job")

    # 📨 Send résumé & photo as attachments to admin
    try:
        smtp.send_resume_and_photo_mail(
            resume_filename, photo_filename,
            current_user.email, job_title
        )
    except Exception as e:
        print("Admin mail error:", e)
        flash("Upload successful, but admin could not be notified.", "warning")

    # ✅ Send confirmation email to student
    try:
        smtp.send_confirmation_mail(
            applicant_email=current_user.email,
            applicant_name=current_user.name,
            application_id=str(app_doc["_id"]),
            job_title=job_title
        )
        flash("Résumé and photo uploaded and confirmation email sent!", "success")
    except Exception as e:
        print("Student mail error:", e)
        flash("Upload successful, but confirmation email failed.", "warning")
        
    return redirect(url_for("student_dashboard"))

# Moved handle_resume_submission outside of the route
def handle_resume_submission(app_doc, new_status="submitted", clear_feedback=True):
    resume = request.files.get("resume")
    photo = request.files.get("photo")

    if not resume or not photo or not resume.filename.strip() or not photo.filename.strip():
        flash("Please upload both résumé and photo.", "warning")
        return redirect(url_for("student_dashboard"))

    ext_resume = os.path.splitext(resume.filename)[1].lower()
    ext_photo = os.path.splitext(photo.filename)[1].lower()
    base = f"{current_user.student_id}_{app_doc['_id']}"

    resume_filename = secure_filename(f"{base}{ext_resume}")
    photo_filename = secure_filename(f"{base}_photo{ext_photo}")

    upload_dir = app.config.get("UPLOAD_FOLDER", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    resume_path = os.path.join(upload_dir, resume_filename)
    photo_path = os.path.join(upload_dir, photo_filename)
    
    resume.save(resume_path)
    photo.save(photo_path)

    update_fields = {
        "resume_filename": resume_filename,
        "photo_filename": photo_filename,
        "resume_uploaded_at": datetime.now(timezone.utc),
        "status": new_status,
    }

    if clear_feedback:
        update_fields["teacher_feedback"] = ""

    mongo.db.applications.update_one(
        {"_id": app_doc["_id"]}, {"$set": update_fields}
    )

    job = mongo.db.jobs.find_one({"_id": app_doc["job_id"]})
    job_title = job.get("title", "Job")

    try:
        smtp.send_confirmation_mail(
            applicant_email=current_user.email,
            applicant_name=current_user.name,
            application_id=str(app_doc["_id"]),
            job_title=job_title
        )
        flash("✅ Résumé submitted and confirmation email sent.", "success")
    except Exception as e:
        print("Email error:", e)
        flash("Upload succeeded, but email failed.", "warning")

    try:
        smtp.send_admin_notification(current_user.name, job_title, current_user.email)
    except Exception as e:
        print("Admin email error:", e)

    return redirect(url_for("student_dashboard"))

@app.route("/resume/reupload/<app_id>", methods=["POST"])
@login_required
def resume_reupload(app_id):
    app_doc = mongo.db.applications.find_one({"_id": ObjectId(app_id)})

    if not app_doc or app_doc["user_id"] != ObjectId(current_user.id):
        flash("Unauthorized re-upload attempt.", "danger")
        return redirect(url_for("student_dashboard"))

    if app_doc["status"] != "corrections_needed":
        flash("You can only re-upload when corrections are requested.", "danger")
        return redirect(url_for("student_dashboard"))

    return handle_resume_submission(app_doc, new_status="submitted", clear_feedback=True)
 

# --- Teacher Routes ---
@app.route("/teacher/")
@teacher_required
def teacher_dashboard():
    import math
    from collections import defaultdict

    # 1️⃣ Pagination settings
    page = int(request.args.get("page", 1))
    per_page = 12
    skip = (page - 1) * per_page

    # 2️⃣ Fetch students and total pages
    students_cursor = mongo.db.users.find({"role": "student"}).sort("name", 1).skip(skip).limit(per_page)
    students = list(students_cursor)
    students_total = mongo.db.users.count_documents({"role": "student"})
    total_pages = math.ceil(students_total / per_page)

    # 3️⃣ Jobs and applications
    jobs = list(mongo.db.jobs.find().sort("created_at", -1))
    active_app_count = mongo.db.applications.count_documents({"status": "submitted"})
    pending_app_count = mongo.db.applications.count_documents({"status": "pending_resume"})
    total_applications = mongo.db.applications.count_documents({})

    recent_pending_apps = list(
        mongo.db.applications.aggregate([
            {"$match": {"status": "pending_resume"}},
            {"$sort": {"applied_at": -1}},
            {"$limit": 8},
            {"$lookup": {
                "from": "users",
                "localField": "user_id",
                "foreignField": "_id",
                "as": "user"
            }},
            {"$unwind": "$user"},
            {"$lookup": {
                "from": "jobs",
                "localField": "job_id",
                "foreignField": "_id",
                "as": "job"
            }},
            {"$unwind": "$job"},
        ])
    )

    # 4️⃣ Current time in IST
    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist)

    # 5️⃣ Self-Assessment Reflections
    reflections = list(mongo.db.self_assessments.find().sort("submission_date", -1))

    # 6️⃣ Growth Hub Response Stats (per student)
    growth_responses = list(mongo.db.growth_responses.find())
    student_hub_stats = defaultdict(lambda: {"name": "", "student_id": "", "completed": 0})
    for entry in growth_responses:
        sid = entry.get("student_id")
        if sid:
            student_hub_stats[sid]["name"] = entry.get("name", "")
            student_hub_stats[sid]["student_id"] = sid
            student_hub_stats[sid]["completed"] += 1
    growth_stats = sorted(student_hub_stats.values(), key=lambda x: x["name"])

    # 🔚 Finally render the dashboard
    return render_template(
        "teacher_dashboard.html",
        students=students,
        students_total=students_total,
        total_pages=total_pages,
        page=page,
        jobs=jobs,
        active_app_count=active_app_count,
        pending_app_count=pending_app_count,
        total_applications=total_applications,
        recent_pending_apps=recent_pending_apps,
        now=now_ist,
        reflections=reflections,       # ✅ Q1–Q5 assessments
        growth_responses=growth_responses,  # ✅ Full growth answers
        growth_stats=growth_stats      # ✅ Per-student completion counts
    )


@app.route("/select_job_to_delete")
@teacher_required
def select_job_to_delete():
    jobs = list(mongo.db.jobs.find().sort("created_at", -1))
    return render_template("select_job_to_delete.html", jobs=jobs)

@app.route("/teacher/job/<job_id>/applications")
@teacher_required
def job_applications(job_id):
    job = mongo.db.jobs.find_one({"_id": ObjectId(job_id), "created_by": ObjectId(current_user.id)})
    if not job:
        flash("Job not found or access denied.", "danger")
        return redirect(url_for("teacher_dashboard"))

    pipeline = [
        {"$match": {"job_id": ObjectId(job_id)}},
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "_id", "as": "user"}},
        {"$unwind": "$user"},
        {"$sort": {"applied_at": -1}},
    ]
    applications = list(mongo.db.applications.aggregate(pipeline))

    now_ist = datetime.now(IST)
    for app in applications:
        deadline = app.get("resume_deadline")
        if deadline and deadline.tzinfo is None:
            app["resume_deadline"] = pytz.utc.localize(deadline).astimezone(IST)
        else:
            app["resume_deadline"] = deadline.astimezone(IST) if deadline else None

    return render_template("job_applications.html", job=job, applications=applications, now=now_ist)


@app.route("/job/new", methods=["GET", "POST"])
@teacher_required
def new_job():
    """Page for teachers to add a new job"""
    form = JobForm()
    if form.validate_on_submit():
        pof_name = None
        if form.pof.data and form.pof.data.filename:
            pof_name = secure_filename(form.pof.data.filename)
            form.pof.data.save(os.path.join(app.config["UPLOAD_FOLDER"], pof_name))
        mongo.db.jobs.insert_one({
            "title": form.title.data,
            "job_description": form.job_description.data,
            "job_specification": form.job_specification.data,
            "vacancies": form.vacancies.data,
            "pof_filename": pof_name,
            "created_by": ObjectId(current_user.id),
            "status": "open",
            "created_at": datetime.now(timezone.utc),
        })
        flash("Job created", "success")
        return redirect(url_for("teacher_dashboard"))
    return render_template("job_form.html", form=form)


from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user, login_required
from bson.objectid import ObjectId
from werkzeug.utils import secure_filename
import os

@app.route("/job/edit/<job_id>", methods=["GET", "POST"])
@login_required
def edit_job(job_id):
    # Only teachers allowed
    if current_user.role != "teacher":
        return redirect(url_for("index"))

    # Fetch the job from the database
    job = mongo.db.jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        flash("Job not found.", "danger")
        return redirect(url_for("teacher_dashboard"))

    # Instantiate the form and pre-populate with job data on GET
    form = JobForm()
    if request.method == "GET":
        form.title.data = job.get("title", "")
        # Correctly pre-populating the new fields in the form
        form.job_description.data = job.get("job_description", "")
        form.job_specification.data = job.get("job_specification", "")
        form.vacancies.data = job.get("vacancies", 6)
        # Assuming the JobForm has a pof field, pre-populate if needed
        # form.pof.data = job.get("pof_filename", "")
    
    # If the form is submitted and passes validation
    if form.validate_on_submit():
        # Handle PoF file upload if present
        pof_name = job.get("pof_filename")
        if form.pof.data and form.pof.data.filename:
            pof_name = secure_filename(form.pof.data.filename)
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], pof_name)
            form.pof.data.save(save_path)
        
        # Update job in MongoDB with all fields
        mongo.db.jobs.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {
                "title": form.title.data,
                # Correctly using the form object to get the new fields
                "job_description": form.job_description.data,
                "job_specification": form.job_specification.data,
                "vacancies": form.vacancies.data,
                "pof_filename": pof_name,
            }}
        )
        flash("Job updated successfully.", "success")
        return redirect(url_for("teacher_dashboard"))
        
    return render_template("edit_job.html", form=form, job=job)


@app.route("/job/delete/<job_id>", methods=["POST"])
@teacher_required
def delete_job(job_id):
    """
    Deletes job from database; only accessible to teachers.
    Redirects to delete jobs listing page.
    """
    result = mongo.db.jobs.delete_one({"_id": ObjectId(job_id)})
    if result.deleted_count:
        flash("Job deleted.", "info")
    else:
        flash("Job not found.", "warning")

    return redirect(url_for("select_job_to_delete"))


@app.route("/jobs/manage")
@app.route("/jobs/edit")
@teacher_required
def edit_jobs_list():
    """Page showing all jobs to be edited by teachers"""
    jobs = list(mongo.db.jobs.find().sort("created_at", -1))
    return render_template("edit_jobs_list.html", jobs=jobs)


@app.route("/jobs/delete")
@teacher_required
def delete_jobs_list():
    """Page listing all jobs with delete options for teachers"""
    jobs = list(mongo.db.jobs.find().sort("created_at", -1))
    return render_template("delete_jobs_list.html", jobs=jobs)


# --- Application Status Updates by Teacher ---



@app.route("/teacher/clear_application")
@teacher_required
def clear_application():
    name_filter = request.args.get("name", "").strip()
    status_filter = request.args.get("status", "").strip()
    resume_filter = request.args.get("resume", "").strip()

    pipeline = [
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "_id", "as": "user"}},
        {"$unwind": "$user"},
        {"$lookup": {"from": "jobs", "localField": "job_id", "foreignField": "_id", "as": "job"}},
        {"$unwind": "$job"},
        {"$sort": {"applied_at": -1}},
    ]

    match_filters = {}
    if name_filter:
        match_filters["user.name"] = {"$regex": name_filter, "$options": "i"}
    if status_filter:
        match_filters["status"] = status_filter
    if resume_filter == 'uploaded':
        match_filters["resume_filename"] = {"$exists": True, "$ne": None}
    elif resume_filter == 'not_uploaded':
        match_filters["resume_filename"] = {"$exists": False}

    if match_filters:
        pipeline.insert(0, {"$match": match_filters})

    applications = list(mongo.db.applications.aggregate(pipeline))
    all_statuses = ["pending_resume", "submitted", "approved", "rejected", "rejected_auto", "corrections_needed"]
    resume_options = [
        {"value": "", "label": "All"},
        {"value": "uploaded", "label": "Resume Uploaded"},
        {"value": "not_uploaded", "label": "Resume Not Uploaded"},
    ]

    return render_template(
        "clear_application.html",
        applications=applications,
        name_filter=name_filter,
        status_filter=status_filter,
        resume_filter=resume_filter,
        statuses=all_statuses,
        resume_options=resume_options
    )

@app.route('/teacher/clear_application_bulk', methods=['POST'])
@teacher_required
def clear_application_bulk():
    app_ids = request.form.getlist('app_ids')
    if not app_ids:
        flash('No applications selected.', 'warning')
        return redirect(url_for('clear_application'))

    object_ids = [ObjectId(app_id) for app_id in app_ids]

    apps_to_clear = list(mongo.db.applications.find({"_id": {"$in": object_ids}}))
    job_id_to_count = {}
    for app_doc in apps_to_clear:
        job_id = app_doc['job_id']
        job_id_to_count[job_id] = job_id_to_count.get(job_id, 0) + 1

    result = mongo.db.applications.delete_many({"_id": {"$in": object_ids}})

    for job_id, inc_count in job_id_to_count.items():
        mongo.db.jobs.update_one(
            {"_id": job_id},
            {"$inc": {"vacancies": inc_count}}
        )

    flash(f'{result.deleted_count} application(s) cleared and vacancies updated.', 'success')
    return redirect(url_for('clear_application'))
 
@app.route("/teacher/assess", methods=["GET", "POST"])
@teacher_required
def assess_students():
    if request.method == "POST":
        app_id = request.form.get("app_id")
        new_status = request.form.get("status")
        feedback = request.form.get("feedback", "").strip()

        if app_id and new_status in {"approved", "rejected", "needs_corrections"}:
            mongo.db.applications.update_one(
                {"_id": ObjectId(app_id)},
                {"$set": {"status": new_status, "teacher_feedback": feedback}}
            )
            flash("Application updated successfully.", "success")
        else:
            flash("Invalid update data.", "danger")
        return redirect(url_for("assess_students"))

    name_filter = request.args.get("name", "").strip()
    status_filter = request.args.get("status", "").strip()
    resume_filter = request.args.get("resume", "").strip()

    pipeline = [
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "_id", "as": "user"}},
        {"$unwind": "$user"},
        {"$lookup": {"from": "jobs", "localField": "job_id", "foreignField": "_id", "as": "job"}},
        {"$unwind": "$job"},
        {"$sort": {"applied_at": -1}},
    ]

    match_filters = {}
    if name_filter:
        match_filters["user.name"] = {"$regex": name_filter, "$options": "i"}
    if status_filter:
        match_filters["status"] = status_filter
    if resume_filter == "uploaded":
        match_filters["resume_filename"] = {"$exists": True, "$ne": None}
    elif resume_filter == "not_uploaded":
        match_filters["resume_filename"] = {"$exists": False}

    if match_filters:
        pipeline.insert(0, {"$match": match_filters})

    applications = list(mongo.db.applications.aggregate(pipeline))

    now = datetime.now(timezone.utc)

    for app in applications:
        applied_at = app.get("applied_at")
        resume_uploaded_at = app.get("resume_uploaded_at")

        if applied_at and resume_uploaded_at:
            duration = resume_uploaded_at - applied_at
            hours = duration.total_seconds() / 3600
            app["upload_duration_hours"] = round(hours, 1)
        elif applied_at and app.get("resume_filename"):
            duration = now - applied_at
            hours = duration.total_seconds() / 3600
            app["upload_duration_hours"] = round(hours, 1)
        else:
            app["upload_duration_hours"] = None

    all_statuses = [
        "pending_resume", "submitted", "approved",
        "rejected", "rejected_auto", "corrections_needed"
    ]
    resume_options = [
        {"value": "", "label": "All"},
        {"value": "uploaded", "label": "Resume Uploaded"},
        {"value": "not_uploaded", "label": "Resume Not Uploaded"},
    ]

    return render_template(
        "assess_students.html",
        applications=applications,
        name_filter=name_filter,
        status_filter=status_filter,
        resume_filter=resume_filter,
        statuses=all_statuses,
        resume_options=resume_options,
    )

@app.route('/teacher/delete_student_reflection/<reflection_id>', methods=["POST"])
@teacher_required
def delete_student_reflection(reflection_id):
    try:
        mongo.db.self_assessments.delete_one({"_id": ObjectId(reflection_id)})
        flash("✅ Reflection successfully deleted.", "success")
    except Exception as e:
        flash("❌ Failed to delete reflection.", "danger")
        print(f"Delete error: {e}")
    return redirect(url_for('view_student_reflections'))

@app.route("/teacher/registered_students")
@teacher_required
def registered_students():
    name_filter = request.args.get("name", "").strip().lower()
    student_id_filter = request.args.get("student_id", "").strip().lower()
    phone_filter = request.args.get("phone", "").strip()
    email_filter = request.args.get("email", "").strip().lower()

    sort_field = request.args.get("sort", "name")
    direction = request.args.get("direction", "asc")
    allowed_sort_fields = {"name", "student_id", "phone", "email"}
    sort_by = sort_field if sort_field in allowed_sort_fields else "name"
    sort_dir = 1 if direction == "asc" else -1

    query = {"role": "student"}
    if name_filter:
        query["name"] = {"$regex": name_filter, "$options": "i"}
    if student_id_filter:
        query["student_id"] = {"$regex": student_id_filter, "$options": "i"}
    if phone_filter:
        query["phone"] = {"$regex": phone_filter}
    if email_filter:
        query["email"] = {"$regex": email_filter, "$options": "i"}

    students = list(mongo.db.users.find(query).sort(sort_by, sort_dir))

    return render_template(
        "registered_students.html",
        students=students,
        name_filter=name_filter,
        student_id_filter=student_id_filter,
        phone_filter=phone_filter,
        email_filter=email_filter,
        sort_field=sort_by,
        direction=direction
    )

@app.route("/teacher/edit_profile", methods=["GET", "POST"])
@teacher_required
def edit_teacher_profile():
    teacher = mongo.db.users.find_one({"_id": ObjectId(current_user.id)})
    if not teacher:
        flash("User not found", "danger")
        return redirect(url_for("teacher_dashboard"))

    form = EditProfileForm()
    if form.validate_on_submit():
        update_dict = {
            "name": form.name.data,
            "email": form.email.data.lower(),
            "phone": form.phone.data,
        }
        if form.password.data and form.password.data.strip():
            update_dict["pw_hash"] = hash_pw(form.password.data)

        mongo.db.users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": update_dict}
        )
        flash("Profile updated!", "success")
        return redirect(url_for("teacher_dashboard"))

    if request.method == "GET":
        form.name.data = teacher.get("name", "")
        form.email.data = teacher.get("email", "")
        form.phone.data = teacher.get("phone", "")

    return render_template("edit_teacher_profile.html", form=form)

@app.route("/teacher/export_assessed")
@teacher_required
def export_assessed_students():
    assessed_statuses = ["approved", "rejected", "corrections_needed"]
    pipeline = [
        {"$match": {"status": {"$in": assessed_statuses}}},
        {
            "$lookup": {
                "from": "users",
                "localField": "user_id",
                "foreignField": "_id",
                "as": "user"
            }
        },
        {"$unwind": "$user"},
        {
            "$lookup": {
                "from": "jobs",
                "localField": "job_id",
                "foreignField": "_id",
                "as": "job"
            }
        },
        {"$unwind": "$job"},
        {"$sort": {"applied_at": -1}},
    ]
    results = list(mongo.db.applications.aggregate(pipeline))

    data = []
    for app in results:
        row = {
            "Student Name": app["user"].get("name", ""),
            "Student Email": app["user"].get("email", ""),
            "Job Title": app["job"].get("title", ""),
            "Status": app.get("status", "").replace("_", " ").title(),
            "Applied At": app.get("applied_at").strftime("%Y-%m-%d %H:%M") if app.get("applied_at") else "",
            "Teacher Feedback": app.get("teacher_feedback") or "",
        }
        data.append(row)

    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Assessed Students")
    output.seek(0)

    filename = f"Assessed_Students_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(
        output,
        download_name=filename,  
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ---------- File Serving Routes ----------
@app.route("/uploads/<path:filename>")
@login_required
def view_resume(filename):
    """
    Serve uploaded files.
    """
    upload_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    
    try:
        with open(upload_path, 'rb') as f:
            kind = filetype.guess(f.read(1024))
            mime_type = kind.mime if kind else 'application/octet-stream'
    except Exception:
        mime_type = 'application/octet-stream'
    
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename,
        as_attachment=False,
        mimetype=mime_type
    )


@app.route("/resumes/download/<path:filename>")
@login_required
def download_resume(filename):
    """
    Force download of résumé files.
    """
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename,
        as_attachment=True
    )

# ---------- Profile Editing with OTP Verification ----------
@app.route("/student/edit_profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    if current_user.role != "student":
        return redirect(url_for("teacher_dashboard"))
    student = mongo.db.users.find_one({"_id": ObjectId(current_user.id)})
    if not student:
        flash("User not found", "danger")
        return redirect(url_for("student_dashboard"))
    
    form = EditProfileForm()
    if 'awaiting_otp' not in session:
        if form.validate_on_submit():
            if not form.password.data.strip():
                mongo.db.users.update_one(
                    {"_id": ObjectId(current_user.id)},
                    {"$set": {
                        "name": form.name.data,
                        "email": form.email.data.lower(),
                        "phone": form.phone.data,
                    }}
                )
                flash("Profile updated!", "success")
                return redirect(url_for("student_dashboard"))
            else:
                otp = generate_otp()
                session['awaiting_otp'] = True
                session['pending_profile'] = {
                    "name": form.name.data,
                    "email": form.email.data.lower(),
                    "phone": form.phone.data,
                    "password": form.password.data,
                }
                session['otp_code'] = otp
                smtp.send_otp_email(form.email.data.lower(), otp)
                flash("OTP sent to your email for password change.", "info")
                return render_template("otp_verify.html")

        if request.method == "GET":
            form.name.data = student.get("name", "")
            form.email.data = student.get("email", "")
            form.phone.data = student.get("phone", "")
        return render_template("edit_profile.html", form=form)

    if request.method == "POST" and 'otp' in request.form:
        user_input_otp = request.form.get("otp")
        pending = session.get('pending_profile')
        if pending and user_input_otp == session.get('otp_code'):
            update_fields = dict(pending)
            update_fields["pw_hash"] = hash_pw(update_fields.pop("password"))
            mongo.db.users.update_one(
                {"_id": ObjectId(current_user.id)},
                {"$set": update_fields}
            )
            flash("Profile and password updated!", "success")
            session.pop('awaiting_otp', None)
            session.pop('pending_profile', None)
            session.pop('otp_code', None)
            return redirect(url_for("student_dashboard"))
        else:
            flash("Incorrect OTP. Please try again.", "danger")
        return render_template("otp_verify.html")

    return render_template("otp_verify.html")

# --- Student Self-Assessment Routes ---

@app.route('/student/self_assessment')
@login_required
def self_assessment_start():
    """Initial route to start the self-assessment."""
    if current_user.role != 'student':
        flash("You are not authorized to access this page.", "danger")
        return redirect(url_for('teacher_dashboard'))
    return redirect(url_for('self_assessment_step', step=1))


@app.route('/student/self_assessment/<int:step>', methods=['GET', 'POST'])
@login_required
def self_assessment_step(step):
    """Multi-step route for the self-assessment."""
    if current_user.role != 'student':
        flash("You are not authorized to access this page.", "danger")
        return redirect(url_for('teacher_dashboard'))

    form = SelfAssessmentForm()
    
    # Define which questions belong to each step
    step_map = {
        1: ['q1', 'q2'],
        2: ['q3', 'q4'],
        3: ['q5']
    }

    if step not in step_map:
        abort(404)

    if request.method == 'POST':
        # Check if the submitted data is for the current step
        all_present = True
        for q in step_map[step]:
            if not getattr(form, q).data:
                all_present = False
                break

        if all_present:
            # Store data from the current step in the session
            for q in step_map[step]:
                session[q] = getattr(form, q).data
            
            # Check if there is a next step
            if step < len(step_map):
                return redirect(url_for('self_assessment_step', step=step + 1))
            else:
                # Final step: combine all data and save to DB
                try:
                    assessment_data = {
                        'student_id': current_user.student_id,
                        'student_name': current_user.name,
                        'submission_date': datetime.now(timezone.utc),
                        'q1_answer': session.get('q1'),
                        'q2_answer': session.get('q2'),
                        'q3_answer': session.get('q3'),
                        'q4_answer': session.get('q4'),
                        'q5_answer': session.get('q5'),
                    }
                    mongo.db.self_assessments.insert_one(assessment_data)

                    # Clear session data
                    for q in step_map:
                        for field in step_map[q]:
                            session.pop(field, None)

                    flash("Your self-assessment has been recorded. Thank you!", "success")
                    return redirect(url_for('student_dashboard'))
                except Exception as e:
                    print(f"Error saving self-assessment: {e}")
                    flash("An error occurred while submitting your answers. Please try again.", "danger")
        else:
            flash("Please fill out all the fields.", "warning")
    
    # Handle GET request and re-render on validation failure
    if step == 1:
        return render_template('self_assessment_part1.html', form=form, step=step)
    elif step == 2:
        return render_template('self_assessment_part2.html', form=form, step=step)
    elif step == 3:
        return render_template('self_assessment_part3.html', form=form, step=step)

# --- Teacher Route to View Self-Assessment Answers ---
@app.route('/teacher/student_reflections')
@teacher_required
def view_student_reflections():
    reflections = list(mongo.db.self_assessments.find({}).sort("submission_date", -1))
    return render_template('student_reflections.html', reflections=reflections)

# ---------- Teacher's Applied and Registered Students ----------
@app.route("/teacher/applied_students")
@teacher_required
def applied_students():
    name_filter = request.args.get("name", "").strip()
    status_filter = request.args.get("status", "").strip()

    pipeline = [
        {"$lookup": {
            "from": "users",
            "localField": "user_id",
            "foreignField": "_id",
            "as": "user",
        }},
        {"$unwind": "$user"},
        {"$lookup": {
            "from": "jobs",
            "localField": "job_id",
            "foreignField": "_id",
            "as": "job",
        }},
        {"$unwind": "$job"},
    ]

    match_filters = {}
    if name_filter:
        match_filters["user.name"] = {"$regex": name_filter, "$options": "i"}
    if status_filter:
        match_filters["status"] = status_filter

    if match_filters:
        pipeline.insert(0, {"$match": match_filters})

    applications = list(mongo.db.applications.aggregate(pipeline))

    statuses = ["pending_resume", "submitted", "approved", "rejected", "rejected_auto", "corrections_needed"]

    return render_template("applied_students.html",
                           applications=applications,
                           name_filter=name_filter,
                           status_filter=status_filter,
                           statuses=statuses)

@app.route("/support")
def support():
    return render_template("support.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/creator")
def creator():
    return render_template("creator.html")

from flask import request, jsonify

DOG_RESPONSES = [
    ("hello", "Woof! Hi there, friend! 🐾"),
    ("resume", "Need résumé tips? Make sure it's clear and shows your unique strengths!"),
    ("motivate", "You can do it! Remember, I'm your cheerleader 🐶✨"),
    ("reflection", "Reflect often—growth comes from small steps!"),
    ("sad", "It's okay to have ruff days. Here’s a tail wag! 🐕🐾"),
    ("treat", "I love treats! Did you finish a task? Give yourself a treat!"),
]

@app.route("/virtual_pet_dog_chat", methods=["POST"])
def virtual_pet_dog_chat():
    user_msg = request.json.get("msg", "").lower()
    for kw, reply in DOG_RESPONSES:
        if kw in user_msg:
            return jsonify({"reply": reply})
    # Fallback generic dog reply
    import random
    replies = [
        "I'm here whenever you want to talk or need a little encouragement!",
        "Wag wag! Let's keep learning new tricks together.",
        "If you need advice, just ask. I'm a very good dog."
    ]
    return jsonify({"reply": random.choice(replies)})

@app.route('/teacher/update_application/<application_id>', methods=['POST'])
@login_required
def update_application_status(application_id):
    status = request.form.get('status')
    feedback = request.form.get('feedback', "").strip()

    print(f"DEBUG (app.py route): update_application_status called for app_id: {application_id}")
    print(f"DEBUG (app.py route): Status received: {status}, Feedback: {feedback}")

    if status not in ["approved", "rejected", "needs_corrections"]:
        flash("Invalid application status submitted.", "danger")
        return redirect(url_for("teacher_dashboard"))

    application = mongo.db.applications.find_one({"_id": ObjectId(application_id)})
    if not application:
        flash("Application not found.", "danger")
        return redirect(url_for("teacher_dashboard"))

    student = mongo.db.users.find_one({"_id": ObjectId(application["user_id"])})
    job = mongo.db.jobs.find_one({"_id": ObjectId(application["job_id"])})

    print(f"DEBUG (app.py route): Found student: {student['email']}, job: {job['title']}")

    # Update application in database
    mongo.db.applications.update_one(
        {"_id": ObjectId(application_id)},
        {"$set": {
            "status": status,
            "teacher_feedback": feedback,
            "updated_at": datetime.utcnow()
        }}
    )
    print(f"DEBUG (app.py route): Database updated for application {application_id}")

    # Send notification email
    smtp.send_application_status_email(
        student_email=student["email"],
        student_name=student.get("name", "Student"),
        status=status,
        job_title=job.get("title", "Your Job Application"),
        feedback=feedback if status == "needs_corrections" else None
    )
    print(f"DEBUG (app.py route): smtp.send_application_status_email called.")

    flash("✅ Application updated and student notified.", "success")
    return redirect(url_for("teacher_dashboard"))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=True)
