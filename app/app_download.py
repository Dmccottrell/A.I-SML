"""
app_download.py - Download a model file that can survive a dropped connection.

WHAT THIS FILE DOES
    Models are hundreds of MB, so downloads break. This one:
      * writes to <file>.part and only renames it to <file> after the SHA-256 matches, so a half-file is never loaded;
      * resumes from the end of the .part file (HTTP "Range"), and starts over if the server can't resume;
      * throws a file away if its checksum is wrong (DownloadCorrupt);
      * reports progress, and on any network error leaves the .part file and raises DownloadInterrupted.

    Where it fits: the app calls download() when the person picks a model to put on their device. A "SHA-256 checksum" is a
    fingerprint of a file's bytes: if even one byte differs, the fingerprint differs, so it proves the file arrived intact.
"""
import hashlib
import http.client
import os
import urllib.error
import urllib.request

from app_errors import DownloadCorrupt, DownloadInterrupted

# How many bytes to read at a time: 1 << 20 means "1 shifted left 20 places" = 2**20 = 1,048,576 bytes (1 MB).
# Reading in pieces keeps memory small even for a multi-gigabyte file.
CHUNK = 1 << 20


def sha256_of(path):
    """Return the SHA-256 fingerprint (as a lowercase hex string) of the file at `path`.

    The file is read one CHUNK at a time so a huge model never has to fit in memory all at once."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        # `:=` (the "walrus") assigns and tests in one step: keep looping until read() returns empty bytes (end of file).
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, sha256, progress=None, timeout=20, headers=None):
    """Download url to dest. `sha256` is required (an unchecked model file is never accepted).
    progress(done_bytes, total_bytes_or_None) is called after each chunk.

    In: the web address, the final file path, the expected checksum, an optional progress callback, a network timeout in
    seconds, and optional extra HTTP headers. Out: `dest` once the file is complete and verified.
    Raises: ValueError (no checksum given), DownloadInterrupted (network trouble; the .part file is kept so it can resume),
    DownloadCorrupt (checksum mismatch; the bad file is deleted)."""
    if not sha256:
        raise ValueError("a checksum is required: put the file's sha256 in models.json")
    # If the finished file is already there and its fingerprint matches, there is nothing to do.
    if os.path.exists(dest) and sha256_of(dest) == sha256.lower():
        return dest                                                   # already have it
    # Downloads go into "<name>.part" so a half-downloaded file can never be mistaken for a real model.
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    # If we already hold some bytes, ask the server for only the rest with the HTTP "Range" header ("bytes=N-" = from byte N onward).
    # `{**a, **b}` merges two dicts into one.
    req = urllib.request.Request(url, headers={**(headers or {}), **({"Range": f"bytes={have}-"} if have else {})})
    total = None
    try:
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            # HTTP 416 means "the range you asked for is past the end of the file": we already have every byte.
            if e.code != 416:
                raise
            r = None                                                  # the .part file is already complete
        if r is not None:
            with r:
                # 206 = "Partial Content" (the server honoured our Range). Any other status means it sent the whole file again,
                # so throw away our idea of what we have and rewrite from the start.
                if have and r.status != 206:
                    have = 0                                          # no resume support: start again
                # Content-Length is how many bytes are coming in THIS response (only the rest, when resuming).
                length = r.headers.get("Content-Length")
                total = have + int(length) if length else None
                # "ab" appends to the existing .part file; "wb" starts a fresh one.
                with open(part, "ab" if have else "wb") as f:
                    while chunk := r.read(CHUNK):
                        f.write(chunk)
                        have += len(chunk)
                        if progress:
                            progress(have, total)
                # The server closed the connection early: we got fewer bytes than promised, so report it as interrupted.
                if total is not None and have < total:
                    raise DownloadInterrupted(have, total)
    except DownloadInterrupted:
        raise
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        # Any network/disk problem: keep the .part file (so the next try resumes) and tell the person how far we got.
        got = os.path.getsize(part) if os.path.exists(part) else 0
        raise DownloadInterrupted(got, total) from e
    # All bytes are here. Check the fingerprint; a mismatch means a damaged or swapped file, so delete it and start fresh next time.
    if sha256_of(part) != sha256.lower():
        os.remove(part)
        raise DownloadCorrupt()
    # os.replace renames in one step, so `dest` is either the old file or the complete new one, never half-written.
    os.replace(part, dest)
    return dest
