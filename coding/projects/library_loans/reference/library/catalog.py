# The book catalog of the library reference solution: which books exist, how many copies, how many are lent out.
# library/loans.py uses it to decide whether a copy can be borrowed.


class Catalog:
    """Knows each book by its ISBN (the book's unique number) and counts its copies."""

    def __init__(self):
        # books: {isbn: {"title", "copies"}} (how many the library owns); out: {isbn: number currently lent out}.
        self.books, self.out = {}, {}

    def add_book(self, isbn, title, copies=1):
        """Add a book, or add more copies if the ISBN is already known (the original title is kept)."""
        if isbn in self.books:
            self.books[isbn]["copies"] += copies
        else:
            self.books[isbn] = {"title": title, "copies": copies}
            self.out[isbn] = 0

    def _book(self, isbn):
        """Look up a book's record; an unknown ISBN raises KeyError. The leading underscore means 'for internal use'."""
        if isbn not in self.books:
            raise KeyError(isbn)
        return self.books[isbn]

    def title(self, isbn):
        """The book's title (KeyError if the ISBN is unknown)."""
        return self._book(isbn)["title"]

    def available(self, isbn):
        """How many copies are on the shelf right now: copies owned minus copies lent out."""
        return self._book(isbn)["copies"] - self.out[isbn]
