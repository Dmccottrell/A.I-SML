// Device test for one small piece of the screen: a row in the side panel (menu). It draws the row with Jetpack Compose (Android's UI toolkit,
// where the screen is built from Kotlin functions) and measures it, to make sure long text cannot squash the row's name.
package app.emvryx.android

import androidx.compose.foundation.layout.width
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.height
import androidx.compose.ui.unit.width
import androidx.compose.foundation.layout.Box
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.emvryx.android.ui.SideLink
import app.emvryx.android.ui.theme.EmvryxTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** The side panel's rows: the name always stays on one line; a long grey note gives way ("Scheduled tasks" was drawn one letter per line) */
@RunWith(AndroidJUnit4::class)
class SideLinkTest {
    // A rule that starts a Compose screen for the test, so we can draw things and look at them
    @get:Rule
    val compose = createComposeRule()

    /**
     * Proves: in a row with a short name and a long grey note, the NAME keeps its room and stays on one line (the note is the one that shrinks).
     * Setup: draw a SideLink inside a 300 dp wide box. (dp = density-independent pixel, Android's screen size unit, so it looks the same on any phone.)
     */
    @Test
    fun theNameStaysOnOneLineNextToALongNote() {
        compose.setContent {
            EmvryxTheme {
                Box(Modifier.width(300.dp)) {                                       // the side panel on a phone
                    SideLink("clock", "Scheduled tasks", "Answered by itself at a set time") {}
                }
            }
        }
        // useUnmergedTree: the row is one tappable item, so without it this measured the whole row instead of the name in it
        // Measure the name text. The assert: it is under 30 dp tall (one line, not many stacked lines) and over 100 dp wide (not squeezed thin).
        val name = compose.onNodeWithText("Scheduled tasks", useUnmergedTree = true).getUnclippedBoundsInRoot()
        assertTrue("the name was squeezed to ${name.width} wide, ${name.height} tall", name.height < 30.dp && name.width > 100.dp)       // one line of 16 sp is about 22 dp tall
    }
}
