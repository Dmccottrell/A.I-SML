"""
benchmarks.py - Download and cache public AI test sets.

WHAT THIS FILE DOES
    Two well-known tests are used in this project:
      * HellaSwag (validation, 10,042 questions): pick the sensible ending of
        an everyday situation out of 4 choices. Random guessing scores 25%.
        Used by exam.py and by train.py's mini-exam.
      * GSM8K (test, 1,319 questions): grade-school math word problems.

    prepare_web_data.py also uses both to REMOVE any training document that
    contains a test question ("decontamination"), so the scores stay fair.

    Files are downloaded once into data/benchmarks/ and reused after that.

USED BY
    exam.py, train.py, prepare_web_data.py
"""
import json
import os
import urllib.request

CACHE_DIR = os.path.join("data", "benchmarks")

HELLASWAG_URL = "https://raw.githubusercontent.com/rowanz/hellaswag/master/data/hellaswag_val.jsonl"
GSM8K_URL = "https://raw.githubusercontent.com/openai/grade-school-math/master/grade_school_math/data/test.jsonl"


def _download(url, path):
    """Download `url` to `path` (via a temporary file, so a failed download leaves nothing)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        f.write(r.read())
    os.replace(tmp, path)


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_hellaswag(cache_dir=CACHE_DIR):
    """HellaSwag validation set as a list of {"ctx", "endings", "label"} dicts.

    Uses the Hugging Face copy (the original GitHub file is no longer
    available), with the GitHub URL as a fallback.
    """
    path = os.path.join(cache_dir, "hellaswag_val.jsonl")
    if not os.path.exists(path):
        try:
            from datasets import load_dataset
            ds = load_dataset("Rowan/hellaswag", split="validation")
            os.makedirs(cache_dir, exist_ok=True)
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                for row in ds:
                    f.write(json.dumps({"ctx": row["ctx"], "endings": row["endings"],
                                        "label": int(row["label"])}) + "\n")
            os.replace(path + ".tmp", path)
        except Exception:
            _download(HELLASWAG_URL, path)
    return [{"ctx": r["ctx"], "endings": r["endings"], "label": int(r["label"])}
            for r in _read_jsonl(path)]


def load_gsm8k(cache_dir=CACHE_DIR):
    """GSM8K test set as a list of {"question", "answer"} dicts."""
    path = os.path.join(cache_dir, "gsm8k_test.jsonl")
    if not os.path.exists(path):
        try:
            _download(GSM8K_URL, path)
        except Exception:
            from datasets import load_dataset   # fallback: the Hugging Face copy
            ds = load_dataset("openai/gsm8k", "main", split="test")
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                for row in ds:
                    f.write(json.dumps({"question": row["question"], "answer": row["answer"]}) + "\n")
    return _read_jsonl(path)


def test_texts(cache_dir=CACHE_DIR):
    """Every test passage that must NOT appear in training data (for decontamination)."""
    texts = [ex["ctx"] + " " + ex["endings"][ex["label"]] for ex in load_hellaswag(cache_dir)]
    texts += [ex["question"] for ex in load_gsm8k(cache_dir)]
    return texts
