"""
routes_chat.py - The chat web routes: the app state, a chat's messages, sending a message, and the /api/v1 interface for other programs.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import queue
import time
import chat_polish
import app_links
import regen_modes
import usage_limits as U
from app_shared import EFFORTS, MAX_TEXT, error_payload
import chat_turn
from chat_turn import start_turn


class RoutesChat:
    """The chat routes."""

    # ---- the API
    def api_state(self, who, qs):
        st = self.state
        cat = st.catalog(who)
        model_id = (qs.get("model") or [None])[0]
        effort = (qs.get("effort") or ["balanced"])[0]
        effort = "balanced" if effort == "auto" else (effort if effort in EFFORTS else "balanced")   # Auto: show Balanced's numbers
        pool = {m["id"]: m for m in cat["cards"] + cat["other"]}
        ready = [m for m in cat["cards"] + cat["other"] if m["state"] == "ready"]
        default = next((m for m in ready if m["name"] == "Flare"), ready[0] if ready else cat["cards"][0])
        model = pool.get(model_id) or default
        snap = st.usage_snapshot(who, model, effort)
        win = st.window_for(who, model)
        return {"user": who["user"], "owner": who["owner"], "admin": who["admin"], "founder": who["founder"], "granter": who["granter"], "plan": who["tier"], "demo": st.demo, "contact": st.security.get("contact_email") or None,
                "models": cat, "model": model["id"], "efforts": [
                    {"id": "auto", "name": "Auto", "use": "Picks for you",
                     "blurb": "Decides how long to think from your message: quick for simple questions, deeper for hard ones."},
                    {"id": "quick", "name": "Quick", "use": "Uses less", "blurb": "Answers fast and thinks briefly. Best for simple questions."},
                    {"id": "balanced", "name": "Balanced", "use": "Normal usage", "blurb": "A good mix of speed and care. The default."},
                    {"id": "deep", "name": "Deep", "use": "Uses more",
                     "blurb": "Takes longer: thinks it through and checks its work. More accurate on hard questions."}],
                "usage": snap, "window": {k: win[k] for k in ("window", "reason", "mode", "limited_by", "cache_bits", "cache_mb")},
                "chats": st.store(who["user"]).list_chats(), "settings": st.get_settings(who["user"]),
                "briefing": bool(st.get_settings(who["user"]).get("connected_apps", True) and st.links.store.connected(who["user"]) & set(app_links.BRIEF_APPS)),
                "thinking_words": list(chat_polish.THINKING_WORDS), "think_switch_s": chat_polish.THINKING_SWITCH_S,
                "pause_by_effort": chat_polish.PAUSE_BASE, "regen_options": regen_modes.menu(),
                "features": st.flags.mapping(who), "gaming": bool(st.cfg.get("gaming"))}

    def api_get_chat(self, who, cid):
        store = self.state.store(who["user"])
        if not store.exists(cid):
            return self._send(404, {"code": "not_found", "message": "That chat is gone."})
        lib = self.state.docs_for(who["user"])
        msgs = [{"id": m["id"], "role": m["role"], "content": m["content"], "model_id": m["model_id"], "status": m["status"],
                 "cut": bool((m.get("flags") or {}).get("cut")), "fb": (m.get("flags") or {}).get("fb", ""), "ctx": (m.get("flags") or {}).get("ctx"),
                 "docs": [{"id": d["id"], "name": d["name"], "kind": d["kind"]} for d in (lib.info(i) for i in m.get("docs") or []) if d]}
                for m in store.messages(cid) if not (m["status"] == "compacted" and not m["content"])]
        ctx = None
        if msgs and not any(m["ctx"] for m in msgs) and self.state.flags.on("context_meter", who):     # a chat from before the meter: measure it now
            last = next((m["model_id"] for m in reversed(msgs) if m["role"] == "assistant" and m["model_id"]), None)
            try:
                ctx = chat_turn.meter_for(self.state, who, cid, last) if last else None
            except Exception as e:                             # noqa: BLE001 - a model that is gone or not ready: the page estimates until the next reply
                ctx = None
                if self.state.verbose:
                    print(f"(memory meter: could not measure chat {cid}: {type(e).__name__})", flush=True)
        self._send(200, {"id": cid, "title": store.title(cid), "private": cid < 0, "skill": store.skill(cid), "messages": msgs, "ctx": ctx, **store.meta(cid),
                         "generating": (who["user"], cid) in self.state.stops,
                         "docs": [d for d in (self.state.docs_for(who["user"]).info(i) for i in store.docs(cid)) if d]})

    # ---- the Emvryx API: other programs (your own apps) ask a question and get an answer. Key-only, one key per app, never a browser.
    def _app_auth(self):
        """(who, record) for the app behind this request's key, or None after the right error was sent."""
        st = self.state
        if self._locked():
            return None
        h = self.headers.get("Authorization", "")
        key = h[7:].strip() if h.startswith("Bearer ") else ""
        who = st.who(key) if key else None
        if not who or not who.get("app"):
            self._fail("bad app key")
            self._send(401, {"code": "bad_key", "message": "That key isn't right.", "action": "Use the key made for this app (Admin > Apps). It starts with emvx_."})
            return None
        rec = st.app_record(who["user"]) or {}
        if who["banned"] or not rec.get("app_enabled", True):
            self._send(403, {"code": "app_off", "message": "This app has been switched off.", "action": "Ask the owner of Emvryx to switch it on."})
            return None
        return who, rec

    def _api_model_id(self, who, ref):
        """A model's id from a name (flare, equinox, solstice, apogee: the newest of that name) or an id (flare-2.5), or None."""
        cat = self.state.catalog(who)
        ref = str(ref or "").strip().lower()
        for m in cat["cards"]:
            if m["name"].lower() == ref:
                return m["id"]
        return next((m["id"] for m in cat["cards"] + cat["other"] if m["id"].lower() == ref), None)

    def api_v1_models(self):
        got = self._app_auth()
        if not got:
            return
        who, rec = got
        cat = self.state.catalog(who)
        self._send(200, {"default": rec.get("app_model", "flare"), "models": [{"name": m["name"].lower(), "id": m["id"], "label": f"{m['name']} {m['version']:g}", "state": m["state"]}
                                                                          for m in cat["cards"]]})

    def api_v1_ask(self, body):
        st = self.state
        got = self._app_auth()
        if not got:
            return
        who, rec = got
        ok, wait = st.app_rate_ok(who["user"], int(rec.get("app_rpm", 20)))
        if not ok:
            return self._send(429, {"code": "rate_limit", "message": "This app is asking too fast.", "action": f"Wait {wait} seconds and try again.", "retry_after": wait},
                              headers={"Retry-After": str(wait)})
        question = str(body.get("question") or "").strip()
        if not question:
            return self._send(400, {"code": "empty", "message": "Send a question.", "action": 'POST {"question": "..."} to /api/v1/ask.'})
        if len(question) > 8000:
            return self._send(400, {"code": "too_long", "message": "The question is too long (8,000 characters at most)."})
        facts = body.get("facts") or []
        if not isinstance(facts, list) or len(facts) > 50 or not all(isinstance(f, str) for f in facts) or sum(len(f) for f in facts) > 20000:
            return self._send(400, {"code": "bad_facts", "message": '"facts" is a list of up to 50 short texts (20,000 characters in all).'})
        history = body.get("history") or []
        if (not isinstance(history, list) or len(history) > 10 or not all(isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str)
                                                                      and len(h["content"]) <= 2000 for h in history)):
            return self._send(400, {"code": "bad_history", "message": '"history" is up to 10 earlier turns: {"role": "user" or "assistant", "content": "..."} (2,000 characters each).'})
        effort = str(body.get("effort") or rec.get("app_effort", "balanced"))
        if effort not in ("auto", "quick", "balanced", "deep"):
            return self._send(400, {"code": "bad_effort", "message": "effort is auto, quick, balanced or deep."})
        if st.cfg.get("gaming"):
            status, headers, payload = U.LimitError("gaming", "Emvryx is resting while the PC is being used for something else. Please try again in a little while.", retry_after=300).to_http()
            return self._send(status, payload, headers=headers)
        model_id = self._api_model_id(who, body.get("model") or rec.get("app_model", "flare"))
        if not model_id:
            return self._send(400, {"code": "bad_model", "message": "That model isn't available to this app.", "action": "GET /api/v1/models lists them."})
        hints = [rec.get("app_instructions", ""), " ".join(str(body.get("instructions") or "").split())[:2000]]
        if facts:
            hints.append("Use only the facts in the notes for any number or figure. Quote numbers exactly as given and never calculate or invent totals. If the notes do not contain the answer, say so.")
        notes = [{"title": f"Fact {i + 1}", "text": f[:2000]} for i, f in enumerate(facts)]
        store = st.store(who["user"])
        cid = store.new_chat(private=True)                      # nothing about a call is ever saved
        for h in history:                                       # the earlier turns of a conversation the app keeps itself (Emvryx remembers nothing between calls)
            store.add(cid, h["role"], h["content"].strip() or "...")
        stream = bool(body.get("stream"))
        try:
            q, stop, model, win, decision = start_turn(st, who, cid, question, model_id, effort, pace=False, extra_notes=notes, extra_hint="\n\n".join(h for h in hints if h))
        except ValueError as e:
            store.delete_chat(cid)
            return self._send(400, {"code": "bad_option", "message": str(e)})
        except KeyError:
            store.delete_chat(cid)
            return self._send(400, {"code": "bad_model", "message": "That model isn't available to this app."})
        except Exception as e:                                 # noqa: BLE001
            store.delete_chat(cid)
            status, headers, payload = error_payload(e)
            return self._send(status, payload, headers=headers)
        st.note_app_call(who["user"])

        def finished(r):
            snap = st.usage_snapshot(who, model, decision["effort"])
            return {"answer": (r.get("text") or "").strip(), "model": f"{model['name']} {model['version']:g}", "model_id": model["id"], "effort": decision["effort"],
                    "complete": r.get("reason") in ("done", None), "usage": {"left_pct": int(snap["tank"]["pct"]), "messages_left": int(snap["tank"]["messages_left"])}}
        try:
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                for k, v in self._security_headers().items():
                    self.send_header(k, v)
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                emit = lambda ev, data: (self.wfile.write(f"event: {ev}\ndata: {json.dumps(data)}\n\n".encode()), self.wfile.flush())
                deadline = time.monotonic() + 900
                while True:
                    try:
                        kind, val = q.get(timeout=1)
                    except queue.Empty:
                        if time.monotonic() > deadline:
                            stop.set()
                            return emit("error", {"code": "timeout", "message": "The model took too long."})
                        continue
                    if kind == "piece":
                        emit("piece", {"text": val})
                    elif kind == "done":
                        return emit("done", finished(val))
                    elif kind == "error":
                        return emit("error", error_payload(val)[2])
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
        except (BrokenPipeError, ConnectionResetError):
            stop.set()
        finally:
            store.delete_chat(cid)

    def api_send(self, who, cid, body):
        st = self.state
        store = st.store(who["user"])
        if not store.exists(cid):
            return self._send(404, {"code": "not_found", "message": "That chat is gone."})
        text = str(body.get("text", "")).strip()
        regenerate = bool(body.get("regenerate"))
        if not regenerate and not text:
            return self._send(400, {"code": "empty", "message": "Type a message first."})
        if len(text) > MAX_TEXT:
            return self._send(400, {"code": "too_long", "message": "That message is too long. Please shorten it."})
        if st.cfg.get("gaming"):                              # Gaming mode: a plain "resting" answer at once, nothing is saved or counted
            status, headers, payload = U.LimitError("gaming", "Emvryx is resting while the PC is being used for something else. Please try again in a little while.", retry_after=300).to_http()
            return self._send(status, payload, headers=headers)
        try:
            q, stop, model, win, decision = start_turn(st, who, cid, text, str(body.get("model", "")), str(body.get("effort", "balanced")),
                                             regenerate, body.get("regen_mode") or None, cont=bool(body.get("continue")))
        except ValueError as e:
            return self._send(400, {"code": "bad_option", "message": str(e)})
        except KeyError:
            return self._send(400, {"code": "bad_model", "message": "That model isn't available."})
        except Exception as e:
            status, headers, payload = error_payload(e)
            return self._send(status, payload, headers=headers)
        # wait a moment: limits and connection errors come back at once and deserve a proper HTTP status
        first = None
        try:
            first = q.get(timeout=0.4)
        except queue.Empty:
            pass
        if first and first[0] == "error":
            status, headers, payload = error_payload(first[1])
            return self._send(status, payload, headers=headers)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in self._security_headers().items():
            self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(event, data):
            self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()
        try:
            emit("thinking", {"min_first_s": decision["pause"], "effort": decision["effort"], "auto": decision["auto"],
                              "reason": decision["reason"], "temperature": decision["temperature"]})
            item = first
            while True:
                if item is None:
                    try:
                        item = q.get(timeout=10)
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        continue
                kind, val = item
                item = None
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
                elif kind == "done":
                    snap = st.usage_snapshot(who, model, decision["effort"])
                    emit("done", {"reason": val["reason"], "compacted": val["compacted_messages"],
                                  "forgotten": val["forgotten_messages"], "message_id": val["message_id"],
                                  "title": store.title(cid), "usage": snap, "effort": decision["effort"], "auto": decision["auto"], "cut": bool(val.get("cut")),
                                  "context": val.get("context")})
                    return
                else:
                    status, headers, payload = error_payload(val)
                    payload["http"] = status
                    emit("error", payload)
                    return
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                                               # the page went away (the app was closed or switched away from): the reply keeps being written and saved, and shows when they come back
