# Teacher mode

**Menu > Teacher mode** opens a chat with the Teacher assistant switched on. Type anything in your own words, or tap a tool chip: the tools open a short form and the answer lands in the same chat. A **Tools** button stays at the top of the chat so you can use a tool at any point. There are two sides, **For teachers** and **For students** (switch at the start of the chat), and each side has two kinds of tool.

**Make** tools are short forms (grade, subject, topic ...). Pressing "Make it" sends the request into the current Teacher chat (or starts one with the Study helper for the student tools).

| For teachers | For students |
|---|---|
| Worksheet with answer key and teacher notes, quiz or test with marking guide, lesson plan, reading passage with questions, rubric (a table), email to a parent, report card comments, ideas for different learners | Explain it to me, help with a problem (hints first, not just the answer), study guide, quiz me (one question at a time), flashcards, study plan, feedback on my writing |

**Calculate** tools are exact code (`app/teacher_tools.py`), never the model's guess: class results (average, median, pass rate, letter grades, who may need help), overall grade from weighted categories, curve scores (add points, top score to 100%, square root), points per question, reading level; for students, what they need on the final and their overall grade. After a calculation, **Get suggestions** hands the real numbers to the assistant, which is told never to change them, and asks what to reteach or focus on.

## Saving documents

Any long answer, and every answer in a skill chat, has **Save as...**: **PDF**, **Word**, **Google Docs** or **Copy text**. Worksheets print with a Name/Date line, writing space under each question, and the answer key and teacher notes each on their own page (print page 1 for the class). Tables (rubrics) are kept.

**Google Docs:** the app saves a Word file and opens Google Docs; on a phone tap the file and choose Docs, on a computer use File > Open > Upload. Creating a Google Doc directly in your Drive needs the Google connection under Connected apps, which is not built yet (it needs a Google developer registration that only you can do).

Needs `pip install fpdf2 python-docx` (already in requirements.txt).

## Adding a tool

Add an entry to `app/teacher_mode.py` (fields, and for "make" the prompt with `{field}` placeholders; for "calc" the calculator). The page builds the form from the list, and `tests/test_teacher.py` checks that every placeholder has a field.
