# ProGuard / R8 rules: the release build shrinks and renames code to make the app small. These lines tell it what it must NOT rename or delete,
# because something finds that code by its exact name at run time (reflection or native code), and renaming would break it.

# kotlinx.serialization: keep the generated serializers for the API types
# (a serializer turns a Kotlin object into JSON text and back; the library looks the generated ones up by name)
-keepattributes *Annotation*, InnerClasses
-keepclassmembers @kotlinx.serialization.Serializable class app.emvryx.android.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class app.emvryx.android.**$$serializer { *; }

# Tink (used by androidx.security-crypto for the encrypted session) refers to Error Prone's compile-time annotations, which are not shipped
# (-dontwarn: do not stop the build with a warning about classes that are missing on purpose)
-dontwarn com.google.errorprone.annotations.**

# android_offline_model: llama.cpp calls back into these by name (src/main/cpp/emvryx_llama.cpp)
# (native code looks up the Java/Kotlin names by text, so they must keep their real names)
-keep class app.emvryx.android.local.Llama { native <methods>; }
-keep interface app.emvryx.android.local.Llama$Sink { *; }
-keepclassmembers class * implements app.emvryx.android.local.Llama$Sink { boolean piece(byte[]); }
