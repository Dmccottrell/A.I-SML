import SwiftUI
import WebKit

@main
struct EmvryxApp: App {
    var body: some Scene {
        WindowGroup { RootView() }
    }
}

/// The whole app: the native screens (sign-in, chat) when the server's ios_native switch is on for you, otherwise the website.
struct RootView: View {
    @StateObject private var vm = AppModel()
    @ObservedObject private var lock = AppLock.shared
    @ObservedObject private var bridge = IncomingBridge.shared
    @Environment(\.scenePhase) private var phase

    private var locked: Bool { lock.locked && vm.screen != .signIn && vm.screen != .starting }

    var body: some View {
        ZStack {
            // While locked the app is not drawn at all (hiding it from VoiceOver was not enough: other accessibility tools still saw it).
            // Its state lives in the model, so it comes back as it was.
            if !locked {
                screens
            } else {
                LockScreen(lock: lock).transition(.opacity)
            }
        }
        .preferredColorScheme(vm.light ? .light : .dark)
        .onAppear { LocalAlerts.shared.setUp(); if vm.screen == .starting { vm.start() } }
        .onOpenURL { vm.receive($0) }
        .onReceive(bridge.$openChat) { if let id = $0 { bridge.openChat = nil; vm.screen = .chat; vm.openChat(id) } }
        .onReceive(bridge.$pending) { if let words = $0 { bridge.pending = nil; vm.receive(words) } }
        .onChange(of: phase) { p in
            if p == .background { lock.lockNow() }
            if p == .active && lock.locked { Task { await lock.unlock() } }
            if p == .active { vm.cameBack() }
        }
    }

    @ViewBuilder private var screens: some View {
        Group {
            Group {
                switch vm.screen {
                case .starting:
                    ZStack { Emvryx.bg.ignoresSafeArea(); Logo().frame(width: 64, height: 64) }
                case let .off(resting):
                    OffScreen(phoneOnline: true, resting: resting, retry: vm.start, onLocal: vm.phone.allowed && vm.phone.ready ? { vm.screen = .local } : nil)
                case .local:
                    LocalChatView(vm: vm, phone: vm.phone).environment(\.palette, vm.palette)
                case .signIn:
                    SignInView(vm: vm)
                case .chat:
                    ChatView(vm: vm)
                case .website:
                    ContentView()
                case let .page(path, title, run):
                    WebPage(path: path, title: title, run: run, done: vm.backToChat)
                case .memory:
                    MemoryPanel(vm: vm).environment(\.palette, vm.palette)
                case .files:
                    FilesPanel(vm: vm).environment(\.palette, vm.palette)
                case .skills:
                    SkillsPanel(vm: vm).environment(\.palette, vm.palette)
                case .settings:
                    SettingsPanel(vm: vm).environment(\.palette, vm.palette)
                case .code:
                    CodeView_(vm: vm)
                }
            }
        }
    }
}

/// One website page inside the native app (Settings, Admin, VryxCode ...), signed in, with a bar to go back to the chat.
struct WebPage: View {
    @StateObject private var web: WebController
    let title: String
    let done: () -> Void

    init(path: String, title: String, run: String?, done: @escaping () -> Void) {
        _web = StateObject(wrappedValue: WebController(start: URL(string: path, relativeTo: Site.home)!.absoluteURL, run: run))
        self.title = title
        self.done = done
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button(action: done) {
                    Label("Chat", systemImage: "chevron.left").font(Emvryx.body(16, semibold: true)).foregroundStyle(Emvryx.text)
                }
                .accessibilityLabel("Back to chat")
                Spacer()
            }
            .overlay(Text(title).font(Emvryx.body(17, semibold: true)).foregroundStyle(Emvryx.text))
            .padding(.horizontal, 16).frame(height: 52)
            Rectangle().fill(Emvryx.line).frame(height: 1)
            ZStack {
                Color(uiColor: Site.background)
                WebView(webView: web.webView).ignoresSafeArea(.keyboard)
                if web.offline { OffScreen(phoneOnline: web.phoneOnline, retry: web.retry) }
            }
        }
        .background(Emvryx.bg.ignoresSafeArea())
    }
}

/// The whole website full screen (version 1), the dark colour behind it (status bar and home bar areas too), and the
/// "No connection" page on top when the site cannot be reached.
struct ContentView: View {
    @StateObject private var web = WebController()

    var body: some View {
        ZStack {
            Color(uiColor: Site.background).ignoresSafeArea()
            // The page stays inside the safe area (clear of the notch and home bar); the web view moves for the keyboard by itself.
            WebView(webView: web.webView).ignoresSafeArea(.keyboard)
            if web.offline { OffScreen(phoneOnline: web.phoneOnline, retry: web.retry) }
        }
    }
}

/// Puts the controller's web view on screen.
struct WebView: UIViewRepresentable {
    let webView: WKWebView
    func makeUIView(context: Context) -> WKWebView { webView }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
