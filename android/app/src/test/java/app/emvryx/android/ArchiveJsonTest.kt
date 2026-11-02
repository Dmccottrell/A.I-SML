package app.emvryx.android

import app.emvryx.android.data.CodeSessions
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Test

/** vryxcode_archive: the sessions list as the server sends it (app/routes_code.py), with and without the "archived" mark */
class ArchiveJsonTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun anArchivedRowIsMarkedAndAnOrdinaryOneIsNot() {
        val s = json.decodeFromString<CodeSessions>("""{"sessions": [
            {"id": "s1-1", "title": "old idea", "project": "tips", "state": "done", "archived": true},
            {"id": "s1-2", "title": "new idea", "project": "tips", "state": "done"}]}""")
        assertEquals(listOf(true, false), s.sessions.map { it.archived })
    }
}
