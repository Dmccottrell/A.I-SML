// The Application object: Android makes exactly one of these when the app process starts, before any screen or service. It holds the few things
// the whole app shares (the saved login, the server client, the on-phone models) so every screen and service gets the same copy.
package app.emvryx.android

import android.app.Application
import app.emvryx.android.data.ApiClient
import app.emvryx.android.data.SessionStore

/** The app's single shared "home": created first by Android (named in AndroidManifest.xml) and used by screens, services and widgets alike */
class EmvryxApp : Application() {
    // lateinit: set in onCreate instead of here. "private set": other code can read these but only this class can assign them.
    // session = the saved (encrypted) login; api = the client that talks to the Emvryx server
    lateinit var session: SessionStore
        private set
    lateinit var api: ApiClient
        private set
    // "by lazy": built only the first time someone uses it, then reused. This keeps app start quick and avoids loading models that are never used.
    /** android_offline_model: the model that runs on the phone itself */
    val phone by lazy { app.emvryx.android.local.PhoneModel(this, api) }
    /** android_phone_vision: the picture model that runs on the phone itself */
    val vision by lazy { app.emvryx.android.local.PhoneVision(this, api, phone) }
    /** android_native: Admin as it was last read, and switch changes made with the PC off */
    val admin by lazy { app.emvryx.android.local.AdminCache(this) }

    /** Runs once at app start: open the saved login, then make the server client that uses it (order matters: api needs session) */
    override fun onCreate() {
        super.onCreate()
        session = SessionStore(this)
        api = ApiClient(session)
    }
}
