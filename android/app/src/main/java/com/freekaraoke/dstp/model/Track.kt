package com.freekaraoke.dstp.model

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Room Entity для трека.
 * Хранит метаданные и пути к файлам в локальном хранилище.
 */
@Entity(tableName = "tracks")
data class Track(
    @PrimaryKey
    val id: String,

    val fileName: String,            // base_name.mp3
    val title: String?,
    val artist: String?,
    val durationSec: Int?,

    // Пути к файлам внутри app-specific хранилища
    val instrumentalPath: String?,   // локальный URI или путь к _(Instrumental).mp3
    val vocalsPath: String?,         // локальный URI или путь к _(Vocals).mp3
    val lyricsJsonPath: String?,     // локальный URI к _(Karaoke Lyrics).json
    val lyricsText: String?,         // сырой текст (Genius)

    val coverUrl: String?,           // URL или base64 обложки
    val bgUrl: String?,              // URL или base64 фона

    val offset: Float = 0f,          // смещение синхронизации (сек)
    val status: String = "done",     // done, error, pending

    val createdAt: Long = System.currentTimeMillis(),
    val updatedAt: Long = System.currentTimeMillis()
) {
    /** Отображаемое имя */
    val displayName: String
        get() = when {
            artist != null && title != null -> "$artist — $title"
            title != null -> title
            fileName.isNotBlank() -> fileName.removeSuffix(".mp3")
                .replace("_", " ")
                .replace("(Vocals)", "")
                .replace("(Instrumental)", "")
                .trim()
            else -> "Unknown Track"
        }

    /** Оба аудиофайла на месте? */
    val isComplete: Boolean
        get() = !instrumentalPath.isNullOrBlank() && !vocalsPath.isNullOrBlank()

    /** Есть ли синхронизированный текст? */
    val hasLyrics: Boolean
        get() = !lyricsJsonPath.isNullOrBlank()
}
