package com.freekaraoke.dstp.player

import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer

/**
 * Караоке-плеер с двумя синхронизированными ExoPlayer (Instrumental + Vocals).
 * Обеспечивает точную синхронизацию двух аудио-потоков.
 */
class KaraokePlayer(context: Context) {

    private val instrumentalPlayer = ExoPlayer.Builder(context).build().apply {
        playWhenReady = false
    }
    private val vocalsPlayer = ExoPlayer.Builder(context).build().apply {
        playWhenReady = false
    }

    private val handler = Handler(Looper.getMainLooper())
    private var positionUpdateCallback: ((Long) -> Unit)? = null
    private var isReleased = false

    // Громкости
    private var instrumentalVolume = 1f
    private var vocalsVolume = 1f

    init {
        // Синхронизация: vocalsPlayer следует за instrumentalPlayer
        instrumentalPlayer.addListener(object : Player.Listener {
            override fun onPlaybackStateChanged(playbackState: Int) {
                when (playbackState) {
                    Player.STATE_READY -> {
                        vocalsPlayer.prepare()
                    }
                    Player.STATE_ENDED -> {
                        // Оба завершились
                    }
                    Player.STATE_IDLE -> {}
                    Player.STATE_BUFFERING -> {}
                }
            }

            override fun onIsPlayingChanged(isPlaying: Boolean) {
                if (isPlaying) {
                    vocalsPlayer.play()
                    startPositionUpdates()
                } else {
                    vocalsPlayer.pause()
                    stopPositionUpdates()
                }
            }
        })
    }

    /**
     * Загрузка аудиофайлов
     */
    fun load(instrumentalPath: String, vocalsPath: String) {
        val instrumentalUri = android.net.Uri.parse(instrumentalPath)
        val vocalsUri = android.net.Uri.parse(vocalsPath)

        instrumentalPlayer.setMediaItem(MediaItem.fromUri(instrumentalUri))
        instrumentalPlayer.prepare()

        vocalsPlayer.setMediaItem(MediaItem.fromUri(vocalsUri))
        // vocalsPlayer.prepare() вызывается когда instrumentalPlayer готов
    }

    /** Воспроизведение */
    fun play() {
        instrumentalPlayer.play()
    }

    /** Пауза */
    fun pause() {
        instrumentalPlayer.pause()
    }

    /** Переключение play/pause */
    fun playPause() {
        if (instrumentalPlayer.isPlaying) pause() else play()
    }

    /** Перемотка */
    fun seekTo(positionMs: Long) {
        instrumentalPlayer.seekTo(positionMs)
        vocalsPlayer.seekTo(positionMs)
    }

    /** Текущая позиция */
    fun getCurrentPosition(): Long = instrumentalPlayer.currentPosition

    /** Длительность */
    fun getDuration(): Long = instrumentalPlayer.duration.coerceAtLeast(0)

    /** Состояние воспроизведения */
    fun isPlaying(): Boolean = instrumentalPlayer.isPlaying

    /** Громкость Instrumental */
    fun setInstrumentalVolume(volume: Float) {
        instrumentalVolume = volume.coerceIn(0f, 1f)
        instrumentalPlayer.volume = instrumentalVolume
    }

    fun getInstrumentalVolume(): Float = instrumentalVolume

    /** Громкость Vocals */
    fun setVocalsVolume(volume: Float) {
        vocalsVolume = volume.coerceIn(0f, 1f)
        vocalsPlayer.volume = vocalsVolume
    }

    fun getVocalsVolume(): Float = vocalsVolume

    /** Callback обновления позиции */
    fun onPositionUpdate(callback: (Long) -> Unit) {
        positionUpdateCallback = callback
    }

    private val positionRunnable = object : Runnable {
        override fun run() {
            if (!isReleased) {
                positionUpdateCallback?.invoke(getCurrentPosition())
                handler.postDelayed(this, 50) // 20 Гц обновление
            }
        }
    }

    private fun startPositionUpdates() {
        handler.removeCallbacks(positionRunnable)
        handler.post(positionRunnable)
    }

    private fun stopPositionUpdates() {
        handler.removeCallbacks(positionRunnable)
    }

    /** Сброс */
    fun reset() {
        stopPositionUpdates()
        instrumentalPlayer.stop()
        vocalsPlayer.stop()
        instrumentalPlayer.clearMediaItems()
        vocalsPlayer.clearMediaItems()
    }

    /** Освобождение ресурсов */
    fun release() {
        isReleased = true
        stopPositionUpdates()
        instrumentalPlayer.release()
        vocalsPlayer.release()
    }

    /** Текущее состояние для UI */
    data class PlayerState(
        val isPlaying: Boolean,
        val currentPosition: Long,
        val duration: Long,
        val instrumentalVolume: Float,
        val vocalsVolume: Float
    ) {
        val progress: Float
            get() = if (duration > 0) currentPosition.toFloat() / duration else 0f

        val currentSec: Float
            get() = currentPosition / 1000f
    }

    fun getState(): PlayerState = PlayerState(
        isPlaying = isPlaying(),
        currentPosition = getCurrentPosition(),
        duration = getDuration(),
        instrumentalVolume = instrumentalVolume,
        vocalsVolume = vocalsVolume
    )
}
