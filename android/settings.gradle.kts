pluginManagement {
    repositories {
        // Build-from-Iran: uncomment these two mirror blocks and comment the
        // google()/mavenCentral() lines below -- they work WITHOUT any proxy.
        // maven { url = uri("https://maven.aliyun.com/repository/google") }
        // maven { url = uri("https://maven.aliyun.com/repository/public") }
        // maven { url = uri("https://maven.tencent.com/repository/google") }
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        // maven { url = uri("https://maven.aliyun.com/repository/google") }
        // maven { url = uri("https://maven.aliyun.com/repository/public") }
        google()
        mavenCentral()
    }
}

rootProject.name = "BatteryMusicNotifier"
include(":app")
