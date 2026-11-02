# Export helper for the gradebook reference solution: writes the class results to a CSV (spreadsheet-style text) file.
import csv

from grades.book import letter


def to_csv(book, path):
    """Write one row per student (name, average, letter grade) to the file at path, with a header row first.

    book is a Gradebook; path is where to write. Students come out in alphabetical order.
    """
    # newline="" is what the csv module asks for, so it controls line endings itself (no blank lines on Windows).
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["student", "average", "letter"])
        for s in book.students():
            avg = book.average(s)
            # Format with exactly 2 decimals ("70.00"); the letter uses the number, not the text.
            w.writerow([s, f"{avg:.2f}", letter(avg)])
