# kotlinx.serialization: keep the generated serializers for the API types
-keepattributes *Annotation*, InnerClasses
-keepclassmembers @kotlinx.serialization.Serializable class app.emvryx.android.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class app.emvryx.android.**$$serializer { *; }

# Tink (used by androidx.security-crypto for the encrypted session) refers to Error Prone's compile-time annotations, which are not shipped
-dontwarn com.google.errorprone.annotations.**
