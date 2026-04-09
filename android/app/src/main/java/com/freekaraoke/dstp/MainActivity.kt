package com.freekaraoke.dstp

import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.freekaraoke.dstp.library.LibraryManager
import com.freekaraoke.dstp.model.Track
import com.freekaraoke.dstp.player.KaraokePlayer
import com.freekaraoke.dstp.player.KaraokePlayerScreen
import com.freekaraoke.dstp.utils.FeatureLock
import com.freekaraoke.dstp.utils.FeatureLockState
import com.freekaraoke.dstp.utils.FeatureNotAvailableDialog
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            FreeKaraokeTheme {
                MainScreen()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen() {
    val context = LocalContext.current
    val libraryManager = remember { LibraryManager(context) }
    val scope = rememberCoroutineScope()
    val featureLockState = remember { FeatureLockState() }

    var tracks by remember { mutableStateOf<List<Track>>(emptyList()) }
    var selectedTrack by remember { mutableStateOf<Track?>(null) }
    var showPlayer by remember { mutableStateOf(false) }
    var showSearch by remember { mutableStateOf(false) }
    var searchQuery by remember { mutableStateOf("") }

    // Загрузка треков
    LaunchedEffect(Unit) {
        libraryManager.getAllTracksFlow().collect {
            tracks = it
        }
    }

    // Импорт ZIP
    val importLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        uri?.let {
            scope.launch {
                val result = libraryManager.importZip(it)
                if (result.added > 0) {
                    Toast.makeText(
                        context,
                        context.getString(R.string.import_success, result.added),
                        Toast.LENGTH_LONG
                    ).show()
                }
                if (result.hasErrors) {
                    Toast.makeText(
                        context,
                        context.getString(R.string.import_errors, result.errors.size),
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
    }

    // Экспорт ZIP
    val exportLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.CreateDocument("application/zip")
    ) { uri: Uri? ->
        uri?.let {
            scope.launch {
                val result = libraryManager.exportToZip(it)
                result.fold(
                    onSuccess = {
                        Toast.makeText(context, R.string.export_success, Toast.LENGTH_LONG).show()
                    },
                    onFailure = {
                        Toast.makeText(
                            context,
                            context.getString(R.string.export_error, it.message),
                            Toast.LENGTH_LONG
                        ).show()
                    }
                )
            }
        }
    }

    // Фильтрация по поиску
    val filteredTracks = tracks.filter { track ->
        if (searchQuery.isBlank()) return@filter true
        val query = searchQuery.lowercase()
        track.displayName.lowercase().contains(query) ||
            (track.artist?.lowercase()?.contains(query) == true)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.app_name)) },
                actions = {
                    IconButton(onClick = { showSearch = !showSearch }) {
                        Icon(Icons.Default.Search, stringResource(R.string.nav_search))
                    }
                    IconButton(onClick = { importLauncher.launch("application/zip") }) {
                        Icon(Icons.Default.Share, stringResource(R.string.action_import))
                    }
                    IconButton(onClick = {
                        if (tracks.isNotEmpty()) {
                            exportLauncher.launch("free_karaoke_library.zip")
                        }
                    }) {
                        Icon(Icons.Default.Share, stringResource(R.string.action_export))
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
            // Поисковая строка
            AnimatedVisibility(visible = showSearch) {
                OutlinedTextField(
                    value = searchQuery,
                    onValueChange = { searchQuery = it },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(8.dp),
                    placeholder = { Text(stringResource(R.string.nav_search)) },
                    leadingIcon = { Icon(Icons.Default.Search, null) },
                    trailingIcon = {
                        if (searchQuery.isNotEmpty()) {
                            IconButton(onClick = { searchQuery = "" }) {
                                Icon(Icons.Default.Close, null)
                            }
                        }
                    },
                    singleLine = true
                )
            }

            // Список треков
            if (filteredTracks.isEmpty()) {
                EmptyLibraryView(
                    onImportClick = { importLauncher.launch("application/zip") }
                )
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(bottom = 80.dp)
                ) {
                    items(filteredTracks, key = { it.id }) { track ->
                        TrackListItem(
                            track = track,
                            onPlay = {
                                selectedTrack = track
                                showPlayer = true
                            },
                            onDelete = {
                                scope.launch {
                                    libraryManager.deleteTrack(track)
                                }
                            }
                        )
                    }
                }
            }

            // Мини-плеер внизу
            if (showPlayer && selectedTrack != null) {
                KaraokePlayerScreen(
                    track = selectedTrack!!,
                    onClose = {
                        showPlayer = false
                        selectedTrack = null
                    },
                    libraryManager = libraryManager,
                    featureLockState = featureLockState
                )
            }
        }

        // Диалог блокировки функции
        if (featureLockState.showDialog) {
            FeatureNotAvailableDialog(
                featureName = featureLockState.lockedFeature ?: "",
                onDismiss = { featureLockState.dismissDialog() }
            )
        }
    }
}

@Composable
fun EmptyLibraryView(onImportClick: () -> Unit) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = Modifier.padding(32.dp)
        ) {
            Icon(
                Icons.Default.MusicNote,
                contentDescription = null,
                modifier = Modifier.size(80.dp),
                tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.3f)
            )
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = stringResource(R.string.empty_library_title),
                style = MaterialTheme.typography.headlineSmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = stringResource(R.string.empty_library_desc),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.4f),
                textAlign = TextAlign.Center
            )
            Spacer(modifier = Modifier.height(24.dp))
            Button(onClick = onImportClick) {
                Icon(Icons.Default.Upload, null)
                Spacer(modifier = Modifier.width(8.dp))
                Text(stringResource(R.string.empty_library_button))
            }
        }
    }
}

@Composable
fun TrackListItem(
    track: Track,
    onPlay: () -> Unit,
    onDelete: () -> Unit
) {
    var showDeleteDialog by remember { mutableStateOf(false) }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 8.dp, vertical = 4.dp)
            .clickable { onPlay() }
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // Иконка воспроизведения
            IconButton(onClick = { onPlay() }) {
                Icon(Icons.Default.PlayArrow, stringResource(R.string.action_play))
            }

            // Информация о треке
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = track.displayName,
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Row {
                    if (track.hasLyrics) {
                        Icon(
                            Icons.Default.Subtitles,
                            contentDescription = null,
                            modifier = Modifier.size(16.dp),
                            tint = MaterialTheme.colorScheme.primary
                        )
                        Spacer(modifier = Modifier.width(4.dp))
                    }
                    Text(
                        text = track.status,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            // Меню действий
            IconButton(onClick = { showDeleteDialog = true }) {
                Icon(Icons.Default.Delete, stringResource(R.string.action_delete))
            }
        }
    }

    if (showDeleteDialog) {
        AlertDialog(
            onDismissRequest = { showDeleteDialog = false },
            title = { Text(stringResource(R.string.delete)) },
            text = { Text(stringResource(R.string.confirm_delete, track.displayName)) },
            confirmButton = {
                TextButton(onClick = {
                    onDelete()
                    showDeleteDialog = false
                }) {
                    Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteDialog = false }) {
                    Text(stringResource(R.string.cancel))
                }
            }
        )
    }
}
