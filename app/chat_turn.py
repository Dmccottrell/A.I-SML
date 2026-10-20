"""
chat_turn.py - One chat turn: look things up, build the prompt, run the model and stream the answer (start_turn), and the model safety-check helper.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import base64
import queue
import re
import threading
import time
import app_engine as E
import chat_polish
import app_skills
import documents
import live_data
import identity_answer
import lookup_auto
import effort_router
import regen_modes
import usage_limits as U
from app_errors import AppError, ModelRefused, ModelTooBig
from app_shared import CONTINUE_HINT, EFFORTS, OPEN_EFFORTS, TEMPERATURE, Cancelled


def _meter_parts(state, who, model_id):
    model = state.pick_model(who, model_id)
    window = state.window_for(who, model)["window"]
    caps = OPEN_EFFORTS if model.get("open") else EFFORTS
    return state.tok_for(model), window, min(caps["balanced"], max(32, window // 2), model.get("max_reply_tokens", caps["balanced"]))


def meter_for(state, who, chat_id, model_id):
    """The memory meter for a chat as it is now (for a chat from before the meter, or right after Compact now)."""
    tok, window, max_new = _meter_parts(state, who, model_id)
    return E.context_meter(E.chat.context_report(tok, state.store(who["user"]).history(chat_id), window, reserve=max_new)["used"], window, max_new)


CASUAL = re.compile(r"\b(?:ya know|y'?know|ngl|tbh|fr|lowkey|highkey|idk|imo|bruh|gonna|wanna|kinda|sorta|lol|lmao|smh|tho|rn|u|ur)\b", re.I)
CASUAL_HINT = ("[They are typing casually (slang, short forms or typos). Work out what they mean and answer that, talking to them as \"you\" "
               "in a relaxed, natural way. Never correct their spelling, never say you did not understand when the meaning can be guessed, and never "
               "talk about them as someone else.]")
# House rules for the Emvryx 3 models until they are retrained on Lessons 4 (flag chat_house_rules): the habits the owner's tests found in Equinox 3
# (Oct 19) - answering something else, claiming what the person never said, flattery, stacks of "!" and emoji, a "use this command" with no command
HOUSE_HINT = ("[How to answer: answer exactly what was just asked, first and directly. Never claim something the person did not say or that you do not "
              "know (for example that something is already installed). No praise or flattery, no emoji unless they use them, and at most one "
              "exclamation mark. Only mention what you remember about them, or other people, when it helps with this message. When you mention a "
              "command, a link or a setting, write it out exactly. If you are not sure of a fact, say so briefly. Never talk about \"the notes\", "
              "\"the search results\" or \"the provided information\": just answer, naming a source in a few words if it helps. When something has not "
              "happened yet or does not exist, say that plainly and add what you do know (for example when the next one is).]")
# chat_fixes, Emvryx 3 models: how an answer is laid out, so it reads like other assistants' answers (the page shows Markdown; LaTeX showed as raw code)
FORMAT_HINT = ("[Layout: answer at the length the question needs (a short question gets a short answer, with no preamble). Use Markdown: code in ``` blocks "
               "with the language name, numbered lists for steps, a table only to compare several things. Write maths as plain text (3/4, x², √2, ×, ÷), never LaTeX.]")
MAX_PICTURES = 3          # at most this many of the chat's pictures go to a model that sees them, with each message


def compact_now(state, who, chat_id, model_id):
    """The "Compact now" button: shorten this chat at once (the same summary the automatic one makes). Returns {"folded", "context"}; folded is 0 when
    the chat is too short to have anything old enough to fold. The new meter reading is kept on the last reply, so it shows when the chat is opened again."""
    store = state.store(who["user"])
    tok, window, max_new = _meter_parts(state, who, model_id)
    folded = chat_polish.compact_chat(tok, store, chat_id, window, max_new, force=True)
    ctx = meter_for(state, who, chat_id, model_id)
    last = next((m for m in reversed(store.messages(chat_id)) if m["role"] == "assistant" and m["status"] != "compacted"), None)
    if last:
        store.set_flag(chat_id, last["id"], "ctx", ctx)
    return {"folded": folded, "context": ctx}


def start_turn(state, who, chat_id, text, model_id, effort, regenerate=False, regen_mode=None, cont=False, pace=None, extra_notes=None, extra_hint="", picture_only=False):
    """Begin a reply in a worker thread. Returns (queue, stop_event); the queue yields ("piece", text), then
    ("done", result) or ("error", exception). With effort "auto" the level is chosen from the message (effort_router);
    the page is told which one in `decision`. The API passes pace=False (no show of thinking), extra_notes (facts the app sends) and extra_hint (the app's instructions)."""
    store = state.store(who["user"])
    model = state.pick_model(who, model_id)
    if model["state"] == "too_big":
        raise ModelTooBig(model, state.ram_gb, None)
    if model["state"] != "ready":
        raise U.LimitError("model_unavailable", f"{model['name']} {model['version']:g}: {model['badge']}.")
    tok = state.tok_for(model)
    if effort != "auto" and effort not in EFFORTS:
        raise U.LimitError("bad_effort", "Pick Auto, Quick, Balanced or Deep.")
    decision = {"effort": effort, "auto": False, "reason": ""}
    question = text
    if regenerate:                                             # the question is the last one already in the chat
        question = next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "user" and m["status"] != "compacted"), "")
    if effort == "auto":
        allowed = tuple(model.get("efforts", effort_router.ORDER))
        pct = 100.0 if who["owner"] else state.usage_snapshot(who, model, "balanced")["tank"]["pct"]
        chosen, why = effort_router.choose_effort(question, allowed, pct, strict=state.flags.on("chat_fixes", who))
        decision = {"effort": chosen, "auto": True, "reason": why}
        effort = chosen
    if effort not in model.get("efforts", effort_router.ORDER):    # a model lists the levels it offers (Ember has no Deep)
        raise U.LimitError("effort_not_available", f"{model['name']} doesn't offer {effort.title()}. Deep needs Flare or a bigger model.",
                           choices=["flare"])
    win = state.window_for(who, model)
    if not win["fits"]:
        raise AppError("There isn't enough free memory for this model.", "Close other apps or pick a smaller model.")
    window = win["window"]
    mode = regen_mode if regenerate else None
    regen_modes.get(mode)                                      # an unknown option is a ValueError (a 400 for the page)
    caps = OPEN_EFFORTS if model.get("open") else EFFORTS
    fixes = state.flags.on("chat_fixes", who)                  # the overnight chat fixes (flag chat_fixes) and the model's own part of them (models.json "fixes")
    tuned = (model.get("fixes") or {}) if fixes else {}
    max_new = min(caps[effort], max(32, window // 2), model.get("max_reply_tokens", caps[effort]))
    if tuned.get("reply_tokens", {}).get(effort):              # more room for a long answer, so it is not cut off and "Continue" is rarely needed
        max_new = min(int(tuned["reply_tokens"][effort]), max(32, window // 2))
    if mode:
        max_new = min(regen_modes.length_for(max_new, mode), max(32, window // 2))
    pause = round(chat_polish.pause_for(question, effort) * chat_polish.PAUSE_SCALE[state.get_settings(who["user"])["thinking_pause"]], 2)   # fits the message, then the person's setting
    if fixes:
        pause = min(pause, chat_polish.FIXES_PAUSE_MAX)          # the models answer fast: a long staged pause only made replies feel slow
    decision["pause"] = pause
    bounds = tuple(model.get("temperature_bounds", effort_router.DEFAULT_BOUNDS))
    base_temp = (tuned.get("sampling") or model.get("sampling", {})).get("temperature", TEMPERATURE["balanced"])
    decision["temperature"] = None                             # None = keep the model's own setting
    if decision["auto"]:                                       # Auto also picks how adventurous the wording is
        decision["temperature"], decision["temperature_reason"] = effort_router.choose_temperature(question, base_temp, bounds)
    think = effort == "deep" and model.get("think") == "empty"   # Deep on a model that can think: it reasons first (hidden), Quick and Balanced answer straight away
    decision["thinking"] = think
    q, stop = queue.Queue(), threading.Event()
    key = (who["user"], chat_id)
    state.stops[key] = stop
    started = time.monotonic()
    counted_model = dict(model, where="online")                # the server runs it, so the person's plan counts it
    if regenerate:
        msgs = [m for m in store.messages(chat_id) if m["status"] != "compacted"]
        if msgs and msgs[-1]["role"] == "assistant":
            store.remove_message(chat_id, msgs[-1]["id"])
        text = None

    skill_hint = "\n\n".join(h for h in (app_skills.custom_hint(state.get_settings(who["user"]).get("custom_instructions")),
                                         app_skills.hint(store.skill(chat_id)),
                                         CONTINUE_HINT if cont else "") if h)   # the person's own preference, then the chat's skill (Study helper ...), then "continue": extra instructions for the model only
    if extra_hint:
        skill_hint = (skill_hint + "\n\n" if skill_hint else "") + extra_hint
    if model.get("think") == "empty" and state.flags.on("chat_house_rules", who):    # an Emvryx 3 model: the house rules on every message
        skill_hint = (skill_hint + "\n\n" if skill_hint else "") + HOUSE_HINT
    if fixes and model.get("think") == "empty":
        skill_hint = (skill_hint + "\n\n" if skill_hint else "") + FORMAT_HINT
    if text and CASUAL.search(text):                          # "Sometimes I overtime ya know": read what they mean, as a friend would
        skill_hint = (skill_hint + "\n\n" if skill_hint else "") + CASUAL_HINT
    library = state.docs_for(who["user"])
    attached = [d for d in (library.info(i) for i in store.docs(chat_id)) if d]     # documents attached to this chat: their passages go in as notes
    sent_before = store.sent_docs(chat_id)                     # pictures and files that went with an earlier message: only new ones go with this one
    if attached:
        seen_by_model = state.sees(model)                      # a model that looks at pictures itself gets them as pictures, not as a document to quote from
        papers = [d["name"] for d in attached if d["kind"] not in documents.IMAGE_KINDS]     # a picture is never a document, whatever reads it
        if papers:
            skill_hint = (skill_hint + "\n\n" if skill_hint else "") + documents.hint(papers)
        if len(papers) < len(attached) and not seen_by_model:
            skill_hint = (skill_hint + "\n\n" if skill_hint else "") + documents.picture_words_hint()
        elif len(papers) < len(attached):
            earlier = not any(d["kind"] in documents.IMAGE_KINDS and d["id"] not in sent_before for d in attached)
            skill_hint = (skill_hint + "\n\n" if skill_hint else "") + documents.picture_hint(picture_only, earlier=earlier and not regenerate)
    timing = {}

    def timed(stream):
        """Notes when the model's first word arrives (before the pause and the steady writing are added)."""
        for piece in stream:
            timing.setdefault("first", time.monotonic())
            yield piece

    def pacer(stream):
        stream = timed(stream)
        gen = chat_polish.paced(stream, min_first_s=pause, start=started, adaptive=fixes) if (state.pace if pace is None else pace) else stream
        try:
            for bit in gen:
                q.put(("piece", bit))
                yield bit
        finally:
            close = getattr(gen, "close", None)
            if close:
                close()

    def work():
        nonlocal skill_hint, think
        try:
            if state.runner and not state.runner.ready(model["id"], window):
                q.put(("loading", model["name"]))
            notes, found = None, None
            mem_note = None
            asked_id = text or next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "user"), "")
            canned = identity_answer.answer(asked_id) if not attached else None      # "who are you?": the app answers in the owner's words, no model, no web search
            if chat_id >= 0 and state.get_settings(who["user"])["memory"]:         # what the app knows about this person: the same for every model
                memory = state.memory_for(who["user"])
                if text:
                    learned = memory.learn("" if text in (documents.PICTURE_ONLY_TEXT, documents.FILE_ONLY_TEXT) else text)
                    if learned["saved"] or learned["forgot"]:
                        q.put(("memory", learned))
                asked = text
                if not asked:                                                       # a regenerate: the question is the last thing they said
                    last = [m for m in store.messages(chat_id) if m["role"] == "user"]
                    asked = last[-1]["content"] if last else ""
                mem_note = memory.note(asked)
                voice = memory.style_hint()                                         # "no emojis", "talk normal": how every reply should sound
                if voice:
                    skill_hint = voice + ("\n\n" + skill_hint if skill_hint else "")
                past = store.recall(asked, exclude_chat=chat_id)                   # "what did I tell you last time about...": earlier chats, archived ones too
                if past:
                    mem_note = (mem_note + "\n\n" + past) if mem_note else past
            doc_notes = []
            seen_pictures = []                                                     # base64 pictures for a model that can see (state.sees)
            pictures = {"looked": 0, "read": 0}
            if attached:                                                           # the question is about the documents: no Wikipedia or web notes to distract
                asked_doc = text or next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "user"), "")
                described, picture_notes = set(), []
                helper = state.vision if (state.vision and state.vision.available()) else None
                own_eyes = state.sees(model)                                       # an Emvryx 3 model looks at the picture itself
                for d in attached:
                    if d["kind"] not in documents.IMAGE_KINDS:
                        continue
                    pictures["read"] += 1
                    if own_eyes and len(seen_pictures) < MAX_PICTURES:                # it keeps seeing the chat's pictures on later messages too (like other chat apps), not their words as a document
                        img = library.image(d["id"])
                        if img:
                            seen_pictures.append(base64.b64encode(img[0]).decode("ascii"))
                            described.add(d["id"]); pictures["looked"] += 1
                            continue
                    img = library.image(d["id"]) if helper else None
                    if not img:
                        continue
                    try:
                        q.put(("loading", "the picture reader")) if not helper.proc and not helper.fixed_url else None
                        picture_notes.append({"title": "Picture: " + d["name"], "text": helper.describe(d["id"], img[0], img[1], asked_doc)})
                        described.add(d["id"]); pictures["looked"] += 1
                    except RuntimeError as e:
                        sys.stderr.write(f"vision: {e}\n")
                rest = [d["id"] for d in attached if d["id"] not in described]
                doc_notes = picture_notes + (documents.notes_for(library, rest, asked_doc, budget=int(min(24000, max(3000, window * 3.5 * 0.45)))) if rest else [])
                unreadable = [d["name"] for d in attached if d["id"] not in described and (not (library.text(d["id"]) or "").strip() or (library.text(d["id"]) or "").startswith(documents.PICTURE_ONLY))]      # nothing could be read from it (a scan, a photo with no text)
                if unreadable:                                                     # say so, instead of letting the model answer around it
                    shown = ", ".join(f'"{n}"' for n in unreadable[:3])
                    doc_notes.append({"title": "Could not read: " + ", ".join(unreadable[:3]),
                                      "text": f"No text could be read from {shown} (it has no readable text, and the picture reader is not available). Tell the person you could not read it "
                                              "and ask them to type out the part they mean. Do not guess what it says."})
                if pictures["read"] or unreadable:
                    q.put(("notes", {"asked": True, "saved": 0, "wiki": 0, "web": 0, "web_tried": False, "recent": False, "live": 0, "names": [], "sources": [],
                                     "pictures": pictures["looked"], "ocr": pictures["read"] - pictures["looked"], "unreadable": unreadable}))
            live_notes = []
            live_mode = state.get_settings(who["user"])["web_search"]
            if not attached and not canned and live_mode != "none" and state.get_settings(who["user"]).get("live_data", True):
                asked_live = text or next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "user"), "")
                live_notes, live_found = live_data.gather(asked_live, state.clock(), online=(live_mode in ("auto", "always") and chat_id >= 0), net=state.live_net,
                                                          default_place=state.default_place)
                if live_notes:                                                     # exact facts (a sum, a date, a price): no Wikipedia or web notes needed
                    q.put(("notes", dict(live_found, saved=0, wiki=0, web=0, web_tried=False, recent=False)))
            app_notes = []
            if (chat_id >= 0 and not attached and not canned and live_mode != "none" and state.get_settings(who["user"]).get("connected_apps", True)
                    and state.links.store.connected(who["user"])):                  # the person's own connected apps (calendar, notes, tasks...): only when the question is about them
                asked_app = text or next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "user"), "")
                app_notes, app_found = state.links.gather(who["user"], asked_app, state.usage.get_user(who["user"]).get("tz_minutes", 0))
                if app_notes:
                    q.put(("notes", {"asked": True, "saved": 0, "wiki": 0, "web": 0, "web_tried": False, "recent": False, "live": 0, "names": [], "sources": [], "apps": app_found["apps"],
                                     "app_errors": app_found["errors"]}))
            earlier = [m["content"] for m in store.messages(chat_id) if m["role"] == "user"]      # what was asked before: a follow-up ("how many has he scored?") needs it to be searched
            if text and not attached and not canned and not live_notes and not app_notes:         # Auto lookup (lookup_auto.py)
                web_mode = state.get_settings(who["user"])["web_search"]
                ordered = lookup_auto.asks_for_web(text)                           # "look online", "check again": an order, so the web is searched whatever the rules say
                notes, found = lookup_auto.gather(lookup_auto.search_query(text, earlier), state.wiki, state.web_fn, web_mode, private=chat_id < 0,
                                                  max_notes=5 if window >= 6000 else 3, force_web=ordered, force_notes=ordered,
                                                  saved=state.saved_for(who["user"]), now=state.clock(), policy=model.get("lookup", "always"))
                if found["asked"]:
                    import web_search
                    q.put(("notes", {k: v for k, v in found.items() if k != "used"} | ({"web_source": web_search.pick_source("auto")} if found.get("recent") else {})))
            if doc_notes:
                notes = doc_notes + list(notes or [])
            if live_notes:
                notes = [{"title": n["title"], "text": n["text"]} for n in live_notes] + list(notes or [])
            if app_notes:
                notes = list(app_notes) + list(notes or [])
            if extra_notes:                                                        # facts an app sent with its question: the answer must come from these
                notes = list(extra_notes) + list(notes or [])
            today = lookup_auto.date_note(text or (store.messages(chat_id)[-1]["content"] if regenerate and store.messages(chat_id) else ""), state.clock())
            if today:                                                              # "what day is Christmas this year": the model has no clock
                notes = [today] + list(notes or [])
            if mem_note:
                notes = [mem_note] + list(notes or [])
            if think and (live_notes or (found and found.get("asked") and (found.get("web") or found.get("wiki")))):
                think = False          # Deep with looked-up facts: the answer is in the notes, so it answers from them at once instead of thinking at length first
            t_load = time.monotonic()
            timing["lookup"], timing["thought"] = t_load - started, think      # everything before the model: notes, Wikipedia, the web, pictures
            backend = E.FakeBackend(canned) if canned else state.backend_for(model, text or "", window, cancel=stop.is_set)     # may load the model the first time (can take a while); Stop ends the load
            timing["load"] = time.monotonic() - t_load
            if tuned.get("sampling") and hasattr(backend, "sampling"):     # the settings the base model's makers give (no strong repeat penalty: it bent code and names)
                backend.sampling = dict(backend.sampling, **tuned["sampling"])
            if fixes and hasattr(backend, "timeout"):
                backend.timeout = max(backend.timeout, 300)            # a very long chat can take minutes to read before the first word: that is not "can't reach the PC"
            if decision["temperature"] is not None and hasattr(backend, "sampling"):
                backend.sampling = dict(backend.sampling, temperature=decision["temperature"])
            if regenerate and hasattr(backend, "sampling"):
                t = regen_modes.sampling_for(backend.sampling.get("temperature", 0.8), mode)
                backend.sampling = dict(backend.sampling, temperature=round(min(bounds[1], max(bounds[0], t)), 2))   # never outside the model's safe range
            if think and (tuned.get("sampling_think") or model.get("sampling_think")) and hasattr(backend, "sampling"):     # Deep on an Emvryx 3 model: the settings Qwen gives for thinking
                backend.sampling = dict(backend.sampling, **(tuned.get("sampling_think") or model["sampling_think"]))
            prior_reply = next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "assistant"), "")      # to notice a reply that is only a copy of this one
            first_hint = "\n\n".join(h for h in (skill_hint, regen_modes.get(mode)["hint"] if regenerate else "",
                                                  "" if regenerate else (chat_polish.answer_hint(text, next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "assistant"), ""))
                                                                               or chat_polish.follow_up_hint(text, any(m["role"] == "assistant" for m in store.messages(chat_id))))) if h)

            def first(backend, again=False):
                return E.run_turn(tok, store, chat_id, backend, counted_model, window, max_new, pictures=seen_pictures or None, user_text=None if again else text, stop=stop,
                                  notes=notes or None, user_docs=None if again else ([d["id"] for d in attached if d["id"] not in sent_before] if text else None),
                                  limiter=state.limiter, user=who["user"], effort=effort, clock=state.clock, pacer=pacer, think=think,
                                  on_compact=lambda: q.put(("compacting", True)), style_hint=first_hint, fixes=fixes)
            try:
                r = first(backend)
            except ModelRefused as e:
                # A model with guess-ahead on can turn down a message with a picture: load it without guess-ahead and answer the same message once more.
                # (Not for a prompt it could not read: that is not about guess-ahead, and reloading would only cost time.)
                if "tokeniz" in e.reason.lower() or not (seen_pictures and state.runner and state.runner.drop_draft(model["id"])):
                    raise
                msgs = [m for m in store.messages(chat_id) if m["status"] != "compacted"]
                if msgs and msgs[-1]["role"] == "assistant" and not msgs[-1]["content"]:
                    store.remove_message(chat_id, msgs[-1]["id"])
                q.put(("loading", model["name"]))
                again = state.backend_for(model, text or "", window)
                if hasattr(backend, "sampling") and hasattr(again, "sampling"):
                    again.sampling = dict(backend.sampling)                          # the same settings as the first try
                r = first(again, again=True)
            if fixes and not canned and not stop.is_set() and not (r.get("text") or "").strip():
                # Nothing came out (it spent the whole reply thinking, or stopped at once): take the empty reply back and answer straight away, once.
                msgs = [m for m in store.messages(chat_id) if m["status"] != "compacted"]
                if msgs and msgs[-1]["role"] == "assistant":
                    store.remove_message(chat_id, msgs[-1]["id"])
                timing["tries"] = timing.get("tries", 1) + 1
                r = E.run_turn(tok, store, chat_id, backend, counted_model, window, max_new, pictures=seen_pictures or None, user_text=None, stop=stop, notes=notes or None,
                               limiter=state.limiter, user=who["user"], effort=effort, clock=state.clock, pacer=pacer, think=False, on_compact=lambda: q.put(("compacting", True)),
                               style_hint=first_hint, fixes=fixes)
            if text and not canned and not regenerate and not stop.is_set() and r.get("reason") in ("done", None) and chat_polish.is_repeat(r["text"], prior_reply):
                # A small model answered its own last message again. Take that reply back and ask once more, firmly, a little less predictably.
                msgs = [m for m in store.messages(chat_id) if m["status"] != "compacted"]
                if msgs and msgs[-1]["role"] == "assistant":
                    store.remove_message(chat_id, msgs[-1]["id"])
                if hasattr(backend, "sampling"):
                    backend.sampling = dict(backend.sampling, temperature=round(min(1.0, backend.sampling.get("temperature", 0.8) + 0.2), 2),
                                            repeat_penalty=max(1.3, backend.sampling.get("repeat_penalty", 1.15)))
                r = E.run_turn(tok, store, chat_id, backend, counted_model, window, max_new, pictures=seen_pictures or None, user_text=None, stop=stop, notes=notes or None,
                               limiter=state.limiter, user=who["user"], effort=effort, clock=state.clock, pacer=pacer, think=think, on_compact=lambda: q.put(("compacting", True)),
                               style_hint="\n\n".join(h for h in (skill_hint, chat_polish.repeat_hint(text)) if h), fixes=fixes)
            web_mode_now = state.get_settings(who["user"])["web_search"]
            knowledge_first = (model.get("lookup") == "when_needed" and found is not None and not found["asked"] and bool(text) and not regenerate
                               and web_mode_now != "none" and lookup_auto.wants_lookup(text))
            old_way = (found and found["asked"] and not regenerate and not found["web_tried"] and state.web_fn is not None and
                       web_mode_now not in ("off", "none") and chat_id >= 0)
            pretended = bool(text and not regenerate and chat_id >= 0 and state.web_fn is not None and web_mode_now not in ("off", "none")
                             and not (found and found.get("web")) and lookup_auto.pretends_to_search(r["text"]))      # it wrote "checking online" but no search ran: do the real one
            if not stop.is_set() and (((old_way or knowledge_first) and lookup_auto.gave_up(r["text"])) or pretended):     # never a second try after Stop
                # The model said it doesn't know. Old way: the web has not been tried, so search it. The second answer comes straight from the notes,
                # without Deep's thinking again (thinking twice was most of the wait on looked-up questions). Knowledge-first models (Qwen) had no notes yet:
                # look it up now. Then answer again (the second chance).
                notes2, found2 = lookup_auto.gather(lookup_auto.search_query(text, earlier, force=pretended), state.wiki, state.web_fn, "always" if (old_way or pretended) else web_mode_now, private=(chat_id < 0 and knowledge_first),
                                                    max_notes=5 if window >= 6000 else 3, saved=state.saved_for(who["user"]),
                                                    now=state.clock(), force_web=True, force_notes=True)
                if found2["web"] or (knowledge_first and (found2["wiki"] or found2["saved"])):
                    q.put(("notes", {k: v for k, v in found2.items() if k != "used"} | {"retry": True}))
                    timing["tries"] = timing.get("tries", 1) + 1
                    msgs = [m for m in store.messages(chat_id) if m["status"] != "compacted"]
                    if msgs and msgs[-1]["role"] == "assistant":
                        store.remove_message(chat_id, msgs[-1]["id"])
                    r = E.run_turn(tok, store, chat_id, backend, counted_model, window, max_new, pictures=seen_pictures or None, user_text=None, stop=stop, notes=([mem_note] if mem_note else []) + list(notes2 or []),
                                   limiter=state.limiter, user=who["user"], effort=effort, clock=state.clock, pacer=pacer, think=False, on_compact=lambda: q.put(("compacting", True)), style_hint=skill_hint, fixes=fixes)
                    found = found2
            if found and found["asked"] and text:
                state.remember_lookup(who["user"], chat_id, r["message_id"], text, found)
            if text and store.title(chat_id) == "New chat":
                store.set_title(chat_id, "Picture" if picture_only else attached[0]["name"][:48] if text == documents.FILE_ONLY_TEXT and attached else (chat_polish.short_title(text) if fixes else (" ".join(text.split())[:48] or "New chat")))
            end = time.monotonic()                              # where the time went, for the owner and admins (shown under the reply)
            r["timing"] = {"lookup": round(timing.get("lookup", 0), 1), "load": round(timing.get("load", 0), 1),
                           "first_word": round(timing.get("first", end) - started, 1), "total": round(end - started, 1),
                           "tries": timing.get("tries", 1), "thought": bool(timing.get("thought")), "chars": len(r.get("text") or "")}
            q.put(("done", r))
            if state.verbose:                                  # numbers only, never any text
                end = time.monotonic()
                first = timing.get("first", end) - started
                sys.stderr.write(f"reply: {model['id']} load={timing.get('load', 0):.1f}s model_first_word={first:.1f}s "
                                 f"total={end - started:.1f}s chars={len(r['text'])} window={window}\n")
        except Cancelled:                                       # Stop pressed while the model was still loading
            q.put(("error", AppError("Stopped before the answer started.", "Send it again when you are ready.")))
        except BaseException as e:                              # sent to the page as an error event
            q.put(("error", e))
        finally:
            state.stops.pop(key, None)

    threading.Thread(target=work, daemon=True).start()
    return q, stop, model, win, decision


def model_guard_tests(path):
    import quality_check
    return quality_check.load_sheet(path)
