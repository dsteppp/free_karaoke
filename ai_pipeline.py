import os
import json
import logging
from dotenv import load_dotenv
from audio_separator.separator import Separator
import lyricsgenius
from tinytag import TinyTag

# Наш новый фонетический движок
from karaoke_aligner import KaraokeAligner
from app_logger import get_logger

load_dotenv()
log = get_logger("ai_pipeline")


def get_audio_metadata(file_path: str, fallback_name: str = "") -> tuple[str, str]:
    """
    Извлекает артиста и название из MP3-тегов.
    Если файл None или тегов нет, пытается распарсить имя файла.
    """
    artist, title = "", fallback_name
    
    if file_path and os.path.exists(file_path):
        try:
            tag = TinyTag.get(file_path)
            if tag.artist: artist = tag.artist.strip()
            if tag.title: title = tag.title.strip()
        except Exception as e:
            log.warning(f"Could not read tags from {file_path}: {e}")

    # Если теги пустые или файла нет, парсим имя файла
    if not artist or not title or title == fallback_name:
        fname = fallback_name if fallback_name else (os.path.basename(file_path) if file_path else "Unknown")
        fname = os.path.splitext(fname)[0]
        if " - " in fname:
            parts = fname.split(" - ", 1)
            if not artist: artist = parts[0].strip()
            if not title or title == fallback_name: title = parts[1].strip()
        else:
            if not title or title == fallback_name: title = fname.strip()

    return artist, title


class AIPipeline:
    def __init__(self):
        genius_token = os.getenv("GENIUS_ACCESS_TOKEN")
        if not genius_token:
            log.warning("GENIUS_ACCESS_TOKEN not found in .env! Lyrics fetching will fail.")
            self.genius = None
        else:
            self.genius = lyricsgenius.Genius(genius_token, verbose=False, remove_section_headers=True)

    def separate_audio(self, audio_path: str, output_dir: str, base_name: str):
        """
        Разделение аудио. Если стемы уже есть на диске - пропускает этот шаг.
        """
        final_vocal = os.path.join(output_dir, f"{base_name}_(Vocals).mp3")
        final_inst = os.path.join(output_dir, f"{base_name}_(Instrumental).mp3")
        
        # Умный пропуск: если файлы уже есть, не тратим время и видеокарту
        if os.path.exists(final_vocal) and os.path.exists(final_inst):
            log.info(f"Stems already exist for {base_name}. Skipping separation.")
            return final_vocal, final_inst
            
        # Если файлов нет, и оригинала тоже нет — это фатальная ошибка
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(f"Original audio file not found for {base_name}, and stems are missing!")

        log.info(f"Starting audio separation for: {audio_path}")
        
        separator = Separator(
            output_dir=output_dir,
            output_format="MP3",
            mdx_params={"hop_length": 1024, "segment_size": 256, "overlap": 0.25}
        )
        separator.load_model(model_filename='UVR-MDX-NET-Inst_HQ_3.onnx')
        
        primary_stem_path, secondary_stem_path = separator.separate(audio_path)
        
        inst_path = os.path.join(output_dir, primary_stem_path)
        vocal_path = os.path.join(output_dir, secondary_stem_path)
        
        # Переименовываем под стандарты твоего проекта
        if os.path.exists(final_inst): os.remove(final_inst)
        if os.path.exists(final_vocal): os.remove(final_vocal)
            
        os.rename(inst_path, final_inst)
        os.rename(vocal_path, final_vocal)
        
        log.info(f"Separation complete. Vocal: {final_vocal}")
        return final_vocal, final_inst

    def fetch_lyrics(self, artist: str, title: str, output_path: str) -> str:
        """
        Поиск текста в Genius и сохранение.
        """
        log.info(f"Fetching lyrics for: {artist} - {title}")
        
        if not self.genius:
            raise ValueError("Genius API token is missing. Cannot fetch lyrics.")

        song = self.genius.search_song(title, artist)
        
        if song and song.lyrics:
            log.info("Lyrics found successfully on Genius.")
            lyrics_text = song.lyrics
            
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(lyrics_text)
                
            return lyrics_text
        else:
            log.error("Lyrics not found on Genius.")
            raise ValueError(f"Lyrics not found for {artist} - {title}")

    def run_pipeline(self, track_id: str, audio_path: str, artist: str, title: str, output_dir: str, base_name: str):
        """
        Главный оркестратор.
        """
        log.info(f"=== Starting AI Pipeline for Track: {track_id} ===")
        
        # 1. Выделяем вокал (Или пропускаем, если стемы уже есть)
        vocal_path, inst_path = self.separate_audio(audio_path, output_dir, base_name)
        
        # 0. Извлекаем метаданные. Если оригинала нет, читаем прямо из свежего вокала!
        meta_source_path = audio_path if (audio_path and os.path.exists(audio_path)) else vocal_path
        if not artist or not title:
            ext_artist, ext_title = get_audio_metadata(meta_source_path, base_name)
            artist = artist or ext_artist
            title = title or ext_title
        
        # 2. Ищем текст и сохраняем его
        lyrics_path = os.path.join(output_dir, f"{base_name}_(Genius Lyrics).txt")
        raw_lyrics = self.fetch_lyrics(artist, title, lyrics_path)
        
        # 3. Фонетическое выравнивание
        json_output_path = os.path.join(output_dir, f"{base_name}_(Karaoke Lyrics).json")
        
        log.info("Initializing Phonetic Aligner...")
        aligner = KaraokeAligner(model_name="medium") 
        
        log.info("Starting phonetic alignment process...")
        aligner.process_audio(vocal_path, raw_lyrics, json_output_path)
        
        # 4. Создаем мета-файл
        meta_path = os.path.join(output_dir, f"{base_name}_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"artist": artist, "title": title, "status": "done"}, f)

        log.info(f"=== Pipeline completed successfully for Track: {track_id} ===")
        
        return {
            "vocal": vocal_path,
            "instrumental": inst_path,
            "json": json_output_path,
            "lyrics": lyrics_path,
            "artist": artist,
            "title": title
        }