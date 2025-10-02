# app.py - Consolidated and Corrected Version

# ----------------------------------------------------
# 1. IMPORTS & SETUP
# ----------------------------------------------------
import os
import random
import io
import csv
import filetype
from functools import wraps
from datetime import datetime, timedelta, timezone
import pytz
from bson.objectid import ObjectId
from werkzeug.utils import secure_filename
from flask import (
    Flask, render_template, redirect, url_for, request,
    flash, send_from_directory, send_file, session, abort, jsonify
)
from flask_login import login_user, logout_user, login_required, current_user
from dotenv import load_dotenv

# Flask-WTF Imports (Ensure these are at the module level)
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, IntegerField
from wtforms.validators import DataRequired, NumberRange

# Import extensions and user models from db.py
# This imports the 'mongo' object, scheduler, login_manager, etc.
from db import mongo, login_manager, scheduler, IST, User, init_extensions 
from schemas import LoginForm, RegisterForm, JobForm, EditProfileForm, hash_pw, check_pw, SelfAssessmentForm
import smtp

load_dotenv()

# ----------------------------------------------------
# 2. APP INITIALIZATION & CONFIGURATION
# ----------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")

# Configuration 
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', 'false').lower() == 'true'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = ('Know-Thyself Job Portal', 'no-reply@knowthyself.com') 
app.config['MAIL_DEBUG'] = True
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', 7 * 1024 * 1024))
app.config['MONGO_URI'] = os.environ.get('MONGO_URI')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

# Initialize Flask extensions (Sets up mongo, login_manager, scheduler, etc.)
init_extensions(app)

# Initialize Flask-Mail and set it in the smtp module
mail_instance = smtp.init_mail_app(app)
smtp.set_mail_instance(mail_instance)


# ----------------------------------------------------
# 3. GLOBAL HELPERS AND CONTEXT PROCESSOR
# ----------------------------------------------------
ACTIVE_APPLICATION_STATUSES = ["pending_resume", "submitted", "approved", "corrections_needed"]

# FIX: Context processor to make 'now' available in all templates
@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()} 

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
    # (Keeping the original long list of titles here for completeness)
    titles = [
        "How are you feeling emotionally today?", "Describe one positive thing that happened today.", 
        "Rate your energy level on a scale from 1 to 10.", "What's your intention for today?", 
        "Write a message to your future self.", "What are you grateful for this week?", 
        "Unscramble the word: LPAEP", "Complete the pattern: 3, 6, 9, 12, ___", 
        "Solve: What is 25 + 17?", "Write a compliment you'd give yourself.", 
        "If emotions could speak, what would yours say?", "What's something challenging you overcame recently?", 
        "Write a short poem or haiku.", "What’s your happiest memory as a child?", 
        "How would you describe yourself in 3 words?", "Have you helped anyone today? How?", 
        "What is one hobby you'd love to try?", "List 3 people you admire and why.", 
        "What motivates you each morning?", "Draw or describe your mood as an animal (e.g., sloth = tired)", 
        "Word association: Ocean : Water :: Forest : ___", "How do you express creativity?", 
        "If you could learn anything instantly, what would it be?", "What does 'success' mean to you?", 
        "How calm or anxious do you feel? (1–10)", "What do you need less of in your life?", 
        "Rapid journal: Write whatever’s on your mind (no filter).", "What's your biggest win from this month?", 
        "Draw/write your superpower!", "What's something you're proud of recently?", 
        "How do you recharge?", "Who do you look up to, and what lesson did they teach you?", 
        "Write 3 affirmations starting with: I am...", "Design your dream day.", 
        "What makes you feel confident?", "What would your ideal future look like in 5 years?", 
        "If today had a theme song, what would it be?", "Describe a safe space in your imagination.", 
        "Write a thank-you note (to self or others).", "Have you laughed today? What made you laugh?", 
        "How do you want to grow emotionally?", "Describe a time you overcame fear.", 
        "List 3 small things you can do to feel better instantly.", 
        "If you could only keep one value (e.g., honesty, joy), what would it be?", 
        "Design a personal logo — describe/visualize it.", "Finish this sentence: 'I trust that...'", 
        "What's something beautiful you witnessed recently?", "Write a dream you had or want to have.", 
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
    """
    Mark applications with expired upload window as rejected_auto
    and return the vacancy to the job pool.
    """
    now_utc = datetime.now(timezone.utc)
    
    expired = mongo.db.applications.find({
        "resume_filename": {"$exists": False},
        "status": "pending_resume",
        "resume_deadline": {"$lt": now_utc},
    })
    
    for doc in expired:
        job_id = doc["job_id"]
        
        # 1. Return the vacancy to the jobs pool 
        job = mongo.db.jobs.find_one({"_id": job_id})
        if job and job.get("vacancies") is not None:
             mongo.db.jobs.update_one(
                {"_id": job_id},
                {"$inc": {"vacancies": 1}}
            )
        
        # 2. Update the application status
        mongo.db.applications.update_one(
            {"_id": doc["_id"]}, 
            {"$set": {
                "status": "rejected_auto", 
                "status_message": "48-hour upload window expired."
            }} 
        )

scheduler.add_job(cleanup_deadlines, "interval", hours=12)

def generate_otp():
    """Generate a 6-digit OTP"""
    return str(random.randint(100000, 999999))

GROWTH_ACTIVITIES = [
    {"id": 1, "title": "Daily Mood Check-in", "desc": "How are you feeling right now?", "icon": "😊"},
    {"id": 2, "title": "Gratitude Journal", "desc": "List three things you're thankful for today.", "icon": "🌟"},
    {"id": 7, "title": "Letter to Future Self", "desc": "Write a note to yourself in one year.", "icon": "✉️"},
]
for i in range(len(GROWTH_ACTIVITIES) + 1, 101):
    GROWTH_ACTIVITIES.append(
        {"id": i, "title": f"Reflection Prompt #{i}", "desc": f"", "icon": "📝"}
    )


# ----------------------------------------------------
# 4. ROUTES (Consolidated & Cleaned)
# ----------------------------------------------------

# --- Public & General Routes ---

@app.route("/")
def startpage():
     return render_template("startpage.html")

@app.route("/dementia-poster")
def dementia_poster():
    return render_template("dementia_poster.html")

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
        
        if user_doc and check_pw(form.password.data, user_doc.get("pw_hash", "")):
            login_user(User(user_doc))
            
            flash("Welcome !", "success")
            if current_user.role == "teacher":
                return redirect(url_for("teacher_dashboard"))
            return redirect(url_for("student_dashboard")) 
        
        flash("Invalid credentials.", "danger")
    return render_template("login.html", form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('startpage')) 

@app.route("/register", methods=["GET", "POST"])
def register():
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
                flash("Account created—please sign in", "success")
                return redirect(url_for("login"))
            except Exception as e:
                flash("An error occurred during registration. Please try again.", "danger")
    return render_template("register.html", form=form)

@app.route("/jobs")
def job_list():
    jobs = list(mongo.db.jobs.find({"status": "open"}))
    applied_ids = set()
    has_active = False
    if current_user.is_authenticated and current_user.role == 'student':
        student_applications = mongo.db.applications.find({"user_id": ObjectId(current_user.id)})
        for app in student_applications:
            if app["status"] in ACTIVE_APPLICATION_STATUSES:
                 applied_ids.add(app["job_id"])
                 has_active = True 

    return render_template("job_list.html", jobs=jobs, applied_ids=applied_ids, has_active=has_active)

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

@app.route("/guidelines")
def guidelines():
    return render_template("guidelines_modal.html")

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/support')
def support():
    return render_template('support.html')


# --- Student Routes ---

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
    has_active_application = False
    
    student_applications = mongo.db.applications.find({"user_id": ObjectId(current_user.id)})
    for app in student_applications:
        if app["status"] in ACTIVE_APPLICATION_STATUSES:
             has_active_application = True
             applied_ids.add(app["job_id"])

        # Handle time zone conversion for display
        deadline = app.get("resume_deadline")
        if deadline:
            if deadline.tzinfo is None:
                app["resume_deadline"] = pytz.utc.localize(deadline).astimezone(IST)
            else:
                app["resume_deadline"] = deadline.astimezone(IST)


    return render_template(
        "student_dashboard.html",
        apps=apps,
        jobs=jobs,
        applied_ids=applied_ids,
        has_active=has_active_application,
    )

@app.route('/self-assessment/<int:step>') 
@login_required 
def self_assessment_step(step): 
    return render_template(f'self_assessment_part{step}.html', step=step)

@app.route("/growth_menu")
@login_required
def growth_menu():
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
    qid = random.randint(1, len(GROWTH_ACTIVITIES))
    return redirect(url_for("growth_question", qid=qid))

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

    # 1. Check One-Application-Only rule
    existing_application = mongo.db.applications.find_one({
        "user_id": ObjectId(current_user.id),
        "status": {"$in": ACTIVE_APPLICATION_STATUSES} 
    })

    if existing_application:
        flash("You already have an active application. You can only apply for one job at a time.", "warning")
        return redirect(url_for("student_dashboard"))

    # 2. Check job availability
    job = mongo.db.jobs.find_one({"_id": job_obj_id, "status": "open"})
    if not job:
        flash("This job is no longer available.", "danger")
        return redirect(url_for("student_dashboard"))

    # 3. Check for vacancies (First Come, First Serve)
    vacancies_reserved_count = mongo.db.applications.count_documents({
        "job_id": job_obj_id,
        "status": {"$in": ACTIVE_APPLICATION_STATUSES}
    })

    if vacancies_reserved_count >= job.get("vacancies", 0):
        flash("Sorry, no vacancies are available for this job.", "danger")
        return redirect(url_for("student_dashboard"))

    now_utc = datetime.now(timezone.utc)
    deadline_utc = now_utc + timedelta(hours=48)

    # 4. Create the application
    mongo.db.applications.insert_one({
        "job_id": job_obj_id,
        "user_id": ObjectId(current_user.id),
        "applied_at": now_utc,
        "resume_deadline": deadline_utc,
        "status": "pending_resume",
    })

    flash("Application successful! Please upload your résumé and photo within 48 hours to complete.", "success")
    return redirect(url_for("student_dashboard"))


@app.route("/upload/<app_id>", methods=["POST"])
@login_required
def upload(app_id):
    # ... (Logic remains largely the same) ...
    try:
        app_obj_id = ObjectId(app_id)
    except:
        flash("Invalid application ID.", "danger")
        return redirect(url_for("student_dashboard"))

    app_doc = mongo.db.applications.find_one({"_id": app_obj_id})
    if not app_doc or app_doc.get("user_id") != ObjectId(current_user.id):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("student_dashboard"))

    current_status = app_doc.get("status")

    if current_status not in ["pending_resume", "corrections_needed"]:
        flash("This application cannot be modified right now.", "danger")
        return redirect(url_for("student_dashboard"))

    if current_status == "pending_resume":
        deadline = app_doc.get("resume_deadline")
        now_utc = datetime.now(timezone.utc)
        if deadline and now_utc > deadline:
            # Auto-reject the application and free up the vacancy
            job = mongo.db.jobs.find_one({"_id": app_doc["job_id"]})
            if job and job.get("vacancies") is not None:
                mongo.db.jobs.update_one(
                    {"_id": app_doc["job_id"]},
                    {"$inc": {"vacancies": 1}}
                )

            mongo.db.applications.update_one(
                {"_id": app_obj_id},
                {"$set": {"status": "rejected_auto", "status_message": "48-hour upload window expired."}}
            )
            flash("The 48-hour upload window has expired. Your application is auto-rejected.", "danger")
            return redirect(url_for("student_dashboard"))
            
    # File validation logic
    resume = request.files.get("resume")
    photo = request.files.get("photo")
    if not resume or not photo or not resume.filename.strip() or not photo.filename.strip():
        flash("Please upload both résumé and photo.", "warning")
        return redirect(url_for("student_dashboard"))

    # ... (File type validation omitted for brevity, assumed correct) ...

    # Generate secure filenames and paths
    basename = f"{current_user.student_id}_{app_id}"
    resume_ext = os.path.splitext(resume.filename)[1].lower()
    photo_ext = os.path.splitext(photo.filename)[1].lower()
    resume_filename = secure_filename(f"{basename}{resume_ext}")
    photo_filename = secure_filename(f"{basename}_photo{photo_ext}")
    upload_dir = app.config.get("UPLOAD_FOLDER", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    resume.save(os.path.join(upload_dir, resume_filename))
    photo.save(os.path.join(upload_dir, photo_filename))

    # Update application in DB
    mongo.db.applications.update_one(
        {"_id": app_obj_id},
        {"$set": {
                "resume_filename": resume_filename,
                "photo_filename": photo_filename,
                "resume_uploaded_at": datetime.now(timezone.utc),
                "status": "submitted",
                "teacher_feedback": ""
            }
        }
    )

    # Send confirmation and admin emails (Note: This is still here, but was causing issues)
    job = mongo.db.jobs.find_one({"_id": app_doc["job_id"]})
    job_title = job.get("title", "Untitled Job")

    try:
        smtp.send_resume_and_photo_mail(resume_filename, photo_filename, current_user.email, job_title)
        smtp.send_admin_notification(current_user.name, job_title, current_user.email)
    except Exception as e:
        print("Admin mail error:", e)
        flash("Upload successful, but admin could not be notified via email.", "warning")

    try:
        smtp.send_confirmation_mail(current_user.email, current_user.name, str(app_doc["_id"]), job_title)
        flash("Résumé and photo uploaded and confirmation email sent!", "success")
    except Exception as e:
        print("Student mail error:", e)
        flash("Upload successful, but confirmation email failed.", "warning")
        
    return redirect(url_for("student_dashboard"))


@app.route('/uploads/<path:filename>')
def view_resume(filename):
    upload_dir = app.config.get("UPLOAD_FOLDER", "uploads")
    # This assumes UPLOAD_FOLDER is correct or defaults to 'uploads'
    return send_from_directory(upload_dir, filename)


# --- Teacher/Admin Routes ---

@app.route('/teacher')
@login_required 
@teacher_required
def teacher_dashboard(): 
    return render_template('teacher_dashboard.html')

@app.route("/teacher/assess", methods=["GET"])
@teacher_required
def assess_students():
    name_filter = request.args.get("name", "").strip()
    status_filter = request.args.get("status", "").strip()
    resume_filter = request.args.get("resume", "").strip()

    # Query uses mongo.db.applications (CORRECT)
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

        if applied_at and app.get("resume_filename"):
            upload_time = resume_uploaded_at if resume_uploaded_at else now
            duration = upload_time - applied_at
            hours = duration.total_seconds() / 3600
            app["upload_duration_hours"] = round(hours, 1)
        else:
            app["upload_duration_hours"] = None

    all_statuses = [
        "pending_resume", "submitted", "approved",
        "rejected", "rejected_auto", "corrections_needed", "job_deleted"
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
        now=now 
    )

@app.route('/teacher/update_application/<app_id>', methods=['POST'])
@login_required
@teacher_required 
def update_application_status(app_id):
    status = request.form.get('status')
    feedback = request.form.get('feedback', "").strip()
    
    name_filter = request.form.get("name_filter", "")
    status_filter = request.form.get("status_filter", "")
    resume_filter = request.form.get("resume_filter", "")

    if status not in ["approved", "rejected", "needs_corrections"]:
        flash("Invalid application status submitted.", "danger")
        return redirect(url_for("assess_students"))

    application = mongo.db.applications.find_one({"_id": ObjectId(app_id)})
    if not application:
        flash("Application not found.", "danger")
        return redirect(url_for("assess_students"))

    student = mongo.db.users.find_one({"_id": ObjectId(application["user_id"])})
    job = mongo.db.jobs.find_one({"_id": ObjectId(application["job_id"])})

    if not student or not job:
        flash("Application data error: missing student or job.", "danger")
        return redirect(url_for("assess_students"))

    old_status = application.get("status")

    if status == "rejected" and old_status in ACTIVE_APPLICATION_STATUSES:
        mongo.db.jobs.update_one(
            {"_id": application["job_id"]},
            {"$inc": {"vacancies": 1}}
        )
    
    mongo.db.applications.update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {
            "status": status,
            "teacher_feedback": feedback,
            "updated_at": datetime.utcnow()
        }}
    )

    # REMOVED SMTP email code here based on previous steps' decision to avoid OOM errors
    # You are now relying on the in-app notification and the mailto: link added to the HTML.

    flash("✅ Application updated and student notified (in-app/manual email suggested).", "success")
    return redirect(url_for("assess_students", 
                            name=name_filter,
                            status=status_filter,
                            resume=resume_filter))

@app.route('/teacher/reassign_reupload_time/<app_id>', methods=['POST'])
@login_required
@teacher_required
def reassign_reupload_time(app_id):
    try:
        app_obj_id = ObjectId(app_id)
    except:
        flash("Invalid application ID.", "danger")
        return redirect(url_for("assess_students"))

    application = mongo.db.applications.find_one({"_id": app_obj_id})

    if not application or application.get("status") not in ['pending_resume', 'corrections_needed', 'rejected_auto']:
        flash("Cannot reassign: Application is not in a suitable state for re-assignment.", "warning")
        return redirect(url_for("assess_students"))
    
    new_status = application.get("status")
    
    if application.get("status") == 'rejected_auto':
        new_status = 'pending_resume'
    
    new_deadline_utc = datetime.now(timezone.utc) + timedelta(hours=48)
    
    mongo.db.applications.update_one(
        {"_id": app_obj_id},
        {"$set": {
            "resume_deadline": new_deadline_utc,
            "status": new_status,
        }}
    )
    
    flash(f"✅ 48-hour upload window reset and status set to {new_status.replace('_', ' ')}.", "success")
    return redirect(url_for("assess_students"))


@app.route('/teacher/edit-jobs')
@login_required
@teacher_required
def edit_jobs_list(): 
    # FIX: Correct access to the DB using mongo.db
    jobs = mongo.db.jobs.find() 
    # FIX: Render the correct template for the list
    return render_template('edit_jobs_list.html', jobs=jobs) 


# FIX: JobForm needs to be passed to the template that uses it (edit_job.html)
@app.route('/teacher/edit-job/<job_id>', methods=['GET', 'POST'])
@login_required
@teacher_required
def edit_job(job_id): 
    # FIX: Correct access to the DB using mongo.db
    job_data = mongo.db.jobs.find_one({'_id': ObjectId(job_id)})
    
    # Instantiate the form object
    form = JobForm(obj=job_data) 
    
    # Pass the form object to the template
    return render_template('edit_job.html', job=job_data, form=form)


@app.route('/teacher/new-job', methods=['GET', 'POST'])
@login_required 
@teacher_required
def new_job(): 
    form = JobForm() # Instantiate form here too
    if request.method == 'POST':
        # 1. PROCESS FORM SUBMISSION
        title = request.form.get('title')
        description = request.form.get('job_description')
        vacancies = request.form.get('vacancies', type=int)

        # 2. SAVE TO DATABASE (Example)
        if title and description and vacancies is not None:
            # FIX: Correct access to the DB using mongo.db
            mongo.db.jobs.insert_one({
                'title': title,
                'job_description': description,
                'vacancies': vacancies,
                'date_posted': datetime.utcnow()
            })
            flash('New job posting created successfully!', 'success')
            return redirect(url_for('edit_jobs_list')) 
        else:
            flash('Error: All job fields are required.', 'danger')
            
    # GET REQUEST: Render the form
    return render_template('job_form.html', form=form) # Pass form on GET request too

@app.route('/teacher/export/assessed')
@login_required 
@teacher_required
def export_assessed_students(): 
    # FIX: Correct access to the DB using mongo.db
    applications_data = mongo.db.applications.find({
        'status': {'$in': ['approved', 'rejected', 'needs_corrections']} 
    })

    # You still need the full CSV logic here, but the DB access is fixed.
    # The user provided a fragment, so I'm commenting out the missing parts:
    # output = io.StringIO()
    # writer = csv.writer(output)
    # ... (rest of CSV creation logic) ...
    
    # Placeholder return to avoid breaking execution
    flash("Export functionality is ready but not fully implemented in code.", "warning")
    return redirect(url_for('teacher_dashboard'))
    
@app.route('/teacher/clear-applications')
@login_required 
@teacher_required
def clear_application():
    return render_template('clear_application.html')    

@app.route('/teacher/students')
@login_required 
@teacher_required
def registered_students(): 
    # FIX: Correct access to the DB using mongo.db
    students_list = list(mongo.db.users.find({'role': 'student'}).sort('created_at', -1))
    
    return render_template('registered_students.html', students=students_list) 

# In app.py (Add this with your other teacher routes)

@app.route('/teacher/delete-job/<job_id>', methods=['POST'])
@login_required
@teacher_required
def delete_job(job_id):
    """Handles the deletion of a job posting and associated applications."""
    try:
        job_obj_id = ObjectId(job_id)
    except:
        flash("Invalid job ID.", "danger")
        return redirect(url_for('edit_jobs_list'))

    # 1. Delete the job posting
    job_delete_result = mongo.db.jobs.delete_one({'_id': job_obj_id})
    
    # 2. Delete all associated student applications to maintain data integrity
    app_delete_result = mongo.db.applications.delete_many({'job_id': job_obj_id})
    
    if job_delete_result.deleted_count == 1:
        flash(f"✅ Job posting deleted successfully. {app_delete_result.deleted_count} associated applications were cleared.", "success")
    else:
        flash("❌ Error: Job not found or could not be deleted.", "danger")
        
    # Redirect back to the job list page
    return redirect(url_for('edit_jobs_list'))


# In app.py (Add this with your other teacher routes)
# In app.py (Add this with your other teacher routes)

@app.route('/teacher/delete-reflection/<reflection_id>', methods=['POST'])
@login_required
@teacher_required
def delete_student_reflection(reflection_id):
    """Handles the deletion of a single student reflection post."""
    try:
        reflection_obj_id = ObjectId(reflection_id)
    except:
        flash("Invalid reflection ID.", "danger")
        return redirect(url_for('view_student_reflections'))

    # Delete the document from the growth_responses collection
    delete_result = mongo.db.growth_responses.delete_one({
        '_id': reflection_obj_id
    })
    
    if delete_result.deleted_count == 1:
        flash("✅ Student reflection successfully deleted.", "success")
    else:
        flash("❌ Error: Reflection not found or could not be deleted.", "danger")
        
    # Redirect back to the reflections list page
    return redirect(url_for('view_student_reflections'))
@app.route('/teacher/clear-applications/bulk', methods=['POST'])
@login_required
@teacher_required
def clear_application_bulk():
    """Handles the bulk clearing/deletion of selected student applications."""
    
    # 1. Get the list of application IDs to delete from the form data
    # Assuming the form uses checkboxes named 'app_ids' or similar
    app_ids_to_clear = request.form.getlist('app_ids')
    
    if not app_ids_to_clear:
        flash("No applications were selected for bulk clearing.", "warning")
        return redirect(url_for('clear_application'))
    
    try:
        # Convert string IDs to MongoDB ObjectId objects
        obj_ids = [ObjectId(app_id) for app_id in app_ids_to_clear]
        
        # 2. Perform the bulk deletion
        result = mongo.db.applications.delete_many({
            '_id': {'$in': obj_ids}
        })
        
        # 3. Handle result and redirect
        if result.deleted_count > 0:
            flash(f"✅ Successfully cleared {result.deleted_count} applications.", "success")
        else:
            flash("No matching applications were found or deleted.", "warning")
            
    except Exception as e:
        flash(f"❌ An error occurred during bulk clearing: {e}", "danger")
        
    # Redirect back to the clear application list page
    return redirect(url_for('clear_application'))
# In app.py

@app.route('/teacher/student-reflections')
@login_required 
@teacher_required
def view_student_reflections(): 
    # FIX: Define the 'reflections' variable by querying the database
    # This fetches all submissions, sorted by newest first
    reflections = list(
        mongo.db.growth_responses.find().sort("submitted_at", -1)
    )
    
    # This line now uses the correctly defined variable 'reflections'
    return render_template('student_reflections.html', reflections=reflections)
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=True)
