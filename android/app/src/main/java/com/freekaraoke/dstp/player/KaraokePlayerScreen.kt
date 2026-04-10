package com.freekaraoke.dstp.player

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.freekaraoke.dstp.R
import com.freekaraoke.dstp.library.LibraryManager
import com.freekaraoke.dstp.model.LyricsWord
import com.freekaraoke.dstp.model.Track
import com.freekaraoke.dstp.utils.FeatureLock
import com.freekaraoke.dstp.utils.FeatureLockState
import kotlinx.coroutines.launch

/**
 * Полноэкранный караоке-плеер с ExoPlayer x2 и подсветкой слов.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KaraokePlayerScreen(
    track: Track,
    onClose: () -> Unit,
    libraryManager: LibraryManager,
    featureLockState: FeatureLockState
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    val karaokePlayer = remember { KaraokePlayer(context) }
    var playerState by remember { mutableStateOf(karaokePlayer.getState()) }
    var lyricsWords by remember { mutableStateOf<List<LyricsWord>>(emptyList()) }
    var instrumentalVol by remember { mutableStateOf(1f) }
    var vocalsVol by remember { mutableStateOf(1f) }

    // Загрузка трека
    LaunchedEffect(track) {
        if (track.instrumentalPath != null && track.vocalsPath != null) {
            karaokePlayer.load(track.instrumentalPath, track.vocalsPath)
        }

        // Загрузка таймингов
        lyricsWords = libraryManager.getLyricsWords(track)

        // Обновление состояния
        karaokePlayer.onPositionUpdate { positionMs ->
            playerState = karaokePlayer.getState().copy(currentPosition = positionMs)
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            karaokePlayer.release()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            text = track.displayName,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onClose) {
                        Icon(Icons.Default.ArrowBack, "Назад")
                    }
                },
                actions = {
                    // Редактор метаданных
                    IconButton(onClick = {
                        // TODO: открыть MetadataEditorActivity
                    }) {
                        Icon(Icons.Default.Edit, stringResource(R.string.action_edit_metadata))
                    }
                    // Редактор таймингов
                    IconButton(onClick = {
                        // TODO: открыть TimingEditorActivity
                    }) {
                        Icon(Icons.Default.Tune, stringResource(R.string.action_edit_timings))
                    }
                }
            )
        }
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
        ) {
            // Текст караоке
            if (lyricsWords.isEmpty()) {
                Box(
                    modifier = Modifier.weight(1f),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = stringResource(R.string.player_no_lyrics),
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            } else {
                KaraokeLyricsView(
                    words = lyricsWords,
                    currentSecond = playerState.currentSec,
                    modifier = Modifier.weight(1f)
                )
            }

            // Управление громкостью
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.SpaceEvenly
            ) {
                VolumeSlider(
                    label = stringResource(R.string.player_instrumental),
                    volume = instrumentalVol,
                    onVolumeChange = {
                        instrumentalVol = it
                        karaokePlayer.setInstrumentalVolume(it)
                    }
                )
                VolumeSlider(
                    label = stringResource(R.string.player_vocals),
                    volume = vocalsVol,
                    onVolumeChange = {
                        vocalsVol = it
                        karaokePlayer.setVocalsVolume(it)
                    }
                )
            }

            // Кнопки управления
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                // Назад на 10 сек
                IconButton(onClick = {
                    karaokePlayer.seekTo((playerState.currentPosition - 10000).coerceAtLeast(0))
                }) {
                    Icon(Icons.Default.Replay10, "Назад 10с")
                }

                // Play/Pause
                FilledIconButton(
                    onClick = { karaokePlayer.playPause() },
                    modifier = Modifier.size(64.dp)
                ) {
                    Icon(
                        imageVector = if (playerState.isPlaying) Icons.Default.Pause else Icons.Default.PlayArrow,
                        contentDescription = null,
                        modifier = Modifier.size(36.dp)
                    )
                }

                // Вперёд на 10 сек
                IconButton(onClick = {
                    karaokePlayer.seekTo((playerState.currentPosition + 10000).coerceAtMost(playerState.duration))
                }) {
                    Icon(Icons.Default.Forward10, "Вперёд 10с")
                }
            }

            // Прогресс-бар
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp)
            ) {
                Slider(
                    value = playerState.progress.coerceIn(0f, 1f),
                    onValueChange = { progress ->
                        karaokePlayer.seekTo((progress * playerState.duration).toLong())
                    },
                    modifier = Modifier.fillMaxWidth()
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(formatTime(playerState.currentPosition), style = MaterialTheme.typography.bodySmall)
                    Text(formatTime(playerState.duration), style = MaterialTheme.typography.bodySmall)
                }
            }

            // Кнопки ML-функций (заблокированы)
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                horizontalArrangement = Arrangement.SpaceEvenly
            ) {
                FilterChip(
                    onClick = { featureLockState.showLockDialog(FeatureLock.getFeatureName(FeatureLock.Feature.SEPARATION)) },
                    label = { Text(stringResource(R.string.feature_separation)) },
                    leadingIcon = { Icon(Icons.Default.MusicNote, null) },
                    selected = false,
                    enabled = false
                )
                FilterChip(
                    onClick = { featureLockState.showLockDialog(FeatureLock.getFeatureName(FeatureLock.Feature.TRANSCRIPTION)) },
                    label = { Text(stringResource(R.string.feature_transcription)) },
                    leadingIcon = { Icon(Icons.Default.Mic, null) },
                    selected = false,
                    enabled = false
                )
            }
        }
    }
}

@Composable
private fun VolumeSlider(
    label: String,
    volume: Float,
    onVolumeChange: (Float) -> Unit
) {
    Column(
        modifier = Modifier.width(150.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(label, style = MaterialTheme.typography.labelSmall)
        Slider(
            value = volume,
            onValueChange = onVolumeChange,
            valueRange = 0f..1f,
            modifier = Modifier.fillMaxWidth()
        )
    }
}

private fun formatTime(ms: Long): String {
    val totalSec = ms / 1000
    val min = totalSec / 60
    val sec = totalSec % 60
    return "%d:%02d".format(min, sec)
}
