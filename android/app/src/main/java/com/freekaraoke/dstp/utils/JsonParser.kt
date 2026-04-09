package com.freekaraoke.dstp.utils

import com.freekaraoke.dstp.model.LibraryMetadata
import com.freekaraoke.dstp.model.LyricsWord
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/**
 * Парсинг и сериализация JSON-форматов Free Karaoke
 * Совместимо с Desktop-форматом v1.0
 */
object JsonParser {
    private val json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
        isLenient = true
        encodeDefaults = true
    }

    /**
     * Парсинг _(Karaoke Lyrics).json
     * Desktop-формат: массив объектов с полями word, start, end, line_break, letters
     */
    fun parseKaraokeLyrics(jsonString: String): List<LyricsWord> {
        return try {
            val rawWords = json.decodeFromString<List<RawLyricsWord>>(jsonString)
            rawWords.map { raw ->
                LyricsWord(
                    word = raw.word,
                    start = raw.start,
                    end = raw.end,
                    lineBreak = raw.lineBreak ?: (raw.line_break ?: false),
                    letters = raw.letters?.map { l ->
                        LyricsWord.LetterAnim(
                            letter = l.letter ?: "",
                            time = l.time ?: 0f
                        )
                    } ?: emptyList()
                )
            }
        } catch (e: Exception) {
            emptyList()
        }
    }

    /**
     * Сериализация таймингов обратно в JSON (для сохранения из редактора)
     */
    fun serializeKaraokeLyrics(words: List<LyricsWord>): String {
        val rawWords = words.map { w ->
            RawLyricsWord(
                word = w.word,
                start = w.start,
                end = w.end,
                line_break = w.lineBreak,
                letters = w.letters.map { l ->
                    RawLetterAnim(l.letter, l.time)
                }
            )
        }
        return json.encodeToString(rawWords)
    }

    /**
     * Парсинг *_library.json
     */
    fun parseLibraryMetadata(jsonString: String): LibraryMetadata {
        return try {
            json.decodeFromString(jsonString)
        } catch (e: Exception) {
            LibraryMetadata()
        }
    }

    /**
     * Сериализация метаданных библиотеки
     */
    fun serializeLibraryMetadata(metadata: LibraryMetadata): String {
        return json.encodeToString(metadata)
    }

    // ── Raw DTOs для десериализации (совместимость с Desktop snake_case) ──

    @kotlinx.serialization.Serializable
    private data class RawLyricsWord(
        val word: String,
        val start: Float,
        val end: Float,
        val line_break: Boolean? = null,     // Desktop-формат
        val lineBreak: Boolean? = null,       // Альтернативное имя
        val letters: List<RawLetterAnim>? = null
    )

    @kotlinx.serialization.Serializable
    private data class RawLetterAnim(
        val letter: String? = null,
        val time: Float? = null
    )
}
