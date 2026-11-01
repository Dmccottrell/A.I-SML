package app.emvryx.android.local

/** What the "downloading" notification says: the phone model and the picture model are read as one (the model first). */
object DownloadNote {
    data class Note(val active: Boolean, val title: String, val text: String, val done: Long = 0, val total: Long = 0) {
        val percent get() = if (total > 0) (done * 100 / total).toInt().coerceIn(0, 100) else 0
    }

    private fun mb(b: Long) = "${b / (1 shl 20)} MB"

    fun of(model: PhoneModel.Status, picture: PhoneModel.Status): Note {
        val (name, s) = if (model is PhoneModel.Status.Downloading || model == PhoneModel.Status.Checking) "the phone model" to model else "the picture model" to picture
        return when (s) {
            is PhoneModel.Status.Downloading -> Note(true, "Downloading $name", "${mb(s.done)} of ${mb(s.total)}. It carries on with the app closed.", s.done, s.total)
            PhoneModel.Status.Checking -> Note(true, "Checking $name", "Making sure it arrived whole…")
            else -> Note(false, "", "")
        }
    }

    /** The one line when it is over: ready, or why it stopped ([model] then [picture]); null when nothing happened */
    fun finished(model: PhoneModel.Status, picture: PhoneModel.Status): Pair<String, String>? {
        (model as? PhoneModel.Status.Failed)?.let { return "The download stopped" to it.message }
        (picture as? PhoneModel.Status.Failed)?.let { return "The download stopped" to it.message }
        return if (model == PhoneModel.Status.Ready || picture == PhoneModel.Status.Ready) "Ready for offline" to "Emvryx can answer on this phone with the PC off." else null
    }
}
