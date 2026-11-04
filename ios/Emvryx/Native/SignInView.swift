import SwiftUI

/// The sign-in card (android/.../ui/SignInScreen.kt and the PWA's .auth .card): "Welcome back" with name and password, an access key,
/// or a code by email, and the second step (an authenticator code) when the account asks for it.
struct SignInView: View {
    @ObservedObject var vm: AppModel
    @State private var way = SignInWay.password
    @State private var id = ""
    @State private var secret = ""
    @State private var code = ""
    @State private var email = ""
    @State private var show = false

    private var twoStep: Bool { vm.twoStepTicket != nil }
    private var codeSent: Bool { vm.emailSentTo != nil }

    private var ready: Bool {
        if twoStep { return !code.isBlank }
        if way == .email { return codeSent ? !code.isBlank : email.contains("@") }
        return !secret.isBlank && (way == .key || !id.isBlank)
    }

    private func submit() {
        guard ready, !vm.signInBusy else { return }
        if twoStep { vm.submitTwoStep(code) }
        else if way == .email { codeSent ? vm.signInWithEmailCode(code) : vm.sendEmailCode(email) }
        else { vm.signIn(way, id: id, secret: secret) }
    }

    var body: some View {
        ZStack {
            Emvryx.bg.ignoresSafeArea()
            AccentWash(glow: Emvryx.glow, height: 420).ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 10) {
                        Logo().frame(width: 32, height: 32)
                        Text("Emvryx").font(Emvryx.heading(22, bold: true)).foregroundStyle(Emvryx.text)
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        Text(twoStep ? "Two-step check" : "Welcome back").font(Emvryx.heading(28, bold: true)).foregroundStyle(Emvryx.text)
                        Text(twoStep ? "Enter the 6-digit code from your authenticator app, or one of your recovery codes."
                                     : "Sign in to keep going where you left off.")
                            .font(Emvryx.body(16)).foregroundStyle(Emvryx.muted)
                    }
                    fields
                    if let e = vm.signInError { Text(e).font(Emvryx.body(15)).foregroundStyle(Emvryx.danger) }
                    PwaButton(text: twoStep ? "Continue" : way == .email && !codeSent ? "Email me a code" : "Sign in",
                              enabled: ready, busy: vm.signInBusy, action: submit)
                    if twoStep {
                        PwaButton(text: "Back", ghost: true) { vm.cancelTwoStep(); code = "" }
                    } else {
                        HStack(spacing: 12) {
                            Rectangle().fill(Emvryx.line).frame(height: 1)
                            Text("or").font(Emvryx.body(15)).foregroundStyle(Emvryx.muted)
                            Rectangle().fill(Emvryx.line).frame(height: 1)
                        }
                        if way != .password { PwaButton(text: "Sign in with a password", ghost: true) { switchTo(.password) } }
                        if way != .key { PwaButton(text: "Use an access key", ghost: true) { switchTo(.key) } }
                        if vm.emailOffered && way != .email { PwaButton(text: "Email me a sign-in code", ghost: true) { switchTo(.email) } }
                        Text("Forgot your password? Ask the owner for a one-time sign-in link, then choose a new one in Settings > Security.")
                            .font(Emvryx.body(15)).foregroundStyle(Emvryx.muted)
                    }
                }
                .padding(.horizontal, 20).padding(.vertical, 24)
                .frame(maxWidth: 420)
                .overlay(RoundedRectangle(cornerRadius: 22).stroke(Emvryx.line, lineWidth: 1))
                .padding(.horizontal, 20).padding(.vertical, 32)
                .frame(maxWidth: .infinity)
                Text("Server: " + Site.host).font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).padding(.bottom, 20)
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .preferredColorScheme(.dark)
        .onAppear { vm.checkSignInOptions() }
    }

    @ViewBuilder private var fields: some View {
        if twoStep {
            Field(label: "Code", text: $code, placeholder: "123456", keyboard: .numberPad, onDone: submit)
        } else if way == .password {
            Field(label: "Name or email", text: $id, placeholder: "Name or email", keyboard: .emailAddress, content: .username)
            Field(label: "Password", text: $secret, placeholder: "Your password", hidden: !show, content: .password, onDone: submit) {
                Button(show ? "Hide" : "Show") { show.toggle() }
                    .font(Emvryx.body(16, semibold: true)).foregroundStyle(Palette.brand.accentText).padding(.horizontal, 10)
            }
        } else if way == .email && codeSent {
            Text("If \(vm.emailSentTo ?? "") belongs to an account, a 6-digit code is on its way. It works for 10 minutes.")
                .font(Emvryx.body(15)).foregroundStyle(Emvryx.muted)
            Field(label: "Code from the email", text: $code, placeholder: "123456", keyboard: .numberPad, content: .oneTimeCode, onDone: submit)
        } else if way == .email {
            Field(label: "Email", text: $email, placeholder: "you@example.com", keyboard: .emailAddress, content: .emailAddress, onDone: submit)
        } else {
            Field(label: "Access key", text: $secret, placeholder: "emvx_…", hidden: true, onDone: submit)
        }
    }

    private func switchTo(_ w: SignInWay) {
        way = w
        secret = ""
        code = ""
        vm.cancelEmailCode()
    }
}

/// .field: a label above a rounded box with an accent outline while typing; [trailing] sits at the right (Show).
struct Field<Trailing: View>: View {
    let label: String
    @Binding var text: String
    var placeholder = ""
    var hidden = false
    var keyboard: UIKeyboardType = .default
    var content: UITextContentType?
    var onDone: (() -> Void)?
    @ViewBuilder var trailing: () -> Trailing
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(Emvryx.body(15, semibold: true)).foregroundStyle(Emvryx.text)
            HStack(spacing: 0) {
                Group {
                    if hidden { SecureField("", text: $text, prompt: prompt) } else { TextField("", text: $text, prompt: prompt) }
                }
                .font(Emvryx.body(16)).foregroundStyle(Emvryx.text).tint(Emvryx.accent)
                .keyboardType(keyboard).textContentType(content)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                .focused($focused)
                .submitLabel(.done).onSubmit { onDone?() }
                .accessibilityLabel(label)
                .padding(.horizontal, 14).frame(minHeight: 50)
                trailing()
            }
            .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(focused ? Emvryx.accent : Emvryx.line, lineWidth: 1))
        }
    }

    private var prompt: Text { Text(placeholder).foregroundColor(Emvryx.muted) }
}

extension Field where Trailing == EmptyView {
    init(label: String, text: Binding<String>, placeholder: String = "", hidden: Bool = false, keyboard: UIKeyboardType = .default,
         content: UITextContentType? = nil, onDone: (() -> Void)? = nil) {
        self.init(label: label, text: text, placeholder: placeholder, hidden: hidden, keyboard: keyboard, content: content, onDone: onDone) { EmptyView() }
    }
}

extension String { var isBlank: Bool { trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } }
