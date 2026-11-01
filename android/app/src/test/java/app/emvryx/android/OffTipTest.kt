// Unit test for ui/OffScreen.kt offTip(): the small hint on the "Emvryx is off" screen that suggests downloading the phone model
// (so the phone can answer by itself when the PC is off). Tested on its own because it is plain text logic.
package app.emvryx.android

import app.emvryx.android.ui.offTip
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** "Emvryx is off": a tip about the phone model when it could answer here but is not on the phone yet */
class OffTipTest {
    /** Proves the tip appears only when it helps: allowed and not on the phone yet; it differs while a download is already running. */
    @Test
    fun theTipShowsOnlyWhenItHelps() {
        // allowed, not downloaded, not downloading: suggest downloading it
        assertTrue(offTip(allowed = true, ready = false, downloading = false)!!.contains("download the phone model while the PC is on"))
        // allowed and already downloading: say it is still downloading
        assertTrue(offTip(allowed = true, ready = false, downloading = true)!!.contains("still downloading"))
        assertNull(offTip(allowed = true, ready = true, downloading = false))          // the model is here: the Chat on this phone button shows instead
        assertNull(offTip(allowed = false, ready = false, downloading = false))        // the switch is off for this person: nothing to suggest
    }
}
