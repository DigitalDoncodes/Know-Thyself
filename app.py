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
    flash, send_from_directory, send_file, session, abort, current_app, jsonify
)
from flask_login import login_user, logout_user, login_required, current_user
from dotenv import load_dotenv

load_dotenv()

from db import mongo, login_manager, scheduler, IST, User, init_extensions
from schemas import LoginForm, RegisterForm, JobForm, EditProfileForm, hash_pw, check_pw, SelfAssessmentForm

# Import SMTP functions
import smtp

# Initialize Flask app
app = Flask(__name__, template_folder="templates", static_folder="static")

# Configure your SMTP settings (using values from environment variables)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] =587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = ('Know-Thyself Job Portal', 'no-reply@knowthyself.com')

# Set UPLOAD_FOLDER and MAX_CONTENT_LENGTH from environment variables
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', 7 * 1024 * 1024))

# Initialize Flask extensions
init_extensions(app)

# Initialize Flask-Mail and set it in the smtp module
mail_instance = smtp.init_mail_app(app)
smtp.set_mail_instance(mail_instance)

# Load MongoDB URI and Secret Key from environment variables
app.config['MONGO_URI'] = os.environ.get('MONGO_URI')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
app.config['MAIL_DEBUG'] = True


# --- GLOBAL CONSTANTS ---
# Statuses that count as an active application and reserve a vacancy
ACTIVE_APPLICATION_STATUSES = ["pending_resume", "submitted", "approved", "corrections_needed"]


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


# Dummy function definitions (kept for context, but truncated)
def generate_growth_modules():
    titles = ["How are you feeling emotionally today?", "Describe one positive thing...",]
    modules = []
    for i, title in enumerate(titles, start=1):
        field = f"q{i}"
        html = f'<textarea name="{field}" placeholder="Write here..." rows="3" required></textarea>'
        modules.append({"title": title, "html": html})
    return modules


def cleanup_deadlines():
    """
    FIXED LOGIC: Mark applications with expired upload window as rejected_auto
    and MOST IMPORTANTLY, return the vacancy.
    """
    now_utc = datetime.now(timezone.utc)
    
    # Find applications that are still waiting for files AND whose deadline has passed
    expired = mongo.db.applications.find({
        "status": "pending_resume", 
        "resume_filename": {"$exists": False},
        "resume_deadline": {"$lt": now_utc},
    })
    
    for doc in expired:
        job_id = doc["job_id"]
        
        # 1. Return the vacancy to the jobs pool (Crucial Fix)
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
        print(f"✅ Auto-rejected application {doc['_id']} and returned vacancy for job {job_id}.")

scheduler.add_job(cleanup_deadlines, "interval", hours=12)

def generate_otp():
    """Generate a 6-digit OTP"""
    return str(random.randint(100000, 999999))


# --- Routes (truncated non-essential definitions) ---

@app.route("/")
def startpage():
     return render_template("startpage.html")

# ... (other non-essential routes like /dementia-poster, /growth_menu, /login, /register are omitted for brevity, assuming their original core logic is sound as per previous verification)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('startpage')) 

# ... (routes for job_list, job_detail, resources, advice, guidelines are omitted)

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
    
    # Check for *any* active application to enforce the "one job" rule
    student_applications = mongo.db.applications.find({"user_id": ObjectId(current_user.id)})
    for app in student_applications:
        if app["status"] in ACTIVE_APPLICATION_STATUSES:
             has_active_application = True
             applied_ids.add(app["job_id"])

    now_ist = datetime.now(IST) 
    for app in apps:
        status = app.get("status", "")
        if status == "approved":
            app["status_message"] = "🎉 Yay! Your application is approved."
        elif status == "rejected":
            app["status_message"] = "😞 Unfortunately, your application was rejected."
        elif status == "rejected_auto":
            app["status_message"] = "⏳ Auto-Rejected. You missed the 48-hour upload window."
        elif status == "corrections_needed":
            app["status_message"] = "✍️ Your application needs corrections. Please check feedback."
        elif status == "submitted":
             app["status_message"] = "👀 Submitted and under review by the teacher."
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

    # 1. Check One-Application-Only rule
    existing_application = mongo.db.applications.find_one({
        "user_id": ObjectId(current_user.id),
        "status": {"$in": ACTIVE_APPLICATION_STATUSES} # CORRECT: Use the constant list
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
    # Count how many slots are currently reserved/taken
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
    
    # 5. Vacancy is now implicitly taken by the ACTIVE_APPLICATION_STATUSES count

    flash("Application successful! Please upload your résumé and photo within 48 hours to complete.", "success")
    return redirect(url_for("student_dashboard"))


@app.route("/upload/<app_id>", methods=["POST"])
@login_required
def upload(app_id):
    # 📌 1. Verify application ownership and existence
    try:
        app_obj_id = ObjectId(app_id)
    except:
        flash("Invalid application ID.", "danger")
        return redirect(url_for("student_dashboard"))

    app_doc = mongo.db.applications.find_one({"_id": app_obj_id})
    if not app_doc or app_doc.get("user_id") != ObjectId(current_user.id):
        flash("Unauthorized access or application not found.", "danger")
        return redirect(url_for("student_dashboard"))

    current_status = app_doc.get("status")

    if current_status not in ["pending_resume", "corrections_needed"]:
        flash("This application cannot be modified right now.", "danger")
        return redirect(url_for("student_dashboard"))

    # 📌 2. CRITICAL FIX: 48-HOUR DEADLINE CHECK for initial submission
    if current_status == "pending_resume":
        deadline = app_doc.get("resume_deadline")
        now_utc = datetime.now(timezone.utc)
        if deadline and now_utc > deadline:
            # Auto-reject the application and return the vacancy
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
            
    # 📌 3. Get uploaded files and validate (file checking logic is fine)
    resume = request.files.get("resume")
    photo = request.files.get("photo")
    if not resume or not photo or not resume.filename.strip() or not photo.filename.strip():
        flash("Please upload both résumé and photo.", "warning")
        return redirect(url_for("student_dashboard"))

    allowed_resume = {".pdf", ".doc", ".docx"}
    allowed_photo = {".jpg", ".jpeg", ".png"}
    resume_ext = os.path.splitext(resume.filename)[1].lower()
    photo_ext = os.path.splitext(photo.filename)[1].lower()

    if resume_ext not in allowed_resume:
        flash("Résumé must be a PDF, DOC, or DOCX file.", "danger")
        return redirect(url_for("student_dashboard"))
    if photo_ext not in allowed_photo:
        flash("Photo must be JPG or PNG.", "danger")
        return redirect(url_for("student_dashboard"))

    # 📌 4. Generate secure filenames and paths (unchanged, correct)
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
        {"_id": app_obj_id},
        {"$set": {
                "resume_filename": resume_filename,
                "photo_filename": photo_filename,
                "resume_uploaded_at": datetime.now(timezone.utc),
                "status": "submitted", # Final status after initial or re-upload
                "teacher_feedback": ""  # Clear feedback upon re-submission
            }
        }
    )

    # 📌 7. Send confirmation and admin emails
    job = mongo.db.jobs.find_one({"_id": app_doc["job_id"]})
    job_title = job.get("title", "Untitled Job")

    try:
        smtp.send_resume_and_photo_mail(
            resume_filename, photo_filename,
            current_user.email, job_title
        )
        smtp.send_admin_notification(current_user.name, job_title, current_user.email)
    except Exception as e:
        print("Admin mail error:", e)
        flash("Upload successful, but admin could not be notified via email.", "warning")

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

# ... (Teacher and Admin routes omitted for brevity, assuming most logic is sound)

@app.route('/teacher/update_application/<app_id>', methods=['POST'])
@login_required
@teacher_required
def update_application_status(app_id):
    status = request.form.get('status')
    feedback = request.form.get('feedback', "").strip()
    
    # Hidden fields used to redirect back to the current filter view
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
    
    old_status = application.get("status")

    # --- CRITICAL FIX: Vacancy Management Logic ---
    if status == "rejected" and old_status in ACTIVE_APPLICATION_STATUSES:
        # If the application was active and is now rejected, return the vacancy
        mongo.db.jobs.update_one(
            {"_id": application["job_id"]},
            {"$inc": {"vacancies": 1}}
        )
        print(f"Vacancy returned for job {application['job_id']} due to rejection.")
    
    # If a previously rejected/cleared application is somehow approved,
    # it would *not* take a new vacancy because the "one job" and FCFS rule
    # are enforced on the initial /apply route. The teacher handles exceptions manually.

    # Update application in database
    mongo.db.applications.update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {
            "status": status,
            "teacher_feedback": feedback,
            "updated_at": datetime.utcnow()
        }}
    )

    # Send notification email
    smtp.send_application_status_email(
        student_email=student["email"],
        student_name=student.get("name", "Student"),
        status=status,
        job_title=job.get("title", "Your Job Application"),
        # Only include feedback in the email if it's not 'approved'
        feedback=feedback if status in ["needs_corrections", "rejected"] else None
    )

    flash("✅ Application updated and student notified.", "success")
    # Redirect back to the assessment page, maintaining filters
    return redirect(url_for("assess_students", 
                            name=name_filter,
                            status=status_filter,
                            resume=resume_filter))

# ... (rest of the teacher routes are assumed sound)

@app.route('/teacher/reassign_reupload_time/<app_id>', methods=['POST'])
@login_required
@teacher_required
def reassign_reupload_time(app_id):
    """Allows a teacher to reset the 48-hour window for a 'corrections_needed' application."""
    try:
        app_obj_id = ObjectId(app_id)
    except:
        flash("Invalid application ID.", "danger")
        return redirect(url_for("assess_students"))

    application = mongo.db.applications.find_one({"_id": app_obj_id})

    if not application or application.get("status") not in ['corrections_needed', 'pending_resume']:
        flash("Cannot reassign: Application is not in a modifiable state.", "warning")
        return redirect(url_for("assess_students"))

    # Resetting the deadline to 48 hours from now
    new_deadline_utc = datetime.now(timezone.utc) + timedelta(hours=48)
    
    mongo.db.applications.update_one(
        {"_id": app_obj_id},
        {"$set": {
            "resume_deadline": new_deadline_utc,
            # Set status back to pending_resume if it was corrected but missed the timer previously
            "status": "pending_resume" if application.get("status") == "corrections_needed" and not application.get("resume_filename") else application.get("status")
        }}
    )
    
    flash("✅ 48-hour upload window reset for the student.", "success")
    return redirect(url_for("assess_students"))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=True)
