plugins {
    id("com.android.application")
    kotlin("android")
}

android {
    namespace = "com.wolfpack.carseat"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.wolfpack.carseat"
        minSdk = 26
        targetSdk = 34
        versionCode = 3
        versionName = "0.1.2"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        }
    }
}

dependencies {
    implementation("androidx.car.app:app:1.4.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
}
