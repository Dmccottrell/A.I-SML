import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

/// Pictures and files for the message box (android/.../ui/ChatExtras.kt readPicked, PictureThumb, DocRow).

/// Reads what was picked into (name, bytes). Pictures are turned upright, made a sensible size and saved as JPEG (the website does the same
/// before it uploads, and iPhone photos are often HEIC, which the models cannot open).
enum Picked {
    static let longestSide: CGFloat = 2000

    static func picture(_ data: Data, name: String) -> (name: String, data: Data)? {
        guard let image = UIImage(data: data) else { return nil }
        let big = max(image.size.width, image.size.height)
        let scale = big > longestSide ? longestSide / big : 1
        let size = CGSize(width: (image.size.width * scale).rounded(), height: (image.size.height * scale).rounded())
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        let upright = UIGraphicsImageRenderer(size: size, format: format).image { _ in image.draw(in: CGRect(origin: .zero, size: size)) }
        guard let jpeg = upright.jpegData(compressionQuality: 0.85) else { return nil }
        let stem = (name as NSString).deletingPathExtension
        return (stem + ".jpg", jpeg)
    }

    /// A file from the Files app (a security-scoped address): its name and bytes; pictures are shrunk like photos.
    static func file(_ url: URL) -> (name: String, data: Data)? {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        guard let data = try? Data(contentsOf: url) else { return nil }
        if let type = UTType(filenameExtension: url.pathExtension), type.conforms(to: .image) { return picture(data, name: url.lastPathComponent) }
        return (url.lastPathComponent, data)
    }
}

/// The camera, for "Take photo".
struct CameraPicker: UIViewControllerRepresentable {
    let done: (UIImage?) -> Void
    func makeUIViewController(context: Context) -> UIImagePickerController {
        let p = UIImagePickerController()
        p.sourceType = .camera
        p.delegate = context.coordinator
        return p
    }
    func updateUIViewController(_ vc: UIImagePickerController, context: Context) {}
    func makeCoordinator() -> Coordinator { Coordinator(done) }
    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let done: (UIImage?) -> Void
        init(_ done: @escaping (UIImage?) -> Void) { self.done = done }
        func imagePickerController(_ p: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            done(info[.originalImage] as? UIImage)
        }
        func imagePickerControllerDidCancel(_ p: UIImagePickerController) { done(nil) }
    }
}

/// A picture that went with a message, loaded from the server once and kept.
struct PictureThumb: View {
    @ObservedObject var vm: AppModel
    let doc: DocInfo
    let size: CGFloat
    @State private var image: UIImage?
    private static let cache = NSCache<NSNumber, UIImage>()

    var body: some View {
        Group {
            if let image { Image(uiImage: image).resizable().scaledToFill() } else { Emvryx.surface2 }
        }
        .frame(width: size, height: size).clipShape(RoundedRectangle(cornerRadius: 12))
        .accessibilityLabel(doc.name)
        .task(id: doc.id) {
            if let hit = Self.cache.object(forKey: NSNumber(value: doc.id)) { image = hit; return }
            if let data = await vm.api.picture(doc.id), let img = UIImage(data: data) {
                Self.cache.setObject(img, forKey: NSNumber(value: doc.id))
                image = img
            }
        }
    }
}

/// The pictures and files that go with a message: pictures as small previews, files as their name. [onRemove]: a × on each (the box).
struct DocRow: View {
    @ObservedObject var vm: AppModel
    let docs: [DocInfo]
    var onRemove: ((DocInfo) -> Void)?

    var body: some View {
        if !docs.isEmpty {
            Flow(spacing: 8) {
                ForEach(docs) { d in
                    HStack(spacing: 6) {
                        if d.isPicture { PictureThumb(vm: vm, doc: d, size: onRemove == nil ? 96 : 56) }
                        else {
                            Text("📄 " + d.name).font(Emvryx.body(14)).foregroundStyle(Emvryx.text).lineLimit(1)
                                .padding(.horizontal, 12).frame(height: 36).background(Emvryx.surface2, in: Capsule())
                        }
                        if let onRemove {
                            Button { onRemove(d) } label: {
                                Image(systemName: "xmark").font(.system(size: 11, weight: .bold)).foregroundStyle(Emvryx.muted).frame(width: 24, height: 24)
                            }
                            .accessibilityLabel("Remove " + d.name)
                        }
                    }
                }
            }
        }
    }
}
