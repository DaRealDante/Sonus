plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.chaquo.python")
}

val pythonCommand = providers.environmentVariable("SONUS_BUILD_PYTHON").orElse("python3").get()
val generatedPython = layout.buildDirectory.dir("generated/python")
val prepareCore by tasks.registering(Exec::class) {
    inputs.dir(rootProject.file("../app"))
    inputs.file(rootProject.file("tools/prepare_core.py"))
    outputs.dir(generatedPython)
    commandLine(pythonCommand, rootProject.file("tools/prepare_core.py"),
        "--source", rootProject.projectDir.parentFile, "--output", generatedPython.get().asFile)
}

android {
    namespace = "it.sonus.mobile"
    compileSdk = 35
    defaultConfig {
        applicationId = "it.sonus.mobile"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0-android.1"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    buildFeatures { compose = true; buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    packaging {
        jniLibs.useLegacyPackaging = true // FFmpeg/QuickJS are executable native files.
        resources.excludes += setOf("META-INF/AL2.0", "META-INF/LGPL2.1")
    }
    buildTypes {
        release {
            isMinifyEnabled = false // Python calls Java classes by their names.
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    lint { abortOnError = true }
}
kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }

chaquopy {
    defaultConfig {
        // SciPy's official Android wheels currently stop at CPython 3.10.
        version = "3.10"
        providers.environmentVariable("SONUS_BUILD_PYTHON").orNull?.let { buildPython(it) }
        pip {
            install("numpy==1.23.3")
            install("scipy==1.8.1")
            install("Pillow==11.0.0")
            install("yt-dlp==2026.10.21")
            install("yt-dlp-ejs==0.8.0")
            install("mutagen==1.48.1")
            install("spotifyscraper==3.9.2")
            install("paho-mqtt==2.1.0")
            install("certifi==2026.10.23")
        }
    }
    sourceSets.getByName("main") { srcDir(generatedPython) }
}
tasks.configureEach {
    if (name.startsWith("generate") && name.endsWith("PythonProxies")) dependsOn(prepareCore)
    if (name.startsWith("merge") && name.endsWith("PythonSources")) dependsOn(prepareCore)
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.10.01"))
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.4")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.media:media:1.7.0")
    implementation("androidx.media3:media3-exoplayer:1.6.1")
    implementation("androidx.media3:media3-ui:1.6.1")
    implementation("io.coil-kt:coil-compose:2.7.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("io.github.junkfood02.youtubedl-android:library:0.18.1")
    implementation("io.github.junkfood02.youtubedl-android:ffmpeg:0.18.1")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    androidTestImplementation(platform("androidx.compose:compose-bom:2025.10.01"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20250517")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
}
