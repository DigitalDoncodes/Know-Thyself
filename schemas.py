# smtp.py
import os
from datetime import datetime
import pytz
from flask import render_template, url_for, current_app
from flask_mail import Message, Mail

# Define the Indian Standard Time zone
IST = pytz.timezone("Asia/Kolkata")

# Global mail object (will be initialized by init_mail_app in app.py)
mail = None

def init_mail_app(app_instance):
    """Initializes the Flask-Mail extension with the given app instance."""
    global mail
    mail = Mail(app_instance)
    print(f"DEBUG (smtp.py init): Mail instance initialized: {mail is not None}")
    return mail

def set_mail_instance(mail_instance):
    """Sets the global mail instance for use in this module."""
    global mail
    mail = mail_instance
    print(f"DEBUG (smtp.py set): Global mail instance set: {mail is not None}")


def send_confirmation_mail(applicant_email, applicant_name, application_id, job_title):
    """Send confirmation email to the student."""
    if not mail:
        print("Mail instance not initialized in smtp.py (send_confirmation_mail)")
        return

    try:
        with current_app.app_context():
            now = datetime.now(IST)

            msg = Message(
                subject="✅ Application Files Received – Next Step: Review",
                sender=current_app.config.get("MAIL_USERNAME"),
                recipients=[applicant_email],
            )

            # NOTE: Assuming you have a template named 'confirmation_mail.html'
            msg.html = render_template(
                "confirmation_mail.html",
                name=applicant_name,
                job_title=job_title,
                application_id=application_id,
                submitted_date=now.strftime("%B %d, %Y – %I:%M %p IST")
            )
            mail.send(msg)
        print(f"✅ Confirmation email sent to {applicant_email}")
    except Exception as e:
        print(f"❌ Error sending confirmation email: {e}")

def send_otp_email(to_email, otp):
    """Send OTP email for password change verification"""
    if not mail:
        print("Mail instance not initialized in smtp.py (send_otp_email)")
        return
    
    try:
        with current_app.app_context():
            msg = Message(
                subject='🔑 Your OTP for Password Change Verification',
                sender=current_app.config.get("MAIL_USERNAME"),
                recipients=[to_email]
            )
            msg.body = f"Your One-Time Password (OTP) to change your account password is: {otp}\n\nThis code expires soon. If you did not request this change, please ignore this email."
            mail.send(msg)
    except Exception as e:
        print(f"❌ Error sending OTP email: {e}")

def send_resume_and_photo_mail(resume_filename, photo_filename, applicant_email, job_title):
    """
    FIXED LOGIC: Sends student's resume and photo as attachments to the admin for review.
    Uses standard Python file I/O (open) for reliable file reading.
    """
    if not mail:
        print("Mail instance not initialized in smtp.py (send_resume_and_photo_mail)")
        return
    
    try:
        with current_app.app_context():
            admin_recipient = os.getenv("NOTICE_MAILBOX", "admin@example.com")
            
            msg = Message(
                subject=f"📥 NEW SUBMISSION: '{job_title}' from {applicant_email}",
                sender=current_app.config.get("MAIL_USERNAME"),
                recipients=[admin_recipient]
            )
            msg.body = (
                f"Student {applicant_email} ({os.path.splitext(resume_filename)[0]}) has successfully uploaded a résumé and photo for the job '{job_title}'.\n\nPlease review the attached files."
            )

            upload_dir = current_app.config.get("UPLOAD_FOLDER", "uploads")
            resume_path = os.path.join(upload_dir, resume_filename)
            photo_path = os.path.join(upload_dir, photo_filename)
            
            # --- Resume Attachment ---
            if os.path.exists(resume_path):
                with open(resume_path, 'rb') as rf:
                    mime_type = 'application/pdf' if resume_filename.lower().endswith('.pdf') else 'application/octet-stream'
                    msg.attach(resume_filename, mime_type, rf.read())
            else:
                print(f"Warning: Resume file not found at {resume_path}")

            # --- Photo Attachment ---
            if os.path.exists(photo_path):
                with open(photo_path, 'rb') as pf:
                    mime_type = 'image/jpeg' if photo_filename.lower().endswith(('.jpg', '.jpeg')) else 'image/png' if photo_filename.lower().endswith('.png') else 'application/octet-stream'
                    msg.attach(photo_filename, mime_type, pf.read())
            else:
                print(f"Warning: Photo file not found at {photo_path}")
            
            mail.send(msg)
        print(f"✅ Resume/Photo email sent to admin: {admin_recipient}")
    except Exception as e:
        print(f"❌ Error sending resume/photo email: {e}")

def send_admin_notification(student_name, job_title, student_email):
    """Sends a notification to the admin about a new application (less detailed than the one with attachments)."""
    if not mail:
        print("Mail instance not initialized in smtp.py (send_admin_notification)")
        return
    
    try:
        with current_app.app_context():
            admin_recipient = os.getenv("NOTICE_MAILBOX", "admin@example.com")
            msg = Message(
                subject=f"🔔 New Application Alert: {job_title}",
                sender=current_app.config.get("MAIL_USERNAME"),
                recipients=[admin_recipient]
            )
            msg.body = f"""A new job application has been submitted and files uploaded.

Student Name: {student_name}
Student Email: {student_email}
Job Title: {job_title}
Submitted At: {datetime.now(IST).strftime('%d %b %Y, %I:%M %p IST')}

Check your secure email or the admin panel to review the documents.
"""
            mail.send(msg)
    except Exception as e:
        print(f"❌ Error sending admin notification email: {e}")

def send_application_status_email(student_email, student_name, status, job_title, feedback=None):
    """Sends application status updates (approved, rejected, corrections_needed) to students."""
    if not mail:
        print("Mail instance not initialized in smtp.py (send_application_status_email)")
        return

    templates = {
        "approved": ("approved_status.html", f"🎉 Application Approved for {job_title}!"),
        "rejected": ("rejected_status.html", f"Update on your application for {job_title}"),
        "rejected_auto": ("rejected_status.html", f"Update on your application for {job_title}"),
        "needs_corrections": ("corrections_status.html", f"✍️ Corrections Needed for Your Application"),
    }

    if status not in templates:
        print(f"[✘] Unknown status: {status} in send_application_status_email. Exiting.")
        return

    template_name, subject = templates[status]
    
    try:
        with current_app.app_context():
            portal_link = url_for('student_dashboard', _external=True)

            # NOTE: Assuming 'email_templates' subfolder is used, fallback to main 'templates' folder
            template_path = f"email_templates/{template_name}"
            
            html_body = render_template(
                template_path,
                student_name=student_name,
                job_title=job_title,
                feedback=feedback,
                portal_link=portal_link,
                current_year=datetime.now().year
            )

            msg = Message(
                subject=subject, 
                sender=current_app.config.get("MAIL_USERNAME"),
                recipients=[student_email], 
                html=html_body
            )
            mail.send(msg)
        print(f"[✓] Email sent to {student_email} – {status}")
    except Exception as e:
        print(f"[✘] Error sending email: {e}")
