# smtp.py (final improved version)

import os
from datetime import datetime
import pytz
from flask import render_template, url_for, current_app
from flask_mail import Message, Mail
from threading import Thread

# Indian Standard Time zone
IST = pytz.timezone("Asia/Kolkata")

# Global mail instance
mail = None


def init_mail_app(app_instance):
    """Initializes the Flask-Mail extension with the given app instance."""
    global mail
    mail = Mail(app_instance)
    app_instance.logger.info("[SMTP] Mail initialized")
    return mail


def set_mail_instance(mail_instance):
    """Sets the global mail instance for use in this module."""
    global mail
    mail = mail_instance


# ---------------- HELPER ---------------- #

def _send_async_email(app, msg):
    """Run mail.send in a separate thread with app context."""
    try:
        with app.app_context():
            mail.send(msg)
        app.logger.info(f"[SMTP] Email sent to {msg.recipients}")
    except Exception as e:
        app.logger.error(f"[SMTP] Failed to send email: {e}")


def send_email(msg):
    """Threaded send wrapper to avoid blocking Flask requests."""
    if not mail:
        print("[SMTP] Mail instance not initialized")
        return
    Thread(target=_send_async_email, args=(current_app._get_current_object(), msg), daemon=True).start()


# ---------------- MAILERS ---------------- #

def send_confirmation_mail(applicant_email, applicant_name, application_id, job_title):
    """Send confirmation email to the student."""
    now = datetime.now(IST)
    msg = Message(
        subject="✅ Application Files Received – Next Step: Review",
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
    send_email(msg)


def send_otp_email(to_email, otp):
    """Send OTP email for password change verification"""
    msg = Message(
        subject="🔑 Your OTP for Password Change Verification",
        sender=current_app.config.get("MAIL_USERNAME"),
        recipients=[to_email],
        body=f"Your One-Time Password (OTP) is: {otp}\n\nIf you didn’t request this, ignore this email."
    )
    send_email(msg)


def send_resume_and_photo_mail(resume_filename, photo_filename, applicant_email, job_title):
    """Send resume/photo attachments to admin."""
    admin_recipient = os.getenv("NOTICE_MAILBOX", "admin@example.com")
    msg = Message(
        subject=f"📥 NEW SUBMISSION: '{job_title}' from {applicant_email}",
        sender=current_app.config.get("MAIL_USERNAME"),
        recipients=[admin_recipient],
        body=f"Student {applicant_email} submitted files for '{job_title}'. See attached."
    )

    upload_dir = current_app.config.get("UPLOAD_FOLDER", "uploads")
    resume_path = os.path.join(upload_dir, resume_filename)
    photo_path = os.path.join(upload_dir, photo_filename)

    if os.path.exists(resume_path):
        with open(resume_path, "rb") as rf:
            mime_type = "application/pdf" if resume_filename.endswith(".pdf") else "application/octet-stream"
            msg.attach(resume_filename, mime_type, rf.read())

    if os.path.exists(photo_path):
        with open(photo_path, "rb") as pf:
            mime_type = "image/jpeg" if photo_filename.lower().endswith((".jpg", ".jpeg")) else "image/png"
            msg.attach(photo_filename, mime_type, pf.read())

    send_email(msg)


def send_admin_notification(student_name, job_title, student_email):
    """Notify admin about new application."""
    admin_recipient = os.getenv("NOTICE_MAILBOX", "admin@example.com")
    msg = Message(
        subject=f"🔔 New Application Alert: {job_title}",
        sender=current_app.config.get("MAIL_USERNAME"),
        recipients=[admin_recipient],
        body=f"New application from {student_name} ({student_email}) for {job_title}."
    )
    send_email(msg)


def send_application_status_email(student_email, student_name, status, job_title, feedback=None):
    """Send status update email to student."""
    templates = {
        "approved": ("approved_status.html", f"🎉 Application Approved for {job_title}!"),
        "rejected": ("rejected_status.html", f"Update on your application for {job_title}"),
        "rejected_auto": ("rejected_status.html", f"Update on your application for {job_title}"),
        "needs_corrections": ("corrections_status.html", f"✍️ Corrections Needed for Your Application"),
    }

    if status not in templates:
        current_app.logger.error(f"[SMTP] Unknown status: {status}")
        return

    template_name, subject = templates[status]
    portal_link = url_for("student_dashboard", _external=True)

    html_body = render_template(
        f"email_templates/{template_name}",
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
        html=html_body,
    )
    send_email(msg)
