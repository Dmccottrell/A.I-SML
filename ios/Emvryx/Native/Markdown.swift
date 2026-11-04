import Foundation

/// The parts of a reply, as android/.../ui/Markdown.kt splits it: prose (with **bold**, *italic*, `code` and links) and code blocks.
enum MdBlock: Equatable {
    case prose(AttributedString)
    case code(String)
}

enum Markdown {
    /// Splits [text] into prose and ``` code blocks. A code block still being written (no closing ```) shows as code already.
    static func blocks(_ text: String) -> [MdBlock] {
        var out: [MdBlock] = []
        var prose: [String] = [], code: [String] = []
        var inCode = false
        func flushProse() {
            let joined = prose.joined(separator: "\n").trimmingCharacters(in: .newlines)
            if !joined.isEmpty {
                for para in joined.components(separatedBy: "\n\n") where !para.isBlank { out.append(.prose(inline(para))) }
            }
            prose = []
        }
        for line in text.components(separatedBy: "\n") {
            if line.trimmingCharacters(in: .whitespaces).hasPrefix("```") {
                if inCode { out.append(.code(code.joined(separator: "\n"))); code = [] } else { flushProse() }
                inCode.toggle()
            } else if inCode {
                code.append(line)
            } else {
                prose.append(line)
            }
        }
        if inCode { out.append(.code(code.joined(separator: "\n"))) } else { flushProse() }
        return out
    }

    /// One paragraph: headings in bold, list dashes as bullets, then the inline marks. Text that is not valid Markdown shows as it is.
    static func inline(_ para: String) -> AttributedString {
        let lines = para.components(separatedBy: "\n").map { line -> String in
            let t = line.trimmingCharacters(in: .whitespaces)
            if let r = t.range(of: #"^#{1,6}\s+"#, options: .regularExpression) { return "**" + t[r.upperBound...] + "**" }
            if let r = line.range(of: #"^(\s*)[-*+]\s+"#, options: .regularExpression) {
                let indent = String(line[r].prefix { $0 == " " })
                return indent + "• " + String(line[r.upperBound...])
            }
            return line
        }
        let md = lines.joined(separator: "\n")
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        return (try? AttributedString(markdown: md, options: options)) ?? AttributedString(md)
    }
}
