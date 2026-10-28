package app.emvryx.android

import android.app.Application
import app.emvryx.android.data.ApiClient
import app.emvryx.android.data.SessionStore

class EmvryxApp : Application() {
    lateinit var session: SessionStore
        private set
    lateinit var api: ApiClient
        private set
    /** android_offline_model: the model that runs on the phone itself */
    val phone by lazy { app.emvryx.android.local.PhoneModel(this, api) }
    /** android_phone_vision: the picture model that runs on the phone itself */
    val vision by lazy { app.emvryx.android.local.PhoneVision(this, api, phone) }
    /** android_native: Admin as it was last read, and switch changes made with the PC off */
    val admin by lazy { app.emvryx.android.local.AdminCache(this) }

    override fun onCreate() {
        super.onCreate()
        session = SessionStore(this)
        api = ApiClient(session)
    }
}
