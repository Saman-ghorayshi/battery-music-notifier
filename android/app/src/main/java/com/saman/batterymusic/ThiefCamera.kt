package com.saman.batterymusic

import android.annotation.SuppressLint
import android.content.Context
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread

/**
 * One-shot front-camera photo, taken only while the alarm is ringing: the
 * whole point is a photograph of whoever is holding the device, uploaded to
 * the owner's own relay account next to the alert. No preview, no shutter
 * sound control, no gallery write -- capture, encode, hand back, close.
 *
 * Camera2 without a preview surface: legal for stills as long as the capture
 * session is built with the ImageReader surface alone.
 */
object ThiefCamera {

    /** @param onDone called on a background thread with JPEG bytes, or null. */
    @SuppressLint("MissingPermission")
    fun captureSelfie(context: Context, onDone: (ByteArray?) -> Unit) {
        val delivered = java.util.concurrent.atomic.AtomicBoolean(false)
        fun deliver(bytes: ByteArray?) {
            if (delivered.compareAndSet(false, true)) onDone(bytes)
        }
        try {
            val manager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
            val cameraId = manager.cameraIdList.firstOrNull { id ->
                manager.getCameraCharacteristics(id)
                    .get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_FRONT
            } ?: manager.cameraIdList.firstOrNull() ?: run { deliver(null); return }

            val characteristics = manager.getCameraCharacteristics(cameraId)
            val largest = characteristics
                .get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
                ?.getOutputSizes(android.graphics.ImageFormat.JPEG)
                ?.maxByOrNull { it.width.toLong() * it.height.toLong() }
                ?: run { deliver(null); return }

            val thread = HandlerThread("thief-camera").apply { start() }
            val handler = Handler(thread.looper)
            val reader = ImageReader.newInstance(largest.width, largest.height, android.graphics.ImageFormat.JPEG, 1)

            var camera: CameraDevice? = null
            val closeAll = {
                try { camera?.close() } catch (_: Exception) {}
                try { reader.close() } catch (_: Exception) {}
                thread.quitSafely()
            }

            reader.setOnImageAvailableListener({ r ->
                val image = try { r.acquireLatestImage() } catch (_: Exception) { null }
                val bytes = image?.let {
                    val buffer = it.planes[0].buffer
                    val arr = ByteArray(buffer.remaining())
                    buffer.get(arr)
                    arr
                }
                image?.close()
                closeAll()
                deliver(bytes)
            }, handler)

            val stateCallback = object : CameraDevice.StateCallback() {
                override fun onOpened(device: CameraDevice) {
                    camera = device
                    try {
                        device.createCaptureSession(
                            listOf(reader.surface),
                            object : android.hardware.camera2.CameraCaptureSession.StateCallback() {
                                override fun onConfigured(session: CameraCaptureSession) {
                                    try {
                                        val builder = device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE)
                                        builder.addTarget(reader.surface)
                                        builder.set(CaptureRequest.JPEG_ORIENTATION, 270)
                                        session.capture(builder.build(), null, handler)
                                    } catch (_: Exception) { closeAll(); deliver(null) }
                                }
                                override fun onConfigureFailed(session: CameraCaptureSession) {
                                    closeAll(); deliver(null)
                                }
                            },
                            handler,
                        )
                    } catch (_: Exception) { closeAll(); deliver(null) }
                }

                override fun onDisconnected(device: CameraDevice) { closeAll(); deliver(null) }
                override fun onError(device: CameraDevice, error: Int) { closeAll(); deliver(null) }
            }

            manager.openCamera(cameraId, stateCallback, handler)

            // Hard ceiling: if nothing came back in 8s, give up quietly.
            handler.postDelayed({
                closeAll()
                deliver(null)
            }, 8_000)
        } catch (_: Exception) {
            deliver(null)
        }
    }
}
