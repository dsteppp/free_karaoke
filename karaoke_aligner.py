import os
import re
import json
import logging
import torch
import stable_whisper
from rapidfuzz import process, fuzz

class KaraokeAligner:
    def __init__(self, model_name="medium"):
        """
        Инициализация PhoneticAlignerV15.
        Используем medium, так как он дает идеальный баланс 
        между скоростью локальной работы и точностью фонетики.
        """
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing PhoneticAlignerV15 with Whisper '{model_name}'...")
        
        # Автоопределение GPU для Linux/Manjaro
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = stable_whisper.load_model(model_name, device=self.device)
        self.logger.info(f"Model loaded successfully on {self.device.upper()}.")

    def clean_lyrics(self, text: str) -> list:
        """
        Агрессивная и безопасная очистка текста Genius.
        Обход бага регулярных выражений: удаляем любые скобки и их содержимое.
        """
        # Стандартизация переносов строк
        text = text.replace('\r\n', '\n')
        
        # Безопасные паттерны для любых видов скобок (включая азиатские)
        patterns = [
            r'$$.*?$$',
            r'$.*?$',
            r'\{.*?\}',
            r'【.*?】',
            r'［.*?］'
        ]
        
        for p in patterns:
            text = re.sub(p, '', text)
            
        # Убираем пустые строки и лишние пробелы
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        return lines

    def _unfold_structure(self, genius_lines: list, whisper_result) -> list:
        """
        Магия развертывания: сопоставляет черновой звук с идеальным текстом.
        Если певец спел припев три раза, а в тексте он один - функция размножит текст.
        """
        unfolded = []
        last_idx = -1
        
        for seg in whisper_result.segments:
            seg_text = seg.text.strip()
            if not seg_text: 
                continue
            
            # Ищем, к какой строке Genius больше всего подходит этот кусок аудио
            match = process.extractOne(seg_text, genius_lines, scorer=fuzz.token_set_ratio)
            
            if match and match[1] > 55:  # Порог уверенности (55% совпадения)
                idx = genius_lines.index(match[0])
                
                # Защита от разрезания одной строки на два сегмента
                # Но если сегмент длинный (больше 3 слов), считаем это настоящим повтором в песне
                if idx != last_idx:
                    unfolded.append(genius_lines[idx])
                    last_idx = idx
                else:
                    if len(seg_text.split()) > 3:
                        unfolded.append(genius_lines[idx])
                        last_idx = idx
                        
        return unfolded

    def _format_result(self, result) -> list:
        """
        Конвертирует сырой результат выравнивания строго в формат, 
        который ожидает твой script.js для CSS-анимаций.
        """
        karaoke_data = []
        for seg in result.segments:
            words = []
            for w in seg.words:
                clean_word = w.word.strip()
                if clean_word:
                    words.append({
                        "word": clean_word,
                        "start": round(w.start, 3),
                        "end": round(w.end, 3)
                    })
            if words:
                karaoke_data.append({
                    "start": words[0]["start"],
                    "end": words[-1]["end"],
                    "text": seg.text.strip(),
                    "words": words
                })
        return karaoke_data

    def process_audio(self, audio_path: str, lyrics_input: str, output_json_path: str):
        """
        Главный пайплайн фонетического выравнивания.
        """
        # Проверяем, передали нам текст или путь к файлу с текстом
        if os.path.isfile(lyrics_input):
            with open(lyrics_input, 'r', encoding='utf-8') as f:
                lyrics_text = f.read()
        else:
            lyrics_text = lyrics_input

        self.logger.info("Step 1: Cleaning Genius Lyrics...")
        genius_lines = self.clean_lyrics(lyrics_text)
        
        if not genius_lines:
            raise ValueError("Lyrics are empty after cleaning! Check the Genius source.")

        self.logger.info("Step 2: Reality Mapping (Transcribing with VAD)...")
        # Черновое прослушивание с жестким контролем тишины (vad=True)
        # word_timestamps=False ускоряет процесс, так как нам нужна только структура
        reality_result = self.model.transcribe(audio_path, vad=True, word_timestamps=False)
        detected_lang = reality_result.language  # Запоминаем язык для выравнивания

        self.logger.info("Step 3: Structural Unfolding...")
        unfolded_lines = self._unfold_structure(genius_lines, reality_result)
        
        if not unfolded_lines:
            self.logger.warning("Unfolding failed (0 matches). Falling back to Blind Transcription.")
            # Фолбэк как у Монеточки: если текст вообще не совпадает, делаем слепую транскрибацию
            blind_result = self.model.transcribe(audio_path, vad=True, word_timestamps=True)
            karaoke_json = self._format_result(blind_result)
        else:
            self.logger.info("Step 4: Phonetic Forced Alignment...")
            try:
                # Магия: принудительно выравниваем развернутый текст по аудио
                aligned_result = self.model.align(
                    audio_path, 
                    unfolded_lines, 
                    language=detected_lang
                )
                karaoke_json = self._format_result(aligned_result)
            except Exception as e:
                self.logger.error(f"Forced Alignment failed: {e}. Falling back to Blind Transcription.")
                blind_result = self.model.transcribe(audio_path, vad=True, word_timestamps=True)
                karaoke_json = self._format_result(blind_result)

        self.logger.info(f"Step 5: Saving final JSON to {output_json_path}...")
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(karaoke_json, f, ensure_ascii=False, indent=4)
        
        self.logger.info("Phonetic Alignment complete!")
        return karaoke_json
