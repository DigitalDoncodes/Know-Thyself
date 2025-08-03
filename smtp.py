# smtp_test.py
import smtplib
import ssl
import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Get credentials from environment variables
sender_email = os.getenv("psychologyresumemail@gmail.com")
password = os.getenv("ltgtowqtgjkpbjpr")

print(f"--- Environment Variable Check ---")
print(f"Current Working Directory: {os.getcwd()}")
print(f".env file expected at: {os.path.join(os.getcwd(), '.env')}")
print(f"MAIL_USERNAME loaded: {sender_email}")
print(f"MAIL_PASSWORD loaded: {password}") # This should show the actual password or None
print(f"--- Attempting SMTP Test ---")

# Only proceed if credentials are not None
if sender_email is None or password is None:
    print("SMTP Test: Failed to send email. Error: MAIL_USERNAME or MAIL_PASSWORD not loaded from .env.")
else:
    receiver_email = sender_email # Send to self for testing
    message = """\
Subject: Test Email from Flask App

This is a test email from your Flask app environment."""

    print(f"Attempting to send email from: {sender_email}")
    print(f"SMTP Server: smtp.gmail.com, Port: 465")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, message)
        print("SMTP Test: Email sent successfully!")
    except Exception as e:
        print(f"SMTP Test: Failed to send email. Error: {e}")