"""
routes_chat.py - The chat web routes: the app state, a chat's messages, sending a message, and the /api/v1 interface for other programs.

Where it fits: app_server.py builds its request handler from several "mixin" classes (small classes that each add a group of methods).
This one covers chatting. The reply to a chat message is streamed with SSE (Server-Sent Events: the server keeps the connection open and
writes small "event: name / data: {...}" text blocks as the answer grows, so the page can show words as they are written).
The model writes in a background thread and hands its pieces over through a `queue` (a safe line of items passed between threads).
`self.state` is the shared server object; `self._send(status, data)` writes a normal JSON answer.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
# Standard library: json (data as text), queue (thread-safe hand-over line), threading (background threads), time.
# Project helpers: chat_polish (thinking words/pauses), app_links (connected apps), regen_modes (the 'try again' menu), usage_limits (limits and their errors),
# app_shared (shared constants and error formatting), chat_turn (runs one chat turn), documents, research (Deep Research), web_search.
import json
import queue
import threading
import time
import chat_polish
import app_links
import regen_modes
import usage_limits as U
from app_shared import EFFORTS, MAX_TEXT, error_payload
import chat_turn
import documents
import research
import web_search
from chat_turn import start_turn


class RoutesChat:
    """The chat routes."""

    # ---- the API
    def api_state(self, who, qs):
        """GET /api/state: everything the page needs when it opens (who you are, models, effort choices, usage, chat list, settings, feature switches).
        who: the signed-in person's info dict. qs: the parsed query string (dict of lists), which may name a model and an effort."""
        st = self.state
        # The model catalog for this person: "cards" (the main models) and "other" (the rest), each with a state such as "ready".
        cat = st.catalog(who)
        # Query-string values are lists, so take the first one (or None when absent).
        model_id = (qs.get("model") or [None])[0]
        effort = (qs.get("effort") or ["balanced"])[0]
        # How hard the model thinks. Anything unknown becomes "balanced".
        effort = "balanced" if effort == "auto" else (effort if effort in EFFORTS else "balanced")   # Auto: show Balanced's numbers
        # Look-up table: model id -> model.
        pool = {m["id"]: m for m in cat["cards"] + cat["other"]}
        # Only models that are loaded and usable.
        ready = [m for m in cat["cards"] + cat["other"] if m["state"] == "ready"]
        # Default model: Flare if ready, else the first ready one, else the first card even if not ready.
        default = next((m for m in ready if m["name"] == "Flare"), ready[0] if ready else cat["cards"][0])
        # Use the asked-for model when it exists.
        model = pool.get(model_id) or default
        # How much of the person's allowance is left, for this model and effort.
        snap = st.usage_snapshot(who, model, effort)
        # The model's memory window (how much of the chat it can keep in view).
        win = st.window_for(who, model)
        # The answer is one big dict: identity and plan, the models, the effort choices (below), usage, memory window, the chat list, settings,
        # the morning-briefing switch, thinking-animation words, the 'try again' options and the feature flags.
        return {"user": who["user"], "owner": who["owner"], "admin": who["admin"], "founder": who["founder"], "granter": who["granter"], "plan": who["tier"], "demo": st.demo, "contact": st.security.get("contact_email") or None,
                "models": cat, "model": model["id"], "efforts": [
                    {"id": "auto", "name": "Auto", "use": "Picks for you",
                     "blurb": "Decides how long to think from your message: quick for simple questions, deeper for hard ones."},
                    {"id": "quick", "name": "Quick", "use": "Uses less", "blurb": "Answers fast and thinks briefly. Best for simple questions."},
                    {"id": "balanced", "name": "Balanced", "use": "Normal usage", "blurb": "A good mix of speed and care. The default."},
                    {"id": "deep", "name": "Deep", "use": "Uses more",
                     "blurb": "Takes longer: thinks it through and checks its work. More accurate on hard questions."}],
                # Only these keys of the window info are sent to the page.
                "usage": snap, "window": {k: win[k] for k in ("window", "reason", "mode", "limited_by", "cache_bits", "cache_mb")},
                "chats": st.store(who["user"]).list_chats(), "settings": st.get_settings(who["user"]),
                # True if the person allows connected apps, and at least one connected app can feed the briefing (set intersection with &).
                "briefing": bool(st.get_settings(who["user"]).get("connected_apps", True) and st.links.store.connected(who["user"]) & set(app_links.BRIEF_APPS)),
                "thinking_words": list(chat_polish.THINKING_WORDS), "think_switch_s": chat_polish.THINKING_SWITCH_S,
                "pause_by_effort": chat_polish.PAUSE_BASE, "regen_options": regen_modes.menu(),
                "features": st.flags.mapping(who), "gaming": bool(st.cfg.get("gaming"))}

    def api_get_chat(self, who, cid):
        """GET one chat with its messages. cid: the chat id (private chats have negative ids). Sends 404 if it does not exist."""
        store = self.state.store(who["user"])
        if not store.exists(cid):
            return self._send(404, {"code": "not_found", "message": "That chat is gone."})
        # The person's document library, to describe files attached to messages.
        lib = self.state.docs_for(who["user"])
        # Feature flag: show what each answer looked up and how long it thought.
        lines = self.state.flags.on("chat_lines", who)                   # chat_lines: what each answer looked up and how long it thought
        # Which answer-checking extras are switched on for this person (each is its own feature flag).
        checks = [k for k, fid in (("calc_fixed", "chat_calc"), ("unsupported", "chat_verify"), ("cites", "chat_cite")) if self.state.flags.on(fid, who)]
        # Build the message list. Each message may carry a `flags` dict of extra facts; (m.get("flags") or {}) safely handles a missing one.
        msgs = [{"id": m["id"], "role": m["role"], "content": m["content"], "model_id": m["model_id"], "status": m["status"],
                 "cut": bool((m.get("flags") or {}).get("cut")), "fb": (m.get("flags") or {}).get("fb", ""), "ctx": (m.get("flags") or {}).get("ctx"),
                 **({"looked": (m.get("flags") or {}).get("looked"), "thought_s": (m.get("flags") or {}).get("thought_s")} if lines else {}),
                 **{k: (m.get("flags") or {})[k] for k in checks if k in (m.get("flags") or {})},
                 "docs": [{"id": d["id"], "name": d["name"], "kind": d["kind"]} for d in (lib.info(i) for i in m.get("docs") or []) if d]}
                # Skip messages that were squeezed away (compacted) and have no text left.
                for m in store.messages(cid) if not (m["status"] == "compacted" and not m["content"])]
        ctx = None
        # Older chats have no memory-meter reading; measure it now from the last model that answered.
        if msgs and not any(m["ctx"] for m in msgs) and self.state.flags.on("context_meter", who):     # a chat from before the meter: measure it now
            # Walk backwards to find the newest assistant message that records a model.
            last = next((m["model_id"] for m in reversed(msgs) if m["role"] == "assistant" and m["model_id"]), None)
            try:
                # May fail if that model is gone or not ready; handled just below.
                ctx = chat_turn.meter_for(self.state, who, cid, last) if last else None
            except Exception as e:                             # noqa: BLE001 - a model that is gone or not ready: the page estimates until the next reply
                ctx = None
                if self.state.verbose:
                    print(f"(memory meter: could not measure chat {cid}: {type(e).__name__})", flush=True)
        # Optional extras, added only when their feature flag is on.
        extra = {}
        if self.state.flags.on("chat_versions", who):
            # JSON object keys must be text, so the numeric keys are turned into strings.
            extra["versions"] = {str(k): v for k, v in store.versions(cid).items()}
        if self.state.flags.on("chat_projects", who) and store.meta(cid).get("folder"):
            p = store.project(store.meta(cid)["folder"])
            extra["project"] = p["name"] if p else None
        # Final answer: the chat header, its messages, memory reading, stored metadata, extras, whether a reply is being written right now, and attached documents.
        self._send(200, {"id": cid, "title": store.title(cid), "private": cid < 0, "skill": store.skill(cid), "messages": msgs, "ctx": ctx, **store.meta(cid), **extra,
                         # `stops` holds a stop switch for every reply currently being written.
                         "generating": (who["user"], cid) in self.state.stops,
                         "docs": [d for d in (self.state.docs_for(who["user"]).info(i) for i in store.docs(cid)) if d]})

    # ---- the Emvryx API: other programs (your own apps) ask a question and get an answer. Key-only, one key per app, never a browser.
    # Checks the API key of another program. Unlike people, apps have no browser session: each request must carry a key.
    def _app_auth(self):
        """(who, record) for the app behind this request's key, or None after the right error was sent."""
        st = self.state
        # Too many wrong tries from this address: a 429 was already sent.
        if self._locked():
            return None
        h = self.headers.get("Authorization", "")
        # The header looks like `Authorization: Bearer <key>`; 7 is the length of "Bearer ", so [7:] is the key.
        key = h[7:].strip() if h.startswith("Bearer ") else ""
        who = st.who(key) if key else None
        # Unknown key, or a key that belongs to a person rather than an app.
        if not who or not who.get("app"):
            self._fail("bad app key")
            self._send(401, {"code": "bad_key", "message": "That key isn't right.", "action": "Use the key made for this app (Admin > Apps). It starts with emvx_."})
            return None
        # The app's settings (default model, rate limit, instructions, on/off).
        rec = st.app_record(who["user"]) or {}
        # The owner can switch an app off.
        if who["banned"] or not rec.get("app_enabled", True):
            self._send(403, {"code": "app_off", "message": "This app has been switched off.", "action": "Ask the owner of Emvryx to switch it on."})
            return None
        return who, rec

    def _api_model_id(self, who, ref):
        """A model's id from a name (flare, equinox, solstice, apogee: the newest of that name) or an id (flare-2.5), or None."""
        cat = self.state.catalog(who)
        # Compare case-insensitively.
        ref = str(ref or "").strip().lower()
        # A bare name (like a model family name) picks the newest model of that name; cards hold the newest of each.
        for m in cat["cards"]:
            if m["name"].lower() == ref:
                return m["id"]
        # Otherwise accept an exact model id; None if nothing matches.
        return next((m["id"] for m in cat["cards"] + cat["other"] if m["id"].lower() == ref), None)

    def api_v1_models(self):
        """GET /api/v1/models: lists the models an app may ask (name, id, label, state) and which one is its default."""
        got = self._app_auth()
        if not got:
            return
        # (person-like info for the app, its settings record)
        who, rec = got
        cat = self.state.catalog(who)
        # `{m['version']:g}` prints a number without trailing zeros (2.5, not 2.50).
        self._send(200, {"default": rec.get("app_model", "flare"), "models": [{"name": m["name"].lower(), "id": m["id"], "label": f"{m['name']} {m['version']:g}", "state": m["state"]}
                                                                          for m in cat["cards"]]})

    def api_v1_ask(self, body):
        """POST /api/v1/ask: another program sends a question (and optional facts, history, model, effort) and gets an answer, either all at once or
        streamed ("stream": true). The chat used for the call is private and deleted at the end, so nothing is kept."""
        st = self.state
        got = self._app_auth()
        if not got:
            return
        who, rec = got
        # Per-app speed limit in requests per minute (default 20).
        ok, wait = st.app_rate_ok(who["user"], int(rec.get("app_rpm", 20)))
        if not ok:
            return self._send(429, {"code": "rate_limit", "message": "This app is asking too fast.", "action": f"Wait {wait} seconds and try again.", "retry_after": wait},
                              headers={"Retry-After": str(wait)})
        # Check every input before using it: type, size and shape. Bad input gets a clear 400 message saying what to send.
        question = str(body.get("question") or "").strip()
        if not question:
            return self._send(400, {"code": "empty", "message": "Send a question.", "action": 'POST {"question": "..."} to /api/v1/ask.'})
        if len(question) > 8000:
            return self._send(400, {"code": "too_long", "message": "The question is too long (8,000 characters at most)."})
        # Facts: short texts the answer must rely on for numbers (limits: 50 items, 20,000 characters in total).
        facts = body.get("facts") or []
        if not isinstance(facts, list) or len(facts) > 50 or not all(isinstance(f, str) for f in facts) or sum(len(f) for f in facts) > 20000:
            return self._send(400, {"code": "bad_facts", "message": '"facts" is a list of up to 50 short texts (20,000 characters in all).'})
        # History: earlier turns of the app's own conversation (up to 10, 2,000 characters each).
        history = body.get("history") or []
        if (not isinstance(history, list) or len(history) > 10 or not all(isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str)
                                                                      and len(h["content"]) <= 2000 for h in history)):
            return self._send(400, {"code": "bad_history", "message": '"history" is up to 10 earlier turns: {"role": "user" or "assistant", "content": "..."} (2,000 characters each).'})
        # How long the model should think; falls back to the app's default setting.
        effort = str(body.get("effort") or rec.get("app_effort", "balanced"))
        if effort not in ("auto", "quick", "balanced", "deep"):
            return self._send(400, {"code": "bad_effort", "message": "effort is auto, quick, balanced or deep."})
        # Gaming mode: the PC is busy with something else, so answer 'resting' (HTTP 429-style limit error) right away.
        if st.cfg.get("gaming"):
            status, headers, payload = U.LimitError("gaming", "Emvryx is resting while the PC is being used for something else. Please try again in a little while.", retry_after=300).to_http()
            return self._send(status, payload, headers=headers)
        # Turn the requested name/id into a real model id.
        model_id = self._api_model_id(who, body.get("model") or rec.get("app_model", "flare"))
        if not model_id:
            return self._send(400, {"code": "bad_model", "message": "That model isn't available to this app.", "action": "GET /api/v1/models lists them."})
        # Extra instructions for the model: the app's saved ones, plus any sent with this call (whitespace squeezed, cut to 2,000 characters).
        hints = [rec.get("app_instructions", ""), " ".join(str(body.get("instructions") or "").split())[:2000]]
        # When facts are given, tell the model to quote numbers exactly and never do its own arithmetic.
        if facts:
            hints.append("Use only the facts in the notes for any number or figure. Quote numbers exactly as given and never calculate or invent totals. If the notes do not contain the answer, say so.")
        # Each fact becomes a numbered 'note' the model can read.
        notes = [{"title": f"Fact {i + 1}", "text": f[:2000]} for i, f in enumerate(facts)]
        # This person's chat storage.
        store = st.store(who["user"])
        cid = store.new_chat(private=True)                      # nothing about a call is ever saved
        for h in history:                                       # the earlier turns of a conversation the app keeps itself (Emvryx remembers nothing between calls)
            store.add(cid, h["role"], h["content"].strip() or "...")
        # Stream the answer piece by piece, or wait and send it whole.
        stream = bool(body.get("stream"))
        try:
            # Start the answer in a background thread. Returns: q (the queue the pieces arrive on), stop (a switch that cancels it), the model, its window and the effort decision. pace=False: no artificial thinking pause for programs.
            q, stop, model, win, decision = start_turn(st, who, cid, question, model_id, effort, pace=False, extra_notes=notes, extra_hint="\n\n".join(h for h in hints if h))
        # Bad option (for example a wrong effort word): remove the temporary chat and say why.
        except ValueError as e:
            store.delete_chat(cid)
            return self._send(400, {"code": "bad_option", "message": str(e)})
        # Unknown model.
        except KeyError:
            store.delete_chat(cid)
            return self._send(400, {"code": "bad_model", "message": "That model isn't available to this app."})
        except Exception as e:                                 # noqa: BLE001
            store.delete_chat(cid)
            status, headers, payload = error_payload(e)
            return self._send(status, payload, headers=headers)
        # Count the call for the app's statistics.
        st.note_app_call(who["user"])

        # Builds the final JSON answer from the turn's result `r`.
        def finished(r):
            snap = st.usage_snapshot(who, model, decision["effort"])
            return {"answer": (r.get("text") or "").strip(), "model": f"{model['name']} {model['version']:g}", "model_id": model["id"], "effort": decision["effort"],
                    # complete is False when the answer was cut short (for example it ran out of length).
                    "complete": r.get("reason") in ("done", None), "usage": {"left_pct": int(snap["tank"]["pct"]), "messages_left": int(snap["tank"]["messages_left"])}}
        try:
            if stream:
                # Stream mode: write the HTTP headers by hand. text/event-stream is the SSE type; "Connection: close" ends the connection after the answer.
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                for k, v in self._security_headers().items():
                    self.send_header(k, v)
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                # Writes one SSE event ("event: name" line, "data: json" line, blank line) and flushes it so the client sees it immediately.
                emit = lambda ev, data: (self.wfile.write(f"event: {ev}\ndata: {json.dumps(data)}\n\n".encode()), self.wfile.flush())
                # Give up after 15 minutes (900 s). monotonic() is a clock that never jumps backwards.
                deadline = time.monotonic() + 900
                while True:
                    try:
                        # Wait up to 1 second for the next item from the model thread: (kind, value).
                        kind, val = q.get(timeout=1)
                    # Nothing arrived this second: check the deadline and wait again.
                    except queue.Empty:
                        if time.monotonic() > deadline:
                            stop.set()
                            return emit("error", {"code": "timeout", "message": "The model took too long."})
                        continue
                    # A new bit of the answer text.
                    if kind == "piece":
                        emit("piece", {"text": val})
                    # The answer is finished: send the final event and end.
                    elif kind == "done":
                        return emit("done", finished(val))
                    # The turn failed: send the error text (element [2] of error_payload is the JSON body).
                    elif kind == "error":
                        return emit("error", error_payload(val)[2])
            # Not streaming: wait for the whole answer, with the same 15-minute limit and a 504 (timeout) answer.
            deadline = time.monotonic() + 900
            while True:
                try:
                    kind, val = q.get(timeout=1)
                except queue.Empty:
                    if time.monotonic() > deadline:
                        stop.set()
                        return self._send(504, {"code": "timeout", "message": "The model took too long.", "action": "Try a shorter question or a smaller model."})
                    continue
                if kind == "done":
                    return self._send(200, finished(val))
                if kind == "error":
                    status, headers, payload = error_payload(val)
                    return self._send(status, payload, headers=headers)
        # The program hung up: stop the model.
        except (BrokenPipeError, ConnectionResetError):
            stop.set()
        # Always delete the temporary private chat, even after an error.
        finally:
            store.delete_chat(cid)

    def api_send(self, who, cid, body):
        """POST /api/chats/<cid>/send: add the person's message (or regenerate the last reply) and stream the answer back as SSE events:
        research, thinking, loading, notes, memory, compacting, piece (the growing text), done, error."""
        st = self.state
        store = st.store(who["user"])
        if not store.exists(cid):
            return self._send(404, {"code": "not_found", "message": "That chat is gone."})
        # The typed message.
        text = str(body.get("text", "")).strip()
        # True means: write the last answer again instead of adding a new message.
        regenerate = bool(body.get("regenerate"))
        # Becomes True when the person sent only a picture.
        picture_only = False
        # No words: allowed only if a new file/picture was attached and not yet sent.
        if not regenerate and not text:                       # only a picture (or file), no words: send it as it is, like other chat apps
            # Attached documents not yet sent with an earlier message (set subtraction).
            new = set(store.docs(cid)) - store.sent_docs(cid)
            if not new:
                return self._send(400, {"code": "empty", "message": "Type a message first."})
            lib = st.docs_for(who["user"])
            picture_only = any((lib.info(i) or {}).get("kind") in documents.IMAGE_KINDS for i in new)
            text = documents.PICTURE_ONLY_TEXT if picture_only else documents.FILE_ONLY_TEXT
        # Refuse over-long messages.
        if len(text) > MAX_TEXT:
            return self._send(400, {"code": "too_long", "message": "That message is too long. Please shorten it."})
        # Gaming mode: answer 'resting' at once.
        if st.cfg.get("gaming"):                              # Gaming mode: a plain "resting" answer at once, nothing is saved or counted
            status, headers, payload = U.LimitError("gaming", "Emvryx is resting while the PC is being used for something else. Please try again in a little while.", retry_after=300).to_http()
            return self._send(status, payload, headers=headers)
        # A list used as a flag: `opened` is empty until the SSE headers have been sent. (A list can be changed inside the helper functions below; a plain variable could not without `nonlocal`.)
        opened = []

        # Send the HTTP headers that start the SSE stream, only once.
        def open_stream():
            if opened:
                return
            opened.append(True)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in self._security_headers().items():
                self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

        # Write one SSE event to the browser and flush.
        def emit(event, data):
            self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()

        # Report a failure: as a normal HTTP error if the stream has not started yet, otherwise as an SSE error event.
        def refuse(status, payload, headers=None):        # before the stream: a proper HTTP status; once research has started: an error event
            if not opened:
                return self._send(status, payload, headers=headers)
            emit("error", dict(payload, http=status))
        # Optional extra material for the model (research notes and a hint on how to use them).
        extra_notes, extra_hint = None, ""
        # Deep Research: gather web notes first (not for private chats, whose ids are negative).
        if body.get("research") and cid >= 0 and not picture_only and st.flags.on("chat_research", who):     # chat_research: Deep Research first
            # The person's setting for where answers may come from ("none" = the model only).
            where = st.get_settings(who["user"])["web_search"]
            if where == "none":
                return self._send(400, {"code": "no_research", "message": "Deep Research needs the web, and your answers are set to Model only.",
                                        "action": "Change Where answers come from in Settings."})
            # What to research: the typed text, or the last user message when regenerating.
            asked = text if not regenerate else next((m["content"] for m in reversed(store.messages(cid)) if m["role"] == "user"), "")
            # Start streaming now so progress events can show while the research runs.
            open_stream()
            try:
                source = "wikipedia" if where == "off" else "auto"
                # Run the research: `search` fetches notes for a query, `on_step` reports progress to the page as an event, `year` is the current year taken from the server clock.
                extra_notes = research.gather(asked, search=lambda q: web_search.web_notes(q, k=3, source=source, read=True),
                                              on_step=lambda t, done, of: emit("research", {"step": t, "done": done, "of": of}),
                                              year=time.gmtime(st.clock()).tm_year)
            # The page went away during research.
            except (BrokenPipeError, ConnectionResetError):
                return
            extra_hint = research.REPORT_HINT
        try:
            # Start the answer in a background thread (same return values as in api_v1_ask).
            q, stop, model, win, decision = start_turn(st, who, cid, text, str(body.get("model", "")), str(body.get("effort", "balanced")),
                                             regenerate, body.get("regen_mode") or None, cont=bool(body.get("continue")), picture_only=picture_only,
                                             extra_notes=extra_notes, extra_hint=extra_hint)
        except ValueError as e:
            return refuse(400, {"code": "bad_option", "message": str(e)})
        except KeyError:
            return refuse(400, {"code": "bad_model", "message": "That model isn't available."})
        except Exception as e:
            status, headers, payload = error_payload(e)
            return refuse(status, payload, headers=headers)
        # wait a moment: limits and connection errors come back at once and deserve a proper HTTP status
        # Peek at the first queue item for up to 0.4 s. Limit errors arrive straight away and can still become a proper HTTP error.
        first = None
        try:
            first = q.get(timeout=0.4)
        except queue.Empty:
            pass
        if first and first[0] == "error":
            status, headers, payload = error_payload(first[1])
            return refuse(status, payload, headers=headers)
        open_stream()
        try:
            # Tell the page how long to show 'thinking' at least, and which effort was chosen and why.
            emit("thinking", {"min_first_s": decision["pause"], "effort": decision["effort"], "auto": decision["auto"],
                              "reason": decision["reason"], "temperature": decision["temperature"]})
            # Start with the item already taken from the queue (may be None).
            item = first
            while True:
                # Need a new item: wait up to 10 s; if none, send an SSE comment line (starting with ':') as a keep-alive so proxies do not close the quiet connection.
                if item is None:
                    try:
                        item = q.get(timeout=10)
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        continue
                # Each item is a (kind, value) pair from the model thread.
                kind, val = item
                item = None
                # Pass each kind of progress straight on to the page.
                if kind == "loading":
                    emit("loading", {"model": val})
                elif kind == "notes":
                    emit("notes", val)
                elif kind == "memory":
                    emit("memory", val)
                elif kind == "compacting":
                    emit("compacting", {})
                elif kind == "piece":
                    emit("piece", {"t": val})
                # Finished: send totals (compacted/forgotten counts, the new message id, title, usage) and stop. Owners and admins also get timing details.
                elif kind == "done":
                    snap = st.usage_snapshot(who, model, decision["effort"])
                    emit("done", {"reason": val["reason"], "compacted": val["compacted_messages"],
                                  "forgotten": val["forgotten_messages"], "message_id": val["message_id"],
                                  "title": store.title(cid), "usage": snap, "effort": decision["effort"], "auto": decision["auto"], "cut": bool(val.get("cut")),
                                  "context": val.get("context"), **({"timing": val.get("timing")} if (who.get("owner") or who.get("admin")) else {})})
                    return
                else:
                    # payload (a dict) gets the HTTP status added so the page can show the right message.
                    status, headers, payload = error_payload(val)
                    payload["http"] = status
                    emit("error", payload)
                    return
        # Writing failed because the browser disconnected.
        except (BrokenPipeError, ConnectionResetError, OSError):
            # the page went away (the app was closed or switched away from): the reply keeps being written and saved, and shows when they come back.
            # pwa_push: when it is ready, the browsers they turned notifications on in are told
            # If they have push notifications on, watch for the end of the reply.
            if st.flags.on("pwa_push", who) and st.push.subscribed(who["user"]):
                # Waits (up to 15 minutes) for the reply to finish and then sends a push notification with the chat title.
                def tell():
                    while True:
                        try:
                            kind, _ = q.get(timeout=900)
                        except queue.Empty:
                            return
                        if kind == "done":
                            st.push.send(who["user"], "Emvryx", "Your answer is ready: " + (store.title(cid) or "your chat")[:60], "/")
                            return
                        if kind == "error":
                            return
                # Run `tell` in the background (a daemon thread does not keep the server alive on shutdown).
                threading.Thread(target=tell, daemon=True).start()
