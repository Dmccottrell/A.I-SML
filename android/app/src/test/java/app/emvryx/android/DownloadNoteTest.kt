package app.emvryx.android

import app.emvryx.android.local.DownloadNote
import app.emvryx.android.local.PhoneModel.Status
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DownloadNoteTest {
    private val mb = 1L shl 20

    @Test
    fun theNotificationShowsHowFarTheModelIs() {
        val n = DownloadNote.of(Status.Downloading(500 * mb, 2000 * mb), Status.None)
        assertTrue(n.active)
        assertEquals(25, n.percent)
        assertEquals("Downloading the phone model", n.title)
        assertEquals("500 MB of 2000 MB. It carries on with the app closed.", n.text)
    }

    @Test
    fun theModelComesBeforeThePictureModelAndNothingIsActiveWhenIdle() {
        assertEquals("Downloading the phone model", DownloadNote.of(Status.Downloading(1, 2), Status.Downloading(1, 2)).title)
        assertEquals("Downloading the picture model", DownloadNote.of(Status.Ready, Status.Downloading(1 * mb, 4 * mb)).title)
        assertEquals(false, DownloadNote.of(Status.Ready, Status.None).active)
        assertEquals(true, DownloadNote.of(Status.Checking, Status.None).active)
    }

    @Test
    fun whenItIsOverItSaysReadyOrWhyItStopped() {
        assertEquals("Ready for offline", DownloadNote.finished(Status.Ready, Status.None)?.first)
        assertEquals("Not enough free space.", DownloadNote.finished(Status.Failed("Not enough free space."), Status.None)?.second)
        assertNull(DownloadNote.finished(Status.None, Status.None))
    }
}
