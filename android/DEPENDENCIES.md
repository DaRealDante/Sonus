# Android build and native dependencies

The Android application is a separate Gradle project. No desktop files are changed.

Build with JDK 17 or 21, Android SDK platform 35/build tools 35.0.0, and a **full CPython 3.10 installation** containing `venv` and `ensurepip`. Set `SONUS_BUILD_PYTHON` to its executable if automatic detection cannot find it. The Windows embeddable Python distribution is insufficient. From this directory run `gradlew.bat :app:assembleDebug :app:testDebugUnitTest :app:lintDebug` (or `./gradlew` on Unix).

Pinned build plugins: Gradle 8.13, AGP 8.13.2, Kotlin/Compose compiler 2.2.20, Chaquopy 17.1.0. Compose libraries use BOM 2025.10.01. Android API 26 minimum; target/compile 35; ARM64 and x86_64.

`prepareCore` runs `tools/prepare_core.py --source <repository> --output app/build/generated/python` before Chaquopy merges Python sources. It generates Android adaptations of desktop modules without editing their originals.

## Python version and device limits

CPython 3.10 is deliberate: the [official SciPy wheel index](https://chaquo.com/pypi-13.1/scipy/) provides SciPy 1.8.1 for CPython 3.10, but no CPython 3.11/3.12 wheels. Keeping the original tested DSP requires this native dependency. NumPy 1.23.3 and SciPy 1.8.1 were successfully resolved for **both** target architectures, together with Pillow 11.0.0 and the remaining declared packages.

ELF inspection of the installed wheel files found **4 KB LOAD segment alignment** in NumPy, SciPy and several support libraries: 127 ARM64 and 129 x86_64 objects. This build requires a device with 4 KB memory pages. It must not be advertised as supporting all newer 16 KB devices or as ready for a store requiring 16 KB native compatibility. [Chaquopy also documents this constraint for older wheels](https://chaquo.com/chaquopy/doc/current/changelog.html). Rebuilding the affected wheels is separate work.

## Executable packaging

`io.github.junkfood02.youtubedl-android:{library,ffmpeg}:0.18.1` supplies native executables. Real AAR inspection confirmed `libffmpeg.so`, `libffprobe.so`, `libqjs.so` and `libpython.so` in both architectures; each executable has 16 KB LOAD alignment. FFmpeg support libraries are stored inside `libffmpeg.zip.so` and extracted by the library initializer to `noBackupFilesDir/youtubedl-android/packages/ffmpeg/usr/lib`.

The host initializes YoutubeDL and FFmpeg **before** starting the Sonus Python entry point. The latter receives the packages directory and native library directory. Chaquopy's Python library uses a versioned name, separate from youtubedl-android's executable `libpython.so`; both artifacts are packaged, rather than resolving a duplicate by discarding one. [Library installation and initialization documentation](https://github.com/JunkFood02/youtubedl-android).

Legacy JNI packaging is enabled so Android extracts the executable files into the installed native directory. HTTPS remains the network default. The only HTTP exceptions are `localhost` and `127.0.0.1`, used by the original local video proxy.

## Audio lifecycle

`PlaybackService` owns a media session, foreground media notification, audio focus, headset/noisy handling, and playback-only CPU/Wi-Fi locks. Python retains queue and playback state. Float PCM from its original DSP goes to `AudioTrack` through `PcmSink`; native ducking changes output gain without changing the saved user volume. Transient focus loss pauses/resumes; permanent loss or an explicit pause cancels automatic resume. Closing the activity does not stop the service.

JVM tests cover incremental state events, explicit collection clearing, deleted equalizer presets, and focus transitions. Instrumentation tests exercise actual float PCM writes and sink closure. Those tests do not establish real speaker quality, Bluetooth routing, battery behavior, or long-duration lock-screen playback; those require a device.
