package com.saman.batterymusic

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Signature
import java.security.spec.ECGenParameterSpec

/**
 * The device disarm key: an EC P-256 pair inside AndroidKeyStore whose
 * private half is gated by the phone's fingerprint (auth-per-use). Only the
 * public half ever leaves the device. Disarm = sign a fresh server
 * challenge; the relay verifies it with WebCrypto. This is the WebAuthn
 * idea adapted to a sideloaded app (no FIDO2/rpId dependency), and it
 * coexists with the shared pass -- the worker accepts either.
 */
object KeystoreManager {

    private const val ALIAS = "disarm_key"
    private const val CURVE = "secp256r1"

    fun hasKey(): Boolean = try {
        keyStore().containsAlias(ALIAS)
    } catch (_: Exception) {
        false
    }

    fun ensureKey() {
        if (hasKey()) return
        val gen = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore")
        gen.initialize(
            KeyGenParameterSpec.Builder(
                ALIAS,
                KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY,
            )
                .setAlgorithmParameterSpec(ECGenParameterSpec(CURVE))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(true)
                .build(),
        )
        gen.generateKeyPair()
    }

    /** SPKI/X.509 public key, base64 -- the only part that goes to the relay. */
    fun publicKeyB64(): String {
        val ks = keyStore()
        val pub = ks.getCertificate(ALIAS).publicKey
        return Base64.encodeToString(pub.encoded, Base64.NO_WRAP)
    }

    /**
     * A signature object prepared for the current key. Pass it to
     * BiometricPrompt as a CryptoObject; after success call sign() on it.
     * Throws if the key was never created.
     */
    fun signingSignature(): Signature {
        val ks = keyStore()
        val entry = ks.getEntry(ALIAS, null) as KeyStore.PrivateKeyEntry
        return Signature.getInstance("SHA256withECDSA").apply { initSign(entry.privateKey) }
    }

    fun sign(signature: Signature): ByteArray = signature.sign()

    /**
     * AndroidKeyStore emits DER-encoded ECDSA signatures; WebCrypto expects
     * the raw r||s form (32 bytes each for P-256). Convert.
     */
    fun derToRaw(der: ByteArray): ByteArray {
        var i = 2 // skip SEQUENCE header
        fun readInt(): ByteArray {
            i += 1 // skip INTEGER tag
            val len = der[i].toInt() and 0xff
            i += 1
            var v = der.copyOfRange(i, i + len)
            i += len
            // strip a possible leading zero (positive-marker)
            if (v.isNotEmpty() && v[0].toInt() == 0) v = v.copyOfRange(1, v.size)
            val out = ByteArray(32)
            v.copyInto(out, 32 - v.size)
            return out
        }
        val r = readInt()
        val s = readInt()
        return r + s
    }

    private fun keyStore(): KeyStore =
        KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
}
