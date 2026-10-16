ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def encode(n):
    if not isinstance(n, int) or n < 0:
        raise ValueError("n must be a non-negative int")
    if n == 0:
        return ALPHABET[0]
    out = ""
    while n:
        n, r = divmod(n, 62)
        out = ALPHABET[r] + out
    return out


def decode(s):
    if not s:
        raise ValueError("empty code")
    n = 0
    for ch in s:
        i = ALPHABET.find(ch)
        if i < 0:
            raise ValueError(f"bad character {ch!r}")
        n = n * 62 + i
    return n
