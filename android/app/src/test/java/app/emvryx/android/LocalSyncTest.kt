package app.emvryx.android

import app.emvryx.android.local.LocalChat
import app.emvryx.android.local.LocalSync
import app.emvryx.android.local.LocalTurn
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** android_offline_model: the phone's copies of the PC's chats, and what is sent back when the PC returns */
class LocalSyncTest {
    private val q = LocalTurn(true, "why do tides happen")
    private val a = LocalTurn(false, "The Moon pulls the sea.")

    @Test
    fun aCopyOfThePcChatHasNothingToSend() {
        val c = LocalSync.merge(null, 7, "Tides", listOf(q, a), now = 1000)
        assertEquals(7L, c.serverId)
        assertEquals(2, c.synced)
        assertTrue(c.pending.isEmpty())
    }

    @Test
    fun whatWasWrittenOfflineIsKeptAndSentNextTime() {
        val copy = LocalSync.merge(null, 7, "Tides", listOf(q, a), now = 1000)
        val offline = copy.copy(turns = copy.turns + LocalTurn(true, "and the sun?") + LocalTurn(false, "A little too."))
        assertEquals(listOf("and the sun?", "A little too."), offline.pending.map { it.text })
        // the PC's copy is read again before the sync went through: the offline turns stay at the end, still to send
        val again = LocalSync.merge(offline, 7, "Tides", listOf(q, a), now = 2000)
        assertEquals(offline.id, again.id)
        assertEquals(4, again.turns.size)
        assertEquals(2, again.pending.size)
    }

    @Test
    fun aRetriedSyncHasTheSameIdAndANewOneDoesNot() {
        val c = LocalChat(5, "x", listOf(q, a), null, 0)
        assertEquals(LocalSync.syncId(c), LocalSync.syncId(c.copy(title = "renamed")))
        assertNotEquals(LocalSync.syncId(c), LocalSync.syncId(c.copy(synced = 2)))
    }

    @Test
    fun anUnfinishedAnswerIsNotSent() {
        assertEquals(1, LocalChat(5, "x", listOf(q, LocalTurn(false, "…")), null, 0).pending.size)
    }

    @Test
    fun chatsWithSomethingToSendAreNeverDropped() {
        val old = LocalChat(1, "old offline", listOf(q), null, 0, updated = 1)
        val newer = (2..10).map { LocalChat(it.toLong(), "c$it", listOf(q, a), it.toLong(), 2, updated = it.toLong() * 100) }
        val kept = LocalSync.keep(listOf(old) + newer, max = 3)
        assertTrue(kept.any { it.id == 1L })                        // the oldest, but not synced yet
        assertEquals(3, kept.size)
        assertTrue(kept.any { it.id == 10L } && kept.any { it.id == 9L })
    }
}
