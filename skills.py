"""
skills.py - Skill packs: small add-ons (LoRA, see lora.py) that make the chat model a specialist.

WHAT THIS FILE DOES
    A skill pack is a small file of extra weights (~19 MB for v3) trained for one job, on top of a finished chat model
    (chat.pt). v4 plans six (study, stories, IT help, fact checking, documents, coding) and a router
    that picks one per message. This file holds:

      SKILLS       what each pack is: its name, what it does, words that suggest it (for the router),
                   and whether it is ready or still a Beta
      save_pack / load_pack   the pack file: <ckpt_dir>/skills/<name>.pt
      route()      the Beta router: picks a pack for a message by its words (v4 replaces this with a
                   small trained classifier)

    The first pack is the **Study helper (Beta)**, trained and tested on v3 so the recipe is proven
    before v4. A pack only fits the model it was trained on: v4's brain gets its own packs (retraining
    takes under an hour each), from the same data.

    Build and train one (details in docs/SKILLS.md):
        python make_teacher_data.py --task study --n 3000        (the teacher writes lessons)
        python make_skill_data.py --version v3 --skill study      (lessons -> training file)
        python train_skill.py --version v3 --skill study          (trains the pack)
        python skill_test.py --version v3 --skill study           (with vs without the pack)
        python generate.py --version v3 --chat --skill study      (or --skill auto)
"""
import hashlib
import os
import re
from dataclasses import dataclass, field

import torch

from lora import add_lora, has_lora, load_lora_state_dict, lora_state_dict, set_lora_enabled


@dataclass
class Skill:
    name: str
    title: str
    what: str
    status: str                       # "beta" (being tried on v3) or "planned" (v4)
    words: tuple = ()                 # words that suggest this skill (router, Beta)
    phrases: tuple = ()               # (regex, points): question shapes and strong phrases
    rank: int = 16
    alpha: int = 32
    extra: dict = field(default_factory=dict)


SKILLS = {
    "study": Skill(
        "study", "Study helper",
        "Explains school topics step by step at the student's level, gives an example, then asks a "
        "quick check question and gives feedback on the answer",
        "beta",
        words=("explain", "understand", "homework", "study", "studying", "test", "exam", "quiz", "learn",
               "learning", "teach", "lesson", "class", "school", "grade", "chapter", "formula", "equation",
               "solve", "math", "algebra", "geometry", "fraction", "fractions", "science", "biology",
               "chemistry", "physics", "history", "geography", "grammar", "essay", "definition", "define",
               "photosynthesis", "cell", "cells", "atom", "molecule", "planet", "revolution", "war", "theorem",
               "heart", "blood", "body", "energy", "force", "plants", "earth", "moon", "sun", "government",
               "equations", "numbers", "percent", "percentages", "simile", "metaphor", "noun", "verb",
               "seasons", "weather", "sky", "law", "laws", "motion", "gravity", "volcano", "continent"),
        # (pattern, points): a question shape alone is 1 point, so "what is your name?" stays plain chat;
        # a shape plus a school word, or a strong phrase ("help me study", an equation), reaches 2
        phrases=((r"\bhow (do|does) .+ work\b", 2), (r"\bwhat (is|are) (a|an|the)?\s*\w+", 1),
                 (r"\bhow (do|does)\b", 1), (r"\bwhy (do|does|is|are|did)\b", 1),
                 (r"\bwhat (caused|causes|happened)\b", 1), (r"\bdifference between\b", 2),
                 (r"\bhow (do|can) (i|you|we) (solve|find|calculate|work out|figure out)\b", 2),
                 (r"\d\s*[a-z]?\s*[-+*/=^]\s*\d", 2),
                 (r"\bhelp me (understand|study|learn|with my)\b", 2), (r"\bi (don't|do not) (get|understand)\b", 2),
                 (r"\bstep by step\b", 2), (r"\bquiz me\b", 2), (r"\bexplain\b", 1))),
    # Planned for v4 (listed so the router and docs know them; no data or training yet)
    "stories": Skill("stories", "Story writer", "Creative writing and stories", "planned",
                     words=("story", "poem", "write", "character", "tale", "once")),
    "it": Skill("it", "IT helper", "Printers, Wi-Fi, networks and troubleshooting steps", "planned",
                words=("printer", "wifi", "wi-fi", "router", "network", "laptop", "windows", "error",
                       "install", "driver", "password", "email", "slow", "crash")),
    "facts": Skill("facts", "Fact checker", "Looks things up and cites the source", "planned",
                   words=("true", "fact", "source", "check", "really", "verify")),
    "docs": Skill("docs", "Document helper", "Summaries, rewrites, drafts and to-do lists", "planned",
                  words=("summarize", "summary", "rewrite", "draft", "letter", "to-do", "notes", "email")),
    "coding": Skill("coding", "Coding helper", "Small coding tasks in a loop with tests", "planned",
                    words=("code", "python", "function", "bug", "script", "javascript", "html", "error")),
}

PACK_FORMAT = 1


def pack_path(ckpt_dir, name):
    return os.path.join(ckpt_dir, "skills", f"{name}.pt")


def base_fingerprint(model):
    """A short ID of the model's weights, so a pack is never silently used on a different model."""
    h = hashlib.sha256()
    for name, p in sorted(model.state_dict().items()):
        if "lora_" in name:
            continue
        t = p.detach().float().flatten()
        idx = torch.linspace(0, t.numel() - 1, steps=min(64, t.numel())).long()
        h.update(name.replace(".base.", ".").encode())
        h.update(t[idx].cpu().numpy().tobytes())
    return h.hexdigest()[:16]


def save_pack(model, path, skill, base_path, fingerprint, info=None):
    """Save only the add-on weights plus what's needed to check them later."""
    s = SKILLS[skill]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = {"format": PACK_FORMAT, "skill": skill, "title": s.title, "status": s.status,
            "lora": {k: v.to(torch.bfloat16) for k, v in lora_state_dict(model).items()},   # bf16: half the size
            "rank": s.rank, "alpha": s.alpha,
            "base": os.path.basename(base_path), "base_fingerprint": fingerprint,
            "config": model.cfg.__dict__, "info": info or {}}
    tmp = path + ".tmp"
    torch.save(data, tmp)
    os.replace(tmp, path)


def read_pack(path):
    if not os.path.exists(path):
        raise SystemExit(f"skill pack not found: {path}\nTrain it first: python train_skill.py --skill <name> "
                         "(see docs/SKILLS.md)")
    pack = torch.load(path, map_location="cpu")
    if pack.get("format") != PACK_FORMAT:
        raise SystemExit(f"{path}: unknown skill pack format {pack.get('format')}")
    return pack


def load_pack(model, path, strict_base=True):
    """Add the pack's add-ons to `model` (once) and load its weights. Returns the pack's info dict.

    Refuses a pack made for a different model size, and (strict_base) one trained on different weights:
    a v3 pack on v4 would load but give nonsense, so v4 gets its own packs.
    """
    pack = read_pack(path)
    if pack["config"] != model.cfg.__dict__:
        raise SystemExit(f"{path} was trained for a different model shape; retrain it for this model")
    fp = base_fingerprint(model)
    if strict_base and pack["base_fingerprint"] != fp:
        raise SystemExit(f"{path} was trained on a different {pack['base']} (fingerprint "
                         f"{pack['base_fingerprint']}, this model {fp}). Retrain the pack for this model, "
                         "or pass --any_base to try it anyway.")
    if not has_lora(model):
        add_lora(model, pack["rank"], pack["alpha"])
    load_lora_state_dict(model, pack["lora"])
    set_lora_enabled(model, True)
    model.eval()
    return pack


class SkillSwitcher:
    """Several packs on one model: keeps each pack's weights and swaps them in per message.

    Swapping copies a few MB, so it's instant. use(None) switches the add-ons off (the plain model).
    """

    def __init__(self, model, ckpt_dir, names, strict_base=True):
        self.model, self.packs, self.titles, self.current = model, {}, {}, "(not set)"
        for name in names:
            pack = load_pack(model, pack_path(ckpt_dir, name), strict_base)
            self.packs[name] = pack["lora"]
            self.titles[name] = f"{pack['title']}" + (" (Beta)" if pack.get("status") == "beta" else "")
        self.use(None)

    def use(self, name):
        if name == self.current:
            return
        if name is None:
            set_lora_enabled(self.model, False)
        else:
            load_lora_state_dict(self.model, self.packs[name])
            set_lora_enabled(self.model, True)
        self.current = name


def trained_skills(ckpt_dir):
    """Names of skills that have a pack file for this version."""
    return [n for n in SKILLS if os.path.exists(pack_path(ckpt_dir, n))]


# ------------------------------------------------------------------ who may use which pack (the access toggle)
# Each pack has a switch: "everyone", "beta" (only people on the beta list) or "off" (nobody). Beta packs
# start as "beta", planned ones as "off". The owner (you, on your own PC: user "owner") can always use every
# trained pack, so you can test a Beta before anyone else. The app will read the same file with each
# signed-in user's name, so turning a pack on for testers, for everyone, or off is one command.
ACCESS_PATH = os.path.join("data", "skills_access.json")
ACCESS_LEVELS = ("everyone", "beta", "off")
OWNER = "owner"


def default_access():
    return {"skills": {n: ("beta" if s.status == "beta" else "everyone" if s.status == "ready" else "off")
                       for n, s in SKILLS.items()},
            "beta_users": []}


def load_access(path=ACCESS_PATH):
    """The access settings: saved choices on top of the defaults (a new skill starts at its default)."""
    access = default_access()
    if os.path.exists(path):
        import json
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        access["skills"].update({k: v for k, v in saved.get("skills", {}).items() if k in SKILLS and v in ACCESS_LEVELS})
        access["beta_users"] = sorted(set(saved.get("beta_users", [])))
    return access


def save_access(access, path=ACCESS_PATH):
    import json
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(access, f, indent=1)
    os.replace(path + ".tmp", path)


def can_use(skill, user, access):
    """May `user` use this skill's pack?"""
    if user == OWNER:
        return True
    level = access["skills"].get(skill, "off")
    return level == "everyone" or (level == "beta" and user in access["beta_users"])


def allowed_skills(names, user, access):
    return [n for n in names if can_use(n, user, access)]


def access_command(args, path=ACCESS_PATH):
    """`python skills.py access ...` / `python skills.py beta ...`: show or change who may use which pack."""
    access = load_access(path)
    if args[:1] == ["access"] and len(args) == 3:
        skill, level = args[1], args[2]
        if skill not in SKILLS or level not in ACCESS_LEVELS:
            return f"usage: access <{'|'.join(SKILLS)}> <{'|'.join(ACCESS_LEVELS)}>"
        access["skills"][skill] = level
        save_access(access, path)
    elif args[:1] == ["beta"] and len(args) == 3 and args[1] in ("add", "remove"):
        users = set(access["beta_users"])
        (users.add if args[1] == "add" else users.discard)(args[2])
        access["beta_users"] = sorted(users)
        save_access(access, path)
    elif args not in (["access"], []):
        return ("usage: python skills.py access                      (show)\n"
                "       python skills.py access study beta|everyone|off\n"
                "       python skills.py beta add|remove <user>")
    rows = [f"  {SKILLS[n].title:16s} {n:8s} {SKILLS[n].status:8s} -> {lvl}" for n, lvl in access["skills"].items()]
    return ("who can use each skill pack (the owner can always use every trained pack):\n" + "\n".join(rows)
            + f"\nbeta testers: {', '.join(access['beta_users']) or '(none)'}")


# ------------------------------------------------------------------ the Beta router
def score_message(text, skill):
    """How strongly `text` suggests `skill` (0 = not at all)."""
    s = SKILLS[skill]
    low = text.lower()
    words = set(re.findall(r"[a-z][a-z'-]*", low))
    score = sum(1 for w in s.words if w in words)
    score += sum(pts for pat, pts in s.phrases if re.search(pat, low))
    return score


def route(text, available, threshold=2):
    """The skill to use for this message, or None (plain chat model).

    Only skills in `available` (packs that are loaded) can be picked. A message needs a score of at
    least `threshold` so small talk ("hi", "thanks") stays with the plain model.
    """
    best, best_score = None, 0
    for name in available:
        sc = score_message(text, name)
        if sc > best_score:
            best, best_score = name, sc
    return best if best_score >= threshold else None


if __name__ == "__main__":
    import sys
    print(access_command(sys.argv[1:]))
