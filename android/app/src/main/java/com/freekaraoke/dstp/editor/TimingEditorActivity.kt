package com.freekaraoke.dstp.editor

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.freekaraoke.dstp.R
import com.freekaraoke.dstp.library.LibraryManager
import com.freekaraoke.dstp.model.LyricsWord
import com.freekaraoke.dstp.player.KaraokePlayer
import kotlinx.coroutines.launch

class TimingEditorActivity : ComponentActivity() {

    private val viewModel: TimingEditorViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val trackId = intent.getStringExtra("track_id") ?: run {
            finish()
            return
        }

        setContent {
            TimingEditorScreen(
                trackId = trackId,
                libraryManager = LibraryManager(this),
                onBack = { finish() }
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TimingEditorScreen(
    trackId: String,
    libraryManager: LibraryManager,
    onBack: () -> Unit
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()

    var words by remember { mutableStateOf<List<LyricsWord>>(emptyList()) }
    var selectedWordIndex by remember { mutableStateOf<Int?>(null) }
    var isEditing by remember { mutableStateOf(false) }
    var editText by remember { mutableStateOf("") }

    // Загрузка таймингов
    LaunchedEffect(trackId) {
        val track = libraryManager.getTrack(trackId)
        if (track != null) {
            words = libraryManager.getLyricsWords(track)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.timing_editor_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, "Назад")
                    }
                },
                actions = {
                    IconButton(
                        onClick = {
                            scope.launch {
                                val track = libraryManager.getTrack(trackId)
                                if (track != null) {
                                    val success = libraryManager.saveLyricsWords(track, words)
                                    Toast.makeText(
                                        context,
                                        if (success) "Сохранено" else "Ошибка сохранения",
                                        Toast.LENGTH_SHORT
                                    ).show()
                                    if (success) onBack()
                                }
                            }
                        }
                    ) {
                        Icon(Icons.Default.Check, stringResource(R.string.save))
                    }
                }
            )
        }
    ) { paddingValues ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            itemsIndexed(words) { index, word ->
                TimingWordItem(
                    word = word,
                    index = index,
                    isSelected = selectedWordIndex == index,
                    isEditing = selectedWordIndex == index && isEditing,
                    editText = editText,
                    onClick = {
                        selectedWordIndex = index
                        isEditing = false
                    },
                    onEdit = {
                        isEditing = true
                        editText = word.word
                    },
                    onTextChange = { editText = it },
                    onAnchor = {
                        // Якорь — установить точное время
                        // В полной версии здесь была бы логика якорения к текущей позиции плеера
                    },
                    onDelete = {
                        words = words.toMutableList().apply { removeAt(index) }
                    }
                )
            }
        }
    }
}

@Composable
private fun TimingWordItem(
    word: LyricsWord,
    index: Int,
    isSelected: Boolean,
    isEditing: Boolean,
    editText: String,
    onClick: () -> Unit,
    onEdit: () -> Unit,
    onTextChange: (String) -> Unit,
    onAnchor: () -> Unit,
    onDelete: () -> Unit
) {
    var showMenu by remember { mutableStateOf(false) }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onClick() },
        colors = CardDefaults.cardColors(
            containerColor = if (isSelected)
                MaterialTheme.colorScheme.primaryContainer
            else
                MaterialTheme.colorScheme.surface
        )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // Номер
            Text(
                text = "${index + 1}",
                style = MaterialTheme.typography.labelSmall,
                modifier = Modifier.width(30.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            // Слово
            if (isEditing) {
                OutlinedTextField(
                    value = editText,
                    onValueChange = onTextChange,
                    modifier = Modifier.weight(1f),
                    singleLine = true,
                    textStyle = MaterialTheme.typography.bodyMedium
                )
            } else {
                Text(
                    text = word.word,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.weight(1f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }

            // Время
            Text(
                text = String.format("%.2f", word.start),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 8.dp)
            )

            // Меню
            Box {
                IconButton(onClick = { showMenu = true }) {
                    Icon(Icons.Default.MoreVert, null)
                }

                DropdownMenu(
                    expanded = showMenu,
                    onDismissRequest = { showMenu = false }
                ) {
                    DropdownMenuItem(
                        text = { Text("Редактировать") },
                        onClick = { onEdit(); showMenu = false }
                    )
                    DropdownMenuItem(
                        text = { Text("Якорь") },
                        onClick = { onAnchor(); showMenu = false }
                    )
                    DropdownMenuItem(
                        text = { Text("Удалить") },
                        onClick = { onDelete(); showMenu = false }
                    )
                }
            }
        }
    }
}
