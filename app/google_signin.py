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

    Words used here: OAuth is the standard way to let someone sign in with another service without sharing a password. "PKCE" (said "pixy") is a safety
    add-on: the app invents a secret (the verifier), sends only its fingerprint (the challenge) to Google, and shows the secret later, so a stolen
    code is useless. An "ID token" is a signed note from Google saying who the person is.
"""
import base64        # base64 turns bytes into plain text and back
import hashlib       # SHA-256: a one-way fingerprint of some bytes
import json
import secrets       # a safe random-number source for secrets
import time
import urllib.parse  # builds and encodes web addresses and form data

# Google's page where the person signs in, and Google's address where our server swaps the code for the ID token.
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
# The names Google uses for itself inside an ID token ("iss"); a token from anyone else is refused.
ISSUERS = ("https://accounts.google.com", "accounts.google.com")


def pkce():
    """(verifier, challenge) for the S256 method."""
    # The verifier is a long random secret that stays on our side until the code swap.
    verifier = secrets.token_urlsafe(48)
    # The challenge = SHA-256 of the verifier, written in URL-safe base64 with the trailing "=" padding removed (PKCE requires that exact form).
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def auth_url(client_id, redirect_uri, state, challenge):
    """The address to send the person to, to sign in at Google.

    client_id: our app's id at Google. redirect_uri: where Google sends the person back. state: a random value we also keep in a cookie
    and compare on return. challenge: from pkce(). scope "openid email" asks only for the person's email.
    """
    # urlencode builds "key=value&key=value" with special characters made safe. "select_account" always lets the person choose which Google account.
    return AUTH_URL + "?" + urllib.parse.urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": "openid email",
                                                     "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"})


def token_form(client_id, secret, redirect_uri, code, verifier):
    """The form data (as bytes) posted to Google's token address to swap the one-time `code` for an ID token; it includes the PKCE `verifier`."""
    return urllib.parse.urlencode({"code": code, "client_id": client_id, "client_secret": secret, "redirect_uri": redirect_uri, "grant_type": "authorization_code",
                                   "code_verifier": verifier}).encode()


def email_from_id_token(id_token, client_id, now=None):
    """The verified email in an ID token that came straight from Google's token endpoint, or None. (Only for a token received that way: its signature
    is not re-checked because https to Google already authenticated it.)

    `now` can be given in tests. Returns the lower-case email, or None if anything about the token is wrong.
    """
    # An ID token is three base64 parts joined by dots: header.payload.signature. The middle part is the JSON with the facts.
    # base64 text must have a length that is a multiple of 4; "=" * (-len % 4) adds the missing "=" padding that tokens leave off.
    try:
        payload = json.loads(base64.urlsafe_b64decode(id_token.split(".")[1] + "=" * (-len(id_token.split(".")[1]) % 4)))
    # Not a token at all (bad text, no dots, not a string): refuse.
    except (ValueError, IndexError, AttributeError):
        return None
    now = time.time() if now is None else now
    # "aud" (audience) must be OUR client id, so a token made for another app is refused. It can be one value or a list. "iss" must be Google.
    aud = payload.get("aud")
    if payload.get("iss") not in ISSUERS or (aud != client_id and client_id not in (aud if isinstance(aud, list) else [])):
        return None
    # "exp" is the expiry time (seconds since 1970); 60 seconds of leeway allows for clocks that differ a little.
    if float(payload.get("exp", 0)) < now - 60:
        return None
    # Google must say it checked this email address (the value can be a real true or the text "true").
    if payload.get("email_verified") not in (True, "true"):
        return None
    email = str(payload.get("email", "")).strip().lower()
    return email or None


def default_http(method, url, data=None, timeout=15):
    """(status, parsed JSON) with no redirects followed. Replaced in tests.

    Status 0 with {} means the service could not be reached at all. `data` (bytes) makes it a POST body.
    """
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        # read(200000) takes at most 200,000 bytes, so a huge reply cannot use up memory; an empty reply becomes {}.
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read(200000) or b"{}")
    # Google answered with an error status (such as 400): still return its status and its JSON explanation.
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read(20000) or b"{}")
        except ValueError:
            return e.code, {}
    # No connection, timeout, or an answer that is not JSON.
    except (urllib.error.URLError, OSError, ValueError):
        return 0, {}
