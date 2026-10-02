"""
app_download.py - Download a model file that can survive a dropped connection.

WHAT THIS FILE DOES
    Models are hundreds of MB, so downloads break. This one:
      * writes to <file>.part and only renames it to <file> after the SHA-256 matches, so a half-file is never loaded;
      * resumes from the end of the .part file (HTTP "Range"), and starts over if the server can't resume;
      * throws a file away if its checksum is wrong (DownloadCorrupt);
      * reports progress, and on any network error leaves the .part file and raises DownloadInterrupted.
"""
import hashlib
import http.client
import os
import urllib.error
import urllib.request

from app_errors import DownloadCorrupt, DownloadInterrupted

CHUNK = 1 << 20


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, sha256, progress=None, timeout=20, headers=None):
    """Download url to dest. `sha256` is required (an unchecked model file is never accepted).
    progress(done_bytes, total_bytes_or_None) is called after each chunk."""
    if not sha256:
        raise ValueError("a checksum is required: put the file's sha256 in models.json")
    if os.path.exists(dest) and sha256_of(dest) == sha256.lower():
        return dest                                                   # already have it
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    req = urllib.request.Request(url, headers={**(headers or {}), **({"Range": f"bytes={have}-"} if have else {})})
    total = None
    try:
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code != 416:
                raise
            r = None                                                  # the .part file is already complete
        if r is not None:
            with r:
                if have and r.status != 206:
                    have = 0                                          # no resume support: start again
                length = r.headers.get("Content-Length")
                total = have + int(length) if length else None
                with open(part, "ab" if have else "wb") as f:
                    while chunk := r.read(CHUNK):
                        f.write(chunk)
                        have += len(chunk)
                        if progress:
                            progress(have, total)
                if total is not None and have < total:
                    raise DownloadInterrupted(have, total)
    except DownloadInterrupted:
        raise
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        got = os.path.getsize(part) if os.path.exists(part) else 0
        raise DownloadInterrupted(got, total) from e
    if sha256_of(part) != sha256.lower():
        os.remove(part)
        raise DownloadCorrupt()
    os.replace(part, dest)
    return dest
