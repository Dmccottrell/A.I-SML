import re
from urllib.parse import parse_qs, urlsplit

NOT_FOUND = (404, {"error": "not found"})


def handle(store, method, path, body=None):
    parts = urlsplit(path)
    query = parse_qs(parts.query)
    if parts.path == "/items":
        if method == "GET":
            low = query.get("low")
            return 200, store.list_items(int(low[0]) if low else None)
        if method == "POST":
            body = body or {}
            missing = [k for k in ("name", "qty", "price_cents") if k not in body]
            if missing:
                return 400, {"error": "missing " + ", ".join(missing)}
            try:
                new_id = store.add_item(body["name"], body["qty"], body["price_cents"])
            except ValueError as e:
                return 409, {"error": str(e)}
            return 201, store.get(new_id)
        return NOT_FOUND
    m = re.fullmatch(r"/items/(\d+)", parts.path)
    if not m:
        return NOT_FOUND
    item_id = int(m.group(1))
    if method == "GET":
        item = store.get(item_id)
        return (200, item) if item else NOT_FOUND
    if method == "PATCH":
        try:
            return 200, store.update_qty(item_id, int((body or {}).get("delta", 0)))
        except KeyError:
            return NOT_FOUND
        except ValueError as e:
            return 400, {"error": str(e)}
    if method == "DELETE":
        return (204, None) if store.delete(item_id) else NOT_FOUND
    return NOT_FOUND
