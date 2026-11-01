// The words on the "downloading the offline model" notification. Kept separate from the service that shows it so the text can be unit-tested.
package app.emvryx.android.local

/** What the "downloading" notification says: the phone model and the picture model are read as one (the model first). */
object DownloadNote {
    /**
     * One snapshot of the download.
     * [active] = something is downloading right now; [title]/[text] = the two lines of the notification;
     * [done]/[total] = bytes so far and bytes in all (0 when unknown).
     */
    data class Note(val active: Boolean, val title: String, val text: String, val done: Long = 0, val total: Long = 0) {
        // The progress bar needs a whole number 0-100. "coerceIn" stops it ever going below 0 or above 100.
        val percent get() = if (total > 0) (done * 100 / total).toInt().coerceIn(0, 100) else 0
    }

    // Bytes -> "123 MB". "shl 20" is 2^20 = 1,048,576 bytes in a megabyte.
    private fun mb(b: Long) = "${b / (1 shl 20)} MB"

    /** Look at both downloads and describe the one that is busy. The phone model is shown first when both are. */
    fun of(model: PhoneModel.Status, picture: PhoneModel.Status): Note {
        // Pick which download to talk about: the model if it is downloading/checking, otherwise the picture model
        val (name, s) = if (model is PhoneModel.Status.Downloading || model == PhoneModel.Status.Checking) "the phone model" to model else "the picture model" to picture
        return when (s) {
            // Bytes are arriving: show "500 MB of 2000 MB" and a progress bar
            is PhoneModel.Status.Downloading -> Note(true, "Downloading $name", "${mb(s.done)} of ${mb(s.total)}. It carries on with the app closed.", s.done, s.total)
            // All bytes arrived and the app is checking the file is not damaged (no bar, just a spinner)
            PhoneModel.Status.Checking -> Note(true, "Checking $name", "Making sure it arrived whole…")
            // Anything else (nothing started, ready, failed): nothing is downloading
            else -> Note(false, "", "")
        }
    }

    /** The one line when it is over: ready, or why it stopped ([model] then [picture]); null when nothing happened */
    fun finished(model: PhoneModel.Status, picture: PhoneModel.Status): Pair<String, String>? {
        // A failure wins: say why it stopped (the message was written in plain words where the failure happened)
        (model as? PhoneModel.Status.Failed)?.let { return "The download stopped" to it.message }
        (picture as? PhoneModel.Status.Failed)?.let { return "The download stopped" to it.message }
        // No failure: if either model is now on the phone, say it is ready; otherwise there is nothing to report
        return if (model == PhoneModel.Status.Ready || picture == PhoneModel.Status.Ready) "Ready for offline" to "Emvryx can answer on this phone with the PC off." else null
    }
}
