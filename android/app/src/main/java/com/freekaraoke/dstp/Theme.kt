package com.freekaraoke.dstp

import android.app.Application
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// ── Тёмная тема (в стиле Desktop-версии) ────────────────────────────────────
private val DarkColorScheme = darkColorScheme(
    primary = Color(0xFF81D4FA),
    secondary = Color(0xFFB0BEC5),
    tertiary = Color(0xFFCE93D8),
    background = Color(0xFF1A1A2E),
    surface = Color(0xFF16213E),
    surfaceVariant = Color(0xFF1E2A4A),
    onPrimary = Color(0xFF003355),
    onSecondary = Color(0xFF1A1A2E),
    onBackground = Color(0xFFE0E0E0),
    onSurface = Color(0xFFE0E0E0),
    onSurfaceVariant = Color(0xFF90A4AE),
    primaryContainer = Color(0xFF1E3A5F),
    error = Color(0xFFEF5350)
)

@Composable
fun FreeKaraokeTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        content = content
    )
}
