package com.freekaraoke.dstp.utils

import android.content.Context
import android.net.Uri
import com.freekaraoke.dstp.model.ImportResult
import com.freekaraoke.dstp.model.LibraryMetadata
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream

/**
 * ZIP импорт/экспорт библиотеки
 * Совместимо с Desktop-форматом v1.0
 */
object ZipHelper {

    /** Группировка файлов по base_name */
    data class TrackFileGroup(
        val baseName: String,
        var vocalsUri: Uri? = null,
        var instrumentalUri: Uri? = null,
        var lyricsJsonBytes: ByteArray? = null,
        var lyricsText: String? = null,
        var metadata: LibraryMetadata? = null
    )

    /**
     * Импорт ZIP-файла в локальное хранилище приложения.
     *
     * @return ImportResult с количеством добавленных/пропущенных треков и ошибками
     */
    fun importZip(
        context: Context,
        zipUri: Uri,
        tracksDir: File,
        onTrackImported: (TrackFileGroup, File) -> Unit
    ): ImportResult {
        var added = 0
        var skipped = 0
        val errors = mutableListOf<String>()

        try {
            val inputStream = context.contentResolver.openInputStream(zipUri)
                ?: return ImportResult(0, 0, listOf("Не удалось открыть ZIP"))

            ZipInputStream(inputStream).use { zis ->
                // Сначала собираем все файлы в группы
                val fileGroups = mutableMapOf<String, TrackFileGroup>()
                val entryMap = mutableMapOf<String, ZipEntry>()

                var entry = zis.nextEntry
                while (entry != null) {
                    if (!entry.isDirectory) {
                        entryMap[entry.name] = entry
                        val baseName = parseBaseName(entry.name)
                        if (baseName != null) {
                            val group = fileGroups.getOrPut(baseName) { TrackFileGroup(baseName) }
                            when {
                                entry.name.endsWith("_(Vocals).mp3") -> {
                                    group.vocalsUri = saveStreamToAppFile(context, zis.readBytes(), tracksDir, entry.name)
                                }
                                entry.name.endsWith("_(Instrumental).mp3") -> {
                                    group.instrumentalUri = saveStreamToAppFile(context, zis.readBytes(), tracksDir, entry.name)
                                }
                                entry.name.endsWith("_(Karaoke Lyrics).json") -> {
                                    group.lyricsJsonBytes = zis.readBytes()
                                }
                                entry.name.endsWith("_(Genius Lyrics).txt") -> {
                                    group.lyricsText = zis.readBytes().toString(Charsets.UTF_8)
                                }
                                entry.name.endsWith("_library.json") -> {
                                    val jsonStr = zis.readBytes().toString(Charsets.UTF_8)
                                    group.metadata = JsonParser.parseLibraryMetadata(jsonStr)
                                }
                            }
                        }
                    }
                    entry = zis.nextEntry
                }

                // Обрабатываем группы
                for ((baseName, group) in fileGroups) {
                    try {
                        // Оба аудиофайла обязательны
                        if (group.vocalsUri == null || group.instrumentalUri == null) {
                            skipped++
                            continue
                        }

                        // Сохраняем JSON таймингов
                        var lyricsJsonPath: String? = null
                        if (group.lyricsJsonBytes != null) {
                            val jsonFile = File(tracksDir, "$baseName_(Karaoke Lyrics).json")
                            jsonFile.writeBytes(group.lyricsJsonBytes)
                            lyricsJsonPath = jsonFile.absolutePath
                        }

                        // Создаём Track
                        val trackId = baseName
                        val meta = group.metadata

                        onTrackImported(
                            group,
                            File(tracksDir, "$baseName_(Vocals).mp3")
                        )

                        added++
                    } catch (e: Exception) {
                        errors.add("$baseName: ${e.message}")
                        skipped++
                    }
                }
            }
        } catch (e: Exception) {
            errors.add("Ошибка чтения ZIP: ${e.message}")
        }

        return ImportResult(added, skipped, errors)
    }

    /**
     * Экспорт библиотеки в ZIP-файл
     */
    fun exportLibrary(
        context: Context,
        outputUri: Uri,
        tracks: List<ExportTrack>
    ): Result<Unit> {
        return runCatching {
            context.contentResolver.openOutputStream(outputUri)?.use { outputStream ->
                ZipOutputStream(outputStream).use { zos ->
                    for (track in tracks) {
                        // Instrumental
                        track.instrumentalFile?.let { file ->
                            addFileToZip(zos, file, "${track.baseName}_(Instrumental).mp3")
                        }
                        // Vocals
                        track.vocalsFile?.let { file ->
                            addFileToZip(zos, file, "${track.baseName}_(Vocals).mp3")
                        }
                        // Karaoke Lyrics JSON
                        track.lyricsJsonFile?.let { file ->
                            addFileToZip(zos, file, "${track.baseName}_(Karaoke Lyrics).json")
                        }
                        // Library metadata
                        track.metadata?.let { meta ->
                            val jsonBytes = JsonParser.serializeLibraryMetadata(meta).toByteArray(Charsets.UTF_8)
                            addBytesToZip(zos, jsonBytes, "${track.baseName}_library.json")
                        }
                    }
                }
            } ?: throw IllegalStateException("Не удалось открыть выходной поток")
        }
    }

    // ── Внутренние утилиты ─────────────────────────────────────────────────

    private fun parseBaseName(fileName: String): String? {
        return when {
            fileName.endsWith("_(Vocals).mp3") ->
                fileName.removeSuffix("_(Vocals).mp3")
            fileName.endsWith("_(Instrumental).mp3") ->
                fileName.removeSuffix("_(Instrumental).mp3")
            fileName.endsWith("_(Karaoke Lyrics).json") ->
                fileName.removeSuffix("_(Karaoke Lyrics).json")
            fileName.endsWith("_(Genius Lyrics).txt") ->
                fileName.removeSuffix("_(Genius Lyrics).txt")
            fileName.endsWith("_library.json") ->
                fileName.removeSuffix("_library.json")
            else -> null
        }
    }

    private fun saveStreamToAppFile(context: Context, bytes: ByteArray, dir: File, fileName: String): Uri? {
        return try {
            dir.mkdirs()
            val file = File(dir, fileName)
            file.writeBytes(bytes)
            Uri.fromFile(file)
        } catch (e: Exception) {
            null
        }
    }

    private fun addFileToZip(zos: ZipOutputStream, file: File, entryName: String) {
        zos.putNextEntry(ZipEntry(entryName))
        file.inputStream().use { it.copyTo(zos) }
        zos.closeEntry()
    }

    private fun addBytesToZip(zos: ZipOutputStream, bytes: ByteArray, entryName: String) {
        zos.putNextEntry(ZipEntry(entryName))
        zos.write(bytes)
        zos.closeEntry()
    }

    /** Данные трека для экспорта */
    data class ExportTrack(
        val baseName: String,
        val instrumentalFile: File?,
        val vocalsFile: File?,
        val lyricsJsonFile: File?,
        val metadata: LibraryMetadata?
    )
}
