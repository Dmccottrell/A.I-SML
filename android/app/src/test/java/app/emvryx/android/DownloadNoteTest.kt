// Unit tests for local/DownloadNote.kt: the words and progress number on the "downloading the offline model" notification.
// The text lives in plain code (not in the Android service that shows it) so it can be tested here without a phone.
package app.emvryx.android

import app.emvryx.android.local.DownloadNote
import app.emvryx.android.local.PhoneModel.Status
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Tests what the download notification says while the phone model and the picture model download, and when they finish. */
class DownloadNoteTest {
    // One megabyte in bytes: "1L shl 20" shifts the number 1 left by 20 bits, which is 2^20 = 1,048,576. The L makes it a Long (a big whole number).
    private val mb = 1L shl 20

    /** Proves a half-way-ish download shows the right title, text and percentage. */
    @Test
    fun theNotificationShowsHowFarTheModelIs() {
        // 500 MB done of 2000 MB for the phone model; the picture model has not started (Status.None)
        val n = DownloadNote.of(Status.Downloading(500 * mb, 2000 * mb), Status.None)
        assertTrue(n.active)
        assertEquals(25, n.percent)                         // 500 / 2000 = 25 percent
        assertEquals("Downloading the phone model", n.title)
        assertEquals("500 MB of 2000 MB. It carries on with the app closed.", n.text)
    }

    /** Proves which model the note talks about when both are busy, and when it says "nothing active". */
    @Test
    fun theModelComesBeforeThePictureModelAndNothingIsActiveWhenIdle() {
        // both downloading: the phone model is named first
        assertEquals("Downloading the phone model", DownloadNote.of(Status.Downloading(1, 2), Status.Downloading(1, 2)).title)
        // only the picture model is downloading, so it is the one named
        assertEquals("Downloading the picture model", DownloadNote.of(Status.Ready, Status.Downloading(1 * mb, 4 * mb)).title)
        // both finished or never started: not active
        assertEquals(false, DownloadNote.of(Status.Ready, Status.None).active)
        // "Checking" (making sure the file arrived whole) still counts as active
        assertEquals(true, DownloadNote.of(Status.Checking, Status.None).active)
    }

    /** Proves the final message: "Ready for offline", the reason a download stopped, or nothing (null) when nothing happened. */
    @Test
    fun whenItIsOverItSaysReadyOrWhyItStopped() {
        assertEquals("Ready for offline", DownloadNote.finished(Status.Ready, Status.None)?.first)
        // the second part of the pair is the failure's own plain-words message
        assertEquals("Not enough free space.", DownloadNote.finished(Status.Failed("Not enough free space."), Status.None)?.second)
        assertNull(DownloadNote.finished(Status.None, Status.None))
    }
}
