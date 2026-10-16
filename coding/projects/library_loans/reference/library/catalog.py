class Catalog:
    def __init__(self):
        self.books, self.out = {}, {}

    def add_book(self, isbn, title, copies=1):
        if isbn in self.books:
            self.books[isbn]["copies"] += copies
        else:
            self.books[isbn] = {"title": title, "copies": copies}
            self.out[isbn] = 0

    def _book(self, isbn):
        if isbn not in self.books:
            raise KeyError(isbn)
        return self.books[isbn]

    def title(self, isbn):
        return self._book(isbn)["title"]

    def available(self, isbn):
        return self._book(isbn)["copies"] - self.out[isbn]
