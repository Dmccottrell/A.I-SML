# The "web API" layer of the inventory reference solution. It has no real server: handle() takes a method and a
# path (like a web request) and returns (status_code, data), so it is easy to test. It talks to inventory/store.py.
# Status codes used: 200 ok, 201 created, 204 deleted (no content), 400 bad request, 404 not found, 409 conflict.
import re
from urllib.parse import parse_qs, urlsplit

# Reused answer for anything that does not exist or is not allowed.
NOT_FOUND = (404, {"error": "not found"})


def handle(store, method, path, body=None):
    """Answer one request.

    store: a Store. method: "GET", "POST", "PATCH" or "DELETE". path: like "/items", "/items/3" or "/items?low=5".
    body: a dict for POST/PATCH (the JSON a client would send), else None.
    Returns (status, data). Routes: GET/POST /items, and GET/PATCH/DELETE /items/<id>.
    """
    # Split "/items?low=5" into the path part and the query part, and read the query into {"low": ["5"]}.
    parts = urlsplit(path)
    query = parse_qs(parts.query)
    if parts.path == "/items":
        if method == "GET":
            # Optional ?low=N filter: only items with fewer than N in stock.
            low = query.get("low")
            return 200, store.list_items(int(low[0]) if low else None)
        if method == "POST":
            body = body or {}
            # All three fields are required; tell the client which ones are missing.
            missing = [k for k in ("name", "qty", "price_cents") if k not in body]
            if missing:
                return 400, {"error": "missing " + ", ".join(missing)}
            try:
                new_id = store.add_item(body["name"], body["qty"], body["price_cents"])
            except ValueError as e:
                # The name is already taken: 409 means "conflicts with what already exists".
                return 409, {"error": str(e)}
            return 201, store.get(new_id)
        return NOT_FOUND
    # Match paths like /items/12 exactly. The regex (text pattern) \d+ means "one or more digits"; fullmatch means
    # the whole path must fit, so "/items/12/x" or "/items/abc" do not match. group(1) is the digits.
    m = re.fullmatch(r"/items/(\d+)", parts.path)
    if not m:
        return NOT_FOUND
    item_id = int(m.group(1))
    if method == "GET":
        item = store.get(item_id)
        return (200, item) if item else NOT_FOUND
    if method == "PATCH":
        # PATCH changes the stock by body["delta"] (can be negative); a missing delta means 0, i.e. no change.
        try:
            return 200, store.update_qty(item_id, int((body or {}).get("delta", 0)))
        except KeyError:
            return NOT_FOUND
        except ValueError as e:
            # Not enough stock to remove that many.
            return 400, {"error": str(e)}
    if method == "DELETE":
        return (204, None) if store.delete(item_id) else NOT_FOUND
    return NOT_FOUND
