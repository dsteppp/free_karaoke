package com.freekaraoke.dstp.model

import kotlinx.serialization.Serializable

/**
 * Метаданные библиотеки из *_library.json
 * Совместимо с Desktop-форматом v1.0
 */
@Serializable
data class LibraryMetadata(
    val title: String? = null,
    val artist: String? = null,
    val lyrics: String? = null,
    val album: String? = null,
    val year: String? = null,
    val genre: String? = null,
    val cover_url: String? = null,
    val bg_url: String? = null,
    val duration: Float? = null,
    val language: String? = null
)

/**
 * Результат импорта ZIP
 */
data class ImportResult(
    val added: Int,
    val skipped: Int,
    val errors: List<String>
) {
    val totalProcessed: Int get() = added + skipped
    val hasErrors: Boolean get() = errors.isNotEmpty()
}
