import Foundation

// VryxCode's newer parts, worked out from a session's events so the screens only draw them (ports of android/.../ui/CodeParity.kt and CodeReview.kt,
// which follow the website's web/js/ide.js and code.js). Nothing here draws anything or calls the server: plain functions, tested in CodeParityTests.

private func matches(_ pattern: String, in text: String, options: NSRegularExpression.Options = []) -> [String]? {
    guard let re = try? NSRegularExpression(pattern: pattern, options: options),
          let m = re.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) else { return nil }
    return (0..<m.numberOfRanges).map { i in Range(m.range(at: i), in: text).map { String(text[$0]) } ?? "" }
}

// MARK: - The plan box (flag vryxcode_taskbox)

/// One step of VryxCode's plan: [state] is "done", "now" (being worked on) or "todo".
struct PlanStep: Equatable { let text: String; let state: String }

/// Reads the plan from the newest `todo` step. The first unfinished step is "now", but only while VryxCode is working.
func planSteps(_ events: [CodeEvent], working: Bool) -> [PlanStep] {
    guard let last = events.last(where: { $0.kind == "step" && $0.str("tool") == "todo" }) else { return [] }
    var preview = last.str("preview")
    if preview.hasPrefix("todo ") { preview.removeFirst(5) }
    guard let data = preview.data(using: .utf8),
          let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
          let items = obj["items"] as? [[String: Any]] else { return [] }
    let steps: [(String, Bool)] = items.compactMap { i in
        guard let t = i["text"] as? String else { return nil }
        return (t, (i["done"] as? Bool) ?? false)
    }
    let now = steps.firstIndex { !$0.1 }
    return steps.enumerated().map { i, s in PlanStep(text: s.0, state: s.1 ? "done" : (i == now && working ? "now" : "todo")) }
}

// MARK: - How a message ended (flag vryxcode_autocontinue) and the review verdict (flag vryxcode_guardrails)

enum EndState: Equatable { case finished, waiting, outOfSteps(rounds: Int) }

func endState(_ e: CodeEvent) -> EndState? {
    guard e.kind == "end" else { return nil }
    if e.bool("finished") { return .finished }
    if e.str("reason") == "steps" { return .outOfSteps(rounds: e.int("rounds")) }
    if e.bool("said") && !e.bool("plan") { return .waiting }
    return nil
}

/// A review's verdict: [blocking] serious problems that must be fixed, [nits] minor points, [fix] the message that asks VryxCode to fix them (test first).
struct Verdict: Equatable { let approved: Bool; let blocking: Int; let nits: Int; let fix: String }

func verdictOf(_ e: CodeEvent) -> Verdict? {
    guard let v = e.raw["verdict"] as? [String: Any] else { return nil }
    func n(_ k: String) -> Int { (v[k] as? NSNumber)?.intValue ?? 0 }
    return Verdict(approved: (v["status"] as? String) == "APPROVED", blocking: n("blocking"), nits: n("nits"), fix: (v["fix"] as? String) ?? "")
}

// MARK: - Suggested replies (flag vryxcode_autocontinue and vryxcode_suggest)

/// True when the text ends by asking the person something (the website's vxAsksYou).
func asksYou(_ text: String) -> Bool {
    let tail = String(text.trimmingCharacters(in: .whitespacesAndNewlines).suffix(400))
    return tail.hasSuffix("?") || matches(#"\b(would you like|do you want|shall i|should i|let me know|which (one|option|file))\b"#, in: tail, options: .caseInsensitive) != nil
}

/// True when what the person typed is a question, so a plain explanation is the whole answer (the website's vxIsQuestion).
func isQuestion(_ text: String) -> Bool {
    let t = text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    return t.hasSuffix("?") || matches(#"^(why|what|how|when|where|who|which|explain|show me|tell me|describe|can you explain|could you explain|is it|does it|did it|are you)\b"#, in: t) != nil
}

/// Replies one tap sends when VryxCode stops "waiting for your answer": a question gets "Yes, go ahead."; anything else pushes it to save, run the tests and explain.
func waitingReplies(_ text: String) -> [String] {
    asksYou(text) ? ["Yes, go ahead.", "Explain your options first.", "No, I want something different."]
                  : ["Please save the fix to the project files, run the tests, and tell me what was wrong.", "Explain in plain words what was wrong.", "Show me what you changed."]
}

/// What the person last typed before the end event [e], lower case.
func lastAsked(_ events: [CodeEvent], before e: CodeEvent) -> String {
    let at = events.firstIndex { $0.id == e.id } ?? events.count
    for i in stride(from: at - 1, through: 0, by: -1) {
        let x = events[i]
        if x.kind == "user" || x.kind == "start" {
            let t = x.str("text").isEmpty ? x.str("task") : x.str("text")
            return t.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        }
    }
    return ""
}

/// True when the turn ended with a plain answer to a question (not a task waiting for an answer), so no banner.
func justAnswered(_ e: CodeEvent, _ events: [CodeEvent]) -> Bool {
    endState(e) == .waiting && isQuestion(lastAsked(events, before: e)) && !asksYou(e.str("summary"))
}

/// A few things the person could ask next after a plain answer, leaving out what they just asked.
func followUps(last: String, text: String) -> [String] {
    let said = text.lowercased()
    let all = ["Show me what you changed.", "Run the tests and tell me the result.", "Explain it again in simpler words.", "What should I do next?"]
    return Array(all.filter { t in
        t.lowercased() != last
            && !(t.hasPrefix("Explain") && matches("plain words|simpler", in: last) != nil)
            && !(t.hasPrefix("Show") && last.contains("changed") && said.contains("changed"))
    }.prefix(3))
}

// MARK: - The review feed (flags vryxcode_review and vryxcode_lines)

/// The tools that only look (read, list, search): each is one quiet grey line.
let quietTools: Set<String> = ["read_file", "list_files", "glob", "grep", "diagnostics", "command_output", "project_map", "search_project", "code_search", "lookup_docs", "memory"]

private let doneVerb = ["read_file": "Read", "write_file": "Wrote", "edit_file": "Edited", "run": "Ran", "list_files": "Looked around",
                        "git": "Git", "diagnostics": "Checked", "github": "GitHub"]

/// Splits a step into a verb and what it worked on ("Wrote" + "main.py"); the same words as the website's toolParts.
func toolParts(preview: String, tool: String) -> (verb: String, arg: String) {
    let first = preview.components(separatedBy: "\n").first ?? ""
    if let m = matches(#"^write (\S+)"#, in: first) { return ("Wrote", m[1]) }
    if let m = matches(#"^edit (\S+)"#, in: first) { return ("Edited", m[1]) }
    if let m = matches(#"^(\w+) \{.*"(?:path|command|args|action)"\s*:\s*"([^"]*)""#, in: first) { return (doneVerb[m[1]] ?? m[1], m[2]) }
    return (doneVerb[tool] ?? tool, first.count > 90 ? String(first.prefix(90)) + "..." : first)
}

/// One line of a change: [kind] is "+" (added), "-" (taken away) or " " (header or unchanged).
struct DiffLine: Equatable { let text: String; let kind: Character }

func diffLines(_ preview: String) -> [DiffLine] {
    preview.components(separatedBy: "\n").dropFirst().map { l in
        if let m = matches(#"^(\s*)([+-]) "#, in: l), let whole = l.range(of: m[0]) {
            return DiffLine(text: m[2] + " " + String(l[whole.upperBound...]), kind: m[2].first ?? " ")
        }
        return DiffLine(text: l, kind: " ")
    }
}

/// A quiet grey line such as "Read app/page.tsx" or "Thought 4s"; [bad] when the step went wrong, with the first line of why.
struct QuietLine: Equatable { var text: String; var bad = false; var why = "" }

/// What the review feed can show, in order.
enum ReviewItem: Identifiable {
    case quiet(QuietLine)
    case file(path: String, add: Int, del: Int, diff: [DiffLine], bad: Bool, why: String)
    /// The end of a message: every file it changed with its lines added and removed.
    case done(files: [(path: String, add: Int, del: Int)])
    /// Quiet lines in a row folded into one line that opens on a tap (flag vryxcode_lines).
    case group([QuietLine])
    /// Anything else, drawn as before: your message, a long step, the summary, a question.
    case event(CodeEvent)

    var id: String {
        switch self {
        case let .quiet(q): return "q" + q.text
        case let .file(p, a, d, _, _, _): return "f\(p)\(a)\(d)"
        case let .done(f): return "d" + f.map(\.path).joined(separator: ",")
        case let .group(g): return "g" + (g.first?.text ?? "")
        case let .event(e): return "e\(e.id)"
        }
    }
}

/// Builds the review feed from the session's events: quiet lines and file chips take in whether their result failed, and a finished message ends with the files it changed.
func reviewItems(_ events: [CodeEvent]) -> [ReviewItem] {
    var out: [ReviewItem] = []
    var turn: [(path: String, add: Int, del: Int)] = []
    var last = -1
    for e in events {
        let kind = e.kind
        if kind == "start" || kind == "user" { turn = [] }
        if kind == "step" {
            let tool = e.str("tool")
            if !tool.isEmpty && tool != "todo" && tool != "finish" {
                let (verb, arg) = toolParts(preview: e.str("preview"), tool: tool)
                if let secs = e.num("secs"), secs >= 2 { out.append(.quiet(QuietLine(text: "Thought \(Int(secs.rounded()))s"))) }
                if quietTools.contains(tool) {
                    out.append(.quiet(QuietLine(text: (verb + " " + arg).trimmingCharacters(in: .whitespaces)))); last = out.count - 1; continue
                }
                if tool == "write_file" || tool == "edit_file" {
                    out.append(.file(path: arg, add: e.int("add"), del: e.int("del"), diff: diffLines(e.str("preview")), bad: false, why: "")); last = out.count - 1; continue
                }
            }
        }
        if kind == "result" && last >= 0 {
            let t = e.str("text")
            let bad = matches(#"^error|exit code [1-9]|Traceback|FAILED"#, in: t, options: .anchorsMatchLines) != nil
            let why = bad ? String(t.components(separatedBy: "\n")[0].prefix(200)) : ""
            switch out[last] {
            case var .quiet(q): q.bad = bad; q.why = why; out[last] = .quiet(q)
            case let .file(p, a, d, diff, _, _):
                out[last] = .file(path: p, add: a, del: d, diff: diff, bad: bad, why: why)
                if !bad {
                    if let i = turn.firstIndex(where: { $0.path == p }) { turn[i].add += a; turn[i].del += d } else { turn.append((p, a, d)) }
                }
            default: break
            }
            last = -1
            continue
        }
        last = -1
        if kind == "end" && e.bool("finished") && !turn.isEmpty { out.append(.done(files: turn)) }
        out.append(.event(e))
    }
    return out
}

/// Each run of two or more quiet lines becomes one group.
func foldQuiet(_ items: [ReviewItem]) -> [ReviewItem] {
    var out: [ReviewItem] = []
    for item in items {
        guard case let .quiet(q) = item else { out.append(item); continue }
        switch out.last {
        case let .group(g)?: out[out.count - 1] = .group(g + [q])
        case let .quiet(prev)?: out[out.count - 1] = .group([prev, q])
        default: out.append(item)
        }
    }
    return out
}

/// A short title for a folded line, for example "Thought, read 3 files, ran 2 commands".
func groupTitle(_ g: [QuietLine]) -> String {
    let reads = g.filter { $0.text.hasPrefix("Read ") }.count
    let runs = g.filter { $0.text.hasPrefix("Ran ") }.count
    let thought = g.filter { $0.text.hasPrefix("Thought ") }.count
    let other = g.count - reads - runs - thought
    var parts: [String] = []
    if thought > 0 { parts.append("thought") }
    if reads > 0 { parts.append(reads == 1 ? "read a file" : "read \(reads) files") }
    if runs > 0 { parts.append(runs == 1 ? "ran a command" : "ran \(runs) commands") }
    if other > 0 { parts.append(other == 1 ? "looked around" : "\(other) more steps") }
    let s = parts.joined(separator: ", ")
    return s.prefix(1).uppercased() + s.dropFirst()
}

/// The sessions list grouped as on the website (renderHome): WORKING, READY FOR REVIEW (done with changes you have not opened since) and DONE.
/// [seen] maps a session id to its "updated" time when you last opened it.
func sessionGroups(_ sessions: [CodeSessionRow], seen: [String: Double]) -> [(title: String, sessions: [CodeSessionRow])] {
    let busy = { (s: CodeSessionRow) in ["starting", "working", "asking", "queued"].contains(s.state) }
    let ready = { (s: CodeSessionRow) in !busy(s) && s.state == "done" && (s.added > 0 || s.removed > 0 || s.files > 0) && seen[s.id] != s.updated }
    return [("WORKING", sessions.filter(busy)), ("READY FOR REVIEW", sessions.filter(ready)), ("DONE", sessions.filter { !busy($0) && !ready($0) })]
        .filter { !$0.1.isEmpty }
        .map { (title: $0.0, sessions: $0.1) }
}

// MARK: - Slash commands

/// The /commands the app answers itself; anything else starting with a slash is sent to VryxCode as written.
enum Slash: Equatable {
    case mode(String), newSession, memory, permissions
    static func parse(_ text: String) -> Slash? {
        switch text.trimmingCharacters(in: .whitespacesAndNewlines).components(separatedBy: " ")[0].lowercased() {
        case "/plan": return .mode("plan")
        case "/ask": return .mode("ask")
        case "/auto": return .mode("auto")
        case "/new": return .newSession
        case "/memory": return .memory
        case "/permissions": return .permissions
        default: return nil
        }
    }
    /// The commands shown as suggestions when someone types a slash: [name, what it does].
    static let builtIn: [(name: String, about: String)] = [("/plan", "Plan first, change nothing"), ("/ask", "Ask before editing"), ("/auto", "Edit without asking"),
                                                           ("/new", "Start a new session"), ("/memory", "What VryxCode remembers"), ("/permissions", "What it may and may not do")]
}
