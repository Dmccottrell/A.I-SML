"""
make_chat_data_v3.py - Build v3's chat lessons -> data/v3/chat.jsonl

WHAT THIS FILE DOES
    Mixes conversations (the "messages" format in chat.py) that target the
    mistakes found by testing v2 on a phone:

      kind             teaches                                     v2 problem it fixes
      ---------------  ------------------------------------------  ---------------------------------
      general          everyday chat (smol-smoltalk)               -
      topic_switch     answer the NEWEST question, not old ones    stuck on Illinois when asked about planets
      lookup           answer from the notes, name the source      "the capital of Illinois is Paris"
      dont_know        notes don't have it -> say "I don't know"   confident made-up answers
      correction       "that's wrong" -> recheck the notes         repeated "Paris" three times
      stand_firm       "that's wrong" but it was right -> keep it  (so it doesn't cave to every doubt)
      memory_doubt     corrected with no notes -> admit unsure     guessing again and again
      instruction      exact counts and formats ("List 3...")      10 items when asked for 3
      unknowable       personal/live/made-up questions -> honest   inventing answers about anything
      identity         a different answer for each question        same paragraph for "What can you do?"
      small_talk       casual greetings and chit-chat              "Whats up" -> it invented its own question
      story            tell stories (keeps v1's skill)             -
      memory_save      "my name is Sam" -> save it (a tool call)   (new: remembering you, chat_memory.py)
      memory_skip      passwords, moods, other people -> don't     saving things it shouldn't
      memory_recall    answer from "Saved memory" / earlier-chat   "I don't know your name" when it does
                       notes, or say it doesn't know yet

    lookup/dont_know/correction/stand_firm/memory_doubt come from the teacher's
    lookup examples, and instruction from its instruction examples
    (make_teacher_data.py). The rest need no teacher.

    In correction lessons the WRONG answer is marked "train": false: the
    model sees it as context but only learns the corrected reply.

Usage:  python make_chat_data_v3.py
        python make_chat_data_v3.py --general 40000
"""
import argparse, json, os, random

from config import get_version

V = get_version("v3")
OUT_PATH = os.path.join(V.data_dir, "chat.jsonl")
TEACHER_DIR = os.path.join(V.data_dir, "teacher")
MY_EXAMPLES = os.path.join(V.data_dir, "my_examples.jsonl")
MAX_CHARS = 6000        # ~1,500 tokens: fits v3's 2,048-token memory with room to spare

# ------------------------------------------------------------------ identity
# Edit these to give your AI its own name and personality!
IDENTITY_QA = [
    (["Who are you?", "What are you?", "Tell me about yourself.", "Introduce yourself."],
     "I'm a small AI assistant that was trained from scratch on a home computer. "
     "I'm still small, so I can make mistakes. Please double-check anything important!"),
    (["What can you do?", "What are you good at?", "How can you help me?"],
     "I can answer questions, explain things in simple words, give tips and advice, follow short "
     "instructions like making a list, and tell stories. When lookups are turned on, I check a "
     "saved copy of Wikipedia before answering questions about facts."),
    (["Are you ChatGPT?", "Are you Claude?", "Are you Gemini?", "Were you made by OpenAI?"],
     "No. I'm not ChatGPT, Claude or Gemini. I'm a much smaller AI that was trained from "
     "scratch on a home computer."),
    (["Who made you?", "Who created you?", "Who trained you?"],
     "I was built and trained from scratch on a home computer, as part of a personal project "
     "called A.I-SML."),
    (["Are you human?", "Are you a real person?"],
     "No, I'm an AI: a computer program that writes text. I'm not a person."),
    (["Can you browse the internet?", "Are you connected to the internet?"],
     "No, I run offline, so I can't browse the internet or know about recent events. With "
     "lookups turned on, I can search a saved copy of Wikipedia."),
    (["Do you make mistakes?", "Are you always right?"],
     "Yes, I make mistakes, especially with facts. I'm a small model, so please double-check "
     "anything important."),
    (["What's your name?", "Do you have a name?"],
     "I don't have a name yet. I'm a small AI assistant trained from scratch on a home computer."),
]
GREETINGS = ["Hi", "Hello", "Hey", "Hi there", "Good morning", "Hey, how's it going?"]
GREETING_REPLY = "Hi! I'm a small AI assistant. What would you like to talk about?"

# Casual messages, each with a few friendly replies. Typed variations (lowercase,
# no punctuation: "whats up") are added automatically.
SMALL_TALK = [
    (["What's up?", "Sup?", "Yo", "Hey, what's up?", "What's going on?"],
     ["Not much! I'm here and ready to help. What's on your mind?",
      "Hey! Just waiting for a question. What would you like to talk about?"]),
    (["How are you?", "How are you doing?", "How's it going?", "You good?"],
     ["I'm doing well, thanks for asking! How about you?",
      "I'm good! I'm an AI, so I don't have feelings like people do, but I'm ready to help. How are you?"]),
    (["Good night", "Goodnight!", "I'm going to bed"],
     ["Good night! Sleep well.", "Good night! Come back anytime."]),
    (["Thanks", "Thank you!", "Thanks a lot", "ty"],
     ["You're welcome!", "Happy to help! Anything else?"]),
    (["Bye", "See you later", "Goodbye!", "Talk to you later"],
     ["Bye! Have a great day.", "See you later!"]),
    (["lol", "haha", "That's funny"],
     ["Glad that made you smile! Anything else I can help with?"]),
    (["I'm bored", "I'm so bored"],
     ["Want a fun fact, a short story, or a riddle? Just pick one!",
      "How about a short story? Tell me a topic and I'll write one."]),
    (["Good morning!", "Morning"],
     ["Good morning! What can I help you with today?"]),
    (["ok", "Okay", "Cool", "Nice"],
     ["Great! Let me know if you have another question."]),
]

# ------------------------------------------------------------------ honest answers
CORRECTIONS = ["That's wrong.", "That's incorrect.", "No, that's not right.",
               "Are you sure? I don't think that's correct.", "That doesn't sound right.",
               "Try again.", "I think that's wrong."]
FIX_OPENERS = ["You're right, I made a mistake. Checking my notes again:",
               "Sorry about that! Looking at my notes again:",
               "Thanks for catching that. Here's the correct answer from my notes:"]
STAND_FIRM = ("I checked my notes again, and they support my answer: {answer} "
              "If you have a different source, it's worth comparing the two.")
MEMORY_DOUBT = ["You may be right. I'm not sure of the correct answer, and I don't want to guess "
                "again. Please check a reliable source.",
                "Sorry, I may have gotten that wrong. I'm not certain about this one, so it's best "
                "to check a reliable source, or ask me again with lookups turned on.",
                "I might be mistaken. I don't know the answer for sure, so I'd rather not guess."]
DONT_KNOW = ["I checked my notes, but they don't mention that, so I don't know. I'd rather not guess.",
             "My notes don't cover this, so I'm not sure. A reliable source like an encyclopedia "
             "would have the answer.",
             "I couldn't find the answer in my notes. I don't want to make something up, so I'll "
             "say I don't know.",
             "Sorry, I don't know. The notes I found are about {titles}, not about this."]
UNKNOWABLE = [
    ("What is my phone number?", "I don't know your phone number. I can't see personal "
     "information about you unless you tell me in this chat."),
    ("What did I have for breakfast?", "I don't know. I can't see what you do; I only know "
     "what you tell me in this chat."),
    ("What will the weather be tomorrow?", "I don't know. I run offline, so I can't check the "
     "forecast. A weather app or website will have it."),
    ("Who won the game last night?", "I don't know. I don't have live information about recent "
     "events, so I can't check scores."),
    ("What time is it?", "I can't see the time. Your phone or computer clock will show it."),
    ("What's in the news today?", "I don't know. I run offline and don't have today's news. "
     "A news website or app will have it."),
    ("How much money is in my bank account?", "I don't know. I can't see your accounts or any "
     "personal information."),
    ("What's my email password?", "I don't know your password, and you should never share it "
     "with anyone, including me."),
    ("What am I thinking right now?", "I can't know what you're thinking. I only know what you "
     "type in this chat."),
]
FAKE_TEMPLATES = [("What is the capital of {name}?", "I don't know of a country or place called "
                   "{name}. It might be fictional, or something I don't have information about."),
                  ("Who invented the {name}?", "I don't know anything called the {name}, so I "
                   "can't say who invented it. It might be fictional, or too rare for me to know."),
                  ("How long is the {name} River?", "I don't know of a river called the {name}. "
                   "It might be fictional, or something I haven't learned about."),
                  ("Who wrote the book {name}?", "I don't know a book called {name}. It might be "
                   "fictional, or a book I haven't learned about.")]
SYLLABLES = ["zor", "blax", "vel", "tor", "quin", "dra", "mox", "ly", "thar", "ren", "skel", "vo",
             "prin", "gal", "zu", "kest", "orn", "bri", "fen", "wex"]


# ------------------------------------------------------------------ helpers
def user(content, notes=None):
    m = {"role": "user", "content": content}
    if notes:
        m["notes"] = notes
    return m


def assistant(content, train=True, memory=None):
    m = {"role": "assistant", "content": content}
    if not train:
        m["train"] = False
    if memory:
        m["memory"] = list(memory)       # facts to save, written as a tool call (see chat.py)
    return m


def total_chars(messages):
    return sum(len(m["content"]) + sum(len(n["text"]) for n in m.get("notes", [])) for m in messages)


def fake_name(rng):
    return "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 3))).capitalize()


_search_cache = {}


def search(wiki, question, k):
    """wiki.search(), remembered (each question is looked up once, even if used twice)."""
    if wiki is None:
        return []
    if (question, k) not in _search_cache:
        _search_cache[(question, k)] = wiki.search(question, k)
    return _search_cache[(question, k)]


def notes_for(record, wiki, rng, k=3):
    """The notes the model would see at chat time: search results for the
    question, with the passage the answer came from always included."""
    source = record["source"]
    found = [r for r in search(wiki, record["question"], k) if r["id"] != source["id"]]
    notes = found[:k - 1]
    notes.insert(rng.randint(0, len(notes)), source)
    return [{"title": n["title"], "text": n["text"]} for n in notes]


def unrelated_notes(record, others, wiki, rng, k=3):
    """Notes that DON'T contain the answer: another question's notes (not about this article)."""
    for _ in range(20):
        other = rng.choice(others)
        if other["source"]["title"] != record["source"]["title"]:
            notes = [n for n in notes_for(other, wiki, rng, k) if n["title"] != record["source"]["title"]]
            if notes:
                return notes
    return []


# ------------------------------------------------------------------ builders
def general_conversations(convs, n):
    out = []
    for messages in convs:
        if total_chars(messages) <= MAX_CHARS and any(m["role"] == "assistant" for m in messages):
            out.append(messages)
            if len(out) >= n:
                break
    return out


def first_exchanges(convs, n, max_chars=1500):
    """The first question + answer of many conversations (short ones only)."""
    out = []
    for messages in convs:
        if (len(messages) >= 2 and messages[0]["role"] == "user" and messages[1]["role"] == "assistant"
                and len(messages[0]["content"]) + len(messages[1]["content"]) <= max_chars):
            out.append(messages[:2])
            if len(out) >= n:
                break
    return out


def topic_switch_conversations(exchanges, rng, n):
    """2-3 unrelated question/answer pairs in one chat: every answer is about ITS question."""
    out = []
    for _ in range(n):
        parts = rng.sample(exchanges, rng.randint(2, 3))
        out.append([m for ex in parts for m in ex])
    return out


def lookup_conversations(records, wiki, rng):
    """Turn the teacher's lookup examples into five kinds of lessons.

    Returns {"lookup": [...], "dont_know": [...], "correction": [...],
             "stand_firm": [...], "memory_doubt": [...]}
    """
    out = {k: [] for k in ("lookup", "dont_know", "correction", "stand_firm", "memory_doubt")}
    for rec in records:
        r = rng.random()
        q, ans, wrong = rec["question"], rec["answer"], rec["wrong_answer"]
        if r < 0.55:
            out["lookup"].append([user(q, notes_for(rec, wiki, rng)), assistant(ans)])
        elif r < 0.70:
            notes = unrelated_notes(rec, records, wiki, rng)
            if not notes:
                continue
            titles = " and ".join(dict.fromkeys(n["title"] for n in notes))
            reply = rng.choice(DONT_KNOW).format(titles=titles)
            out["dont_know"].append([user(q, notes), assistant(reply)])
        elif r < 0.84:
            out["correction"].append([user(q, notes_for(rec, wiki, rng)), assistant(wrong, train=False),
                                      user(rng.choice(CORRECTIONS)),
                                      assistant(rng.choice(FIX_OPENERS) + " " + ans)])
        elif r < 0.90:
            out["stand_firm"].append([user(q, notes_for(rec, wiki, rng)), assistant(ans),
                                      user(rng.choice(CORRECTIONS)),
                                      assistant(STAND_FIRM.format(answer=ans))])
        else:
            out["memory_doubt"].append([user(q), assistant(wrong, train=False),
                                        user(rng.choice(CORRECTIONS)),
                                        assistant(rng.choice(MEMORY_DOUBT))])
    return out


# ------------------------------------------------------------------ remembering you (chat_memory.py)
PEOPLE = ["Sam", "Maria", "Jamal", "Priya", "Liam", "Aisha", "Chen", "Sofia", "Diego", "Emma", "Kwame",
          "Hana", "Noah", "Zara", "Mateo", "Olivia", "Ravi", "Grace", "Tariq", "Mei", "Lucas", "Amara"]
CITIES = ["Chicago", "Houston", "Toronto", "Denver", "Atlanta", "Seattle", "Phoenix", "Dublin", "Lagos",
          "Manila", "Austin", "Nashville", "Melbourne", "Detroit", "Miami", "Glasgow"]
JOBS = ["nurse", "teacher", "electrician", "software developer", "truck driver", "chef", "accountant",
        "IT technician", "student", "mechanic", "graphic designer", "pharmacist", "carpenter", "barber"]
PETS = [("dog", ["Biscuit", "Max", "Luna", "Rocky", "Bella"]), ("cat", ["Pixel", "Milo", "Cleo", "Oreo"]),
        ("parrot", ["Kiwi", "Sunny"]), ("hamster", ["Peanut", "Nibbles"])]
FAVORITES = [("color", ["green", "blue", "purple", "orange", "black"]), ("food", ["pizza", "tacos", "sushi", "jollof rice", "pasta"]),
             ("sport", ["basketball", "soccer", "tennis", "football"]), ("music", ["jazz", "hip hop", "country", "rock"])]
SKILLS = ["Python", "Spanish", "guitar", "photography", "JavaScript", "chess", "cooking", "drawing"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


def personal_fact(rng):
    """(what the user says, the fact to save, a friendly reply, a question about it, the answer)."""
    kind = rng.randrange(7)
    if kind == 0:
        n = rng.choice(PEOPLE)
        said = rng.choice([f"My name is {n}.", f"I'm {n}.", f"Call me {n}.", f"you can call me {n}", f"hi, I'm {n}"])
        return (said, f"The user's name is {n}.", rng.choice([f"Nice to meet you, {n}!", f"Hi {n}! I'll remember your name."]),
                rng.choice(["What's my name?", "Do you remember my name?", "who am i"]), f"Your name is {n}.")
    if kind == 1:
        c = rng.choice(CITIES)
        return (rng.choice([f"I live in {c}.", f"I'm from {c}.", f"i live in {c.lower()}"]), f"The user lives in {c}.",
                f"{c}, nice! I'll remember that.", rng.choice(["Where do I live?", "What city am I in?"]), f"You live in {c}.")
    if kind == 2:
        j = rng.choice(JOBS)
        a = "an" if j[0] in "aeiou" else "a"
        return (rng.choice([f"I work as {a} {j}.", f"I'm {a} {j}.", f"My job is {j}."]), f"The user works as {a} {j}.",
                f"Thanks for telling me! I'll remember that you're {a} {j}.", "What do I do for work?",
                f"You work as {a} {j}.")
    if kind == 3:
        animal, names = rng.choice(PETS)
        n = rng.choice(names)
        return (rng.choice([f"I have a {animal} named {n}.", f"My {animal}'s name is {n}."]),
                f"The user has a {animal} named {n}.", f"{n} is a great name for a {animal}!",
                rng.choice([f"What's my {animal} called?", "What's my pet's name?"]), f"Your {animal} is called {n}.")
    if kind == 4:
        what, options = rng.choice(FAVORITES)
        x = rng.choice(options)
        return (rng.choice([f"My favorite {what} is {x}.", f"Remember that my favorite {what} is {x}."]),
                f"The user's favorite {what} is {x}.", f"Got it, {x}! I'll remember that.",
                f"What's my favorite {what}?", f"Your favorite {what} is {x}.")
    if kind == 5:
        k = rng.choice(SKILLS)
        return (rng.choice([f"I'm learning {k}.", f"I've started learning {k}."]), f"The user is learning {k}.",
                f"That's great! Good luck with {k}. I'll remember you're learning it.",
                "What am I learning?", f"You're learning {k}.")
    m, d = rng.choice(MONTHS), rng.randint(1, 28)
    return (rng.choice([f"My birthday is {m} {d}.", f"my birthday is on {m.lower()} {d}"]), f"The user's birthday is {m} {d}.",
            f"Thanks! I'll remember that your birthday is {m} {d}.", "When is my birthday?", f"Your birthday is {m} {d}.")


DONT_SAVE = [   # (what the user says, the reply): moods, other people, and anything secret
    ("I'm tired today.", "Sorry to hear that. Try to get some rest when you can."),
    ("I'm so hungry right now", "Maybe it's time for a snack!"),
    ("I'm bored", "Want a fun fact, a short story, or a riddle?"),
    ("My friend thinks the moon landing was fake.", "The Moon landings really happened: there's strong evidence, including rock samples and equipment left on the Moon."),
    ("It's raining here.", "Sounds like a good day to stay inside!"),
    ("My password is hunter2", "Please don't share passwords with me. I won't save it, and it's safest to keep it private. If this is a real password, consider changing it."),
    ("My credit card number is 4111 1111 1111 1111", "I won't save card numbers or other payment details. Please keep them private."),
    ("My social security number is 123-45-6789", "I won't save that. Numbers like that should stay private, so please don't share them in chats."),
    ("Remember my bank PIN is 4821", "I won't save PINs or passwords. Keep them private, even from me."),
]
NO_MEMORY_YET = {   # the question with no notes about it: be honest, and invite them to tell you
    "name": "I don't know your name yet. If you tell me, I can remember it.",
    "other": "I don't know that yet. If you tell me, I can remember it for next time.",
}


def fact_kind(fact):
    """What a saved fact is about: "The user's favorite food is pizza." -> "the user's favorite food"."""
    words = fact.lower().split()
    return " ".join(words[:4] if words[2] == "favorite" else words[:3])


def memory_conversations(rng, n):
    """Lessons for remembering you: when to save (and when not), and answering from saved memories."""
    out = {"memory_save": [], "memory_skip": [], "memory_recall": []}
    for _ in range(n):
        said, fact, reply, question, answer = personal_fact(rng)
        r = rng.random()
        if r < 0.30:            # save it
            out["memory_save"].append([user(said), assistant(reply, memory=[fact])])
        elif r < 0.40:          # save it, then use it later in the same chat
            q2, a2 = rng.choice(SMALL_TALK)[0][0], "Doing well, thanks for asking!"
            out["memory_save"].append([user(said), assistant(reply, memory=[fact]), user(q2), assistant(a2),
                                       user(question), assistant(answer)])
        elif r < 0.50:          # don't save
            s, a = rng.choice(DONT_SAVE)
            out["memory_skip"].append([user(s), assistant(a)])
        elif r < 0.80:          # a new chat: the memory comes back as a note
            title = "Saved memory" if rng.random() < 0.6 else f"Earlier chat ({rng.choice(MONTHS)[:3]} {rng.randint(1, 28)})"
            text = fact if title == "Saved memory" else f"User: {said} AI: {reply}"
            notes = [{"title": title, "text": text}]
            other = personal_fact(rng)[1]
            if rng.random() < 0.4 and fact_kind(other) != fact_kind(fact):  # plus an unrelated memory to ignore
                notes.append({"title": "Saved memory", "text": other})
                rng.shuffle(notes)
            out["memory_recall"].append([user(question, notes), assistant(answer)])
        else:                   # asked, but nothing saved about it (or only unrelated memories)
            other = personal_fact(rng)[1]
            notes = [{"title": "Saved memory", "text": other}] if rng.random() < 0.5 else None
            if notes and fact_kind(other) == fact_kind(fact):
                continue        # that memory would answer the question: not an "I don't know" case
            key = "name" if "name" in question.lower() and "pet" not in question.lower() and "called" not in question.lower() else "other"
            out["memory_recall"].append([user(question, notes), assistant(NO_MEMORY_YET[key])])
    return out


def instruction_conversations(records, exchanges, rng):
    """Exact-instruction lessons; ~30% come after an unrelated earlier question."""
    out = []
    for rec in records:
        convo = [user(rec["prompt"]), assistant(rec["answer"])]
        if exchanges and rng.random() < 0.3:
            convo = list(rng.choice(exchanges)) + convo
        out.append(convo)
    return out


def unknowable_conversations(rng, n):
    out = []
    for _ in range(n):
        if rng.random() < 0.4:
            q, a = rng.choice(UNKNOWABLE)
        else:
            tq, ta = rng.choice(FAKE_TEMPLATES)
            name = fake_name(rng)
            q, a = tq.format(name=name), ta.format(name=name)
        out.append([user(q), assistant(a)])
    return out


def casual_variant(text, rng):
    """How people often type it: sometimes lowercase, without punctuation or apostrophes."""
    if rng.random() < 0.5:
        text = text.lower()
    if rng.random() < 0.5:
        text = text.replace("'", "").rstrip("?!.")
    return text


def small_talk_conversations(rng, n):
    """Casual greetings and chit-chat, sometimes followed by a real question."""
    out = []
    for _ in range(n):
        messages, replies = rng.choice(SMALL_TALK)
        convo = [user(casual_variant(rng.choice(messages), rng)), assistant(rng.choice(replies))]
        if rng.random() < 0.3:
            questions, reply = rng.choice(IDENTITY_QA)
            convo += [user(rng.choice(questions)), assistant(reply)]
        out.append(convo)
    return out


def identity_conversations(rng, n):
    out = []
    for _ in range(n):
        questions, reply = rng.choice(IDENTITY_QA)
        convo = [user(rng.choice(questions)), assistant(reply)]
        if rng.random() < 0.4:
            convo = [user(rng.choice(GREETINGS)), assistant(GREETING_REPLY)] + convo
        out.append(convo)
    return out


def build(general, stories, lookup_records, instruction_records, wiki, a, seed=1337):
    """Combine everything into one shuffled list of {"messages": [...]} examples."""
    rng = random.Random(seed)
    general = list(general)
    parts = {"general": general_conversations(general, a.general)}
    exchanges = first_exchanges(general[a.general:] or general, 30_000)
    parts["topic_switch"] = topic_switch_conversations(exchanges, rng, a.topic_switch) if len(exchanges) >= 3 else []
    parts.update(lookup_conversations(lookup_records, wiki, rng))
    parts["instruction"] = instruction_conversations(instruction_records, exchanges, rng)
    parts["unknowable"] = unknowable_conversations(rng, a.unknowable)
    parts["identity"] = identity_conversations(rng, a.identity)
    parts["small_talk"] = small_talk_conversations(rng, a.small_talk)
    parts.update(memory_conversations(rng, getattr(a, "memory", 0)))
    if stories:
        from make_chat_data_v2 import story_conversations
        rng.shuffle(stories)
        parts["story"] = [ex["messages"] for ex in story_conversations(stories, rng, a.stories)]
    examples = []
    for kind, convos in parts.items():
        kept = [c for c in convos if total_chars(c) <= MAX_CHARS]
        print(f"  {kind:13s} {len(kept):7,}")
        examples += [{"messages": c, "kind": kind} for c in kept]
    if os.path.exists(MY_EXAMPLES):
        with open(MY_EXAMPLES, encoding="utf-8") as f:
            mine = [json.loads(line) for line in f if line.strip()]
        examples += mine * 3
        print(f"  your own examples: {len(mine)} (x3)")
    rng.shuffle(examples)
    return examples


def read_jsonl(path):
    if not os.path.exists(path):
        print(f"(no {path} yet: run make_teacher_data.py first to include these lessons)")
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--general", type=int, default=60_000, help="everyday conversations")
    p.add_argument("--topic_switch", type=int, default=12_000)
    p.add_argument("--unknowable", type=int, default=2_500)
    p.add_argument("--identity", type=int, default=1_000)
    p.add_argument("--small_talk", type=int, default=1_500)
    p.add_argument("--stories", type=int, default=4_000)
    p.add_argument("--memory", type=int, default=3_000, help="remembering-you lessons (save / don't / recall)")
    p.add_argument("--db", default=os.path.join("data", "wiki", "wiki.db"))
    a = p.parse_args()

    from make_chat_data_v2 import load_smoltalk, load_story_texts
    wiki = None
    if os.path.exists(a.db):
        from wiki_index import WikiIndex
        wiki = WikiIndex(a.db)
    else:
        print(f"(no Wikipedia index at {a.db}: lookup lessons will only include the source passage)")
    examples = build(load_smoltalk(), load_story_texts(),
                     read_jsonl(os.path.join(TEACHER_DIR, "lookup.jsonl")),
                     read_jsonl(os.path.join(TEACHER_DIR, "instructions.jsonl")), wiki, a)
    os.makedirs(V.data_dir, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"wrote {OUT_PATH}: {len(examples):,} conversations")
