package app.emvryx.android

import app.emvryx.android.ui.offTip
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** "Emvryx is off": a tip about the phone model when it could answer here but is not on the phone yet */
class OffTipTest {
    @Test
    fun theTipShowsOnlyWhenItHelps() {
        assertTrue(offTip(allowed = true, ready = false, downloading = false)!!.contains("download the phone model while the PC is on"))
        assertTrue(offTip(allowed = true, ready = false, downloading = true)!!.contains("still downloading"))
        assertNull(offTip(allowed = true, ready = true, downloading = false))          // the model is here: the Chat on this phone button shows instead
        assertNull(offTip(allowed = false, ready = false, downloading = false))        // the switch is off for this person: nothing to suggest
    }
}
