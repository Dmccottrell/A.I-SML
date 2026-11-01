"""
teacher_tools.py - Exact calculators for Teacher mode (grades, class statistics, curves, what a student needs on the final).

WHAT THIS FILE DOES
    A language model is unreliable at arithmetic, so every number in Teacher mode comes from here: plain code that is always right.
    Each calculator takes simple inputs and returns {"title", "numbers": {...}, "text"}: `text` is a short report in the layout export_doc.py
    turns into a PDF or Word file, and the same text can be handed to the model to write suggestions about ("here are the real numbers: what should I reteach?").

      class_stats      scores -> average, median, highest, lowest, spread, how many pass, the letter-grade spread, who may need help
      weighted_grade   [score, out of, weight] rows -> the overall percentage and letter (a gradebook with categories)
      needed_on_final  current grade, the final's weight, the grade wanted -> the score needed on the final
      curve            scores -> the new scores after adding points, scaling the top score to 100, or a square-root curve
      points_plan      how many questions, how many points each, to make a worksheet or test total 100 (or any total)
      reading_level    text -> the school grade that can read it (Flesch-Kincaid), to match a passage to a class
    Input problems raise ValueError with a message the page can show as it is.
"""
import math
import re
import statistics

# The grading scale: pairs of (lowest percent for that letter, letter), listed from the top. Checked in order, so 85% is a "B".
DEFAULT_SCALE = ((90, "A"), (80, "B"), (70, "C"), (60, "D"), (0, "F"))      # percent at least -> letter


def to_letter(pct, scale=DEFAULT_SCALE):
    """The letter grade for a percent: the first letter whose minimum the percent reaches."""
    for floor, letter in scale:
        if pct >= floor:
            return letter
    # Below every minimum (a negative percent): give the lowest letter.
    return scale[-1][1]


def _r(x, places=1):
    """Round to `places` decimals. Adding 0.0 first turns a whole number into a float, so results always print the same way (e.g. 85.0)."""
    return round(x + 0.0, places)


def parse_numbers(text):
    """Numbers from a pasted list: separated by commas, spaces, new lines, tabs or semicolons. Words are ignored, % signs are fine."""
    out = []
    # The regex [\s,;]+ means "one or more of: whitespace, comma, semicolon", so the text is cut into separate pieces at any of them.
    for tok in re.split(r"[\s,;]+", str(text or "").strip()):
        # rstrip("%") removes a trailing percent sign, so "85%" becomes "85".
        tok = tok.strip().rstrip("%")
        if not tok:
            continue
        # Anything that is not a number (a name, a word) is silently skipped.
        try:
            out.append(float(tok))
        except ValueError:
            continue
    return out


def class_stats(scores, out_of=100.0, pass_mark=60.0):
    """Statistics for one test. `scores` are raw points; `out_of` the most possible; `pass_mark` is a percent.

    Returns {"title", "numbers", "text"} as described at the top of the file. Raises ValueError for no scores or impossible values.
    """
    scores = [float(s) for s in scores]
    if not scores:
        raise ValueError("Paste at least one score.")
    if out_of <= 0:
        raise ValueError("The most possible points must be more than 0.")
    # Allow up to 150% (extra credit) but treat negatives or far-too-big values as typing mistakes.
    if any(s < 0 or s > out_of * 1.5 for s in scores):
        raise ValueError(f"Some scores look wrong: they should be between 0 and {out_of:g}.")
    # Work in percentages so a test out of 20 and one out of 100 are treated the same.
    pcts = [s / out_of * 100 for s in scores]
    n = len(scores)
    # mean = the average; median = the middle value when sorted. sd = standard deviation (pstdev): how spread out the scores are; a big
    # number means very different results. One student has no spread.
    mean, med = statistics.fmean(pcts), statistics.median(pcts)
    sd = statistics.pstdev(pcts) if n > 1 else 0.0
    passed = sum(1 for p in pcts if p >= pass_mark)
    # Count how many students got each letter.
    spread = {}
    for p in pcts:
        spread[to_letter(p)] = spread.get(to_letter(p), 0) + 1
    letters = [letter for _, letter in DEFAULT_SCALE]
    # "May need help" cut-off: the lower of 60% and (average minus one standard deviation), but never lower than the pass mark.
    # Students below it are listed by position in the pasted list (1 = first score).
    help_below = max(pass_mark, min(60.0, mean - sd))
    needs_help = sorted(i + 1 for i, p in enumerate(pcts) if p < help_below)
    # The numbers the page can show or use. "l" in the comprehension is each letter; letters with nobody get 0.
    numbers = {"students": n, "average_pct": _r(mean), "median_pct": _r(med), "highest_pct": _r(max(pcts)), "lowest_pct": _r(min(pcts)),
               "spread_pct": _r(sd), "passed": passed, "passed_pct": _r(passed / n * 100), "letters": {l: spread.get(l, 0) for l in letters},
               "needs_help_students": needs_help, "average_points": _r(statistics.fmean(scores), 2)}
    # The text report. Lines starting "# " or "## " are headings in the layout export_doc.py understands; "- " lines are bullet points.
    lines = ["# Class results", "Test summary", "## Numbers",
             f"- Students: {n}",
             f"- Average: {numbers['average_pct']}% ({numbers['average_points']:g} of {out_of:g} points), median {numbers['median_pct']}%",
             f"- Highest {numbers['highest_pct']}%, lowest {numbers['lowest_pct']}%",
             f"- Passed (at least {pass_mark:g}%): {passed} of {n} ({numbers['passed_pct']}%)",
             "- Letter grades: " + ", ".join(f"{l} {numbers['letters'][l]}" for l in letters),
             ("- Students below " + f"{help_below:g}% (by position in your list): " + ", ".join(map(str, needs_help))) if needs_help else "- Nobody is far below the rest of the class."]
    # Add one plain-words hint: widely spread scores, or an average under the pass mark.
    if sd > 20:
        lines.append("- The scores are spread out widely: this class may need work at more than one level.")
    elif mean < pass_mark:
        lines.append("- The class average is below the pass mark: the topic may need teaching again.")
    return {"title": "Class results", "numbers": numbers, "text": "\n".join(lines)}


def weighted_grade(rows):
    """rows: [(score, out_of, weight)] for each category (weights are percents and should add to 100, or are scaled). Returns the overall.

    Example: homework 85/100 at 20%, tests 72/100 at 30%, project 90/100 at 50% gives 0.2*85 + 0.3*72 + 0.5*90 = 83.6%.
    """
    items = []
    for r in rows:
        score, out_of, weight = (float(x) for x in r)
        if out_of <= 0 or weight < 0 or score < 0:
            raise ValueError("Each row needs a score, the most possible (more than 0) and a weight.")
        items.append((score, out_of, weight))
    if not items:
        raise ValueError("Add at least one row.")
    # Weights need not add up to 100; each is divided by their total below, which scales them to fit.
    total_w = sum(w for _, _, w in items)
    if total_w <= 0:
        raise ValueError("The weights must add up to more than 0.")
    # Weighted average: each category's percent (s / o * 100) times its weight, summed, divided by the total weight.
    pct = sum(s / o * 100 * w for s, o, w in items) / total_w
    numbers = {"percent": _r(pct, 2), "letter": to_letter(pct), "weights_total": _r(total_w, 2)}
    lines = ["# Overall grade", "## Numbers", f"- Overall: {numbers['percent']}% ({numbers['letter']})"]
    # One line per category (numbered from 1) showing its percent and how much of the grade it counts for.
    for i, (s, o, w) in enumerate(items, 1):
        lines.append(f"- Row {i}: {_r(s / o * 100)}% counts for {_r(w / total_w * 100)}% of the grade")
    # Tell the person if their weights did not add to 100 (allowing a tiny rounding difference).
    if abs(total_w - 100) > 0.01:
        lines.append(f"- The weights add up to {_r(total_w, 2)}, not 100, so they were scaled to fit.")
    return {"title": "Overall grade", "numbers": numbers, "text": "\n".join(lines)}


def needed_on_final(current_pct, final_weight_pct, target_pct):
    """The score (percent) needed on the final to finish with `target_pct`, if the final counts `final_weight_pct` of the grade.

    The maths: final grade = current * (1 - w) + final_score * w, where w is the final's share as a fraction (20% = 0.2). Solving for
    final_score gives (target - current * (1 - w)) / w.
    """
    current, w, target = float(current_pct), float(final_weight_pct), float(target_pct)
    if not 0 < w <= 100:
        raise ValueError("The final's weight must be between 1 and 100 percent.")
    if not (0 <= current <= 150 and 0 <= target <= 150):
        raise ValueError("Grades should be percents between 0 and 100.")
    # The formula above, with w converted from a percent to a fraction.
    need = (target - current * (1 - w / 100)) / (w / 100)
    numbers = {"needed_pct": _r(need, 1), "possible": need <= 100, "already_safe": need <= 0}
    # Three outcomes: already safe (even a 0 is enough), impossible (more than 100% needed), or a score to aim for.
    if need <= 0:
        verdict = f"You already have at least {target:g}% even with a 0 on the final."
    elif need > 100:
        # The best possible result: a perfect 100% on the final.
        best = current * (1 - w / 100) + 100 * w / 100
        verdict = f"{target:g}% is out of reach: with 100% on the final the best possible is {_r(best)}%."
    else:
        verdict = f"You need {_r(need)}% ({to_letter(need)}) on the final to finish with {target:g}%."
    return {"title": "What is needed on the final", "numbers": numbers,
            "text": "\n".join(["# What is needed on the final", "## Answer", f"- Current grade {current:g}%, the final counts {w:g}%, wanted {target:g}%", f"- {verdict}"])}


def curve(scores, method="top_to_100", amount=0.0, out_of=100.0):
    """New scores (points). method: "add" (add `amount` points), "top_to_100" (the best score becomes full marks, others scale), "sqrt"."""
    scores = [float(s) for s in scores]
    if not scores:
        raise ValueError("Paste at least one score.")
    if out_of <= 0:
        raise ValueError("The most possible points must be more than 0.")
    # Three ways to curve. `how` is a plain-words description of what was done, shown in the report. min(out_of, ...) stops any score going over full marks.
    if method == "add":
        new = [min(out_of, s + float(amount)) for s in scores]
        how = f"added {float(amount):g} points to every score (up to {out_of:g})"
    elif method == "top_to_100":
        # Scale everything so the best score becomes full marks: each score is multiplied by out_of / top.
        top = max(scores)
        if top <= 0:
            raise ValueError("The highest score is 0, so it can't be scaled.")
        new = [min(out_of, s / top * out_of) for s in scores]
        how = f"scaled so the highest score ({top:g}) becomes {out_of:g}"
    elif method == "sqrt":
        # Square root of the fraction of full marks, turned back into points: 25% of the marks becomes 50%, 81% becomes 90%. Low scores gain the most.
        new = [math.sqrt(s / out_of) * out_of for s in scores]
        how = "square-root curve (raises low scores the most)"
    else:
        raise ValueError("Pick add, top_to_100 or sqrt.")
    # Round to one decimal for display and compare the averages before and after.
    new = [_r(s, 1) for s in new]
    before, after = statistics.fmean(scores), statistics.fmean(new)
    numbers = {"new_scores": new, "average_before": _r(before), "average_after": _r(after)}
    lines = ["# Curved scores", "## Numbers", f"- Method: {how}", f"- Average before {_r(before)}, after {_r(after)} (out of {out_of:g})",
             "- New scores: " + ", ".join(f"{s:g}" for s in new)]
    return {"title": "Curved scores", "numbers": numbers, "text": "\n".join(lines)}


def points_plan(questions, total=100.0):
    """How many points each question is worth so the paper totals `total`."""
    q, total = int(questions), float(total)
    # Not allowed: no questions, or a zero or negative total.
    if q < 1 or total <= 0:
        raise ValueError("Give the number of questions (1 or more) and a total over 0.")
    each = total / q
    # "whole" = the total is a whole number and divides evenly by the question count (`q and` guards against dividing by zero).
    whole = total == int(total) and q and int(total) % q == 0
    numbers = {"points_each": _r(each, 2), "even": bool(whole)}
    text = ["# Points plan", "## Numbers", f"- {q} questions, {total:g} points in all"]
    if whole:
        text.append(f"- {int(each)} points each")
    else:
        # Not even: some questions get `base` points and the rest base + 1. `extra` is how many questions need the extra point
        # (example: 100 points over 15 questions: base 6, extra 10, so 5 questions get 6 points and 10 questions get 7).
        base = math.floor(each)
        extra = int(round(total - base * q))
        text.append(f"- {_r(each, 2)} points each does not come out even: give {base} points to {q - extra} questions and {base + 1} points to {extra} questions")
    return {"title": "Points plan", "numbers": numbers, "text": "\n".join(text)}


def reading_level(text):
    """The school grade that can read `text` (Flesch-Kincaid, a formula based on sentence length and word length). Needs at least 10 words."""
    # Imported here, when first needed, so this file loads without the classroom module.
    from classroom import reading_grade
    # Regex: runs of letters and apostrophes count as words.
    words = len(re.findall(r"[A-Za-z']+", text or ""))
    if words < 10:
        raise ValueError("Paste a passage of at least 10 words.")
    g = reading_grade(text)
    # Very simple text can score below zero; show 0 at the lowest.
    shown = max(0.0, g)
    numbers = {"grade": _r(shown), "words": words}
    return {"title": "Reading level", "numbers": numbers,
            "text": "\n".join(["# Reading level", "## Numbers", f"- {words} words, about grade {_r(shown)} (Flesch-Kincaid)",
                               "- This is a guide only: short sentences and short words lower the grade."])}


# Name -> a small function that reads the form values (a dict `p`) and calls the right calculator. `or` supplies a default when a box was left
# empty. parse_numbers turns the pasted score text into a list of numbers.
CALCULATORS = {
    "class_stats": lambda p: class_stats(parse_numbers(p.get("scores")), float(p.get("out_of") or 100), float(p.get("pass_mark") or 60)),
    "weighted_grade": lambda p: weighted_grade([tuple(r) for r in p.get("rows") or []]),
    "needed_on_final": lambda p: needed_on_final(p.get("current"), p.get("weight"), p.get("target")),
    "curve": lambda p: curve(parse_numbers(p.get("scores")), str(p.get("method") or "top_to_100"), float(p.get("amount") or 0), float(p.get("out_of") or 100)),
    "points_plan": lambda p: points_plan(p.get("questions"), float(p.get("total") or 100)),
    "reading_level": lambda p: reading_level(str(p.get("text") or "")),
}


def run(name, params):
    """Run a calculator by name. Anything wrong with the inputs is a ValueError with a plain message."""
    fn = CALCULATORS.get(name)
    if not fn:
        raise ValueError("That calculator doesn't exist.")
    # Missing or non-numeric form values show up as TypeError/KeyError/AttributeError; turn them into one friendly message.
    # "raise ... from e" keeps the original error attached for debugging.
    try:
        return fn(params or {})
    except (TypeError, KeyError, AttributeError) as e:
        raise ValueError("Some of the numbers are missing or not numbers.") from e
