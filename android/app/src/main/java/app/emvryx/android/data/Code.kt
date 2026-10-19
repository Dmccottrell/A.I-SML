package app.emvryx.android.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive

// VryxCode as the server sends it (app/routes_code.py, coding/code_sessions.py). Only what the app shows; the rest is ignored.

@Serializable
data class CodeModel(
    val id: String,
    val name: String = "",
    val label: String = "",
    val state: String = "",
    val badge: String = "",
    val outside: Boolean = false,
    val note: String = "",
) {
    val ready get() = state == "ready"
}

@Serializable
data class CodeEnv(val id: String, val name: String = "", val available: Boolean = false, val note: String = "")

/** The effort picker that replaces the model picker (feature flag vryxcode_effort): VryxCode picks the model itself. */
@Serializable
data class CodeEffort(val auto: String? = null, val levels: List<CodeEffortLevel> = emptyList())

@Serializable
data class CodeEffortLevel(val id: String, val name: String = "", val note: String = "")

@Serializable
data class CodeInfo(
    val allowed: Boolean = true,
    @SerialName("why_not") val whyNot: String = "",
    val models: List<CodeModel> = emptyList(),
    val projects: List<String> = emptyList(),
    val environments: List<CodeEnv> = emptyList(),
    val effort: CodeEffort? = null,
    val running: String? = null,
    val project: String? = null,
    @SerialName("ci_watch") val ciWatch: List<String> = emptyList(),
)

@Serializable
data class CodeSessionRow(
    val id: String,
    val title: String = "",
    val project: String = "",
    val model: String = "",
    val state: String = "",
    val age: String = "",
    val snippet: String = "",
    val steps: Int = 0,
    val files: Int = 0,
    val env: String = "local",
    val position: Int = 0,
) {
    val live get() = state in setOf("starting", "working", "asking", "queued")
}

@Serializable
data class CodeSessions(val sessions: List<CodeSessionRow> = emptyList())

/** One poll of a session (GET /api/code/sessions/{id}?after=N): what happened since N, its state, and an open question. */
@Serializable
data class CodeView(
    val events: List<JsonObject> = emptyList(),
    val state: String = "",
    val pending: JsonObject? = null,
    val full: Boolean = false,
    val saved: Boolean = false,
    val project: String = "",
    val model: String = "",
    val env: String = "local",
    val live: JsonObject? = null,
) {
    val working get() = state in setOf("starting", "working", "asking", "queued")
}

@Serializable
data class CodeStarted(val id: String = "", val queued: Boolean = false, val position: Int = 0, val note: String? = null, val ok: Boolean = false,
                       val message: String? = null)

@Serializable
data class CodeRules(val allow: List<String> = emptyList(), val deny: List<String> = emptyList())

@Serializable
data class CodeMemory(val notes: List<String> = emptyList())

@Serializable
data class CodeCommand(val name: String, val about: String = "")

@Serializable
data class CodeCommands(val commands: List<CodeCommand> = emptyList())

/** Reading fields of a session event without a class per kind (the feed has ~20 kinds; see web/js/ide.js renderEvent). */
fun JsonObject.str(key: String): String = (this[key] as? JsonPrimitive)?.let { if (it.isString) it.content else it.toString() } ?: ""

fun JsonObject.bool(key: String): Boolean = (this[key] as? JsonPrimitive)?.booleanOrNull ?: false

fun JsonObject.int(key: String): Int = (this[key] as? JsonPrimitive)?.content?.toDoubleOrNull()?.toInt() ?: 0

fun JsonObject.strings(key: String): List<String> =
    runCatching { this[key]!!.jsonArray.map { it.jsonPrimitive.content } }.getOrDefault(emptyList())
