import Foundation

/// The `emvryx://ask?text=…` link that carries shared words into the app. This one file is built into both the app and the share extension,
/// so what the extension writes is exactly what the app reads (EmvryxTests checks the round trip).
enum EmvryxLink {
    static let longest = 4000

    /// The link for [text]; the text is cut at [longest] characters.
    static func ask(_ text: String) -> URL? {
        var c = URLComponents()
        c.scheme = "emvryx"
        c.host = "ask"
        // URLComponents leaves "+" and "&" alone in a value; spell them out so the words come back exactly as they went in.
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "+&=#")
        c.percentEncodedQueryItems = [URLQueryItem(name: "text", value: String(text.prefix(longest)).addingPercentEncoding(withAllowedCharacters: allowed))]
        return c.url
    }

    /// The words in an `emvryx://ask` link, or nil for any other link (or nothing but spaces).
    static func words(in url: URL) -> String? {
        guard url.scheme?.lowercased() == "emvryx", url.host?.lowercased() == "ask",
              let text = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first(where: { $0.name == "text" })?.value,
              !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        return String(text.prefix(longest))
    }
}
