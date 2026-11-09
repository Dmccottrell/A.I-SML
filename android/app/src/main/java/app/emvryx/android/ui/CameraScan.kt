package app.emvryx.android.ui

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.ActivityResult
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.FileProvider
import com.google.mlkit.vision.documentscanner.GmsDocumentScannerOptions
import com.google.mlkit.vision.documentscanner.GmsDocumentScanning
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult
import java.io.File

// android_camera_scan: Take a photo with the phone's camera app, and Scan a document with Google's scanner (it finds the page, straightens and
// crops it, all on the phone). What comes back is added like a picked picture or file.

/** Opens the camera; [done] gets the photo (in the app's own cache), or nothing when it was cancelled */
@Composable
// rememberCamera: a Compose helper. It gives back a function that opens the phone's camera app; the photo is saved in the app's own cache folder and handed to done.
fun rememberCamera(done: (Uri) -> Unit): () -> Unit {
    val context = LocalContext.current
    // pending remembers the photo's address while the camera app is open.
    var pending by remember { mutableStateOf<Uri?>(null) }
    // The camera result arrives here: if the photo was taken, pass it on.
    val take = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        val u = pending
        pending = null
        if (ok && u != null) done(u)
    }
    return {
        // Old photos (over a day) are deleted so the cache does not grow.
        val dir = File(context.cacheDir, "camera").apply { mkdirs() }
        dir.listFiles()?.filter { System.currentTimeMillis() - it.lastModified() > 86_400_000L }?.forEach { it.delete() }     // yesterday's photos
        val file = File(dir, "photo-${System.currentTimeMillis()}.jpg")
        // FileProvider makes a safe address that the camera app is allowed to write to.
        val uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)
        pending = uri
        runCatching { take.launch(uri) }.onFailure { pending = null }
    }
}

/** Opens Google's document scanner; [done] gets the pages as pictures and the whole scan as one PDF ([problem] when it cannot open) */
@Composable
// rememberScanner: gives back a function that opens Google's document scanner, which finds the page, straightens it and crops it on the phone; done gets the page pictures and one PDF.
fun rememberScanner(problem: (String) -> Unit, done: (pages: List<Uri>, pdf: Uri?) -> Unit): () -> Unit {
    val context = LocalContext.current
    val scan = rememberLauncherForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { r: ActivityResult ->
        if (r.resultCode != Activity.RESULT_OK) return@rememberLauncherForActivityResult
        val res = GmsDocumentScanningResult.fromActivityResultIntent(r.data) ?: return@rememberLauncherForActivityResult
        done(res.pages?.map { it.imageUri }.orEmpty(), res.pdf?.uri)
    }
    return {
        // The scanner needs the screen (an Activity); if it cannot be found, say so.
        val activity = context.findActivity()
        if (activity == null) problem("The scanner could not open here.")
        else {
            // Options: pick from the gallery too, up to 10 pages, JPEG and PDF results, full scanner mode.
            val options = GmsDocumentScannerOptions.Builder().setGalleryImportAllowed(true).setPageLimit(10)
                .setResultFormats(GmsDocumentScannerOptions.RESULT_FORMAT_JPEG, GmsDocumentScannerOptions.RESULT_FORMAT_PDF)
                .setScannerMode(GmsDocumentScannerOptions.SCANNER_MODE_FULL).build()
            GmsDocumentScanning.getClient(options).getStartScanIntent(activity)
                .addOnSuccessListener { scan.launch(IntentSenderRequest.Builder(it).build()) }
                .addOnFailureListener { problem("The document scanner needs Google Play services on this phone. Take a photo instead.") }
        }
    }
}

// findActivity: walk through the wrappers around a Context until the Activity is found.
fun Context.findActivity(): Activity? {
    var c: Context? = this
    while (c is ContextWrapper) {
        if (c is Activity) return c
        c = c.baseContext
    }
    return null
}
