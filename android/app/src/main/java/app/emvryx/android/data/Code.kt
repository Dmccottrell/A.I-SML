package app.emvryx.android.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive

// Code.kt: the JSON shapes for VryxCode, the coding agent (screens: ui/CodeScreen.kt, calls: ApiClient.kt "VryxCode" section).
// Like Api.kt, each @Serializable data class is a box the kotlinx.serialization library fills from the server's JSON,
// and every field has a default so a missing field never crashes the app.
// At the bottom are small helpers for reading the "events" of a session, which are loose JSON rather than fixed classes.
//
// VryxCode as the server sends it (app/routes_code.py, coding/code_sessions.py). Only what the app shows; the rest is ignored.

/** One model VryxCode can use (shown in the model picker): [outside] marks a model that runs elsewhere than the PC, [note] is a hint to show. */
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
    // True once the model is loaded and usable.
    val ready get() = state == "ready"
}

/** A place VryxCode can run code: its id, its name, whether it is [available] right now, and a note (e.g. why not). Real commands run only in Docker or the cloud machine. */
@Serializable
data class CodeEnv(val id: String, val name: String = "", val available: Boolean = false, val note: String = "")

/** The effort picker that replaces the model picker (feature flag vryxcode_effort): VryxCode picks the model itself. [auto] is the default level's id; [levels] are the choices. */
@Serializable
data class CodeEffort(val auto: String? = null, val levels: List<CodeEffortLevel> = emptyList())

/** One effort choice: its id, name and a short note. */
@Serializable
data class CodeEffortLevel(val id: String, val name: String = "", val note: String = "")

/**
 * What the VryxCode screen needs to start (GET /api/code): whether the person may use it ([allowed], else [whyNot] says why),
 * the models, project names, run places, effort levels, the session running now, and usage.
 */
@Serializable
data class CodeInfo(
    val allowed: Boolean = true,
    @SerialName("why_not") val whyNot: String = "",
    val models: List<CodeModel> = emptyList(),
    val projects: List<String> = emptyList(),
    val environments: List<CodeEnv> = emptyList(),
    val effort: CodeEffort? = null,
    // The id of a session that is working right now, or null.
    val running: String? = null,
    val project: String? = null,
    // Repos whose failing automated checks (CI) VryxCode is watching.
    @SerialName("ci_watch") val ciWatch: List<String> = emptyList(),
    val usage: CodeUsage? = null,
)

/** VryxCode's usage in coding steps (app/routes_code.py _code_usage; web/js/ide.js showUsage): one step is one model call at Balanced. [tankPct] is the percent still left, [stepsLeft] the steps. */
@Serializable
data class CodeUsage(
    val exempt: Boolean = false,
    val plan: String = "",
    @SerialName("tank_pct") val tankPct: Int = 100,
    @SerialName("steps_left") val stepsLeft: Int = 0,
) {
    /** "Pro · 87% left · about 1,234 coding steps", or "Owner: no limits" ("%,d" adds the thousands comma) */
    val label get() = if (exempt) "Owner: no limits"
        else plan.replaceFirstChar { it.uppercase() } + " · " + tankPct + "% left · about " + "%,d".format(stepsLeft) + " coding steps"
}

/** One row in the list of VryxCode sessions: title, project, state, a snippet, and counts of steps and files. */
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
    // Where it runs; "local" is the default.
    val env: String = "local",
    val position: Int = 0,
    val added: Int = 0,                 // lines this session added and took away (flag vryxcode_review: +52 -3)
    val removed: Int = 0,
    val updated: Double = 0.0,          // when it last changed: Ready for review until it is opened after that
    val archived: Boolean = false,      // vryxcode_archive: in the Archived list
) {
    // True while the session is still busy (not finished or stopped).
    val live get() = state in setOf("starting", "working", "asking", "queued")
}

/** The reply of the session-list call. */
@Serializable
data class CodeSessions(val sessions: List<CodeSessionRow> = emptyList())

/** One poll of a session (GET /api/code/sessions/{id}?after=N): what happened since N, its state, and an open question. */
@Serializable
data class CodeView(
    // New events since the last poll, as loose JSON (read them with the str/bool/int helpers below).
    val events: List<JsonObject> = emptyList(),
    val state: String = "",
    // The question the agent is waiting for the person to answer, if any.
    val pending: JsonObject? = null,
    val full: Boolean = false,
    val saved: Boolean = false,
    val project: String = "",
    val model: String = "",
    val env: String = "local",
    val live: JsonObject? = null,
    val usage: CodeUsage? = null,
) {
    // True while the agent is busy.
    val working get() = state in setOf("starting", "working", "asking", "queued")
}

/** The reply after starting or messaging a session: its [id], whether it waits in a queue (and its [position]), and a note or message to show. */
@Serializable
data class CodeStarted(val id: String = "", val queued: Boolean = false, val position: Int = 0, val note: String? = null, val ok: Boolean = false,
                       val message: String? = null)

/** A project's rules for the agent: patterns it may do without asking ([allow]) and ones it must never do ([deny]). */
@Serializable
data class CodeRules(val allow: List<String> = emptyList(), val deny: List<String> = emptyList())

/** The agent's saved notes. */
@Serializable
data class CodeMemory(val notes: List<String> = emptyList())

/** One saved command: its name and what it does. */
@Serializable
data class CodeCommand(val name: String, val about: String = "")

/** The reply of the commands call. */
@Serializable
data class CodeCommands(val commands: List<CodeCommand> = emptyList())

/**
 * Reading fields of a session event without a class per kind (the feed has ~20 kinds; see web/js/ide.js renderEvent).
 * Each helper below looks a key up in the JSON object and returns a safe default (empty text, false, 0) when the key is missing or the wrong type.
 * `str` returns text: a JSON string as is, any other value (number, true...) written as text.
 */
fun JsonObject.str(key: String): String = (this[key] as? JsonPrimitive)?.let { if (it.isString) it.content else it.toString() } ?: ""

/** The key as true/false; false when missing or not a boolean. */
fun JsonObject.bool(key: String): Boolean = (this[key] as? JsonPrimitive)?.booleanOrNull ?: false

/** The key as a whole number (a decimal is cut off); 0 when missing or not a number. */
fun JsonObject.int(key: String): Int = (this[key] as? JsonPrimitive)?.content?.toDoubleOrNull()?.toInt() ?: 0

/** The key as a list of texts; an empty list if it is missing or not a list (the failure is caught by runCatching). */
fun JsonObject.strings(key: String): List<String> =
    runCatching { this[key]!!.jsonArray.map { it.jsonPrimitive.content } }.getOrDefault(emptyList())

/** The key as a decimal number; 0.0 when missing or not a number. */
fun JsonObject.num(key: String): Double = (this[key] as? JsonPrimitive)?.content?.toDoubleOrNull() ?: 0.0
