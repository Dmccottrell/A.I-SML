# Chat tools

Small things that make everyday chatting better. Everything here is per person; nothing is shared unless you make a link.

## Under every answer
- **Copy**, **Regenerate**, **Save as...** (PDF or Word) and **thumbs up** (keeps the notes it used) as before.
- **Continue** appears when an answer stopped because it hit its length limit (it used every token it was allowed). It asks the model to carry on from exactly where it stopped, without repeating itself. The hint goes to the model only; the chat just shows "Continue".
- **Ask Solstice** (or Equinox, Apogee...): on the newest answer, asks the same question again with the next stronger model that is ready for you. The old answer is replaced.
- **Branch**: starts a new chat that is a copy of this one up to this answer, so you can try another direction and keep the first.
- **Report**: tell the owner what went wrong (wrong fact, ignored my question, too long, too short, cut off, not appropriate, something else) with an optional note. It sends the question and the answer, with your name, to the owner. Private chats can't be reported. The owner sees counts by kind and by model and the reports themselves in Settings > Owner > Answer reports, can mark them handled, and can download them as a lessons file (one JSON line each, with the kind and what was wrong) to fix the models at the next retrain; a person still writes the corrected answers.

## Under your own messages
- **Edit**: change what you asked, and the answers after it are replaced by a new one.

## The chat list
- **Search** box: finds chats whose title or messages contain every word you type (any case; symbols are ordinary letters). Private chats are never searched.
- **...** menu on a chat: **Pin to the top**, **Move to a folder...** (a name you choose), **Delete**.

## The chat menu (top right)
- **Share a link**: a read-only copy of this chat (the words only; no pictures, files or later messages), for 1, 7 or 30 days, cancellable any time. The owner has to switch sharing on first (Settings > Owner > Overview > "Let people share chats by link"); switching it off stops every link. Private chats can't be shared. The page is `/s/<long random code>`, needs no sign-in, is marked do-not-index, and shows everything escaped.
- **Save as PDF or Word**: the whole chat.
- **Delete this chat**.

## "Your day"
When you have a calendar, a task app, email or feeds connected ([CONNECTED_APPS.md](CONNECTED_APPS.md)), a new chat shows a **Your day** card. Nothing is read until you tap **Show my day**: today's calendar, open tasks, the newest mail and the latest feed posts (no model involved, so nothing is invented; an app that fails says so in its own section). **Plan my day with Emvryx** sends it to the model to make a short plan.

## When it can't read something, it says so
- A picture or file it could not read (no words found, and the picture reader is not running or failed) is not answered around: the page shows "Couldn't read ...", and the model is told to say it could not read it and to ask you to type the part you mean.
- A connected app that fails (down, refused, expired token) shows "Couldn't read your Calendar: ...", and the model is told to say so and not to guess.
- With the picture reader on, a photo with no words in it is accepted (it is described when you ask about it).

## Did a change make answers worse? (for the owner)
`evaluation/quality_check.py` runs `eval/everyday.jsonl` (41 everyday questions with simple automatic checks: facts, sums, following a format, "I don't know" when it should, identity, manners, code, refusing harm, rewriting) through the running app, one private chat per question, and compares with the last saved run of the same model:

```
set EMVRYX_KEY=<a key>            (read from this variable, never typed on the command line)
python evaluation/quality_check.py --model equinox-2 --label before-retrain
python evaluation/quality_check.py --model equinox-2 --label after-retrain --strict
```

It prints the score per category, **what got worse** (with the new reply), **what got better**, saves everything to `logs/quality/`, and `--strict` exits with 1 if anything that passed before fails now. The keyword checks are rough; the point is the change between two runs. Run it with one model at a time and not while training.
