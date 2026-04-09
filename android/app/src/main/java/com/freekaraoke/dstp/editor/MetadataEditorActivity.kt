package com.freekaraoke.dstp.editor

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.freekaraoke.dstp.R
import com.freekaraoke.dstp.library.LibraryManager
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.launch

class MetadataEditorActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val trackId = intent.getStringExtra("track_id") ?: run {
            finish()
            return
        }

        setContent {
            MetadataEditorScreen(
                trackId = trackId,
                libraryManager = LibraryManager(this),
                onBack = { finish() }
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MetadataEditorScreen(
    trackId: String,
    libraryManager: LibraryManager,
    onBack: () -> Unit
) {
    val context = LocalContext.current
    var title by remember { mutableStateOf("") }
    var artist by remember { mutableStateOf("") }
    var coverUrl by remember { mutableStateOf("") }
    var bgUrl by remember { mutableStateOf("") }
    var isLoading by remember { mutableStateOf(true) }

    // Загрузка текущих метаданных
    LaunchedEffect(trackId) {
        val track = libraryManager.getTrack(trackId)
        if (track != null) {
            title = track.title ?: ""
            artist = track.artist ?: ""
            coverUrl = track.coverUrl ?: ""
            bgUrl = track.bgUrl ?: ""
        }
        isLoading = false
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.metadata_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, "Назад")
                    }
                },
                actions = {
                    IconButton(
                        enabled = !isLoading,
                        onClick = {
                            val scope = kotlinx.coroutines.MainScope()
                            scope.launch {
                                libraryManager.updateMetadata(
                                    id = trackId,
                                    title = title.takeIf { it.isNotBlank() },
                                    artist = artist.takeIf { it.isNotBlank() },
                                    coverUrl = coverUrl.takeIf { it.isNotBlank() },
                                    bgUrl = bgUrl.takeIf { it.isNotBlank() }
                                )
                                Toast.makeText(context, "Сохранено", Toast.LENGTH_SHORT).show()
                                onBack()
                            }
                        }
                    ) {
                        Icon(Icons.Default.Check, stringResource(R.string.save))
                    }
                }
            )
        }
    ) { paddingValues ->
        if (isLoading) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues),
                contentAlignment = androidx.compose.ui.Alignment.Center
            ) {
                CircularProgressIndicator()
            }
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues)
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it },
                    label = { Text(stringResource(R.string.metadata_track_name)) },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )

                OutlinedTextField(
                    value = artist,
                    onValueChange = { artist = it },
                    label = { Text(stringResource(R.string.metadata_artist)) },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )

                OutlinedTextField(
                    value = coverUrl,
                    onValueChange = { coverUrl = it },
                    label = { Text(stringResource(R.string.metadata_cover_url)) },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )

                OutlinedTextField(
                    value = bgUrl,
                    onValueChange = { bgUrl = it },
                    label = { Text("URL фона") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
            }
        }
    }
}
