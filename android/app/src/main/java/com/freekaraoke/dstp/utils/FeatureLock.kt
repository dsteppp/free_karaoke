package com.freekaraoke.dstp.utils

import android.content.Context
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.freekaraoke.dstp.R

/**
 * Блокировка ML-функций на Android.
 * Показывает уведомление при попытке доступа к недоступным функциям.
 */
object FeatureLock {

    enum class Feature {
        SEPARATION,         // Сепарация вокала
        TRANSCRIPTION,      // Whisper-транскрипция
        GENIUS_LOOKUP,      // Genius-поиск текста
        PARTIAL_RESCAN      // Рескан от точки
    }

    /**
     * Проверка: функция доступна?
     * На Android всегда false (ML-функции недоступны)
     */
    fun isFeatureAvailable(feature: Feature): Boolean = false

    /**
     * Сообщение о недоступности функции
     */
    fun getFeatureName(feature: Feature): String = when (feature) {
        Feature.SEPARATION -> "Сепарация вокала"
        Feature.TRANSCRIPTION -> "Whisper-транскрипция"
        Feature.GENIUS_LOOKUP -> "Genius-поиск текста"
        Feature.PARTIAL_RESCAN -> "Рескан от точки"
    }

    /**
     * Показать диалог о недоступности функции.
     * Compose-компонент — вызывать внутри @Composable
     */
    @Composable
    fun FeatureNotAvailableDialog(
        feature: Feature,
        onDismiss: () -> Unit
    ) {
        FeatureNotAvailableDialog(
            featureName = getFeatureName(feature),
            onDismiss = onDismiss
        )
    }

    @Composable
    fun FeatureNotAvailableDialog(
        featureName: String,
        onDismiss: () -> Unit
    ) {
        AlertDialog(
            onDismissRequest = onDismiss,
            title = { Text(text = stringResource(R.string.feature_locked)) },
            text = {
                Text(
                    text = "«$featureName» недоступно.\n" +
                            stringResource(R.string.feature_lock_message)
                )
            },
            confirmButton = {
                TextButton(onClick = onDismiss) {
                    Text(stringResource(R.string.ok))
                }
            },
            dismissButton = null
        )
    }
}

/**
 * State holder для показа диалога блокировки функции
 */
class FeatureLockState {
    var lockedFeature by mutableStateOf<String?>(null)
        private set

    val showDialog: Boolean get() = lockedFeature != null

    fun showLockDialog(featureName: String) {
        lockedFeature = featureName
    }

    fun dismissDialog() {
        lockedFeature = null
    }
}
