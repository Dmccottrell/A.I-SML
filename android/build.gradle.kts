// Top-level Gradle build file for the Android project ("Gradle" is the tool that compiles the app).
// The real app code and its dependencies are configured in app/build.gradle.kts; this file only
// declares which plugins the sub-project may use and has one build-folder tweak (see below).
plugins {
    // "apply false" means: make these plugins available here, but do not run them on the root project;
    // the :app module turns them on itself. The names come from the version catalog (gradle/libs.versions.toml).
    // Builds the Android app itself.
    alias(libs.plugins.android.application) apply false
    // Lets us write the app in Kotlin.
    alias(libs.plugins.kotlin.android) apply false
    // Compiler support for Jetpack Compose (the Kotlin way of drawing screens).
    alias(libs.plugins.kotlin.compose) apply false
    // Turns Kotlin classes into JSON and back (used for server replies).
    alias(libs.plugins.kotlin.serialization) apply false
}

// OneDrive syncs the build folder while Gradle writes it and locks files ("Unable to delete directory"),
// so when the repo sits in OneDrive the build goes to the PC's local app data instead
// Step 1: is the project folder path inside a OneDrive folder?
if (rootDir.absolutePath.contains("OneDrive")) {
    // Step 2: LOCALAPPDATA is a Windows environment variable (the PC's local, non-synced app folder); "?.let" runs only if it is set.
    System.getenv("LOCALAPPDATA")?.let { local ->
        // Step 3: point every module's build output at that folder; the module path (":app" becomes "/app") keeps modules apart.
        allprojects { layout.buildDirectory.set(file("$local/emvryx-android-build${path.replace(':', '/')}")) }
    }
}
