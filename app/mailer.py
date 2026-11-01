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
    """Sends real email through an SMTP server (SMTP = the standard way programs hand an email to a mail provider).
    Built by from_env() only when the host, login and password are all set.
    """
    def __init__(self, host, port, user, password, sender):
        """Remember the connection details. `port` is turned into a number because environment variables always arrive as text.
        `sender` is the address shown in the From line.
        """
        # Assign all five settings in one line (tuple unpacking: the left names get the right values in order).
        self.host, self.port, self.user, self.password, self.sender = host, int(port), user, password, sender

    def send(self, to, subject, body):
        """Send one plain-text email to `to` with the given subject and body. Raises an error if the mail server refuses."""
        # Build the email message object: who it is from and to, its subject, then the text.
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, to, subject
        msg.set_content(body)
        # A default TLS context: the rules that make the connection encrypted and check the server's certificate is genuine.
        ctx = ssl.create_default_context()
        # Port 465 is encrypted from the first byte (SSL); the timeout of 20 seconds stops the app hanging if the server never answers.
        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, context=ctx, timeout=20) as s:
                s.login(self.user, self.password)
                s.send_message(msg)
        # Any other port (normally 587) starts as plain text and then upgrades to encrypted with STARTTLS, before the password is sent.
        else:
            with smtplib.SMTP(self.host, self.port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(self.user, self.password)
                s.send_message(msg)


class FakeMailer:
    """Keeps what it was asked to send (tests, and a dry run on your own computer).

    Stand-in for SmtpMailer that sends nothing and just remembers each email, so tests can look at what would have been sent.
    It has the same send() method, so the rest of the app cannot tell the difference.
    """

    # The list of emails this fake was asked to send, oldest first.
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body):
        """Same signature as SmtpMailer.send, but store the email as a dictionary instead of sending it."""
        self.sent.append({"to": to, "subject": subject, "body": body})


def from_env(env=None):
    """Build an SmtpMailer from environment variables, or return None when email is not set up.
    `env` can be a plain dictionary for tests; by default the real environment is used.
    """
    # Use the real environment unless a dictionary was passed in (`is None` so that an empty dictionary still counts as given).
    env = os.environ if env is None else env
    host, user, password = env.get("EMVRYX_SMTP_HOST"), env.get("EMVRYX_SMTP_USER"), env.get("EMVRYX_SMTP_PASS")
    # Host, login and password are all required; if any is missing, email sign-in is simply off.
    if not (host and user and password):
        return None
    # Port defaults to 587 (kept as text, SmtpMailer converts it); the sender defaults to the login name.
    return SmtpMailer(host, env.get("EMVRYX_SMTP_PORT", "587"), user, password, env.get("EMVRYX_MAIL_FROM") or user)


def code_email(code, minutes=10):
    """Return (subject, body) for the sign-in code email. `minutes` is how long the code stays valid and is shown to the person."""
    return ("Your Emvryx sign-in code", f"Your Emvryx code is {code}\n\nIt works for {minutes} minutes and only once. "
            "If you did not ask for it, ignore this email: nobody can sign in without the code.")
