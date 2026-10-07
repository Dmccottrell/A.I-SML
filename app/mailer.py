"""
mailer.py - Sends the sign-in code email. SMTP when configured, a stand-in for tests, nothing otherwise.

WHAT THIS FILE DOES
    The app only ever sends one kind of email: "your Emvryx code is 123456". To turn it on, set these before starting the app:

        EMVRYX_SMTP_HOST   e.g. smtp.gmail.com (or your email provider's server)
        EMVRYX_SMTP_PORT   587 (default; STARTTLS) or 465 (SSL)
        EMVRYX_SMTP_USER   the login
        EMVRYX_SMTP_PASS   its password (an "app password", not your main one)
        EMVRYX_MAIL_FROM   the address shown as the sender (default: the login)

    Without them `from_env()` returns None and the app says email sign-in is not set up (keys and pairing links still work).
    The password is read from the environment only: it is not written to any file by this code.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage


class SmtpMailer:
    def __init__(self, host, port, user, password, sender):
        self.host, self.port, self.user, self.password, self.sender = host, int(port), user, password, sender

    def send(self, to, subject, body):
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, to, subject
        msg.set_content(body)
        ctx = ssl.create_default_context()
        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, context=ctx, timeout=20) as s:
                s.login(self.user, self.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(self.user, self.password)
                s.send_message(msg)


class FakeMailer:
    """Keeps what it was asked to send (tests, and a dry run on your own computer)."""

    def __init__(self):
        self.sent = []

    def send(self, to, subject, body):
        self.sent.append({"to": to, "subject": subject, "body": body})


def from_env(env=None):
    env = os.environ if env is None else env
    host, user, password = env.get("EMVRYX_SMTP_HOST"), env.get("EMVRYX_SMTP_USER"), env.get("EMVRYX_SMTP_PASS")
    if not (host and user and password):
        return None
    return SmtpMailer(host, env.get("EMVRYX_SMTP_PORT", "587"), user, password, env.get("EMVRYX_MAIL_FROM") or user)


def code_email(code, minutes=10):
    return ("Your Emvryx sign-in code", f"Your Emvryx code is {code}\n\nIt works for {minutes} minutes and only once. "
            "If you did not ask for it, ignore this email: nobody can sign in without the code.")
