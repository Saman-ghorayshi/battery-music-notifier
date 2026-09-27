package com.saman.batterymusic

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Card
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.MultiFormatReader
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.common.HybridBinarizer
import java.util.concurrent.Executors

/**
 * Camera scanner for the laptop's pairing QR (BMN1|relay|code). Runs the
 * zxing decoder over CameraX frames; the first successful decode wins.
 * Camera permission is requested here, in context, right where it's used.
 */
@Composable
fun QrScanScreen(onDecoded: (String) -> Unit, onCancel: () -> Unit) {
    val context = LocalContext.current
    var granted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted = it }

    androidx.compose.material3.Surface(Modifier.fillMaxSize()) {
        if (!granted) {
            Column(
                Modifier.fillMaxSize().padding(24.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    "The camera reads the QR code your laptop shows. " +
                        "It is used for nothing else.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                androidx.compose.foundation.layout.Spacer(Modifier.padding(8.dp))
                Button(onClick = { launcher.launch(Manifest.permission.CAMERA) }) {
                    Text("Allow camera")
                }
                androidx.compose.foundation.layout.Spacer(Modifier.padding(4.dp))
                androidx.compose.material3.TextButton(onClick = onCancel) { Text("Cancel") }
            }
        } else {
            Column(Modifier.fillMaxSize()) {
                Box(Modifier.weight(1f).fillMaxWidth()) {
                    CameraPreviewWithScanner(onDecoded = onDecoded)
                }
                Card(Modifier.fillMaxWidth().padding(16.dp)) {
                    Column(Modifier.padding(12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            "Point the camera at the QR on your laptop screen",
                            style = MaterialTheme.typography.bodySmall,
                        )
                        androidx.compose.material3.TextButton(onClick = onCancel) { Text("Cancel") }
                    }
                }
            }
        }
    }
}

@Composable
private fun CameraPreviewWithScanner(onDecoded: (String) -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val executor = remember { Executors.newSingleThreadExecutor() }
    val reader = remember { MultiFormatReader() }
    var fired by remember { mutableStateOf(false) }

    DisposableEffect(Unit) {
        onDispose { executor.shutdown() }
    }

    AndroidView(
        modifier = Modifier.fillMaxSize(),
        factory = { ctx ->
            val previewView = PreviewView(ctx)
            val providerFuture = ProcessCameraProvider.getInstance(ctx)
            providerFuture.addListener({
                val provider = providerFuture.get()
                val preview = Preview.Builder().build().also {
                    it.setSurfaceProvider(previewView.surfaceProvider)
                }
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                analysis.setAnalyzer(executor) { proxy ->
                    if (!fired) {
                        val text = decodeQr(proxy, reader)
                        if (text != null && !fired) {
                            fired = true
                            androidx.core.content.ContextCompat.getMainExecutor(ctx)
                                .execute { onDecoded(text) }
                        }
                    }
                    proxy.close()
                }
                provider.unbindAll()
                try {
                    provider.bindToLifecycle(
                        lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis,
                    )
                } catch (_: Exception) {
                    // camera busy: leave the preview dark, Cancel still works
                }
            }, ContextCompat.getMainExecutor(ctx))
            previewView
        },
    )
}

/** Decode a QR from a CameraX frame, or null. Pure function of the frame. */
fun decodeQr(proxy: ImageProxy, reader: MultiFormatReader): String? {
    return try {
        val plane = proxy.planes[0]
        val buffer = plane.buffer
        val data = ByteArray(buffer.remaining()).also { buffer.get(it) }
        val source = PlanarYUVLuminanceSource(
            data, plane.rowStride, proxy.height,
            0, 0, proxy.width, proxy.height, false,
        )
        val result = reader.decode(
            BinaryBitmap(HybridBinarizer(source)),
            mapOf(DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE)),
        )
        // Reset for the next frame if the caller reuses the reader.
        try { reader.reset() } catch (_: Exception) {}
        result.text
    } catch (_: Exception) {
        null
    } finally {
        proxy.close()
    }
}
