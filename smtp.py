import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# -------------------------------
# SMTP Configuration
# -------------------------------
SMTP_SERVER = "smtp-relay.brevo.com"   # or your SMTP provider
SMTP_PORT = 587
SMTP_USER = "98424e002@smtp-brevo.com"  # change to your email
SMTP_PASS = "DRMBnxzSC7hIEQvJ"     # use App Password if Gmail

# -------------------------------
# Function to send status emails
# -------------------------------
def send_application_status_email(recipient, student_name, job_title, status, feedback):
    """
    Sends an email notification to a student when the teacher updates application status.
    """

    subject = f"Update on your application for {job_title}"

    # Customize message depending on status
    if status == "approved":
        body = f"""
Dear {student_name},

✅ Congratulations! Your application for "{job_title}" has been approved. 

Teacher Feedback: {feedback or 'No additional feedback provided.'}

Best regards,  
Placement Cell
"""
    elif status == "rejected":
        body = f"""
Dear {student_name},

❌ We regret to inform you that your application for "{job_title}" has been rejected. 

Teacher Feedback: {feedback or 'No additional feedback provided.'}

Best regards,  
Placement Cell
"""
    elif status == "needs_corrections":
        body = f"""
Dear {student_name},

⚠️ Your application for "{job_title}" requires corrections.  
Please re-upload your resume/photo within 24 hours.

Teacher Feedback: {feedback or 'No additional feedback provided.'}

Best regards,  
Placement Cell
"""
    else:
        body = f"""
Dear {student_name},

Your application status for "{job_title}" has been updated to: {status}.

Teacher Feedback: {feedback or 'No additional feedback provided.'}

Best regards,  
Placement Cell
"""

    # Build email
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, recipient, msg.as_string())
        server.quit()
        print(f"✅ Email sent to {recipient} for status '{status}'.")
    except Exception as e:
        print(f"❌ Error sending email to {recipient}: {e}")


