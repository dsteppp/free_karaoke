import os
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["PYTORCH_ALLOC_CONF"]       = "expandable_segments:True"

import subprocess
import re
import json
import traceback
import gc
import unicodedata
import torch

import lyricsgenius
from dotenv import load_dotenv
from tinytag import TinyTag
from audio_separator.separator import Separator

# Наш обновленный безотказный выравниватель
from karaoke_aligner import KaraokeAligner
from app_logger import get_logger, dump_debug_text

log = get_logger("pipeline")

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR  = os.path.join(BASE_DIR, "models")
WHISPER_DIR = os.path.join(MODELS_DIR, "whisper")

os.makedirs(MODELS_DIR,  exist_ok=True)
os.makedirs(WHISPER_DIR, exist_ok=True)

load_dotenv()

# ──────────────────────────────────────────────────────────────────────────────
# Технические суффиксы в именах файлов
# ──────────────────────────────────────────────────────────────────────────────
_TECHNICAL_SUFFIXES_RE = re.compile(
    r'\s*[\x5B\x28\{_]?\s*'
    r'(?:Vocals?|Instrumental|No[_ ]?Vocals?|Karaoke|Acapella|Backing|'
    r'вокал|инструментал|минус|бэк|караоке)'
    r'\s*[\x5D\x29\}]?\s*$',
    re.IGNORECASE,
)

# ──────────────────────────────────────────────────────────────────────────────
# Умный фильтр метаданных (NFC Нормализация + Очистка от мусора)
# ──────────────────────────────────────────────────────────────────────────────
def clean_metadata_string(text: str) -> str:
    if not text: return ""
    
    # МАГИЯ UNICODE: Лечит проблему с буквой Ё (NFD vs NFC) для Mac и Linux
    text = unicodedata.normalize('NFC', text.strip())
    text = re.sub(r'[\*]+$', '', text).strip()
    
    whitelist = [
        'live', 'cover', 'acoustic', 'remix', 'feat', 'ft.', 'edit', 
        'version', 'mix', 'prod', 'ost', 'unplugged', 'radio'
    ]
    
    def bracket_replacer(match):
        content = match.group(1) or match.group(2)
        if not content: return ""
        if any(w in content.lower() for w in whitelist):
            return match.group(0) 
        return ""

    text = re.sub(r'\x28([^\x29]+)\x29', bracket_replacer, text)
    text = re.sub(r'\x5B([^\x5D]+)\x5D', bracket_replacer, text)
    text = re.sub(r'^\s*[«"\'`]|[»"\'`]\s*$', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# ──────────────────────────────────────────────────────────────────────────────
# Конвертация и сжатие
# ──────────────────────────────────────────────────────────────────────────────
def convert_to_mp3(input_path: str) -> str:
    basename   = os.path.splitext(input_path)[0]
    final_path = f"{basename}.mp3"
    temp_path  = f"{basename}_tmp_conv.mp3"

    log.info("Конвертация в MP3 192k: %s", input_path)
    subprocess.run(
        ["ffmpeg", "-i", input_path,
         "-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k",
         temp_path, "-y"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        check=True,
    )

    if os.path.abspath(input_path) != os.path.abspath(final_path):
        if os.path.exists(input_path):
            os.remove(input_path)

    os.rename(temp_path, final_path)
    return final_path

def compress_stem_mp3(file_path: str) -> None:
    temp = f"{file_path}.tmp.mp3"
    subprocess.run(
        ["ffmpeg", "-i", file_path,
         "-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k",
         temp, "-y"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        check=True,
    )
    os.replace(temp, file_path)

# ──────────────────────────────────────────────────────────────────────────────
# Разделение вокала (audio-separator)
# ──────────────────────────────────────────────────────────────────────────────
def separate_vocals(mp3_path: str) -> tuple[str, str]:
    log.info("Запуск сепарации аудио (audio-separator на CPU)...")
    basedir  = os.path.dirname(mp3_path)
    basename = os.path.splitext(os.path.basename(mp3_path))[0]

    vocals_final       = os.path.join(basedir, f"{basename}_(Vocals).mp3")
    instrumental_final = os.path.join(basedir, f"{basename}_(Instrumental).mp3")

    # Принудительно активируем CPUExecutionProvider (Ryzen 7500F справится играючи)
    separator = Separator(
        model_file_dir=MODELS_DIR,
        output_dir=basedir,
        output_format="MP3",
        normalization_threshold=0.9,
        execution_providers=["CPUExecutionProvider"]
    )
    separator.load_model(model_filename="MDX23C-8KFFT-InstVoc_HQ.ckpt")
    output_files = separator.separate(mp3_path)

    del separator
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    found_vocals = None
    found_instrumental = None

    for item in output_files:
        out_path = item if os.path.isabs(item) else os.path.join(basedir, item)
        name_lc  = out_path.lower()
        if "vocals" in name_lc: found_vocals = out_path
        elif "instrumental" in name_lc or "no_vocals" in name_lc: found_instrumental = out_path

    if not found_vocals or not found_instrumental:
        raise RuntimeError("audio-separator не вернул нужные файлы.")

    if found_vocals != vocals_final:
        if os.path.exists(vocals_final): os.remove(vocals_final)
        os.rename(found_vocals, vocals_final)

    if found_instrumental != instrumental_final:
        if os.path.exists(instrumental_final): os.remove(instrumental_final)
        os.rename(found_instrumental, instrumental_final)

    log.info("Сжатие стемов...")
    compress_stem_mp3(vocals_final)
    compress_stem_mp3(instrumental_final)

    return vocals_final, instrumental_final

# ──────────────────────────────────────────────────────────────────────────────
# Метаданные
# ──────────────────────────────────────────────────────────────────────────────
def strip_technical_suffix(text: str) -> str:
    return _TECHNICAL_SUFFIXES_RE.sub('', text).strip()

def get_audio_metadata(file_path: str, original_filename: str) -> tuple[str, str]:
    artist, title = "", ""
    if file_path and os.path.exists(file_path):
        try:
            tag = TinyTag.get(file_path)
            if tag.artist: artist = clean_metadata_string(tag.artist)
            if tag.title: title = clean_metadata_string(tag.title)
        except Exception:
            pass

    if artist and title:
        return artist, title

    clean = unicodedata.normalize('NFC', original_filename)
    clean = re.sub(r"\.[^.]+$", "", clean)
    clean = re.sub(r"_+", " ", clean)
    clean = strip_technical_suffix(clean)

    for sep in (" - ", "-"):
        parts = clean.split(sep, 1)
        if len(parts) == 2:
            p_art = clean_metadata_string(parts[0])
            p_tit = clean_metadata_string(parts[1])
            if p_art and p_tit:
                return p_art or artist, p_tit or title

    return artist, clean_metadata_string(clean) or title

# ──────────────────────────────────────────────────────────────────────────────
# Genius и безопасная очистка текста (Sanitizer Phase 1)
# ──────────────────────────────────────────────────────────────────────────────
def clean_genius_lyrics(raw_text: str) -> str:
    text = raw_text.strip()
    
    lines = text.split('\n')
    if lines and ("Lyrics" in lines[0] or "Текст песни" in lines[0] or "Текст" in lines[0]):
        lines = lines[1:]
    text = '\n'.join(lines)

    text = re.sub(r'\d*\s*Embed\s*$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Contributors.*$', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\x5B.*?\x5D', '', text, flags=re.DOTALL)
    text = re.sub(r'\x28.*?\x29', '', text, flags=re.DOTALL)
    text = re.sub(r'\s+([,.:;?!—])', r'\1', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()

def fetch_lyrics(artist: str, title: str, base_path: str) -> tuple[str | None, str | None, str | None]:
    lyrics_file = f"{base_path}_(Genius Lyrics).txt"
    meta_file   = f"{base_path}_meta.json"

    token = os.getenv("GENIUS_ACCESS_TOKEN")
    if not token: return None, None, None

    try:
        genius = lyricsgenius.Genius(token, verbose=False, timeout=15)
        genius.remove_section_headers = False 
        song = genius.search_song(title, artist)
        
        if not song: return None, None, None

        g_artist = clean_metadata_string(song.artist)
        g_title  = clean_metadata_string(song.title)

        meta = {
            "cover": getattr(song, "song_art_image_url", "") or "",
            "bg":    getattr(song, "header_image_url",   "") or "",
        }
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        track_stem = os.path.basename(base_path)
        dump_debug_text("0_GeniusRaw", song.lyrics, track_stem)

        cleaned_lyrics = clean_genius_lyrics(song.lyrics)
        dump_debug_text("0_GeniusCleaned", cleaned_lyrics, track_stem)

        with open(lyrics_file, "w", encoding="utf-8") as f:
            f.write(cleaned_lyrics)

        return lyrics_file, g_artist, g_title
    except Exception as e:
        log.error("Ошибка Genius: %s", e)
        return None, None, None

def generate_karaoke_subtitles(inst_mp3: str, vocals_mp3: str, lyrics_path: str) -> str | None:
    basename = os.path.basename(vocals_mp3).replace("_(Vocals).mp3", "")
    final_json = os.path.join(os.path.dirname(vocals_mp3), f"{basename}_(Karaoke Lyrics).json")

    if not (lyrics_path and os.path.exists(lyrics_path)): return None

    with open(lyrics_path, "r", encoding="utf-8") as f:
        raw_text = f.read()
        
    clean_text = clean_genius_lyrics(raw_text)

    try:
        aligner = KaraokeAligner(model_name="medium")
        aligner.process_audio(vocals_path=vocals_mp3, raw_lyrics=clean_text, output_json_path=final_json)
        return final_json
    except Exception as e:
        log.error("Ошибка выравнивания: %s", e)
        log.debug("Traceback:\n%s", traceback.format_exc())
        return None