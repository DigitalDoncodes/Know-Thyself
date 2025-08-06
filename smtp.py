# smtp.py
import os
from datetime import datetime, timezone
import pytz
from flask import render_template, url_for, current_app
from flask_mail import Message, Mail

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
    print(f"DEBUG (smtp): Entered send_confirmation_mail for {applicant_email}")
    print(f"DEBUG (smtp): Is mail initialized in send_confirmation_mail? {mail is not None}")
    if not mail:
        print("Mail instance not initialized in smtp.py (send_confirmation_mail)")
        return

    try:
        with current_app.app_context():
            ist = pytz.timezone("Asia/Kolkata")
            now = datetime.now(ist)

            msg = Message(
                subject="✅ Application Received – Résumé & Photo",
                sender=current_app.config.get("MAIL_USERNAME"),
                recipients=[applicant_email],
            )

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
    print(f"DEBUG (smtp): Entered send_otp_email for {to_email}")
    print(f"DEBUG (smtp): Is mail initialized in send_otp_email? {mail is not None}")
    if not mail:
        print("Mail instance not initialized in smtp.py (send_otp_email)")
        return
    
    try:
        with current_app.app_context():
            msg = Message(
                subject='Your OTP for Password Change',
                sender=current_app.config.get("MAIL_USERNAME"),
                recipients=[to_email]
            )
            msg.body = f"Your OTP to change your password is: {otp}\nIf you did not request this, ignore this email."
            mail.send(msg)
    except Exception as e:
        print(f"❌ Error sending OTP email: {e}")

def send_resume_and_photo_mail(resume_filename, photo_filename, applicant_email, job_title):
    """Sends student's resume and photo as attachments to the admin."""
    print(f"DEBUG (smtp): Entered send_resume_and_photo_mail for {applicant_email}")
    print(f"DEBUG (smtp): Is mail initialized in send_resume_and_photo_mail? {mail is not None}")
    if not mail:
        print("Mail instance not initialized in smtp.py (send_resume_and_photo_mail)")
        return
    
    try:
        with current_app.app_context():
            msg = Message(
                subject=f"New Résumé & Photo for '{job_title}'",
                sender=current_app.config.get("MAIL_USERNAME"),
                recipients=[os.getenv("NOTICE_MAILBOX", "admin@example.com")] # Fallback admin email
            )
            msg.body = (
                f"Student {applicant_email} has uploaded a résumé and photo for job '{job_title}'."
            )

            upload_dir = current_app.config.get("UPLOAD_FOLDER", "uploads")
            resume_path = os.path.join(upload_dir, resume_filename)
            photo_path = os.path.join(upload_dir, photo_filename)

            if os.path.exists(resume_path):
                with current_app.open_resource(resume_path) as rf:
                    msg.attach(resume_filename, "application/octet-stream", rf.read())
            else:
                print(f"Warning: Resume file not found at {resume_path}")

            if os.path.exists(photo_path):
                with current_app.open_resource(photo_path) as pf:
                    msg.attach(photo_filename, "application/octet-stream", pf.read())
            else:
                print(f"Warning: Photo file not found at {photo_path}")
            
            mail.send(msg)
        print(f"✅ Resume/Photo email sent for {applicant_email}")
    except Exception as e:
        print(f"❌ Error sending resume/photo email: {e}")

def send_admin_notification(student_name, job_title, student_email):
    """Sends a notification to the admin about a new application."""
    print(f"DEBUG (smtp): Entered send_admin_notification for {student_email}")
    print(f"DEBUG (smtp): Is mail initialized in send_admin_notification? {mail is not None}")
    if not mail:
        print("Mail instance not initialized in smtp.py (send_admin_notification)")
        return
    
    try:
        with current_app.app_context():
            msg = Message(
                subject=f"📥 New Application Submitted: {job_title}",
                sender=current_app.config.get("MAIL_USERNAME"),
                recipients=[os.getenv("NOTICE_MAILBOX", "admin@example.com")]
            )
            msg.body = f"""A new job application has been submitted.

Student Name: {student_name}
Student Email: {student_email}
Job Title: {job_title}
Submitted At: {datetime.now().strftime('%d %b %Y, %I:%M %p')}

Check the admin panel to review it.
"""
            mail.send(msg)
    except Exception as e:
        print(f"❌ Error sending admin notification email: {e}")

def send_application_status_email(student_email, student_name, status, job_title, feedback=None):
    """Sends application status updates (approved, rejected, corrections_needed) to students."""
    print(f"DEBUG (smtp): Entered send_application_status_email for {student_email} with status '{status}'")
    print(f"DEBUG (smtp): Is mail initialized in send_application_status_email? {mail is not None}")
    if not mail:
        print("Mail instance not initialized in smtp.py (send_application_status_email)")
        return

    templates = {
        "approved": ("approved_status.html", f"Your application for {job_title} has been approved!"),
        "rejected": ("rejected_status.html", f"Update on your application for {job_title}"),
        "needs_corrections": ("corrections_status.html", f"Corrections needed for your application for {job_title}")
    }

    if status not in templates:
        print(f"[✘] Unknown status: {status} in send_application_status_email. Exiting.")
        return

    template_name, subject = templates[status]
    
    try:
        with current_app.app_context():
            portal_link = url_for('student_dashboard', _external=True)

            html_body = render_template(
                f"email_templates/{template_name}",
                student_name=student_name,
                job_title=job_title,
                feedback=feedback,
                portal_link=portal_link,
                current_year=datetime.now().year
            )

            msg = Message(subject=subject, recipients=[student_email], html=html_body)
            mail.send(msg)
        print(f"[✓] Email sent to {student_email} – {status}")
    except Exception as e:
        print(f"[✘] Error sending email: {e}")

