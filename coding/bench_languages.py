"""
bench_languages.py - How well does each model write code in each programming language? Twelve small programs, every language, two tries each.

WHAT THIS FILE DOES
    The VryxCode exercises we have so far are Python only. This asks the model for the SAME twelve small programs (read numbers or text on standard input, print the answer)
    in each language you pick, builds and runs what it wrote with our own tests, and gives a second try with the error output when the first fails.
    The programs are deliberately plain (no libraries, no files, no network) so they test the language, not the model's memory of a framework.

        python coding/bench_languages.py --model solstice-2 --llama http://127.0.0.1:8080 --langs python,javascript,go,java,cpp,rust --out logs/languages.json

    A language whose tools are not installed on this computer is skipped and reported as such. Like bench_exercises.py this is our own measure, not a published benchmark: use it to compare
    languages and models with each other over time. `--selftest` checks the tests themselves (the built-in reference solutions must pass, a wrong answer must fail) with no model at all.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import json
import shutil
import subprocess
import tempfile


# id -> (what to write, [(standard input, expected output)])
TASKS = {
    "sum": ("Read one line of whole numbers separated by spaces and print their sum.", [("1 2 3\n", "6"), ("10 -4\n", "6"), ("0\n", "0"), ("100 200 300 400\n", "1000")]),
    "fizzbuzz": ("Read a number n and print the numbers 1 to n, one per line, but print Fizz for multiples of 3, Buzz for multiples of 5 and FizzBuzz for multiples of both.",
                 [("5\n", "1\n2\nFizz\n4\nBuzz"), ("15\n", "\n".join(["1", "2", "Fizz", "4", "Buzz", "Fizz", "7", "8", "Fizz", "Buzz", "11", "Fizz", "13", "14", "FizzBuzz"])), ("1\n", "1")]),
    "reverse_words": ("Read one line and print its words in reverse order, separated by single spaces.", [("hello big world\n", "world big hello"), ("one\n", "one"), ("a b c d\n", "d c b a")]),
    "is_prime": ("Read several whole numbers, one per line. For each print yes if it is a prime number and no if it is not.", [("2\n3\n4\n17\n1\n", "yes\nyes\nno\nyes\nno"), ("97\n100\n", "yes\nno"), ("0\n7919\n", "no\nyes")]),
    "word_count": ("Read all of standard input and print how many words it has (words are separated by spaces or new lines).", [("one two three\n", "3"), ("a\nb c\n\nd\n", "4"), ("\n", "0"), ("   spaced   out  \n", "2")]),
    "palindrome": ("Read several lines. For each print yes if the line is a palindrome and no if not. Ignore letter case and ignore everything that is not a letter or digit.",
                   [("racecar\nhello\n", "yes\nno"), ("A man, a plan, a canal: Panama\n", "yes"), ("Was it a car or a cat I saw?\nNot one\n", "yes\nno")]),
    "fibonacci": ("Read a number n and print the n-th Fibonacci number, where the 0th is 0 and the 1st is 1.", [("0\n", "0"), ("1\n", "1"), ("10\n", "55"), ("50\n", "12586269025")]),
    "gcd": ("Read two whole numbers on one line and print their greatest common divisor.", [("12 18\n", "6"), ("17 5\n", "1"), ("100 75\n", "25"), ("0 9\n", "9")]),
    "sort_numbers": ("Read one line of whole numbers separated by spaces and print them sorted from smallest to largest, separated by single spaces.", [("3 1 2\n", "1 2 3"), ("5 -1 5 0\n", "-1 0 5 5"), ("9\n", "9")]),
    "roman": ("Read a whole number from 1 to 3999 and print it as a Roman numeral.", [("4\n", "IV"), ("9\n", "IX"), ("58\n", "LVIII"), ("1994\n", "MCMXCIV"), ("3999\n", "MMMCMXCIX")]),
    "anagram": ("Read several lines, each with two words separated by a space. For each line print yes if the two words are anagrams of each other (same letters, ignoring case) and no if not.",
                [("listen silent\nhello world\n", "yes\nno"), ("Dormitory dirtyroom\n", "yes"), ("abc abd\n", "no")]),
    "brackets": ("Read several lines. For each print yes if the brackets ( ) [ ] { } in the line are balanced and properly nested, otherwise no. Other characters are ignored.",
                 [("()\n([]{})\n", "yes\nyes"), ("(]\n((\n", "no\nno"), ("a(b[c]d)e\n)(\n", "yes\nno")]),
}

# language -> (file the program goes in, build command or None, run command, how the model can check its work, the name of the language for the prompt)
LANGS = {
    "python": ("main.py", None, ["python3", "main.py"], "Test it with: python main.py", "Python"),
    "javascript": ("main.js", None, ["node", "main.js"], "Test it with: node main.js", "JavaScript (Node.js)"),
    "go": ("main.go", ["go", "build", "-o", "main", "main.go"], ["./main"], "Test it with: go run main.go", "Go"),
    "java": ("Main.java", ["javac", "Main.java"], ["java", "-cp", ".", "Main"], "The public class must be called Main. Check that it compiles with: javac Main.java", "Java"),
    "c": ("main.c", ["gcc", "-O2", "-o", "main", "main.c", "-lm"], ["./main"], "Check that it compiles with: gcc -fsyntax-only main.c", "C"),
    "cpp": ("main.cpp", ["g++", "-O2", "-o", "main", "main.cpp"], ["./main"], "Check that it compiles with: g++ -fsyntax-only main.cpp", "C++"),
    "rust": ("main.rs", ["rustc", "-O", "-o", "main", "main.rs"], ["./main"], "Check that it compiles with: rustc main.rs", "Rust"),
    "php": ("main.php", None, ["php", "main.php"], "Test it with: php main.php", "PHP"),
    "ruby": ("main.rb", None, ["ruby", "main.rb"], "Test it with: ruby main.rb", "Ruby"),
}
TOOLS = {"python": "python3", "javascript": "node", "go": "go", "java": "javac", "c": "gcc", "cpp": "g++", "rust": "rustc", "php": "php", "ruby": "ruby"}

PROMPT = ("Write a complete {name} program in {file}. It reads from standard input and writes to standard output, nothing else (no prompts, no extra text). Use only the language's standard library.\n"
          "{what}\nExample: with the input {inp!r} it prints {out!r}.\n{hint}\nWhen it works, call finish.")
RETRY = "It still does not work. {detail}\nFix {file} (rewrite the whole file if that is easier), then call finish."


def installed(lang):
    import languages                                              # for the rust check: a rustup stand-in with no toolchain is on the PATH but cannot compile
    return bool(shutil.which(TOOLS[lang])) and languages._really_runs(TOOLS[lang]) and (lang != "java" or bool(shutil.which("java")))


def env_for(folder):
    return dict(os.environ, HOME=folder, GOCACHE=os.path.join(folder, ".gocache"), GOFLAGS="", CARGO_HOME=os.path.join(folder, ".cargo"),
                RUSTUP_HOME=os.environ.get("RUSTUP_HOME") or os.path.join(os.path.expanduser("~"), ".rustup"),      # rust's installed toolchains live under the real home, not the throw-away one
                PYTHONDONTWRITEBYTECODE="1")


def commands(lang, folder):
    """(build, run) for a language. On Windows a built program must be main.exe, run by its full path ("./main" is not found there)."""
    _, build, run, _, _ = LANGS[lang]
    if os.name == "nt" and run == ["./main"]:
        build = ["main.exe" if a == "main" else a for a in build]
        run = [os.path.join(folder, "main.exe")]
    return build, run


def score(lang, folder, task, timeout=10):
    """{"passed", "passed_tests", "total", "stage", "detail"}: builds (if the language needs it) and runs every test."""
    fname = LANGS[lang][0]
    build, run = commands(lang, folder)
    tests = TASKS[task][1]
    res = {"passed": False, "passed_tests": 0, "total": len(tests), "stage": "build", "detail": ""}
    if not os.path.exists(os.path.join(folder, fname)):
        res["detail"] = f"{fname} was not written"
        return res
    if build:
        try:
            r = subprocess.run(build, cwd=folder, capture_output=True, text=True, timeout=120, env=env_for(folder), stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as e:
            res["detail"] = f"could not build: {e}"
            return res
        if r.returncode != 0:
            res["detail"] = ("it did not compile:\n" + (r.stderr + r.stdout))[-900:]
            return res
    res["stage"] = "run"
    for inp, want in tests:
        try:
            r = subprocess.run(run, cwd=folder, input=inp, capture_output=True, text=True, timeout=timeout, env=env_for(folder))
        except subprocess.TimeoutExpired:
            res["detail"] = f"it ran too long on the input {inp!r} (an endless loop?)"
            return res
        except OSError as e:
            res["detail"] = f"could not run: {e}"
            return res
        got = r.stdout.strip()
        if r.returncode == 0 and got.split() == want.split() and [l.rstrip() for l in got.splitlines()] == [l.rstrip() for l in want.splitlines()]:
            res["passed_tests"] += 1
        elif not res["detail"]:
            res["detail"] = f"with the input {inp!r} it printed {got[:200]!r} but should print {want!r}" + (f" (it crashed: {r.stderr.strip()[-200:]})" if r.returncode else "")
    res["passed"] = res["passed_tests"] == res["total"]
    res["stage"] = "ok" if res["passed"] else "wrong"
    return res


def make_prompt(lang, task):
    fname, _, _, hint, name = LANGS[lang]
    what, tests = TASKS[task]
    return PROMPT.format(name=name, file=fname, what=what, inp=tests[0][0], out=tests[0][1], hint=hint)


def run_one(lang, task, generate, max_turns=10, context_tokens=None, tries=2):
    import vryxcode as V
    work = tempfile.mkdtemp(prefix="vryxlang_")
    attempts, passed, last, first = 0, False, {}, False
    try:
        for attempt in range(tries):
            prompt = make_prompt(lang, task) if attempt == 0 else RETRY.format(detail=last.get("detail", ""), file=LANGS[lang][0])
            V.run_task(prompt, generate, work, V.make_ask(True), max_turns, context_tokens, out=lambda *_: None, checks=False)
            attempts += 1
            last = score(lang, work, task)
            if last["passed"]:
                passed, first = True, attempt == 0
                break
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"lang": lang, "task": task, "passed_first": first, "passed": passed, "attempts": attempts, "stage": last.get("stage"), "tests": f"{last.get('passed_tests', 0)}/{last.get('total', 0)}"}


def summarize(results, skipped=()):
    out = {"skipped_not_installed": sorted(skipped), "languages": {}}
    for lang in sorted({r["lang"] for r in results}):
        rs = [r for r in results if r["lang"] == lang]
        n = len(rs)
        out["languages"][lang] = {"tasks": n, "first_try": sum(r["passed_first"] for r in rs), "after_retry": sum(r["passed"] for r in rs),
                                  "pct_first": round(100 * sum(r["passed_first"] for r in rs) / n, 1), "pct_after_retry": round(100 * sum(r["passed"] for r in rs) / n, 1),
                                  "failed_to_compile": sum(1 for r in rs if not r["passed"] and r["stage"] == "build")}
    return out


# ---------------------------------------------------------------- reference solutions: they prove the tests are fair (and test the build and run steps for each language)
REFERENCE_PY = {
    "sum": "print(sum(int(x) for x in input().split()))",
    "fizzbuzz": "n = int(input())\nfor i in range(1, n + 1):\n    print('FizzBuzz' if i % 15 == 0 else 'Fizz' if i % 3 == 0 else 'Buzz' if i % 5 == 0 else i)",
    "reverse_words": "print(' '.join(input().split()[::-1]))",
    "is_prime": "import sys\nfor line in sys.stdin.read().split():\n    n = int(line)\n    print('yes' if n > 1 and all(n % d for d in range(2, int(n ** 0.5) + 1)) else 'no')",
    "word_count": "import sys\nprint(len(sys.stdin.read().split()))",
    "palindrome": "import sys\nfor line in sys.stdin.read().splitlines():\n    s = [c.lower() for c in line if c.isalnum()]\n    print('yes' if s == s[::-1] else 'no')",
    "fibonacci": "n = int(input())\na, b = 0, 1\nfor _ in range(n):\n    a, b = b, a + b\nprint(a)",
    "gcd": "from math import gcd\na, b = map(int, input().split())\nprint(gcd(a, b))",
    "sort_numbers": "print(' '.join(map(str, sorted(int(x) for x in input().split()))))",
    "roman": ("n = int(input())\nout = ''\nfor v, s in ((1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'), (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')):\n"
              "    while n >= v:\n        out += s\n        n -= v\nprint(out)"),
    "anagram": "import sys\nfor line in sys.stdin.read().splitlines():\n    a, b = line.split()\n    print('yes' if sorted(a.lower()) == sorted(b.lower()) else 'no')",
    "brackets": ("import sys\nfor line in sys.stdin.read().splitlines():\n    st, ok = [], True\n    for c in line:\n        if c in '([{':\n            st.append(c)\n        elif c in ')]}':\n"
                 "            if not st or '([{'.index(st.pop()) != ')]}'.index(c):\n                ok = False\n                break\n    print('yes' if ok and not st else 'no')"),
}
REFERENCE_SUM = {
    "python": REFERENCE_PY["sum"] + "\n",
    "javascript": "const t = require('fs').readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number);\nconsole.log(t.reduce((a, b) => a + b, 0));\n",
    "go": 'package main\n\nimport (\n\t"bufio"\n\t"fmt"\n\t"os"\n)\n\nfunc main() {\n\tr := bufio.NewReader(os.Stdin)\n\ts := 0\n\tfor {\n\t\tvar x int\n\t\tif _, err := fmt.Fscan(r, &x); err != nil {\n\t\t\tbreak\n\t\t}\n\t\ts += x\n\t}\n\tfmt.Println(s)\n}\n',
    "java": "import java.util.*;\n\npublic class Main {\n    public static void main(String[] args) {\n        Scanner sc = new Scanner(System.in);\n        long s = 0;\n        while (sc.hasNextLong()) s += sc.nextLong();\n        System.out.println(s);\n    }\n}\n",
    "c": '#include <stdio.h>\n\nint main(void) {\n    long s = 0, x;\n    while (scanf("%ld", &x) == 1) s += x;\n    printf("%ld\\n", s);\n    return 0;\n}\n',
    "cpp": '#include <iostream>\n\nint main() {\n    long long s = 0, x;\n    while (std::cin >> x) s += x;\n    std::cout << s << std::endl;\n}\n',
    "rust": 'use std::io::Read;\n\nfn main() {\n    let mut t = String::new();\n    std::io::stdin().read_to_string(&mut t).unwrap();\n    let s: i64 = t.split_whitespace().map(|x| x.parse::<i64>().unwrap()).sum();\n    println!("{}", s);\n}\n',
    "php": "<?php\n$t = preg_split('/\\s+/', trim(stream_get_contents(STDIN)));\necho array_sum($t), \"\\n\";\n",
    "ruby": "puts STDIN.read.split.map(&:to_i).sum\n",
}


def selftest(out=print):
    """(problems, checked): every Python reference passes its task, a wrong answer fails, and the sum reference passes in each installed language."""
    problems, checked = [], 0
    for task, src in REFERENCE_PY.items():
        work = tempfile.mkdtemp(prefix="vryxlang_")
        try:
            open(os.path.join(work, "main.py"), "w").write(src + "\n")
            r = score("python", work, task)
            checked += 1
            if not r["passed"]:
                problems.append(f"python reference for {task} fails: {r['detail']}")
            open(os.path.join(work, "main.py"), "w").write("print('wrong')\n")
            if score("python", work, task)["passed"]:
                problems.append(f"a wrong answer passes {task}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    for lang, src in REFERENCE_SUM.items():
        if not installed(lang):
            out(f"skipped {lang}: not installed")
            continue
        work = tempfile.mkdtemp(prefix="vryxlang_")
        try:
            open(os.path.join(work, LANGS[lang][0]), "w").write(src)
            r = score(lang, work, "sum")
            checked += 1
            if not r["passed"]:
                problems.append(f"{lang} reference for sum fails ({r['stage']}): {r['detail']}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return problems, checked


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="solstice-2")
    p.add_argument("--llama", default="http://127.0.0.1:8080")
    p.add_argument("--langs", default="python,javascript,go,java,cpp,rust", help="comma separated: " + ", ".join(LANGS))
    p.add_argument("--limit", type=int, default=None, help="only the first N tasks of each language")
    p.add_argument("--max-turns", type=int, default=10)
    p.add_argument("--context", type=int, default=32768)
    p.add_argument("--out", default="logs/languages.json")
    p.add_argument("--coder", default=None, metavar="LABEL", help="score an outside coding model that llama-server is running, under this label")
    p.add_argument("--selftest", action="store_true", help="check the tests themselves (no model)")
    a = p.parse_args(argv)
    if a.selftest:
        problems, checked = selftest()
        print(f"{checked} checks, {len(problems)} problems")
        for x in problems:
            print(" -", x)
        return 1 if problems else 0
    import vryxcode as V
    ok, note = V.gate(a.model, a.coder)
    if not ok:
        raise SystemExit(note)
    wanted = [x.strip() for x in a.langs.split(",") if x.strip() in LANGS]
    skipped = [x for x in wanted if not installed(x)]
    wanted = [x for x in wanted if x not in skipped]
    if skipped:
        print("skipped (not installed here): " + ", ".join(skipped))
    generate = V.LlamaChat(a.llama)
    results = []
    for lang in wanted:
        for task in list(TASKS)[:a.limit]:
            r = run_one(lang, task, generate, a.max_turns, a.context)
            results.append(r)
            print(f"{lang:11s} {task:14s} {'PASS (1st try)' if r['passed_first'] else 'PASS (2nd try)' if r['passed'] else 'fail ' + r['tests']}", flush=True)
    s = summarize(results, skipped)
    print(json.dumps(s, indent=2))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"model": a.coder or a.model, "outside_model": bool(a.coder), "summary": s, "results": results}, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
