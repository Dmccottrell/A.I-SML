plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.kotlin.serialization) apply false
}

// OneDrive syncs the build folder while Gradle writes it and locks files ("Unable to delete directory"),
// so when the repo sits in OneDrive the build goes to the PC's local app data instead
if (rootDir.absolutePath.contains("OneDrive")) {
    System.getenv("LOCALAPPDATA")?.let { local ->
        allprojects { layout.buildDirectory.set(file("$local/emvryx-android-build${path.replace(':', '/')}")) }
    }
}
