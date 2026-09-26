package com.saman.batterymusic

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.ClipOp
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.unit.dp
import kotlin.math.hypot
import kotlin.math.max

/** Dark is the app's identity; a white flare at 2am defeats the point. */
val DarkScheme = darkColorScheme(
    primary = Color(0xFFB9A6FF),
    onPrimary = Color(0xFF211047),
    primaryContainer = Color(0xFF372566),
    onPrimaryContainer = Color(0xFFE8DEFF),
    secondary = Color(0xFFCDC3E9),
    onSecondary = Color(0xFF332D4B),
    secondaryContainer = Color(0xFF4A4368),
    onSecondaryContainer = Color(0xFFE9DFF9),
    background = Color(0xFF131118),
    onBackground = Color(0xFFE6E1E9),
    surface = Color(0xFF131118),
    onSurface = Color(0xFFE6E1E9),
    surfaceVariant = Color(0xFF48454E),
    onSurfaceVariant = Color(0xFFCAC4CE),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
    errorContainer = Color(0xFF93000A),
    onErrorContainer = Color(0xFFFFDAD6),
    outline = Color(0xFF948F99),
)

/** Light sibling: same purple accent, plain paper background. */
val LightScheme = lightColorScheme(
    primary = Color(0xFF5B3FD6),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFE5DEFF),
    onPrimaryContainer = Color(0xFF1B1046),
    secondary = Color(0xFF5D5472),
    background = Color(0xFFFDFBFF),
    onBackground = Color(0xFF1C1B1F),
    surface = Color(0xFFFDFBFF),
    onSurface = Color(0xFF1C1B1F),
    surfaceVariant = Color(0xFFE7E0EB),
    onSurfaceVariant = Color(0xFF48454E),
    error = Color(0xFFB3261E),
    onError = Color(0xFFFFFFFF),
    errorContainer = Color(0xFFF9DEDC),
    onErrorContainer = Color(0xFF410E0B),
    outline = Color(0xFF79747E),
)

// --- Theme toggle icons (hand-drawn vectors; keeps material-icons-extended
//     out of the APK -- it would double the size for two glyphs). ---

private const val MOON_PATH =
    "M12,3c-4.97,0 -9,4.03 -9,9s4.03,9 9,9 9,-4.03 9,-9c0,-0.46 -0.04,-0.92 -0.1,-1.36 " +
        "-0.98,1.37 -2.58,2.26 -4.4,2.26 -2.98,0 -5.4,-2.42 -5.4,-5.4 0,-1.81 0.89,-3.42 2.26,-4.4 " +
        "-0.44,-0.06 -0.9,-0.1 -1.36,-0.1z"

// Sun: filled core + 8 detached rays. Kept to M/L/z/arc primitives only.
private const val SUN_PATH =
    "M12,6.5c-3.04,0 -5.5,2.46 -5.5,5.5s2.46,5.5 5.5,5.5 5.5,-2.46 5.5,-5.5 -2.46,-5.5 -5.5,-5.5z " +
        "M11,1h2v3h-2z M11,20h2v3h-2z M1,11h3v2h-3z M20,11h3v2h-3z " +
        "M4.22,5.64l1.42,-1.42 2.12,2.12 -1.42,1.42z M16.24,17.66l1.42,-1.42 2.12,2.12 -1.42,1.42z " +
        "M4.22,18.36l2.12,-2.12 1.42,1.42 -2.12,2.12z M16.24,6.34l-1.42,-1.42 2.12,-2.12 1.42,1.42z"

private fun vectorFromPath(name: String, pathData: String): ImageVector? = try {
    ImageVector.Builder(
        name = name,
        defaultWidth = 24.dp, defaultHeight = 24.dp,
        viewportWidth = 24f, viewportHeight = 24f,
    ).addPath(
        pathData = PathParser().parsePathString(pathData).toNodes(),
        fill = SolidColor(Color.Black),
    ).build()
} catch (_: Exception) {
    null // malformed path: ThemeToggleButton falls back to a glyph
}

private val MoonVector = vectorFromPath("BMoon", MOON_PATH)
private val SunVector = vectorFromPath("BSun", SUN_PATH)

/**
 * The theme toggle. Reports the button's center in WINDOW coordinates so
 * the wave reveal grows from the button the finger just pressed. (A tap
 * detector can't live here: IconButton's own clickable consumes the tap
 * before any sibling pointerInput in the chain.)
 */
@Composable
fun ThemeToggleButton(darkTheme: Boolean, onToggle: (Offset) -> Unit, modifier: Modifier = Modifier) {
    var center by remember { mutableStateOf(Offset.Zero) }
    IconButton(
        onClick = { onToggle(center) },
        modifier = modifier.onGloballyPositioned {
            center = it.positionInWindow() + Offset(it.size.width / 2f, it.size.height / 2f)
        },
    ) {
        val v = if (darkTheme) SunVector else MoonVector
        if (v != null) {
            Icon(v, contentDescription = if (darkTheme) "Switch to light theme" else "Switch to dark theme")
        } else {
            Text(if (darkTheme) "SUN" else "MOON", style = androidx.compose.material3.MaterialTheme.typography.labelSmall)
        }
    }
}

/** One in-flight wave: the outgoing frame + where the finger started it. */
data class WaveCapture(val bitmap: ImageBitmap?, val center: Offset)

/**
 * Full-screen overlay: the old frame on top, an expanding circle cut out of
 * it from the tap point, so the new theme floods through like a wave. The
 * circle's edge carries a fading ring for the wavefront feel.
 */
@Composable
fun ThemeWaveOverlay(capture: WaveCapture?, onDone: () -> Unit) {
    if (capture == null) return
    val progress = remember(capture) { Animatable(0f) }
    LaunchedEffect(capture) {
        progress.animateTo(1f, tween(750, easing = FastOutSlowInEasing))
        onDone()
    }
    val bmp = capture.bitmap
    if (bmp == null) {
        // Capture failed (rare): no old frame to reveal through, so just
        // drop the overlay and let the instant switch stand.
        LaunchedEffect(capture) { onDone() }
        return
    }
    val ringColor = androidx.compose.material3.MaterialTheme.colorScheme.primary
    Image(
        bitmap = bmp,
        contentDescription = null,
        modifier = Modifier
            .fillMaxSize()
            .drawWithContent {
                val c = capture.center
                val maxR = hypot(
                    max(c.x, size.width - c.x).toDouble(),
                    max(c.y, size.height - c.y).toDouble(),
                ).toFloat()
                val r = 0.02f * maxR + progress.value * 1.04f * maxR // slight overshoot
                val hole = Path().apply { addOval(Rect(center = c, radius = r)) }
                clipPath(hole, ClipOp.Difference) { this@drawWithContent.drawContent() }
                if (r > 0f && progress.value < 1f) {
                    drawCircle(
                        color = ringColor.copy(alpha = 0.55f * (1f - progress.value)),
                        radius = r,
                        center = c,
                        style = Stroke(width = 3.dp.toPx()),
                    )
                    drawCircle(
                        color = Color.White.copy(alpha = 0.25f * (1f - progress.value)),
                        radius = r * 1.02f,
                        center = c,
                        style = Stroke(width = 9.dp.toPx()),
                    )
                }
            },
    )
}
