// Gradle "settings" file: it runs first and says where to find plugins and libraries and which modules exist.

pluginManagement {
    // Where Gradle may download build plugins from: Google's repository (Android), Maven Central, then the Gradle plugin portal.
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    // Libraries must come from the list below only; a module that adds its own repository makes the build fail (keeps downloads predictable).
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

// The project's name, and the one module it contains: ":app" (the folder app/ holds the real app).
rootProject.name = "Emvryx"
include(":app")
