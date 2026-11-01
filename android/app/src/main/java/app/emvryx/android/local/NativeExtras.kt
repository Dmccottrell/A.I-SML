// Three small helpers for the phone-only extras (shortcuts, widget, assistant bar, notification replies):
//   NativeFlags - remembers which feature switches are on, on the phone itself
//   Launch      - works out WHY the app was opened from outside (selected text? a shortcut? the assistant button?)
//   LastChoice  - remembers the model and effort last used, so answers given outside the app use the same ones
package app.emvryx.android.local

import android.content.Context

/**
 * The switches of the phone's own extras, remembered on the phone: some are needed before the PC has answered (the app opened from selected text
 * or the assistant button) or with the app closed (a reply typed in a notification, the sync in the background).
 */
object NativeFlags {
    // The names of every switch this file cares about (they match the ids in app/flags.py on the server)
    val IDS = setOf("android_text_menu", "android_quick_launch", "android_reply_inline", "android_camera_scan", "android_background_sync", "android_offline_talk", "android_assistant", "android_auto_offline")

    /** The ones that are on, from the PC's list (state.features) */
    fun pick(features: Map<String, Boolean>): Set<String> = IDS.filter { features[it] == true }.toSet()

    // SharedPreferences = Android's small key-value storage file. "MODE_PRIVATE" means only this app can read it.
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("emvryx_native_flags", Context.MODE_PRIVATE)

    // Save the list of switches that are on (called each time the PC answers)
    fun remember(ctx: Context, on: Set<String>) = prefs(ctx).edit().putStringSet("on", on).apply()

    // Read the saved list; an empty set if nothing was ever saved
    fun on(ctx: Context): Set<String> = prefs(ctx).getStringSet("on", emptySet()).orEmpty()

    // Is this one switch on?
    fun on(ctx: Context, id: String) = id in on(ctx)
}

/** What the app was opened for from outside it: selected text (android_text_menu), the assistant button, the icon's shortcuts or the widget
 *  (android_quick_launch). [None]: it opens as always. */
sealed interface Launch {
    // Words the person selected in another app and sent to Emvryx with "Ask Emvryx"
    data class Text(val text: String) : Launch
    // Open Talk (voice conversation)
    data object Talk : Launch
    // Open a fresh chat
    data object NewChat : Launch
    // Open VryxCode
    data object Code : Launch
    // Open the chats that live on the phone
    data object Local : Launch
    // Nothing special: open the app the normal way
    data object None : Launch

    // "companion object" = things that belong to Launch itself (like static members in other languages)
    companion object {
        const val SHORTCUT = "emvryx.shortcut"           // the extra the shortcuts and the widget set: new, talk, code, local
        const val MAX_TEXT = 8000                        // selected text is cut to this many characters so a huge selection cannot overload a chat

        /**
         * Decide what the app was opened for.
         * [action] = the Android intent action; [shortcut] = the value a shortcut/widget attached; [selected] = the selected text, if any;
         * [on] = the feature switches that are on. A feature that is switched off is ignored, so the app just opens as usual.
         */
        fun from(action: String?, shortcut: String?, selected: CharSequence?, on: Set<String>): Launch = when {
            // "Ask Emvryx" was tapped in another app's text-selection menu: use the text, cleaned and cut to MAX_TEXT (nothing left = open normally)
            action == "android.intent.action.PROCESS_TEXT" ->
                if ("android_text_menu" in on) selected?.toString()?.trim()?.take(MAX_TEXT)?.takeIf { it.isNotEmpty() }?.let { Text(it) } ?: None else None
            // The phone's assistant button (power / home long-press) opened the app: start Talk
            action == "android.intent.action.ASSIST" || action == "android.intent.action.VOICE_COMMAND" ->
                if ("android_quick_launch" in on) Talk else None
            // A long-press icon shortcut or a widget button: the attached word says which screen to open
            shortcut != null && "android_quick_launch" in on -> when (shortcut) {
                "new" -> NewChat
                "talk" -> Talk
                "code" -> Code
                "local" -> Local
                else -> None                             // an unknown word: open normally
            }
            // Opened the ordinary way (tapping the icon)
            else -> None
        }
    }
}

/** The model and effort last used in a chat, for the answers given outside the app (the assistant bar, a reply in a notification) */
object LastChoice {
    // A separate small storage file, so this never mixes with the feature switches
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("emvryx_last_choice", Context.MODE_PRIVATE)

    // Save the choice; an empty model name (nothing chosen yet) is ignored so it cannot wipe a good saved one
    fun remember(ctx: Context, model: String, effort: String) {
        if (model.isNotBlank()) prefs(ctx).edit().putString("model", model).putString("effort", effort).apply()
    }

    // The saved model id, or "" if none was saved (the caller then asks the PC for its default)
    fun model(ctx: Context): String = prefs(ctx).getString("model", "").orEmpty()

    // The saved effort level; "balanced" if none was saved or the saved one is empty
    fun effort(ctx: Context): String = prefs(ctx).getString("effort", "balanced").orEmpty().ifEmpty { "balanced" }
}
