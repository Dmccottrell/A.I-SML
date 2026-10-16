import csv

from grades.book import letter


def to_csv(book, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["student", "average", "letter"])
        for s in book.students():
            avg = book.average(s)
            w.writerow([s, f"{avg:.2f}", letter(avg)])
