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
    @get:Rule
    val compose = createComposeRule()

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
        val name = compose.onNodeWithText("Scheduled tasks", useUnmergedTree = true).getUnclippedBoundsInRoot()
        assertTrue("the name was squeezed to ${name.width} wide, ${name.height} tall", name.height < 30.dp && name.width > 100.dp)       // one line of 16 sp is about 22 dp tall
    }
}
