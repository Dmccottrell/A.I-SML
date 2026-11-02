# Number-to-code conversion for the URL shortener reference solution ("url_shortener" exercise).
# A short code is a number written in "base 62" (like binary is base 2): digits, then lowercase letters, then capitals.
# service.py uses encode() to turn a database row number into a code such as "2bj".

# The 62 allowed characters, in value order: "0" is 0, "9" is 9, "a" is 10, "z" is 35, "A" is 36, "Z" is 61.
ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def encode(n):
    """Turn a whole number >= 0 into a base-62 code string (0 gives "0", 62 gives "10"). Anything else raises ValueError."""
    if not isinstance(n, int) or n < 0:
        raise ValueError("n must be a non-negative int")
    if n == 0:
        return ALPHABET[0]
    out = ""
    while n:
        # divmod gives (n // 62, n % 62): the rest is the last "digit", the quotient is what is left to convert.
        n, r = divmod(n, 62)
        # Digits come out last-first, so each new one is put at the front.
        out = ALPHABET[r] + out
    return out


def decode(s):
    """Turn a base-62 code string back into its number. Empty text or a character outside ALPHABET raises ValueError."""
    if not s:
        raise ValueError("empty code")
    n = 0
    for ch in s:
        # find() returns -1 when the character is not in ALPHABET.
        i = ALPHABET.find(ch)
        if i < 0:
            raise ValueError(f"bad character {ch!r}")
        # Shift what we have one place left (times 62) and add the new digit.
        n = n * 62 + i
    return n
