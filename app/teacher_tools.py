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

DEFAULT_SCALE = ((90, "A"), (80, "B"), (70, "C"), (60, "D"), (0, "F"))      # percent at least -> letter


def to_letter(pct, scale=DEFAULT_SCALE):
    for floor, letter in scale:
        if pct >= floor:
            return letter
    return scale[-1][1]


def _r(x, places=1):
    return round(x + 0.0, places)


def parse_numbers(text):
    """Numbers from a pasted list: separated by commas, spaces, new lines, tabs or semicolons. Words are ignored, % signs are fine."""
    out = []
    for tok in re.split(r"[\s,;]+", str(text or "").strip()):
        tok = tok.strip().rstrip("%")
        if not tok:
            continue
        try:
            out.append(float(tok))
        except ValueError:
            continue
    return out


def class_stats(scores, out_of=100.0, pass_mark=60.0):
    """Statistics for one test. `scores` are raw points; `out_of` the most possible; `pass_mark` is a percent."""
    scores = [float(s) for s in scores]
    if not scores:
        raise ValueError("Paste at least one score.")
    if out_of <= 0:
        raise ValueError("The most possible points must be more than 0.")
    if any(s < 0 or s > out_of * 1.5 for s in scores):
        raise ValueError(f"Some scores look wrong: they should be between 0 and {out_of:g}.")
    pcts = [s / out_of * 100 for s in scores]
    n = len(scores)
    mean, med = statistics.fmean(pcts), statistics.median(pcts)
    sd = statistics.pstdev(pcts) if n > 1 else 0.0
    passed = sum(1 for p in pcts if p >= pass_mark)
    spread = {}
    for p in pcts:
        spread[to_letter(p)] = spread.get(to_letter(p), 0) + 1
    letters = [letter for _, letter in DEFAULT_SCALE]
    help_below = max(pass_mark, min(60.0, mean - sd))
    needs_help = sorted(i + 1 for i, p in enumerate(pcts) if p < help_below)
    numbers = {"students": n, "average_pct": _r(mean), "median_pct": _r(med), "highest_pct": _r(max(pcts)), "lowest_pct": _r(min(pcts)),
               "spread_pct": _r(sd), "passed": passed, "passed_pct": _r(passed / n * 100), "letters": {l: spread.get(l, 0) for l in letters},
               "needs_help_students": needs_help, "average_points": _r(statistics.fmean(scores), 2)}
    lines = ["# Class results", "Test summary", "## Numbers",
             f"- Students: {n}",
             f"- Average: {numbers['average_pct']}% ({numbers['average_points']:g} of {out_of:g} points), median {numbers['median_pct']}%",
             f"- Highest {numbers['highest_pct']}%, lowest {numbers['lowest_pct']}%",
             f"- Passed (at least {pass_mark:g}%): {passed} of {n} ({numbers['passed_pct']}%)",
             "- Letter grades: " + ", ".join(f"{l} {numbers['letters'][l]}" for l in letters),
             ("- Students below " + f"{help_below:g}% (by position in your list): " + ", ".join(map(str, needs_help))) if needs_help else "- Nobody is far below the rest of the class."]
    if sd > 20:
        lines.append("- The scores are spread out widely: this class may need work at more than one level.")
    elif mean < pass_mark:
        lines.append("- The class average is below the pass mark: the topic may need teaching again.")
    return {"title": "Class results", "numbers": numbers, "text": "\n".join(lines)}


def weighted_grade(rows):
    """rows: [(score, out_of, weight)] for each category (weights are percents and should add to 100, or are scaled). Returns the overall."""
    items = []
    for r in rows:
        score, out_of, weight = (float(x) for x in r)
        if out_of <= 0 or weight < 0 or score < 0:
            raise ValueError("Each row needs a score, the most possible (more than 0) and a weight.")
        items.append((score, out_of, weight))
    if not items:
        raise ValueError("Add at least one row.")
    total_w = sum(w for _, _, w in items)
    if total_w <= 0:
        raise ValueError("The weights must add up to more than 0.")
    pct = sum(s / o * 100 * w for s, o, w in items) / total_w
    numbers = {"percent": _r(pct, 2), "letter": to_letter(pct), "weights_total": _r(total_w, 2)}
    lines = ["# Overall grade", "## Numbers", f"- Overall: {numbers['percent']}% ({numbers['letter']})"]
    for i, (s, o, w) in enumerate(items, 1):
        lines.append(f"- Row {i}: {_r(s / o * 100)}% counts for {_r(w / total_w * 100)}% of the grade")
    if abs(total_w - 100) > 0.01:
        lines.append(f"- The weights add up to {_r(total_w, 2)}, not 100, so they were scaled to fit.")
    return {"title": "Overall grade", "numbers": numbers, "text": "\n".join(lines)}


def needed_on_final(current_pct, final_weight_pct, target_pct):
    """The score (percent) needed on the final to finish with `target_pct`, if the final counts `final_weight_pct` of the grade."""
    current, w, target = float(current_pct), float(final_weight_pct), float(target_pct)
    if not 0 < w <= 100:
        raise ValueError("The final's weight must be between 1 and 100 percent.")
    if not (0 <= current <= 150 and 0 <= target <= 150):
        raise ValueError("Grades should be percents between 0 and 100.")
    need = (target - current * (1 - w / 100)) / (w / 100)
    numbers = {"needed_pct": _r(need, 1), "possible": need <= 100, "already_safe": need <= 0}
    if need <= 0:
        verdict = f"You already have at least {target:g}% even with a 0 on the final."
    elif need > 100:
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
    if method == "add":
        new = [min(out_of, s + float(amount)) for s in scores]
        how = f"added {float(amount):g} points to every score (up to {out_of:g})"
    elif method == "top_to_100":
        top = max(scores)
        if top <= 0:
            raise ValueError("The highest score is 0, so it can't be scaled.")
        new = [min(out_of, s / top * out_of) for s in scores]
        how = f"scaled so the highest score ({top:g}) becomes {out_of:g}"
    elif method == "sqrt":
        new = [math.sqrt(s / out_of) * out_of for s in scores]
        how = "square-root curve (raises low scores the most)"
    else:
        raise ValueError("Pick add, top_to_100 or sqrt.")
    new = [_r(s, 1) for s in new]
    before, after = statistics.fmean(scores), statistics.fmean(new)
    numbers = {"new_scores": new, "average_before": _r(before), "average_after": _r(after)}
    lines = ["# Curved scores", "## Numbers", f"- Method: {how}", f"- Average before {_r(before)}, after {_r(after)} (out of {out_of:g})",
             "- New scores: " + ", ".join(f"{s:g}" for s in new)]
    return {"title": "Curved scores", "numbers": numbers, "text": "\n".join(lines)}


def points_plan(questions, total=100.0):
    """How many points each question is worth so the paper totals `total`."""
    q, total = int(questions), float(total)
    if q < 1 or total <= 0:
        raise ValueError("Give the number of questions (1 or more) and a total over 0.")
    each = total / q
    whole = total == int(total) and q and int(total) % q == 0
    numbers = {"points_each": _r(each, 2), "even": bool(whole)}
    text = ["# Points plan", "## Numbers", f"- {q} questions, {total:g} points in all"]
    if whole:
        text.append(f"- {int(each)} points each")
    else:
        base = math.floor(each)
        extra = int(round(total - base * q))
        text.append(f"- {_r(each, 2)} points each does not come out even: give {base} points to {q - extra} questions and {base + 1} points to {extra} questions")
    return {"title": "Points plan", "numbers": numbers, "text": "\n".join(text)}


def reading_level(text):
    from classroom import reading_grade
    words = len(re.findall(r"[A-Za-z']+", text or ""))
    if words < 10:
        raise ValueError("Paste a passage of at least 10 words.")
    g = reading_grade(text)
    shown = max(0.0, g)
    numbers = {"grade": _r(shown), "words": words}
    return {"title": "Reading level", "numbers": numbers,
            "text": "\n".join(["# Reading level", "## Numbers", f"- {words} words, about grade {_r(shown)} (Flesch-Kincaid)",
                               "- This is a guide only: short sentences and short words lower the grade."])}


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
    try:
        return fn(params or {})
    except (TypeError, KeyError, AttributeError) as e:
        raise ValueError("Some of the numbers are missing or not numbers.") from e
