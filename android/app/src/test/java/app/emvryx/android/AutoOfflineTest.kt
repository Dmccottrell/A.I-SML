package app.emvryx.android

import app.emvryx.android.local.AutoOffline
import app.emvryx.android.local.AutoOffline.Step
import app.emvryx.android.local.PhoneChoice
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AutoOfflineTest {
    private val gb = 1L shl 30
    private val flare = PhoneChoice("flare", "Flare", size = 2 * gb, minRamGb = 4.0)
    private val equinox = PhoneChoice("equinox", "Equinox", size = 5 * gb, minRamGb = 8.0)

    @Test
    fun theSmallestModelThatFitsIsFetched() {
        assertEquals("flare", AutoOffline.pick(listOf(equinox, flare), null, 20 * gb) { true }?.id)
        assertEquals("flare", AutoOffline.pick(listOf(flare, equinox), null, 20 * gb) { it <= 6.0 }?.id)        // not enough memory for the big one
    }

    @Test
    fun theModelPickedInSettingsIsKeptWhenItFits() {
        assertEquals("equinox", AutoOffline.pick(listOf(flare, equinox), "equinox", 20 * gb) { true }?.id)
        assertEquals("flare", AutoOffline.pick(listOf(flare, equinox), "equinox", 6 * gb) { true }?.id)          // no room for it: the small one
    }

    @Test
    fun nothingIsFetchedWithoutRoomForItAndTwoGbToSpare() {
        assertNull(AutoOffline.pick(listOf(flare, equinox), null, 3 * gb) { true })                               // 2 GB model + 2 GB spare > 3 GB
        assertEquals("flare", AutoOffline.pick(listOf(flare), null, 4 * gb) { true }?.id)
    }

    @Test
    fun itAsksOnceNeedsAConnectionAndNeverGoesAgainstANo() {
        assertEquals(Step.Ask, AutoOffline.step(true, true, true, null, admin = false))
        assertEquals(Step.Go, AutoOffline.step(true, true, true, null, admin = true))            // the owner's own accounts are not asked
        assertEquals(Step.Go, AutoOffline.step(true, true, true, "yes", admin = false))
        assertEquals(Step.Nothing, AutoOffline.step(true, true, true, "no", admin = true))        // Stop, Remove and No thanks are final
        assertEquals(Step.Go, AutoOffline.step(true, true, true, "yes", admin = true))            // Wi-Fi or mobile data: both count as a connection
        assertEquals(Step.Nothing, AutoOffline.step(true, false, true, "yes", admin = true))      // no connection: nothing to download with
        assertEquals(Step.Nothing, AutoOffline.step(true, true, false, null, admin = true))       // already on the phone
        assertEquals(Step.Nothing, AutoOffline.step(false, true, true, "yes", admin = true))      // switch off
    }
}
