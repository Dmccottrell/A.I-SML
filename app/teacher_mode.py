"""
teacher_mode.py - The catalog behind Menu > Teacher mode: what a teacher or a student can ask for, as small forms, and the exact calculators.

WHAT THIS FILE DOES
    Teacher mode has two sides. Each "make" tool is a short form (grade, subject, topic ...) whose answers are filled into a request that starts a
    chat with the Teacher assistant (teachers) or the Study helper (students) switched on (app_skills.py). Each "calc" tool is a calculator
    (teacher_tools.py) that returns exact numbers; the page can then ask the assistant for suggestions about those real numbers.
    The page reads this list (`GET /api/teacher/tools`), so adding a tool is adding an entry here. `fill()` checks and fills a request.

    Field types: text, number, choice (with options), area (several lines).

HOW A TOOL ENTRY IS BUILT (see TOOLS below)
    id: short unique name. side: "teacher" or "student". kind: "make" (fills a prompt) or "calc" (runs a calculator). name/blurb: shown on the page.
    fields: the form boxes. prompt: the request text with {key} slots that fill() replaces with the form answers. advice: for calc tools, a
    request about the computed numbers with a {report} slot.
"""
import re

# The school grades offered in the "Grade" drop-down.
GRADES = ["Kindergarten", "1st grade", "2nd grade", "3rd grade", "4th grade", "5th grade", "6th grade", "7th grade", "8th grade",
          "9th grade", "10th grade", "11th grade", "12th grade", "College"]


def _f(key, label, kind="text", **kw):
    """Build one form field description (a dict): its key, the label shown, its type, plus extras such as default, options, min, max, placeholder."""
    return dict({"key": key, "label": label, "type": kind}, **kw)


# Form fields used by many tools, defined once and reused.
GRADE = _f("grade", "Grade", "choice", options=GRADES, default="3rd grade")
SUBJECT = _f("subject", "Subject", "text", default="Math", placeholder="Math, Reading, Science ...")
TOPIC = _f("topic", "Topic", "text", placeholder="for example: multiplication facts for 7s")

# The list of every tool the page can show. The page reads it as JSON, so every value must be plain text, numbers, lists or dicts.
TOOLS = [
    # ------------------------------------------------------------------ for teachers
    # Worksheet: grade, subject, topic and number of questions fill the prompt; the reply is questions, an answer key and teacher notes.
    {"id": "worksheet", "side": "teacher", "kind": "make", "name": "Worksheet with answer key", "blurb": "Printable questions, an answer key and teacher notes.",
     "fields": [GRADE, SUBJECT, TOPIC, _f("count", "Number of questions", "number", default=10, min=3, max=40)],
     "prompt": "Make a {count}-question worksheet on {topic} for {grade} {subject}, with an answer key. After the answer key add a section called "
               "'Teacher notes' with the most common mistakes, one idea for students who need extra help and one for students who finish early."},
    # Quiz: like the worksheet, plus a question type; asks for an answer key and a marking guide.
    {"id": "quiz", "side": "teacher", "kind": "make", "name": "Quiz or test", "blurb": "A quiz with the right answers and how to mark it.",
     "fields": [GRADE, SUBJECT, TOPIC, _f("count", "Number of questions", "number", default=10, min=3, max=40),
                _f("qtype", "Kind of questions", "choice", options=["Multiple choice", "Short answer", "True or false", "A mix"], default="A mix")],
     "prompt": "Make a {count}-question quiz ({qtype}) on {topic} for {grade} {subject}. Give an answer key and a short marking guide, and say how many points each question is worth."},
    # Lesson plan: adds the lesson length in minutes so the steps get times.
    {"id": "lesson", "side": "teacher", "kind": "make", "name": "Lesson plan", "blurb": "Goals, steps with times, checks for understanding and homework.",
     "fields": [GRADE, SUBJECT, TOPIC, _f("minutes", "Lesson length (minutes)", "number", default=45, min=10, max=180)],
     "prompt": "Write a {minutes}-minute lesson plan on {topic} for {grade} {subject}. Include the learning goal, materials, step-by-step activities with times, "
               "questions to check understanding, and a short homework idea. Add a 'Teacher notes' section with suggestions for students who struggle and students who need a challenge."},
    # Reading passage: needs only grade, topic and a rough word count.
    {"id": "reading", "side": "teacher", "kind": "make", "name": "Reading passage and questions", "blurb": "A passage at the right reading level with questions and a key.",
     "fields": [GRADE, TOPIC, _f("words", "About how many words", "number", default=150, min=60, max=600)],
     "prompt": "Write a reading passage of about {words} words about {topic} that a {grade} student can read, then 5 comprehension questions and an answer key."},
    # Rubric: a scoring table. The 'criteria' field is optional (empty becomes 'not given' in fill()).
    {"id": "rubric", "side": "teacher", "kind": "make", "name": "Rubric", "blurb": "A scoring table with levels for each skill.",
     "fields": [GRADE, _f("task", "What is being graded", "text", placeholder="a paragraph about animals"),
                _f("criteria", "Skills to score (optional)", "text", placeholder="ideas, spelling, neatness")],
     "prompt": "Make a 4-level scoring rubric for {task} for {grade}. Skills to score: {criteria}. Show it as a table with one row per skill and columns 4, 3, 2 and 1, with a short description in each cell, and the total points."},
    # Parent email: a choice of reason, an optional first name and free-text details.
    {"id": "parent_email", "side": "teacher", "kind": "make", "name": "Email to a parent", "blurb": "A warm, professional email you can send.",
     "fields": [_f("situation", "What is it about", "choice", options=["Good news about progress", "A behavior concern", "Missing homework",
                                                                   "An upcoming event", "A progress update", "A meeting request"], default="A progress update"),
                _f("student", "Student's first name", "text", placeholder="optional"), _f("details", "Anything to include", "area", placeholder="what happened, dates, what you suggest")],
     "prompt": "Write a short, warm and professional email to a parent. Reason: {situation}. Student: {student}. Details: {details}. Be kind and specific, suggest one next step, and keep it under 150 words."},
    # Report card comments: grade, subject, how the student is doing and free-text details.
    {"id": "report", "side": "teacher", "kind": "make", "name": "Report card comments", "blurb": "Kind, specific comments for a student.",
     "fields": [GRADE, SUBJECT, _f("level", "How is the student doing", "choice", options=["Excelling", "On track", "Needs support"], default="On track"),
                _f("details", "Strengths and things to work on", "area", placeholder="reads well, rushes math, shy in groups")],
     "prompt": "Write 3 different report card comments for a {grade} student in {subject} who is {level}. Details: {details}. Each is 2 to 3 sentences, positive and specific, "
               "names one thing to work on, and does not use the student's name."},
    # Ideas for different learners: only grade and topic.
    {"id": "differentiate", "side": "teacher", "kind": "make", "name": "Ideas for different learners", "blurb": "Support, challenge and English learner ideas.",
     "fields": [GRADE, TOPIC],
     "prompt": "I am teaching {topic} to {grade}. Suggest specific activities for students who are struggling, for students who need a challenge, and for English learners. Add a short list of what to watch for."},
    # Class results (a "calc" tool): scores typed in any format; teacher_tools.class_stats works out the numbers, then 'advice' asks the assistant about them.
    {"id": "class_stats", "side": "teacher", "kind": "calc", "name": "Class results", "blurb": "Average, median, pass rate, letter grades and who may need help.",
     "fields": [_f("scores", "Scores (one per student, any separator)", "area", placeholder="78 92 55 88 67 ..."),
                _f("out_of", "Most possible points", "number", default=100, min=1), _f("pass_mark", "Pass mark (%)", "number", default=60, min=0, max=100)],
     "advice": "Here are the real results of my class test:\n{report}\nWhat do these numbers suggest? Tell me what to reteach, how to group students and which next steps to take. Do not change the numbers."},
    # Overall grade (a "calc" tool): one line per category. 'rows_tool' names the calculator that reads those lines (see calculate()).
    {"id": "weighted", "side": "teacher", "kind": "calc", "name": "Overall grade", "blurb": "Combine homework, tests and projects with their weights.",
     "fields": [_f("rows", "One line per category: score, out of, weight %", "area", placeholder="85 100 20\n72 100 30\n90 100 50")], "rows_tool": "weighted_grade",
     "advice": "Here is how a student's grade was worked out:\n{report}\nWhat should they focus on to raise it? Do not change the numbers."},
    # Curve scores (a "calc" tool): adds points, scales the top score to 100%, or applies a square-root curve. No 'tool' key, so calc_tool() maps it by id.
    {"id": "curve", "side": "teacher", "kind": "calc", "name": "Curve scores", "blurb": "Add points, scale the top score to 100%, or a square-root curve.",
     "fields": [_f("scores", "Scores", "area", placeholder="45 62 70 38 ..."), _f("out_of", "Most possible points", "number", default=100, min=1),
                _f("method", "Method", "choice", options=["top_to_100", "add", "sqrt"], default="top_to_100"), _f("amount", "Points to add (for 'add')", "number", default=5, min=0)]},
    # Points per question (a "calc" tool): 'tool' names the teacher_tools calculator to run.
    {"id": "points", "side": "teacher", "kind": "calc", "name": "Points per question", "blurb": "Make a paper total 100 (or any number).",
     "fields": [_f("questions", "Number of questions", "number", default=15, min=1), _f("total", "Total points", "number", default=100, min=1)], "tool": "points_plan"},
    # Reading level (a "calc" tool): a pasted passage goes to the reading_level calculator.
    {"id": "level", "side": "teacher", "kind": "calc", "name": "Reading level", "blurb": "The school grade that can read a passage.",
     "fields": [_f("text", "Paste the passage", "area")], "tool": "reading_level"},
    # ------------------------------------------------------------------ for students
    # Student: Explain it to me.
    {"id": "explain", "side": "student", "kind": "make", "name": "Explain it to me", "blurb": "A step-by-step explanation with an example and a quick check.",
     "fields": [GRADE, SUBJECT, TOPIC],
     "prompt": "Explain {topic} ({grade} {subject}) step by step with a worked example, then give me a quick check question."},
    # Student: Help with a problem. The prompt asks for a hint and steps instead of only the answer.
    {"id": "homework", "side": "student", "kind": "make", "name": "Help with a problem", "blurb": "Hints and steps, not just the answer, so you learn it.",
     "fields": [GRADE, SUBJECT, _f("problem", "The problem", "area", placeholder="type or paste it here")],
     "prompt": "I am in {grade} and need help with this {subject} problem: {problem}\nDo not just give the final answer. Guide me with a hint first and then the steps, and check my answer if I give one."},
    # Student: Study guide.
    {"id": "study_guide", "side": "student", "kind": "make", "name": "Study guide", "blurb": "Key ideas, words to know and practice questions with answers.",
     "fields": [GRADE, SUBJECT, TOPIC],
     "prompt": "Make a study guide on {topic} for {grade} {subject}: a short summary, the key words with meanings, the 5 most important things to remember, and 5 practice questions with answers."},
    # Student: Quiz me, one question at a time.
    {"id": "quiz_me", "side": "student", "kind": "make", "name": "Quiz me", "blurb": "One question at a time, with feedback after each answer.",
     "fields": [GRADE, SUBJECT, TOPIC, _f("count", "How many questions", "number", default=5, min=3, max=20)],
     "prompt": "Quiz me on {topic} ({grade} {subject}). Ask {count} questions, one at a time, and wait for my answer before you go on. After each answer say whether I am right, explain if I am not, then ask the next question. Start with question 1."},
    # Student: Flashcards in a 'Term: meaning' form.
    {"id": "flashcards", "side": "student", "kind": "make", "name": "Flashcards", "blurb": "Term and meaning pairs to practise.",
     "fields": [GRADE, SUBJECT, TOPIC, _f("count", "How many cards", "number", default=12, min=4, max=40)],
     "prompt": "Make {count} flashcards on {topic} for {grade} {subject}. Show each as a numbered line in the form 'Term: meaning'."},
    # Student: Study plan for a test (days until the test and minutes per day).
    {"id": "plan", "side": "student", "kind": "make", "name": "Study plan", "blurb": "A realistic plan for a test, day by day.",
     "fields": [SUBJECT, _f("topics", "What the test covers", "text", placeholder="fractions, decimals"),
                _f("days", "Days until the test", "number", default=7, min=1, max=60), _f("minutes", "Minutes you can study each day", "number", default=30, min=10, max=300)],
     "prompt": "Make a study plan for a {subject} test on {topics} in {days} days. I can study {minutes} minutes a day. Give a day-by-day plan, what to do in each session, and a final review day."},
    # Student: Feedback on my writing. The prompt says not to rewrite the text for them.
    {"id": "essay", "side": "student", "kind": "make", "name": "Feedback on my writing", "blurb": "Kind, specific feedback to help you improve it.",
     "fields": [GRADE, _f("essay", "Paste your writing", "area")],
     "prompt": "I am in {grade}. Give me feedback on my writing: 3 things I did well, 3 specific things to improve and how, and one thing to check for spelling or grammar. Do not rewrite it for me.\n\n{essay}"},
    # Student calculator: the score needed on the final exam to reach a target grade (teacher_tools.needed_on_final).
    {"id": "final", "side": "student", "kind": "calc", "name": "What do I need on the final?", "blurb": "The score you need on the final to reach the grade you want.",
     "fields": [_f("current", "Your grade now (%)", "number", default=85, min=0, max=150), _f("weight", "How much the final counts (%)", "number", default=20, min=1, max=100),
                _f("target", "The grade you want (%)", "number", default=90, min=0, max=150)], "tool": "needed_on_final",
     "advice": "Here is my grade situation:\n{report}\nGive me a short, encouraging study plan to get there. Do not change the numbers."},
    # Student calculator: overall grade from weighted categories, same as the teacher's 'weighted'.
    {"id": "my_grade", "side": "student", "kind": "calc", "name": "My overall grade", "blurb": "Combine homework, tests and projects with their weights.",
     "fields": [_f("rows", "One line per category: score, out of, weight %", "area", placeholder="85 100 20\n72 100 30\n90 100 50")], "rows_tool": "weighted_grade",
     "advice": "Here is how my grade was worked out:\n{report}\nWhat should I focus on to raise it? Do not change the numbers."},
]

# A lookup table: tool id -> its entry, so fill() and calculate() can find a tool quickly.
BY_ID = {t["id"]: t for t in TOOLS}


def catalog():
    """The whole list of tools, in the shape the page asks for (GET /api/teacher/tools)."""
    return {"tools": TOOLS}


def calc_tool(tool_id):
    """The teacher_tools calculator name a calc tool uses."""
    t = BY_ID[tool_id]
    # Use the tool's own named calculator if it has one; class_stats and curve have none listed, so they use their own id.
    return t.get("rows_tool") or t.get("tool") or {"class_stats": "class_stats", "curve": "curve"}[tool_id]


def fill(tool_id, values):
    """The request text for a "make" tool. Missing optional fields become 'not given'; numbers are kept within their limits."""
    t = BY_ID.get(tool_id)
    if not t or t["kind"] != "make":
        raise ValueError("That tool doesn't exist.")
    # out will hold each field's cleaned text, keyed by the field name.
    out = {}
    for f in t["fields"]:
        # The value the person typed, or the field's default; None/empty become "". strip() removes spaces at both ends.
        v = str(values.get(f["key"], f.get("default", "")) or "").strip()
        # Numbers: not a number -> use the default. Then clamp into [min, max] (min(max_, n) caps from above, max(min_, ...) lifts from below;
        # a missing limit uses n itself, which changes nothing). Whole numbers print without ".0".
        if f["type"] == "number":
            try:
                n = float(v)
            except ValueError:
                n = float(f.get("default", 0))
            n = max(f.get("min", n), min(f.get("max", n), n))
            v = str(int(n)) if n == int(n) else str(n)
        # Choices: anything not in the allowed options is replaced by the default (or the first option), so odd text never reaches the prompt.
        elif f["type"] == "choice" and f.get("options") and v not in f["options"]:
            v = str(f.get("default") or f["options"][0])
        # Cut long text to 4000 characters; an empty answer becomes "not given" so the sentence still makes sense.
        out[f["key"]] = v[:4000] or "not given"
    # Regex {(\w+)} finds each slot like {topic} (\w+ = one or more letters, digits or underscore). Each is swapped for its value;
    # a slot with no value is left unchanged.
    return re.sub(r"\{(\w+)\}", lambda m: out.get(m.group(1), m.group(0)), t["prompt"])


def _rows(text):
    """Read the "score, out of, weight" lines of the grade calculators. Returns a list of [score, out_of, weight]; blank/number-free lines are skipped.

    Raises ValueError (with a message for the person) if a line has a number count other than 3.
    """
    rows = []
    for line in str(text or "").splitlines():
        # Regex: an optional minus, digits, and an optional decimal part. (?:...) groups without capturing. So "85 / 100, 20%" gives 85, 100, 20.
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", line)]
        if not nums:
            continue
        if len(nums) != 3:
            raise ValueError(f"Each line needs 3 numbers: score, out of, weight. This one has {len(nums)}: {line.strip()[:40]}")
        rows.append(nums)
    return rows


def calculate(tool_id, values):
    """Run a calc tool from its form values. Returns the calculator's result plus `advice_prompt` (a request for suggestions about the real numbers) when the tool has one."""
    # Imported here, when first needed, to keep module loading light.
    import teacher_tools as TT
    t = BY_ID.get(tool_id)
    if not t or t["kind"] != "calc":
        raise ValueError("That calculator doesn't exist.")
    v = dict(values or {})
    name = calc_tool(tool_id)
    # The weighted-grade calculator takes parsed rows, not the raw text, so convert the text first.
    if name == "weighted_grade":
        v = {"rows": _rows(v.get("rows"))}
    result = TT.run(name, v)
    # Add the follow-up request, with the calculator's text inserted for {report}, so the page can ask the assistant about the real numbers.
    if t.get("advice"):
        result["advice_prompt"] = t["advice"].replace("{report}", result["text"])
    return result
