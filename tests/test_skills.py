"""Tests for lora.py, skills.py, train_skill.py, make_skill_data.py, skill_test.py and the study teacher task.
Run:  python -m unittest tests.test_skills -v"""
import json
import os
import random
import shutil
import sys
import tempfile
import types
import unittest

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lora as L
import make_skill_data as MSD
import make_teacher_data as MT
import skill_test as ST
import classroom as C
import export_doc as E
import skills as S
import train_skill as TS
from chat import encode_conversation, normalize, special_ids
from model import ModelConfig, TinyLM, load_checkpoint
from tests.test_context_meter import make_tok

NO_AUTOCAST = torch.autocast(device_type="cpu", enabled=False)


def tiny(tok=None, seed=0):
    torch.manual_seed(seed)
    cfg = ModelConfig(vocab_size=tok.vocab_size if tok else 300, dim=32, n_layers=2, n_heads=4, n_kv_heads=2,
                      hidden_dim=64, max_seq_len=96)
    return TinyLM(cfg).eval()


def poke(model, seed=1):
    """Give every add-on some non-zero weights (as if trained)."""
    g = torch.Generator().manual_seed(seed)
    for m in L.lora_layers(model).values():
        m.lora_B.data = torch.randn(m.lora_B.shape, generator=g) * 0.05


class LoRA(unittest.TestCase):
    def setUp(self):
        self.x = torch.randint(0, 300, (2, 20))

    def test_a_fresh_addon_changes_nothing(self):
        m = tiny()
        before = m(self.x)[0]
        n = L.add_lora(m, rank=4, alpha=8)
        self.assertEqual(n, sum(p.numel() for p in L.lora_parameters(m)) if hasattr(L, "lora_parameters")
                         else sum(p.numel() for p in TS.lora_parameters(m)))
        self.assertTrue(torch.allclose(before, m(self.x)[0], atol=1e-6))
        self.assertEqual(len(L.lora_layers(m)), 2 * 7)                    # 7 projections per block

    def test_only_the_addons_train(self):
        m = tiny()
        L.add_lora(m, rank=4, alpha=8)
        trainable = {n for n, p in m.named_parameters() if p.requires_grad}
        self.assertTrue(trainable)
        self.assertTrue(all("lora_" in n for n in trainable))

    def test_switching_off_gives_the_plain_model(self):
        m = tiny()
        plain = m(self.x)[0]
        L.add_lora(m, rank=4, alpha=8)
        poke(m)
        self.assertFalse(torch.allclose(plain, m(self.x)[0], atol=1e-4))
        L.set_lora_enabled(m, False)
        self.assertTrue(torch.allclose(plain, m(self.x)[0], atol=1e-6))

    def test_merging_gives_the_same_answers_and_the_original_names(self):
        m = tiny()
        names = set(m.state_dict())
        L.add_lora(m, rank=4, alpha=8)
        poke(m)
        with_addon = m(self.x)[0]
        L.merge_lora(m)
        self.assertFalse(L.has_lora(m))
        self.assertEqual(set(m.state_dict()), names)
        self.assertTrue(torch.allclose(with_addon, m(self.x)[0], atol=1e-5))

    def test_generation_with_the_kv_cache_works(self):
        m = tiny()
        L.add_lora(m, rank=4, alpha=8)
        poke(m)
        out = m.generate(self.x[:1, :5], 6, temperature=0.8, top_k=10)
        self.assertEqual(out.shape, (1, 11))


class Packs(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        self.x = torch.randint(0, 300, (1, 16))

    def trained_pack(self, name="study", seed=1):
        m = tiny()
        fp = S.base_fingerprint(m)
        L.add_lora(m, S.SKILLS[name].rank, S.SKILLS[name].alpha)
        poke(m, seed)
        path = S.pack_path(self.d, name)
        S.save_pack(m, path, name, "chat.pt", fp, {"note": "test"})
        return m, path

    def test_save_and_load_gives_the_same_model(self):
        m, path = self.trained_pack()
        m.eval()
        fresh = tiny()
        pack = S.load_pack(fresh, path)
        self.assertEqual(pack["skill"], "study")
        self.assertEqual(pack["status"], "beta")
        self.assertTrue(torch.allclose(m(self.x)[0], fresh(self.x)[0], atol=2e-2))   # saved in bf16
        self.assertLess(os.path.getsize(path), 400_000)

    def test_a_pack_refuses_a_different_model(self):
        _, path = self.trained_pack()
        with self.assertRaises(SystemExit):
            S.load_pack(tiny(seed=7), path)                                # other weights (e.g. v4's brain)
        S.load_pack(tiny(seed=7), path, strict_base=False)                 # --any_base: allowed
        other = TinyLM(ModelConfig(vocab_size=300, dim=48, n_layers=2, n_heads=4, n_kv_heads=2, hidden_dim=96,
                                   max_seq_len=96))
        with self.assertRaises(SystemExit):
            S.load_pack(other, path, strict_base=False)                    # other size: never

    def test_the_switcher_swaps_packs_per_message(self):
        a, _ = self.trained_pack("study", 1)
        b, _ = self.trained_pack("stories", 2)
        a.eval(); b.eval()
        plain = tiny()
        want_plain = plain(self.x)[0]
        sw = S.SkillSwitcher(plain, self.d, ["study", "stories"])
        self.assertEqual(sw.titles["study"], "Study helper (Beta)")
        self.assertTrue(torch.allclose(plain(self.x)[0], want_plain, atol=1e-6))
        sw.use("study")
        self.assertTrue(torch.allclose(plain(self.x)[0], a(self.x)[0], atol=2e-2))
        sw.use("stories")
        self.assertTrue(torch.allclose(plain(self.x)[0], b(self.x)[0], atol=2e-2))
        sw.use(None)
        self.assertTrue(torch.allclose(plain(self.x)[0], want_plain, atol=1e-6))
        self.assertEqual(S.trained_skills(self.d), ["study", "stories"])


class Router(unittest.TestCase):
    def test_school_questions_go_to_study_and_small_talk_doesnt(self):
        for msg in ("Can you explain photosynthesis?", "I don't understand fractions",
                    "How do I solve 2x + 3 = 11?", "help me study for my history test"):
            self.assertEqual(S.route(msg, ["study"]), "study", msg)
        for msg in ("hi", "thanks!", "what is your name?", "tell me a joke", "My printer says offline"):
            self.assertIsNone(S.route(msg, ["study"]), msg)

    def test_only_loaded_packs_can_be_picked(self):
        self.assertIsNone(S.route("Can you explain photosynthesis?", []))

    def test_the_test_sheets_route_correctly_with_both_packs(self):
        for sheet in ("study", "teacher"):
            with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "eval", "skills", f"{sheet}.jsonl")) as f:
                tests = [json.loads(l) for l in f if l.strip()]
            right, total, wrong = ST.router_report(tests, ["study", "teacher"])
            self.assertEqual(right, total, wrong)

    def test_teacher_requests_go_to_the_teacher_pack(self):
        rng = random.Random(1)
        for _ in range(60):
            msg, spec = C.teacher_request(rng)
            self.assertEqual(S.route(msg, ["study", "teacher"]), "teacher", msg)


GOOD = {"question": "What is a fraction?",
        "answer": "A fraction shows part of a whole. The bottom number says how many equal parts the whole has, "
                  "and the top number says how many parts you have.\nFor example, if a pizza is cut into 4 equal "
                  "slices and you eat 1, you ate 1/4 of the pizza. If you eat 3 slices, you ate 3/4.\n"
                  "Fractions with the same bottom number are easy to compare: 3/4 is more than 1/4 because 3 "
                  "parts are more than 1 part of the same size.\nQuick check: If a cake has 8 slices and you eat 3, "
                  "what fraction did you eat?",
        "student_reply": "3/8", "feedback": "That's right! 3 slices out of 8 equal slices is 3/8."}


class StudyLessons(unittest.TestCase):
    def test_a_good_lesson_passes(self):
        self.assertTrue(MT.good_study_lesson(dict(GOOD), True))

    def test_lessons_that_break_the_format_are_thrown_away(self):
        no_check = dict(GOOD, answer=GOOD["answer"].replace("Quick check:", "Question:"))
        self.assertFalse(MT.good_study_lesson(no_check, True))
        self.assertFalse(MT.good_study_lesson(dict(GOOD, answer="Too short. Quick check: ok?"), True))
        self.assertFalse(MT.good_study_lesson(dict(GOOD), False))            # feedback says right, should be wrong
        wrong = dict(GOOD, student_reply="8/3", feedback="Not quite: the bottom number is the 8 slices, so it's 3/8.")
        self.assertTrue(MT.good_study_lesson(wrong, False))
        self.assertFalse(MT.good_study_lesson(dict(GOOD, feedback="As an AI, I think that's right."), True))
        self.assertFalse(MT.good_study_lesson(None, True))

    def test_prompts_vary_and_follow_the_level(self):
        rng = random.Random(3)
        seen = set()
        for _ in range(30):
            prompt, correct, info = MT.study_prompt(rng)
            seen.add(info["subject"])
            self.assertIn(MT.LEVELS[info["level"]], prompt)
            self.assertIn("Quick check:", prompt)
            self.assertIn("correct" if correct else "wrong", prompt)
        self.assertGreaterEqual(len(seen), 4)
        self.assertIn("study", MT.TASKS)


class SkillData(unittest.TestCase):
    def test_build_mixes_replay_into_training_only(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        chat_path = os.path.join(d, "chat.jsonl")
        with open(chat_path, "w") as f:
            for i in range(100):
                f.write(json.dumps({"messages": [{"role": "user", "content": f"hi {i}"},
                                                 {"role": "assistant", "content": "hello"}]}) + "\n")
        lessons = [dict(GOOD, i=i) for i in range(80)]
        train, val = MSD.build("study", lessons, chat_path, random.Random(0), replay=0.2)
        self.assertEqual(len(val), 4)
        self.assertTrue(all(r["kind"].startswith("study") for r in val))
        n_replay = sum(r["kind"] == "replay" for r in train)
        self.assertAlmostEqual(n_replay / len(train), 0.2, delta=0.02)
        follow = [r for r in train if r["kind"] == "study_followup"]
        self.assertTrue(follow and all(len(r["messages"]) == 4 for r in follow))
        self.assertTrue(any(r["kind"] == "study" for r in train))
        with self.assertRaises(SystemExit):
            MSD.build("coding", lessons, chat_path, random.Random(0))


class Training(unittest.TestCase):
    def test_the_pack_learns_the_skill_and_the_model_is_untouched(self):
        tok = make_tok()
        m = tiny(tok)
        base = {k: v.clone() for k, v in m.state_dict().items()}
        _, _, eot = special_ids(tok)
        chats = [[{"role": "user", "content": f"the cat {i % 4}"},
                  {"role": "assistant", "content": "the fox jumps over the lazy dog"}] for i in range(32)]
        ex = [encode_conversation(tok, normalize({"messages": c}), 97) for c in chats]
        L.add_lora(m, rank=8, alpha=16)
        before = TS.val_loss(m, ex[:8], eot, "cpu", NO_AUTOCAST)
        _, hist = TS.train_pack(m, ex, ex[:8], eot, "cpu", NO_AUTOCAST, epochs=10, batch_size=4, lr=1e-2,
                                log=lambda *_: None)
        self.assertLess(hist[-1][1], before - 0.5)
        for name, v in m.state_dict().items():
            if "lora_" not in name:
                self.assertTrue(torch.equal(v, base[name.replace(".base.", ".")]), name)

    def test_the_whole_pipeline_on_a_tiny_model(self):
        """make_skill_data -> train_skill (with --merge) -> the pack and the merged checkpoint load."""
        tok = make_tok()
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        tok.save(os.path.join(d, "tokenizer.json"))
        m = tiny(tok)
        torch.save({"model": m.state_dict(), "config": m.cfg.__dict__}, os.path.join(d, "chat.pt"))
        os.makedirs(os.path.join(d, "teacher"))
        short = dict(GOOD, answer="the cat sat on the mat\nFor example the fox\nQuick check: the dog?",
                     feedback="the lazy dog")
        with open(os.path.join(d, "teacher", "study.jsonl"), "w") as f:
            for i in range(40):
                f.write(json.dumps(dict(short, i=i, question=f"the cat {i}")) + "\n")
        import config
        V = types.SimpleNamespace(name="vt", data_dir=d, ckpt_dir=d)
        saved, argv = config.get_version, sys.argv
        config.get_version = lambda n: V
        MSD.get_version = config.get_version
        try:
            sys.argv = ["make_skill_data.py", "--version", "v1", "--skill", "study"]
            MSD.main()
            sys.argv = ["train_skill.py", "--version", "v1", "--skill", "study", "--epochs", "2", "--batch_size", "8",
                        "--lr", "2e-3", "--rank", "4", "--merge"]
            TS.main()
        finally:
            config.get_version, sys.argv = saved, argv
            MSD.get_version = saved
            S.SKILLS["study"].rank, S.SKILLS["study"].alpha = 16, 32
        pack = torch.load(S.pack_path(d, "study"))
        self.assertLess(pack["info"]["val_loss_pack"], pack["info"]["val_loss_plain"])
        self.assertFalse(os.path.exists(os.path.join(d, "skills", "study_latest.pt")))
        merged, _ = load_checkpoint(os.path.join(d, "chat_study.pt"))
        on = load_checkpoint(os.path.join(d, "chat.pt"))[0]
        S.load_pack(on, S.pack_path(d, "study"))
        x = torch.randint(0, tok.vocab_size, (1, 12))
        self.assertTrue(torch.allclose(merged(x)[0], on(x)[0], atol=5e-2))


class Access(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        self.path = os.path.join(d, "skills_access.json")

    def test_defaults_beta_for_testers_only_planned_off(self):
        a = S.load_access(self.path)
        self.assertEqual(a["skills"]["study"], "beta")
        self.assertEqual(a["skills"]["coding"], "off")
        self.assertTrue(S.can_use("study", S.OWNER, a))                    # the owner can always test it
        self.assertFalse(S.can_use("study", "sam", a))
        self.assertEqual(S.allowed_skills(["study", "coding"], "sam", a), [])

    def test_toggles_and_the_beta_list(self):
        S.access_command(["beta", "add", "sam"], self.path)
        a = S.load_access(self.path)
        self.assertTrue(S.can_use("study", "sam", a))
        self.assertFalse(S.can_use("study", "alex", a))
        S.access_command(["access", "study", "everyone"], self.path)
        self.assertTrue(S.can_use("study", "alex", S.load_access(self.path)))
        S.access_command(["access", "study", "off"], self.path)
        a = S.load_access(self.path)
        self.assertFalse(S.can_use("study", "sam", a))
        self.assertTrue(S.can_use("study", S.OWNER, a))
        S.access_command(["beta", "remove", "sam"], self.path)
        self.assertEqual(S.load_access(self.path)["beta_users"], [])
        self.assertIn("usage", S.access_command(["access", "study", "maybe"], self.path))
        self.assertIn("Study helper", S.access_command(["access"], self.path))


class Checks(unittest.TestCase):
    def test_study_answer_checks(self):
        r = ST.study_checks(GOOD["answer"], True)
        self.assertEqual(r, {"quick check": True, "example": True, "length": True, "finished": True})
        r = ST.study_checks("Photosynthesis is how plants make food.", False)
        self.assertFalse(r["quick check"] or r["example"] or r["length"] or r["finished"])
        steps = "1. Subtract 5 from both sides.\n2. Divide by 3.\n" + "word " * 40 + "\nQuick check: what is x?"
        self.assertTrue(ST.study_checks(steps, True)["example"])
        self.assertEqual(ST.summarize([{"a": True}, {"a": False}]), {"a": 0.5})
        self.assertEqual(ST.summarize([{"a": True}, {"a": False, "b": True}]), {"a": 0.5, "b": 1.0})
        r = ST.teacher_checks(WORKSHEET, True, {"spec": {"type": "worksheet", "n": 4}})
        self.assertTrue(all(r.values()), r)


WORKSHEET = """# Multiplication Facts: 6s
Grade 3 - Math - Worksheet
Instructions: Solve each problem.
## Questions
1. 6 × 4 = ____
2. What is 42 ÷ 6?
3. There are 6 boxes with 3 crayons in each box. How many crayons are there in all?
4. 6 x 9 = ____
## Answer key
1. 24
2. 7
3. 18 crayons
4. 54"""

READING = """# The Busy Bees
Grade 3 - Reading
Bees live in a home called a hive. A hive can have many bees. Each bee has a job. Some bees look for
flowers. They drink the sweet juice inside. It is called nectar. The bees take the nectar back to the hive.
They make honey from it. Other bees keep the hive clean. One big bee is the queen. She lays the eggs. Bees
help plants too. They carry pollen from flower to flower. This helps new seeds grow. Next time you see a
bee, let it work. It is very busy!
## Questions
1. What is a bee's home called?
2. What do bees make honey from?
3. How do bees help plants?
## Answer key
1. A hive.
2. Nectar from flowers.
3. They carry pollen from flower to flower."""


class Export(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)

    def test_parse_finds_the_title_questions_and_key(self):
        doc = E.parse(WORKSHEET)
        self.assertEqual(doc.title, "Multiplication Facts: 6s")
        self.assertTrue(doc.for_students)
        self.assertEqual(len(doc.items("questions")), 4)
        self.assertEqual(doc.items("key"), ["24", "7", "18 crayons", "54"])
        email = E.parse("# Field trip\nDear Families,\nWe are going.\nThank you,\n[Teacher name]")
        self.assertFalse(email.for_students)

    def test_pdf_has_the_key_on_its_own_page(self):
        path = E.export(WORKSHEET, os.path.join(self.d, "ws.pdf"))
        with open(path, "rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(data.count(b"/Type /Page\n") + data.count(b"/Type /Page\r") + data.count(b"/Type /Page "), 2)

    def test_word_file_and_text_formats(self):
        from docx import Document
        path = E.export(WORKSHEET, os.path.join(self.d, "ws.docx"))
        doc = Document(path)
        text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("Name:", text)
        self.assertIn("Answer key", text)
        self.assertIn("w:br", doc.element.xml.split("Answer key")[0][-3000:])          # page break before the key
        md = open(E.export(WORKSHEET, os.path.join(self.d, "ws.md"))).read()
        self.assertIn("## Answer key", md)
        with self.assertRaises(ValueError):
            E.export(WORKSHEET, os.path.join(self.d, "ws.exe"))

    def test_odd_characters_and_safe_names(self):
        E.export("# Quotes \u201chi\u201d \u2014 \u00bd and \u03c0\n1. a", os.path.join(self.d, "q.pdf"))
        E.export("# Odd\x00\x07 bytes\n1. a\x1b", os.path.join(self.d, "odd.docx"))
        self.assertEqual(E.safe_name("../../etc/passwd"), os.path.join("documents", "passwd.pdf"))
        self.assertEqual(E.safe_name(" fractions.docx"), os.path.join("documents", "fractions.docx"))
        self.assertEqual(E.safe_name(""), os.path.join("documents", "document.pdf"))


class Classroom(unittest.TestCase):
    def test_sums_in_answer_keys_are_recalculated(self):
        self.assertEqual(C.arithmetic_answer("6 × 4 = ____"), 24)
        self.assertEqual(C.arithmetic_answer("What is 56 ÷ 8?"), 7)
        self.assertEqual(C.arithmetic_answer("345 + 128 = ____"), 473)
        self.assertIsNone(C.arithmetic_answer("There are 6 boxes with 3 crayons. How many in all?"))
        self.assertIsNone(C.arithmetic_answer("7 ÷ 2 = ____"))                   # not a whole number: skipped
        qs = ["6 × 4 = ____", "8 x 7 = ____", "Name a noun."]
        self.assertEqual(C.wrong_key_items(qs, ["24", "54", "dog"]), [2])

    def test_reading_level(self):
        passage = E.parse(READING).sections[0].blocks
        text = " ".join(v for k, v in passage if k == "para")
        self.assertLess(C.reading_grade(text), 4.0)
        hard = ("Photosynthetic organisms synthesize carbohydrates utilizing electromagnetic radiation, "
                "consequently generating atmospheric oxygen as a byproduct of metabolic transformation.")
        self.assertGreater(C.reading_grade(hard), 12)

    def test_good_answers_pass_every_kind(self):
        good = {
            "worksheet": (WORKSHEET, {"n": 4}),
            "reading": (READING, {"n": 3}),
            "lesson_plan": ("# Area of Rectangles\nGrade 3 - Math - 45 minutes\n## Objective\nStudents will be able "
                            "to find the area of a rectangle by counting square units and multiplying.\n## Materials\n"
                            "- grid paper\n- rulers\n## Warm-up (5 minutes)\nReview multiplication facts with a "
                            "quick game where students say the product out loud.\n## Teaching (15 minutes)\n1. Show a "
                            "rectangle on grid paper.\n2. Count the squares together.\n3. Show that rows times "
                            "columns gives the same number.\n## Practice (20 minutes)\nStudents draw rectangles and "
                            "find the area of each one with a partner, then check each other's work.\n## Exit ticket"
                            "\nWhat is the area of a rectangle that is 3 units by 5 units?", {}),
            "parent_email": ("# Field Trip Next Friday\nDear Families,\nOur class is going to the science museum "
                             "next Friday. We will leave at 9:00 and return by 2:00. Please send your child with a "
                             "packed lunch and a water bottle.\n- Sign and return the permission slip by Wednesday\n"
                             "- Wear comfortable shoes\nWe are so excited to learn together!\nThank you,\n"
                             "[Teacher name]", {}),
            "comments": ("# Report card comments\n1. [Student] has grown so much in reading this term and now reads "
                         "longer books with confidence.\n2. [Student] uses reading strategies well; a next step is "
                         "practicing reading aloud at home.", {"n": 2}),
            "rubric": ("# Favorite Animal Paragraph rubric\nGrade 3\n## Criteria\n- Topic sentence: 3 = clear, 2 = "
                       "some, 1 = missing\n- Details: 3 = three facts, 2 = two, 1 = one\n- Spelling: 3 = few mistakes, "
                       "2 = some, 1 = many", {}),
            "activities": ("# Brain Breaks\n1. Freeze dance: dance and freeze when the music stops.\n2. Simon says: "
                           "follow the leader's moves.\n3. Stretch and count: stretch while counting to 20.", {"n": 3}),
            "spelling": ("# Long A Words\nGrade 3 - Spelling\n## Words\n1. rain: The rain fell all day.\n2. cake: "
                         "We ate cake.\n## Practice idea\nWrite each word three times.", {"n": 2}),
        }
        for kind, (text, extra) in good.items():
            r = C.check_teacher_answer(text, {"type": kind, **extra})
            self.assertTrue(C.passes(r), (kind, r))

    def test_bad_answers_fail(self):
        spec = {"type": "worksheet", "n": 4}
        self.assertFalse(C.check_teacher_answer(WORKSHEET.replace("4. 54", "4. 56"), spec)["key is right"])
        self.assertFalse(C.check_teacher_answer(WORKSHEET, {"type": "worksheet", "n": 5})["count"])
        self.assertFalse(C.check_teacher_answer(WORKSHEET.split("## Answer key")[0], spec)["answer key"])
        self.assertFalse(C.check_teacher_answer("Sure! Here is your worksheet:\n" + WORKSHEET, spec)["layout"])
        named = "# Comments\n1. Emma has grown so much in reading this year and loves books."
        self.assertFalse(C.check_teacher_answer(named, {"type": "comments", "n": 1})["no names"])

    def test_every_request_kind_has_a_layout(self):
        rng = random.Random(2)
        kinds = set()
        for _ in range(200):
            msg, spec = C.teacher_request(rng)
            kinds.add(spec["type"])
            self.assertIn("#", C.layout_for(spec))
        self.assertEqual(kinds, set(C.LAYOUT))

    def test_the_teacher_task_keeps_only_checked_answers(self):
        def fake_teacher(server, messages, **kw):
            """Writes a correct worksheet of the asked length (whatever the request), one wrong key in a few."""
            import re as _re
            m = _re.search(r"exactly (\d+) numbered questions", messages[-1]["content"])
            n = int(m.group(1)) if m else 3
            wrong = n == 8                                                 # a wrong key: must be thrown away
            qs = "\n".join(f"{i}. {i} × 3 = ____" for i in range(1, n + 1))
            keys = "\n".join(f"{i}. {i * 3 + (1 if wrong and i == 2 else 0)}" for i in range(1, n + 1))
            return f"```markdown\n# Times 3\nGrade 3 - Math - Worksheet\n## Questions\n{qs}\n## Answer key\n{keys}\n```"
        saved = MT.ask_teacher
        try:
            MT.ask_teacher = fake_teacher
            results = [MT.make_teacher(i, None, None, 1) for i in range(60)]
        finally:
            MT.ask_teacher = saved
        kept = [r for r in results if r]
        self.assertTrue(kept)                                  # correct worksheets pass
        self.assertTrue(all(r["spec"]["type"] == "worksheet" and r["spec"]["n"] != 8 for r in kept))
        self.assertTrue(all(r["answer"].startswith("# ") for r in kept))
        self.assertLess(len(kept), 40)                         # everything else is thrown away
        chats = MSD.teacher_chats(kept, random.Random(0))
        self.assertEqual(chats[0]["messages"][1]["content"], kept[0]["answer"])
        self.assertEqual(chats[0]["kind"], "teacher_worksheet")


if __name__ == "__main__":
    unittest.main()
