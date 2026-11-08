# Keep kotlinx.serialization
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt

-keepclassmembers class kotlinx.serialization.json.** {
    *** Companion;
}
-keepclasseswithmembers class kotlinx.serialization.json.** {
    kotlinx.serialization.KSerializer serializer(...);
}

-keep,includedescriptorclasses class com.bot4vps.mobile.**$$serializer { *; }
-keepclassmembers class com.bot4vps.mobile.** {
    *** Companion;
}
-keepclasseswithmembers class com.bot4vps.mobile.** {
    kotlinx.serialization.KSerializer serializer(...);
}
