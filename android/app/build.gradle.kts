plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }

android {
    namespace = "com.gideon.bridge"
    compileSdk = 35
    defaultConfig { applicationId = "com.gideon.bridge"; minSdk = 28; targetSdk = 35; versionCode = 1; versionName = "1.0" }
    buildFeatures { viewBinding = false }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("org.nanohttpd:nanohttpd:2.3.1")
}
