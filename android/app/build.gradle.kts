plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "app.emvryx.android"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.emvryx.android"
        minSdk = 29          // Android 10 (docs/NATIVE.md)
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        buildConfigField("String", "DEFAULT_SERVER", "\"https://chat.emvryx.app\"")
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        // android_offline_model: llama.cpp (src/main/cpp) for 64-bit ARM phones (nearly every phone since 2017), and x86_64 for the emulator
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
        externalNativeBuild {
            cmake { arguments += listOf("-DCMAKE_BUILD_TYPE=Release", "-DANDROID_STL=c++_shared") }
        }
    }
    externalNativeBuild {
        cmake { path("src/main/cpp/CMakeLists.txt") }
    }
    // llama.cpp picks the CPU code for the phone's chip from separate files at start (GGML_BACKEND_DL): they must be real files on the phone
    packaging { jniLibs { useLegacyPackaging = true } }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"   // installs next to a release build
            // The emulator reaches the PC's own `python app_server.py` here
            buildConfigField("String", "DEFAULT_SERVER", "\"http://10.0.2.2:8000\"")
        }
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
        // A test build to put on a real phone: optimized like a release (a debug build is noticeably slower, opening the menu stuttered),
        // but signed and named like the debug build, so it installs over it and keeps the person signed in.
        // gradlew assemblePhone -> app/build/outputs/apk/phone/app-phone.apk
        create("phone") {
            initWith(getByName("release"))
            applicationIdSuffix = ".debug"
            signingConfig = signingConfigs.getByName("debug")
            matchingFallbacks += listOf("release")
            buildConfigField("String", "DEFAULT_SERVER", "\"http://10.0.2.2:8000\"")    // on a real phone it starts at chat.emvryx.app instead
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons)
    implementation(libs.androidx.security.crypto)
    implementation(libs.androidx.biometric)
    implementation(libs.mlkit.text.recognition)
    implementation(libs.okhttp)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)
    debugImplementation(libs.androidx.compose.ui.tooling)

    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.rules)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)     // screen tests that measure what is drawn (SideLinkTest)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
}
