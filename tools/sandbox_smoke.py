"""
sandbox_smoke.py - Proves the VryxCode sandbox image works for every language it promises, sealed exactly the way VryxCode runs commands
(code_sandbox.docker_prefix: no network, read-only, limits), and that a server VryxCode starts can be used through the Preview
(code_servers: a real Flask app in a real container, asked through `docker exec`).

    docker build -t emvryx/code-sandbox:1 docker/code-sandbox
    python tools/sandbox_smoke.py            (also run by CI when the image or the sandbox code changes)
Prints one line per language and exits 1 if any of them does not build and run.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import shutil
import subprocess
import tempfile
import time

import code_sandbox
import code_servers

# language -> ({file: text}, the command VryxCode would run, what it must print)
LANGUAGES = {
    "Python": ({"main.py": "print('ok-python')\n"}, "python3 main.py", "ok-python"),
    "Python tests": ({"test_a.py": "import unittest\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(1, 1)\n"}, "python3 -m pytest -q", "1 passed"),
    "JavaScript": ({"main.js": "console.log('ok-js')\n"}, "node main.js", "ok-js"),
    "TypeScript": ({"main.ts": "const n: number = 1;\nconsole.log('ok-ts' + n);\n"}, "tsc main.ts && node main.js", "ok-ts1"),
    "C": ({"main.c": '#include <stdio.h>\nint main(void) { puts("ok-c"); return 0; }\n'}, "gcc main.c -o main && ./main", "ok-c"),
    "C++": ({"main.cpp": '#include <iostream>\nint main() { std::cout << "ok-cpp" << std::endl; }\n'}, "g++ -std=c++17 main.cpp -o main && ./main", "ok-cpp"),
    "C#": ({"app.csproj": '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>\n',
            "Program.cs": 'System.Console.WriteLine("ok-cs");\n'}, "dotnet run", "ok-cs"),
    "Java": ({"Main.java": 'public class Main { public static void main(String[] a) { System.out.println("ok-java"); } }\n'}, "javac Main.java && java Main", "ok-java"),
    "Kotlin": ({"main.kt": 'fun main() { println("ok-kotlin") }\n'}, "kotlinc main.kt -include-runtime -d main.jar 2>/dev/null && java -jar main.jar", "ok-kotlin"),
    "Go": ({"main.go": 'package main\nimport "fmt"\nfunc main() { fmt.Println("ok-go") }\n'}, "go run main.go", "ok-go"),
    "Rust": ({"main.rs": 'fn main() { println!("ok-rust"); }\n'}, "rustc main.rs && ./main", "ok-rust"),
    "PHP": ({"index.php": '<?php echo "ok-php\\n";\n'}, "php index.php", "ok-php"),
    "Ruby": ({"main.rb": 'puts "ok-ruby"\n'}, "ruby main.rb", "ok-ruby"),
    "Perl": ({"main.pl": 'print "ok-perl\\n";\n'}, "perl main.pl", "ok-perl"),
    "Lua": ({"main.lua": 'print("ok-lua")\n'}, "lua5.4 main.lua", "ok-lua"),
    "R": ({"main.R": 'cat("ok-r\\n")\n'}, "Rscript main.R", "ok-r"),
    "Elixir": ({"main.exs": 'IO.puts("ok-elixir")\n'}, "elixir main.exs", "ok-elixir"),
    "Bash": ({"run.sh": "echo ok-bash\n"}, "bash run.sh", "ok-bash"),
    "SQL": ({"q.sql": "CREATE TABLE t(a);\nINSERT INTO t VALUES ('ok-sql');\nSELECT a FROM t;\n"}, "sqlite3 app.db < q.sql", "ok-sql"),
    "make": ({"Makefile": "all:\n\t@echo ok-make\n"}, "make", "ok-make"),
}
FLASK_APP = "from flask import Flask\nimport os\napp = Flask(__name__)\n\n\n@app.route('/')\ndef home():\n    return 'ok-flask'\n\n\napp.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))\n"


def short(out):
    """The start of an error says what went wrong and the end says where: keep both."""
    out = out.strip()
    return out if len(out) <= 1200 else out[:600] + "\n...\n" + out[-600:]


def run(prefix, command, timeout=240):
    try:
        r = subprocess.run(prefix + ["sh", "-c", command], capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        return -1, "timed out"


def main():
    ok, why = code_sandbox.available(code_sandbox.DEFAULT_IMAGE)
    if not ok:
        print("sandbox: " + why)
        return 1
    bad = 0
    for name, (files, command, expect) in LANGUAGES.items():
        d = tempfile.mkdtemp(prefix="smoke_")
        os.chmod(d, 0o777)                                  # the container runs as this user; the folder must be writable from inside
        for rel, text in files.items():
            with open(os.path.join(d, rel), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        t = time.time()
        code, out = run(code_sandbox.docker_prefix(code_sandbox.DEFAULT_IMAGE, d), command)
        good = code == 0 and expect in out
        bad += not good
        print(f"{'ok  ' if good else 'FAIL'} {name:13} {time.time() - t:5.1f}s  {command}" + ("" if good else "\n       " + short(out).replace("\n", "\n       ")))
        shutil.rmtree(d, ignore_errors=True)
    d = tempfile.mkdtemp(prefix="smoke_app_")
    os.chmod(d, 0o777)
    with open(os.path.join(d, "app.py"), "w") as f:
        f.write(FLASK_APP)
    apps = code_servers.AppServers()
    try:
        said = apps.start("smoke", "app", code_sandbox.docker_prefix(code_sandbox.DEFAULT_IMAGE, d), "python3 app.py", 5000)
        status, _, body = apps.relay(apps.token("smoke", "app"), "GET", "", "", {}, b"")
        good = status == 200 and b"ok-flask" in body
        print(f"{'ok  ' if good else 'FAIL'} {'Flask app':13}        start_app through the Preview: {said[:80]}")
    except code_servers.AppError as e:
        good = False
        print(f"FAIL {'Flask app':13}        {e}")
    finally:
        apps.stop_all()
        shutil.rmtree(d, ignore_errors=True)
    bad += not good
    print(f"\n{len(LANGUAGES) + 1 - bad} of {len(LANGUAGES) + 1} work" + ("" if not bad else f"; {bad} failed"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
