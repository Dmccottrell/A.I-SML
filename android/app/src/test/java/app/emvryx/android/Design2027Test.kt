package app.emvryx.android

import app.emvryx.android.ui.D27Telemetry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** design_2027: the speed line under a reply */
class Design2027Test {
    @Test
    fun theSpeedLineSaysTokensPerSecondTheModelAndTheFirstWord() {
        // 640 letters is about 160 tokens; written in 2.5 s after a 0.5 s wait for the first word: 160 / 2.5 = 64 a second
        assertEquals("~64 tok/s · Flare 3 · first word 500 ms", D27Telemetry.line(640, 500, 3000, "Flare 3"))
    }

    @Test
    fun noModelNameLeavesThatPartOut() {
        assertEquals("~40 tok/s · first word 0 ms", D27Telemetry.line(400, 0, 2500, ""))
    }

    @Test
    fun anEmptyOrInstantReplyHasNoLine() {
        assertNull(D27Telemetry.line(0, 100, 2000, "Flare 3"))
        assertNull(D27Telemetry.line(100, 0, 0, "Flare 3"))
    }
}
