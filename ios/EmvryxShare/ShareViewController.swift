import UIKit
import UniformTypeIdentifiers

/// Share to Emvryx (Android's share target): text or a link shared from another app opens Emvryx with the words in the message box of a new
/// chat, ready to send. It only hands the words over (nothing is sent): the app opens `emvryx://ask?text=…`.
final class ShareViewController: UIViewController {
    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        Task {
            let text = await sharedText()
            if let text, !text.isEmpty, let url = EmvryxLink.ask(text) { open(url) }
            extensionContext?.completeRequest(returningItems: nil)
        }
    }

    /// The shared words: the text, or the link (with its page title when there is one).
    private func sharedText() async -> String? {
        var parts: [String] = []
        for item in (extensionContext?.inputItems as? [NSExtensionItem]) ?? [] {
            for provider in item.attachments ?? [] {
                if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier),
                   let url = try? await provider.loadItem(forTypeIdentifier: UTType.url.identifier) as? URL {
                    parts.append(url.absoluteString)
                } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier),
                          let text = try? await provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) as? String {
                    parts.append(text)
                }
            }
            if parts.isEmpty, let text = item.attributedContentText?.string { parts.append(text) }
        }
        return parts.joined(separator: "\n")
    }

    /// An extension cannot call UIApplication.open directly: it walks up to the app that hosts it and asks that to open the link.
    private func open(_ url: URL) {
        var responder: UIResponder? = self
        while let r = responder {
            if let app = r as? UIApplication { app.open(url); return }
            responder = r.next
        }
        let selector = NSSelectorFromString("openURL:")
        responder = self
        while let r = responder {
            if r.responds(to: selector) { r.perform(selector, with: url); return }
            responder = r.next
        }
    }
}
