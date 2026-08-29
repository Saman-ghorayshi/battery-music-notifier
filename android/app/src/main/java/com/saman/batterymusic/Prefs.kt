package com.saman.batterymusic

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Token + settings storage. EncryptedSharedPreferences because the linked
 * token is a bearer credential: anyone holding it controls the account.
 */
class Prefs(context: Context) {

    private val sp = EncryptedSharedPreferences.create(
        context,
        "battery_music_prefs",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    var workerUrl: String
        get() = sp.getString(KEY_WORKER, "https://battery-relay.sthidontknow.workers.dev") ?: ""
        set(value) = sp.edit().putString(KEY_WORKER, value.trim()).apply()

    var token: String
        get() = sp.getString(KEY_TOKEN, "") ?: ""
        set(value) = sp.edit().putString(KEY_TOKEN, value).apply()

    var armed: Boolean
        get() = sp.getBoolean(KEY_ARMED, false)
        set(value) = sp.edit().putBoolean(KEY_ARMED, value).apply()

    fun hasToken(): Boolean = token.isNotEmpty()

    fun newClient(): ApiClient = ApiClient(workerUrl, token)

    companion object {
        private const val KEY_WORKER = "worker_url"
        private const val KEY_TOKEN = "linked_token"
        private const val KEY_ARMED = "armed"

        @Volatile private var instance: Prefs? = null

        fun get(context: Context): Prefs =
            instance ?: synchronized(this) {
                instance ?: Prefs(context.applicationContext).also { instance = it }
            }
    }
}
