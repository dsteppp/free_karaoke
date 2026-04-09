package com.freekaraoke.dstp.player

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.freekaraoke.dstp.model.LyricsWord

/**
 * View для отображения караоке-текста с подсветкой текущего слова.
 */
@Composable
fun KaraokeLyricsView(
    words: List<LyricsWord>,
    currentSecond: Float,
    modifier: Modifier = Modifier
) {
    val listState = rememberLazyListState()

    // Находим текущее слово
    var currentWordIndex by remember { mutableStateOf(0) }
    currentWordIndex = words.indexOfFirstOrNull { word ->
        currentSecond >= word.start && currentSecond < word.end
    }?.coerceAtLeast(0) ?: run {
        // Если не попали в интервал — ближайшее предыдущее
        words.indexOfLast { it.start <= currentSecond }.coerceAtLeast(0)
    }

    // Автоскролл к текущей строке
    LaunchedEffect(currentWordIndex) {
        val targetLine = getCurrentLineIndex(words, currentWordIndex)
        if (targetLine >= 0) {
            listState.animateScrollToItem(
                index = targetLine,
                scrollOffset = -200 // Смещение к центру
            )
        }
    }

    // Группируем слова по строкам
    val lines = groupWordsByLines(words)

    LazyColumn(
        state = listState,
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        contentPadding = PaddingValues(vertical = 200.dp) // Отступы для центрирования
    ) {
        items(lines.size) { lineIndex ->
            val line = lines[lineIndex]
            val isCurrentLine = line.startIndex <= currentWordIndex && line.endIndex >= currentWordIndex

            KaraokeLine(
                words = line.words,
                currentSecond = currentSecond,
                isHighlighted = isCurrentLine
            )
        }
    }
}

@Composable
private fun KaraokeLine(
    words: List<LyricsWord>,
    currentSecond: Float,
    isHighlighted: Boolean
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically
    ) {
        for ((i, word) in words.withIndex()) {
            val isActive = currentSecond >= word.start && currentSecond < word.end
            val isPast = currentSecond >= word.end

            val textColor by animateColorAsState(
                targetValue = when {
                    isActive -> Color(0xFF00E5FF)  // Яркий голубой — текущее слово
                    isPast -> Color(0xFFB0BEC5)     // Серый — прошедшее
                    else -> Color(0xFFE0E0E0)       // Светлый — будущее
                },
                label = "word_color"
            )

            val textScale by animateFloatAsState(
                targetValue = if (isActive) 1.15f else 1f,
                label = "word_scale"
            )

            Text(
                text = word.word,
                style = TextStyle(
                    fontSize = if (isHighlighted) 22.sp else 18.sp,
                    fontWeight = if (isActive) FontWeight.Bold else FontWeight.Normal,
                    color = textColor
                ),
                modifier = Modifier
                    .alpha(if (isHighlighted) 1f else 0.5f)
                    .graphicsLayer { scaleX = textScale; scaleY = textScale },
                maxLines = 1
            )

            // Пробел между словами
            if (i < words.size - 1 && !word.lineBreak) {
                Text(" ", color = textColor, fontSize = 18.sp)
            }
        }
    }
}

// ── Утилиты ─────────────────────────────────────────────────────────────────

private data class LyricsLine(
    val words: List<LyricsWord>,
    val startIndex: Int,
    val endIndex: Int
)

private fun groupWordsByLines(words: List<LyricsWord>): List<LyricsLine> {
    val lines = mutableListOf<LyricsLine>()
    val currentLineWords = mutableListOf<LyricsWord>()
    var lineStartIndex = 0

    for ((i, word) in words.withIndex()) {
        currentLineWords.add(word)
        if (word.lineBreak) {
            lines.add(
                LyricsLine(
                    words = currentLineWords.toList(),
                    startIndex = lineStartIndex,
                    endIndex = i
                )
            )
            currentLineWords.clear()
            lineStartIndex = i + 1
        }
    }

    // Последняя строка
    if (currentLineWords.isNotEmpty()) {
        lines.add(
            LyricsLine(
                words = currentLineWords,
                startIndex = lineStartIndex,
                endIndex = words.size - 1
            )
        )
    }

    return lines
}

private fun getCurrentLineIndex(words: List<LyricsWord>, wordIndex: Int): Int {
    var lineIndex = 0
    var currentLineWordCount = 0

    for ((i, word) in words.withIndex()) {
        currentLineWordCount++
        if (word.lineBreak || i == wordIndex) {
            if (i == wordIndex) return lineIndex
            lineIndex++
            currentLineWordCount = 0
        }
    }

    return lineIndex
}

private fun <T> List<T>.indexOfFirstOrNull(predicate: (T) -> Boolean): Int? {
    val index = indexOfFirst(predicate)
    return if (index >= 0) index else null
}
