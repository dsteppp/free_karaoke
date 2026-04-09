package com.freekaraoke.dstp.model

import kotlinx.serialization.Serializable

/**
 * Одно слово с таймингом из _(Karaoke Lyrics).json
 * Совместимо с Desktop-форматом v1.0
 */
@Serializable
data class LyricsWord(
    val word: String,
    val start: Float,    // секунды от начала аудио
    val end: Float,      // секунды от начала аудио
    val lineBreak: Boolean = false,
    val letters: List<LetterAnim> = emptyList()
) {
    val duration: Float get() = end - start

    @Serializable
    data class LetterAnim(
        val letter: String = "",
        val time: Float = 0f
    )
}
