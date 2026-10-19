# kotlinx.serialization: keep the generated serializers for the API types
-keepattributes *Annotation*, InnerClasses
-keepclassmembers @kotlinx.serialization.Serializable class app.emvryx.android.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class app.emvryx.android.**$$serializer { *; }
