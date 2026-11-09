package app.emvryx.android.assist

import android.app.SearchManager
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.net.Uri
import android.provider.AlarmClock
import android.provider.MediaStore
import android.provider.Settings
import app.emvryx.android.local.Command

/**
 * android_assistant: a voice command carried out on the phone with the phone's own apps (the clock for timers and alarms, Maps, the browser,
 * YouTube, the dialler, the camera, Settings). Nothing is done without an app on the phone doing it the usual way: the dialler only shows the
 * number, it never calls by itself. Returns what was done, in plain words, or what went wrong.
 */
object PhoneActions {
    // run: carry out one spoken command by starting the matching Android screen (an "intent"): open an app, set a timer or alarm, torch, directions, web or YouTube search, dial, camera or settings. It returns a plain sentence saying what happened.
    fun run(ctx: Context, c: Command): String = try {
        // "when" checks which kind of command it is and does the matching thing; each branch builds an intent and starts it.
        when (c) {
            is Command.OpenApp -> openApp(ctx, c.name)
            is Command.Timer -> start(ctx, Intent(AlarmClock.ACTION_SET_TIMER).putExtra(AlarmClock.EXTRA_LENGTH, c.seconds)
                .putExtra(AlarmClock.EXTRA_SKIP_UI, true), "Timer set for ${duration(c.seconds)}.")
            is Command.Alarm -> start(ctx, Intent(AlarmClock.ACTION_SET_ALARM).putExtra(AlarmClock.EXTRA_HOUR, c.hour)
                .putExtra(AlarmClock.EXTRA_MINUTES, c.minute).putExtra(AlarmClock.EXTRA_SKIP_UI, true), "Alarm set for ${clock(c.hour, c.minute)}.")
            is Command.Torch -> torch(ctx, c.on)
            is Command.Navigate -> start(ctx, Intent(Intent.ACTION_VIEW, Uri.parse("geo:0,0?q=" + Uri.encode(c.place))), "Directions to ${c.place}.")
            is Command.Search -> start(ctx, Intent(Intent.ACTION_WEB_SEARCH).putExtra(SearchManager.QUERY, c.query), "Searching for ${c.query}.")
            is Command.YouTube -> try {
                start(ctx, Intent(Intent.ACTION_SEARCH).setPackage("com.google.android.youtube").putExtra(SearchManager.QUERY, c.query), "Playing ${c.query} on YouTube.")
            } catch (e: ActivityNotFoundException) {
                start(ctx, Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com/results?search_query=" + Uri.encode(c.query))), "Searching YouTube for ${c.query}.")
            }
            is Command.Dial -> start(ctx, Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + c.number)), "The number is in the dialler: tap Call.")
            is Command.Camera -> start(ctx, Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA), "Camera.")
            is Command.Settings -> start(ctx, Intent(when (c.which) {
                "wifi" -> Settings.Panel.ACTION_INTERNET_CONNECTIVITY
                "bluetooth" -> Settings.ACTION_BLUETOOTH_SETTINGS
                "display" -> Settings.ACTION_DISPLAY_SETTINGS
                "sound" -> Settings.Panel.ACTION_VOLUME
                "battery" -> Intent.ACTION_POWER_USAGE_SUMMARY
                else -> Settings.ACTION_SETTINGS
            }), "Opening ${c.which} settings (Android lets apps open them, not switch them by themselves).")
            else -> ""
        }
    // If no app can handle it, or the phone refuses, say so in plain words instead of crashing.
    } catch (e: ActivityNotFoundException) {
        "There is no app on this phone for that."
    } catch (e: SecurityException) {
        "The phone did not allow that."
    }

    // start: launch the screen in its own task and give back the sentence to show.
    private fun start(ctx: Context, i: Intent, done: String): String {
        ctx.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        return done
    }

    /** The app whose name best matches what was said: the same name first, then one that starts with it, then one that contains it */
    // openApp: find the installed app that best matches the name (same name first, then starts with, then contains) by looking at the apps that can be launched from the home screen.
    private fun openApp(ctx: Context, name: String): String {
        val pm = ctx.packageManager
        val apps = pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
            .map { it.loadLabel(pm).toString() to it.activityInfo.packageName }
        val want = name.lowercase().replace(" ", "")
        val pick = apps.firstOrNull { it.first.lowercase().replace(" ", "") == want }
            ?: apps.firstOrNull { it.first.lowercase().replace(" ", "").startsWith(want) }
            ?: apps.firstOrNull { it.first.lowercase().replace(" ", "").contains(want) }
            ?: return "No app called $name on this phone."
        val launch = pm.getLaunchIntentForPackage(pick.second) ?: return "${pick.first} cannot be opened from here."
        return start(ctx, launch, "Opening ${pick.first}.")
    }

    // torch: find a camera that has a flash and switch it on or off.
    private fun torch(ctx: Context, on: Boolean): String {
        val cm = ctx.getSystemService(CameraManager::class.java) ?: return "This phone has no flashlight."
        val id = cm.cameraIdList.firstOrNull { cm.getCameraCharacteristics(it).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true }
            ?: return "This phone has no flashlight."
        cm.setTorchMode(id, on)
        return if (on) "Flashlight on." else "Flashlight off."
    }

    /** Does it open another app's screen (then the bar steps aside), or is it done in place (the torch, a timer, an alarm)? */
    // opensScreen: true when the command opens another app's screen (so the assistant bar steps aside).
    fun opensScreen(c: Command): Boolean = c !is Command.Torch && c !is Command.Timer && c !is Command.Alarm && c !is Command.Ask && c !is Command.None

    // duration: seconds as words, like "1 hour 5 minutes".
    fun duration(s: Int): String = listOfNotNull(
        (s / 3600).takeIf { it > 0 }?.let { "$it " + if (it == 1) "hour" else "hours" },
        (s % 3600 / 60).takeIf { it > 0 }?.let { "$it " + if (it == 1) "minute" else "minutes" },
        (s % 60).takeIf { it > 0 }?.let { "$it " + if (it == 1) "second" else "seconds" },
    ).joinToString(" ")

    // clock: an hour and minute as 12-hour time, like "7:30 AM".
    fun clock(h: Int, m: Int): String = "%d:%02d %s".format(if (h % 12 == 0) 12 else h % 12, m, if (h < 12) "AM" else "PM")
}
