"""
google_signin.py - "Continue with Google": the OAuth authorization-code flow with PKCE, for people whose Emvryx account uses their Google email.

WHAT THIS FILE DOES
    The pure parts: the address that sends the person to Google, the PKCE pair, and the check of the ID token Google hands back.
    The server (app_server.py) runs the two steps: /auth/google/start and /auth/google/callback.

    The owner turns it on once: make an OAuth client at console.cloud.google.com (APIs and Services > Credentials > OAuth client ID > Web
    application), add `https://<your address>/auth/google/callback` as an authorised redirect URI, and put GOOGLE_CLIENT_ID and
    GOOGLE_CLIENT_SECRET in `.emvryx/keys.env`. Without them the button does not appear.

    Safety: the `state` is checked against a cookie in the same browser (stops a forged callback); the code is exchanged together with the
    PKCE verifier; the ID token comes straight from Google over https in that exchange, and its issuer, audience (our client id), expiry and
    `email_verified` are all checked. Google proves the EMAIL, so it only signs in an account that already has that email verified (or creates
    one when sign-ups are open / the invite is good); an account whose email was typed at sign-up but never verified is never taken over.
"""
import base64
import hashlib
import json
import secrets
import time
import urllib.parse

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")


def pkce():
    """(verifier, challenge) for the S256 method."""
    verifier = secrets.token_urlsafe(48)
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def auth_url(client_id, redirect_uri, state, challenge):
    return AUTH_URL + "?" + urllib.parse.urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": "openid email",
                                                     "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"})


def token_form(client_id, secret, redirect_uri, code, verifier):
    return urllib.parse.urlencode({"code": code, "client_id": client_id, "client_secret": secret, "redirect_uri": redirect_uri, "grant_type": "authorization_code",
                                   "code_verifier": verifier}).encode()


def email_from_id_token(id_token, client_id, now=None):
    """The verified email in an ID token that came straight from Google's token endpoint, or None. (Only for a token received that way: its signature
    is not re-checked because https to Google already authenticated it.)"""
    try:
        payload = json.loads(base64.urlsafe_b64decode(id_token.split(".")[1] + "=" * (-len(id_token.split(".")[1]) % 4)))
    except (ValueError, IndexError, AttributeError):
        return None
    now = time.time() if now is None else now
    aud = payload.get("aud")
    if payload.get("iss") not in ISSUERS or (aud != client_id and client_id not in (aud if isinstance(aud, list) else [])):
        return None
    if float(payload.get("exp", 0)) < now - 60:
        return None
    if payload.get("email_verified") not in (True, "true"):
        return None
    email = str(payload.get("email", "")).strip().lower()
    return email or None


def default_http(method, url, data=None, timeout=15):
    """(status, parsed JSON) with no redirects followed. Replaced in tests."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read(200000) or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read(20000) or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError, ValueError):
        return 0, {}
