// Unit tests for LocalSync / LocalChat (local/PhoneModel.kt): the phone keeps copies of the PC's chats and can add its own offline chats.
// When the PC is back, only the turns it has not seen are sent. These tests check that merging, id and "which chats to keep" logic.
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
    // Two turns used in most tests: a question from the person (mine = true) and the answer (mine = false)
    private val q = LocalTurn(true, "why do tides happen")
    private val a = LocalTurn(false, "The Moon pulls the sea.")

    /** Proves a fresh copy of a PC chat remembers the PC's id, counts both turns as synced, and has nothing waiting to be sent. */
    @Test
    fun aCopyOfThePcChatHasNothingToSend() {
        // existing = null: the phone has no copy yet. 7 is the chat's id on the PC; "now" is the time as a number.
        val c = LocalSync.merge(null, 7, "Tides", listOf(q, a), now = 1000)
        assertEquals(7L, c.serverId)
        assertEquals(2, c.synced)
        assertTrue(c.pending.isEmpty())
    }

    /** Proves turns written offline are not lost when the PC's copy is fetched again, and are still waiting to be sent. */
    @Test
    fun whatWasWrittenOfflineIsKeptAndSentNextTime() {
        val copy = LocalSync.merge(null, 7, "Tides", listOf(q, a), now = 1000)
        // The person keeps chatting on the phone with the PC off: two more turns are added after the synced ones.
        val offline = copy.copy(turns = copy.turns + LocalTurn(true, "and the sun?") + LocalTurn(false, "A little too."))
        // only the two new turns count as pending
        assertEquals(listOf("and the sun?", "A little too."), offline.pending.map { it.text })
        // the PC's copy is read again before the sync went through: the offline turns stay at the end, still to send
        val again = LocalSync.merge(offline, 7, "Tides", listOf(q, a), now = 2000)
        assertEquals(offline.id, again.id)                  // same phone chat, not a new one
        assertEquals(4, again.turns.size)
        assertEquals(2, again.pending.size)
    }

    /** Proves the id of a sync attempt is stable for the same state (so a retry is not added twice) and changes once more turns are synced. */
    @Test
    fun aRetriedSyncHasTheSameIdAndANewOneDoesNot() {
        val c = LocalChat(5, "x", listOf(q, a), null, 0)
        // renaming the chat does not change what is sent, so the id stays the same
        assertEquals(LocalSync.syncId(c), LocalSync.syncId(c.copy(title = "renamed")))
        // but once 2 turns count as synced, a different id is made
        assertNotEquals(LocalSync.syncId(c), LocalSync.syncId(c.copy(synced = 2)))
    }

    /** Proves an answer that is still being written (shown as "…") is not sent to the PC. */
    @Test
    fun anUnfinishedAnswerIsNotSent() {
        // nothing is synced; the question is pending but the "…" placeholder answer is skipped, so only 1 turn is pending
        assertEquals(1, LocalChat(5, "x", listOf(q, LocalTurn(false, "…")), null, 0).pending.size)
    }

    /** Proves that when old chats are trimmed to a maximum, a chat that still has unsent turns survives even if it is the oldest. */
    @Test
    fun chatsWithSomethingToSendAreNeverDropped() {
        // The setup: one old chat that was written offline and never synced, plus nine newer chats that are fully synced (synced = 2).
        val old = LocalChat(1, "old offline", listOf(q), null, 0, updated = 1)
        val newer = (2..10).map { LocalChat(it.toLong(), "c$it", listOf(q, a), it.toLong(), 2, updated = it.toLong() * 100) }
        // keep at most 3: the unsynced one takes a place, and the two newest synced chats fill the other two
        val kept = LocalSync.keep(listOf(old) + newer, max = 3)
        assertTrue(kept.any { it.id == 1L })                        // the oldest, but not synced yet
        assertEquals(3, kept.size)
        assertTrue(kept.any { it.id == 10L } && kept.any { it.id == 9L })
    }
}
