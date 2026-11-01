package app.emvryx.android.ui

import android.content.Context
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.OpenableColumns
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.emvryx.android.data.Ctx
import app.emvryx.android.data.DocInfo
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.LocalPalette
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

// ChatExtras.kt: smaller pieces of the chat screen: reading a picked picture/file, showing picture thumbnails and the files
// attached to a message, the "memory ring" by the message box, and the small dialogs for Regenerate, Report and Edit.
// They are Jetpack Compose functions (@Composable): each one describes a bit of screen, and Compose redraws it when the
// values it reads (state) change. The chat screen that uses them is built around AppViewModel (the app's shared state).
// (PWA = the website installed as an app.)
//
// What the PWA's chat has beyond the first milestone (web/js/chat.js, documents.js): pictures and files, the memory ring, reporting an answer,
// editing what you asked, and the chat list's Pin and Delete.

/**
 * A picture or file picked on the phone: its name and bytes (null when it cannot be read).
 * [uri] is Android's address for the chosen item; the content resolver is the system service that opens it.
 */
fun readPicked(context: Context, uri: Uri): Pair<String, ByteArray>? = runCatching {
    // Start with a plain name in case the phone does not give one.
    var name = "file"
    // Ask the system for the file's display name (the query returns a small table; `use` closes it when done).
    context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
        if (c.moveToFirst()) name = c.getString(0) ?: name
    }
    // A name with no extension (e.g. "IMG_001") gets one from the file's type, so the server can tell pictures apart: "image/jpeg" gives "jpg".
    if (!name.contains('.')) {
        val ext = context.contentResolver.getType(uri)?.substringAfter('/')?.let { if (it == "jpeg") "jpg" else it }
        if (ext != null) name = "$name.$ext"
    }
    // Read the whole file into memory. If it cannot be opened, leave readPicked and give null (the `return null` leaves the whole function).
    val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: return null
    // The last line is the result: a (name, bytes) pair.
    name to bytes
}.getOrNull()

/** A picture someone sent, loaded from the server (the session cookie goes with it). Shows a picture icon until the image has loaded or if it fails. [size] is the square side. */
@Composable
fun PictureThumb(vm: AppViewModel, doc: DocInfo, size: Dp, modifier: Modifier = Modifier) {
    // produceState runs the block in the background and exposes its result as state; it starts again if doc.id changes.
    // The bytes come from the server; decoding them into a bitmap is heavy, so it runs on the Default thread pool (not the screen thread).
    val bmp by produceState<ImageBitmap?>(null, doc.id) {
        value = vm.pictureBytes(doc.id)?.let { b -> withContext(Dispatchers.Default) { BitmapFactory.decodeByteArray(b, 0, b.size)?.asImageBitmap() } }
    }
    // A square box with rounded corners and a thin border; the picture is cropped to fill it.
    val shape = RoundedCornerShape(12.dp)
    Box(modifier.size(size).clip(shape).background(Emvryx.surface2).border(1.dp, Emvryx.line, shape), contentAlignment = Alignment.Center) {
        // Show the picture when we have it, otherwise a placeholder emoji.
        bmp?.let { Image(it, doc.name, contentScale = ContentScale.Crop, modifier = Modifier.size(size)) }
            ?: Text("🖼", fontSize = 18.sp)
    }
}

/** The pictures and files that go with a message (in the thread, and waiting in the box with an × to take one off). [onRemove] is null in the thread (no ×). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun DocRow(vm: AppViewModel, docs: List<DocInfo>, onRemove: ((DocInfo) -> Unit)? = null) {
    if (docs.isEmpty()) return
    // FlowRow lays items left to right and wraps onto a new line when the row is full.
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        docs.forEach { d ->
            // Each item is a box so the × button can sit on its top-right corner.
            Box {
                // Pictures show as thumbnails (big in the thread, small while waiting in the box); other files show as a name tag.
                if (d.picture) PictureThumb(vm, d, if (onRemove == null) 140.dp else 56.dp)
                else Text(
                    "📄 " + d.name, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.clip(RoundedCornerShape(10.dp)).background(Emvryx.surface2).border(1.dp, Emvryx.line, RoundedCornerShape(10.dp))
                        .padding(horizontal = 10.dp, vertical = 8.dp),
                )
                // The × button, drawn only while the file is still waiting to be sent.
                if (onRemove != null) Box(
                    Modifier.align(Alignment.TopEnd).padding(2.dp).size(20.dp).clip(CircleShape).background(Emvryx.bg).clickable { onRemove(d) },
                    contentAlignment = Alignment.Center,
                ) { Text("×", fontSize = 13.sp) }
            }
        }
    }
}

/** The memory ring by the message box: how full the model's memory is (feature flag context_meter). Tapping calls [onClick]. */
@Composable
fun MemoryRing(ctx: Ctx, onClick: () -> Unit) {
    val p = LocalPalette.current
    // The fullness as a 0..1 fraction, kept inside that range.
    val frac = (ctx.pct / 100.0).toFloat().coerceIn(0f, 1f)
    // The ring turns red when memory is within 10% of the point where old messages get folded away (compactAt).
    val color = if (ctx.compactAt > 0 && ctx.used >= ctx.compactAt * 0.9) Emvryx.danger else p.accent
    Box(Modifier.size(36.dp).clip(CircleShape).clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        // Canvas lets us draw shapes by hand: a grey full circle (the track), then a coloured arc on top for the amount used.
        Canvas(Modifier.size(28.dp)) {
            // w = ring thickness in pixels. Arcs are drawn inset by half of it so the thick line does not get cut off at the edge.
            val w = 3.dp.toPx()
            // Grey track: a full 360-degree circle.
            drawArc(Emvryx.surface2, 0f, 360f, false, Offset(w / 2, w / 2), Size(size.width - w, size.height - w), style = Stroke(w))
            // The used part: starts at the top (-90 degrees), sweeps clockwise by fraction x 360 degrees, with rounded ends.
            drawArc(color, -90f, 360f * frac, false, Offset(w / 2, w / 2), Size(size.width - w, size.height - w), style = Stroke(w, cap = StrokeCap.Round))
        }
        // The percent in the middle.
        Text("${Math.round(ctx.pct)}%", fontSize = 9.sp, color = Emvryx.muted)
    }
}

/** The "Regenerate" choices (app/regen_modes.py): one button per way the new answer can differ. [close] hides the menu. */
@Composable
fun RegenMenuBody(vm: AppViewModel, close: () -> Unit) {
    Text("REGENERATE", color = Emvryx.muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.2.sp, modifier = Modifier.padding(6.dp))
    // The server's list of choices; if it sent none, fall back to a single "Try again".
    val opts = vm.state?.regenOptions.orEmpty().ifEmpty { listOf(app.emvryx.android.data.RegenOption("again", "Try again", "Same question, a fresh answer")) }
    opts.forEach { o ->
        Column(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).border(1.dp, Emvryx.line, RoundedCornerShape(14.dp))
                // Tapping asks for a new answer in that style and closes the menu.
                .clickable { vm.regenerate(o.id); close() }.padding(horizontal = 14.dp, vertical = 10.dp),
        ) {
            Text(o.label, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            if (o.blurb.isNotBlank()) Text(o.blurb, color = Emvryx.muted, fontSize = 14.sp)
        }
    }
}

// What can be wrong with an answer: the word sent to the server, then the label shown.
private val REPORT_KINDS = listOf("wrong_fact" to "Wrong fact", "ignored" to "Ignored my question", "too_long" to "Too long", "too_short" to "Too short or vague",
                                  "cut_off" to "Cut off", "unsafe" to "Not appropriate", "other" to "Something else")

/** "That didn't work": what was wrong, and a note. The question and answer go to the owner (said before sending, as on the website). [onSend] gets (kind, note). */
@Composable
fun ReportDialog(onSend: (String, String) -> Unit, onClose: () -> Unit) {
    // The chosen reason and the typed note live here while the dialog is open.
    var kind by remember { mutableStateOf("wrong_fact") }
    var note by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onClose, containerColor = Emvryx.surface,
        // The dialog body: one tappable row per reason (the chosen one gets an accent border), a note box and a privacy line.
        title = { Text("What went wrong?") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                REPORT_KINDS.forEach { (id, label) ->
                    val p = LocalPalette.current
                    Text(label, fontSize = 15.sp, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
                        .border(1.dp, if (kind == id) p.accent else Emvryx.line, RoundedCornerShape(10.dp)).clickable { kind = id }.padding(10.dp))
                }
                NoteBox(note, { note = it }, "Anything else? (optional)")
                Text("Your question and this answer go to the owner so the next version gets it right.", color = Emvryx.muted, fontSize = 13.sp)
            }
        },
        // Send reports the choice, then closes.
        confirmButton = { TextButton({ onSend(kind, note); onClose() }) { Text("Send") } },
        dismissButton = { TextButton(onClose) { Text("Cancel") } },
    )
}

/** Change what you asked: the answers after it are replaced with a new one. [start] is the old text; [laterAnswers] says whether there are answers to replace. */
@Composable
fun EditDialog(start: String, laterAnswers: Boolean, onSave: (String) -> Unit, onClose: () -> Unit) {
    // The text being edited, starting from the old message.
    var text by remember { mutableStateOf(start) }
    AlertDialog(
        onDismissRequest = onClose, containerColor = Emvryx.surface,
        title = { Text("Edit your message") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                NoteBox(text, { text = it }, "Your message", minHeight = 100.dp)
                if (laterAnswers) Text("This replaces the answers after it with a new one.", color = Emvryx.muted, fontSize = 13.sp)
            }
        },
        // Save is disabled while the text is blank.
        confirmButton = { TextButton({ onSave(text); onClose() }, enabled = text.isNotBlank()) { Text("Save and ask again") } },
        dismissButton = { TextButton(onClose) { Text("Cancel") } },
    )
}

/** A multi-line text input with a rounded box and a grey [placeholder] that shows while it is empty. */
@Composable
fun NoteBox(value: String, onChange: (String) -> Unit, placeholder: String, minHeight: Dp = 48.dp) {
    val p = LocalPalette.current
    // Box draws the outline; the placeholder sits under the real input and is hidden once there is text.
    Box(Modifier.fillMaxWidth().heightIn(min = minHeight).clip(RoundedCornerShape(12.dp)).background(Emvryx.bg)
        .border(1.dp, Emvryx.line, RoundedCornerShape(12.dp)).padding(12.dp)) {
        if (value.isEmpty()) Text(placeholder, color = Emvryx.muted, fontSize = 15.sp)
        BasicTextField(value, onChange, Modifier.fillMaxWidth(), textStyle = MaterialTheme.typography.bodyMedium.copy(color = Emvryx.text, fontSize = 15.sp),
            cursorBrush = SolidColor(p.accent))
    }
}

/** A row in the side panel that opens another part of Emvryx (.link): the website's [icon], the name, and a small grey [note] ("Never saved") */
@Composable
fun SideLink(icon: String, label: String, note: String = "", onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 42.dp).clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick).padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        PwaIcon(icon, Emvryx.muted)
        // the name always gets its room on one line; the note takes what is left and ends in "…" (a long note squeezed "Scheduled tasks" to a letter per line)
        Text(label, fontSize = 16.sp, fontWeight = FontWeight.Medium, maxLines = 1, softWrap = false)
        Text(note, color = Emvryx.muted, fontSize = 12.sp, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
            textAlign = androidx.compose.ui.text.style.TextAlign.End, modifier = Modifier.weight(1f))
    }
}
