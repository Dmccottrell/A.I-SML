package app.emvryx.android.ui

import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

// The website's own line icons (web/js/core.js ICONS): 24 x 24, drawn with a 1.8 stroke and round ends, in the text colour.
private val PATHS = mapOf(
    "signout" to "M10 4H5v16h5M15 8l4 4-4 4M19 12H9",
    "folder" to "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
    "code" to "M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 6l-3 12",
    "lock" to "M7 11V8a5 5 0 0 1 10 0v3M6 11h12v9H6z",
    "chart" to "M5 20V10M12 20V4M19 20v-7",
    "brain" to "M12 4a3 3 0 0 0-3 3 3 3 0 0 0-3 3 3 3 0 0 0 1 5 3 3 0 0 0 5 2zM12 4a3 3 0 0 1 3 3 3 3 0 0 1 3 3 3 3 0 0 1-1 5 3 3 0 0 1-5 2z",
    "doc" to "M7 3h7l4 4v14H7zM14 3v4h4M9.5 12h5M9.5 16h5",
    "pencil" to "M4 20l1-4L16 5l3 3L8 19zM14 7l3 3",
    "spark" to "M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z",
    "gear" to "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1",
    "eye" to "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    "shield" to "M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z",
    "chevron" to "M6 15l6-6 6 6",
)

private val cache = HashMap<String, ImageVector>()

private fun vector(name: String): ImageVector = cache.getOrPut(name) {
    ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f).apply {
        addPath(
            PathParser().parsePathString(PATHS[name] ?: PATHS.getValue("doc")).toNodes(),
            fill = null, stroke = SolidColor(Color.White), strokeLineWidth = 1.8f,
            strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round,
        )
    }.build()
}

/** One of the website's icons; [tint] colours it (the stroke above is replaced by the tint) */
@Composable
fun PwaIcon(name: String, tint: Color, size: Dp = 20.dp, contentDescription: String? = null) {
    val v = remember(name) { vector(name) }
    Icon(v, contentDescription, tint = tint, modifier = Modifier.size(size))
}
