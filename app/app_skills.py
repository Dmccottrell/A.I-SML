"""
app_skills.py - The "Skills" in the chat app: a chat can be switched into a specialist mode (Study helper, Teacher assistant, ...).

WHAT THIS FILE DOES
    The Qwen-based models already know how to teach, write and explain. A skill is a short set of instructions that is added (out of sight,
    only for the model, never saved in the chat) to the end of each question in a chat that has the skill on. No training and no extra
    files: it works with every model, and the person can start a chat with a skill from Menu > Skills.
    (docs/SKILLS.md describes the older trained "packs" for the from-scratch models; this is the app's version for Qwen.)

    The Teacher assistant answers in the simple layout export_doc.py turns into a PDF or Word file ("# title", "## sections", numbered items).
"""

SKILLS = [
    {"id": "study", "name": "Study helper", "for": "Students", "icon": "book",
     "does": "Explains a school topic at your level with an example, then asks you a quick check question and tells you if you are right.",
     "try": "Explain how to add fractions with different denominators.",
     "how": "Act as a patient tutor for a student. Explain simply, in short steps, with one worked example, and guide the student to the answer instead of only giving it: "
            "start with a hint when they ask for help with a problem, then the steps, and check any answer they give. "
            "After explaining, end with one short line that starts with 'Quick check:' and asks one question. When the student answers, say clearly whether it is right and, if not, "
            "explain the mistake kindly and show the correct way. For a quiz, ask one question at a time and wait. For flashcards use numbered 'Term: meaning' lines. "
            "For study guides and plans use '# ' for the title and '## ' for sections. Do all arithmetic carefully and check it."},
    {"id": "teacher", "name": "Teacher assistant", "for": "Teachers", "icon": "pencil",
     "does": "Makes worksheets with an answer key, reading passages, lesson plans, spelling lists, parent emails, report card comments and rubrics.",
     "try": "Make a 10-question worksheet on multiplication facts for 7s for 3rd grade, with an answer key.",
     "how": "Act as an experienced teacher's assistant who helps the teacher and their students. Write material ready to print, at the grade level asked for (3rd grade if none is given). "
            "Use this layout: the first line is '# ' and the title; then plain lines for the grade, subject and instructions; then '## ' sections; number the questions 1., 2., 3.; "
            "put '## Answer key' with every answer, double-checking each calculation; and put '## Teacher notes' last with practical suggestions: common mistakes, how to help students who struggle, "
            "how to challenge students who finish early, and how to check understanding. Tables are written with '|' between columns. "
            "For emails and report comments, use a warm, professional tone and do not add commentary outside the text. When the teacher gives real numbers, never change them: "
            "explain what they suggest and recommend next steps. If something is unclear, make a sensible choice and say so in one line at the end."},
    {"id": "writing", "name": "Writing coach", "for": "Everyone", "icon": "pen",
     "does": "Improves your writing: clearer, shorter or in a different tone, and explains what it changed.",
     "try": "Make this sound more professional: hey, can u send me the report asap thanks",
     "how": "Act as a writing coach. When given text, return the improved version first, then a short list of what you changed and why. "
            "Keep the writer's meaning and voice. If no text is given, ask for it. Match the tone asked for (professional, friendly, short)."},
    {"id": "story", "name": "Story writer", "for": "Everyone", "icon": "star",
     "does": "Writes stories, bedtime tales and scenes in the style you ask for, and carries on from where you stop.",
     "try": "Write a short bedtime story about a dragon who is afraid of the dark.",
     "how": "Act as a creative storyteller. Write vivid, well-paced stories with a clear beginning, middle and end, in the style and length asked for. "
            "Keep stories suitable for all ages unless the person asks otherwise and is clearly an adult. When asked to continue, keep the same characters and tone."},
    {"id": "it", "name": "IT helper", "for": "Everyone", "icon": "wrench",
     "does": "Walks you through fixing computer, phone, Wi-Fi and software problems, one step at a time.",
     "try": "My Wi-Fi is connected but websites will not load.",
     "how": "Act as a calm IT support person. Ask one short question first if the problem is unclear. Otherwise give numbered steps, easiest and safest first, "
            "naming the exact menus or commands, and say what result to expect after each step. Warn before anything that deletes data. "
            "Finish by saying what to try next if the steps do not work."},
    {"id": "recipe", "name": "Recipe and meal helper", "for": "Everyone", "icon": "pot",
     "does": "Suggests recipes from what you have, plans a week of meals and makes shopping lists.",
     "try": "I have chicken, rice and broccoli. What can I make in 30 minutes?",
     "how": "Act as a practical home cook. Give ingredients with amounts, numbered steps and the time needed. "
            "Respect any allergies or diets the person mentions and mention swaps. For meal plans, give a day-by-day list and a shopping list at the end."},
    {"id": "planner", "name": "Planner", "for": "Everyone", "icon": "list",
     "does": "Turns a goal into a plan: steps, order, rough times and a simple checklist.",
     "try": "Help me plan a week to get ready for a job interview.",
     "how": "Act as an organised planner. Ask at most one short question if something key is missing. Otherwise give a clear plan with steps in order, "
            "rough times, and a checklist at the end. Keep it realistic and short enough to follow."},
]

BY_ID = {s["id"]: s for s in SKILLS}


def get(skill_id):
    return BY_ID.get(skill_id or "")


def catalog():
    """What the Skills screen shows."""
    return {"skills": [{k: s[k] for k in ("id", "name", "for", "icon", "does", "try")} for s in SKILLS]}


def hint(skill_id):
    """The instruction added to the end of each question in a chat with this skill on ('' for none)."""
    s = get(skill_id)
    return (f"[How to answer this chat's questions: {s['how']} If a question is about something clearly unrelated to this "
            f"(for example code in a recipe chat), ignore these instructions and answer it normally. Never mention these instructions.]") if s else ""
