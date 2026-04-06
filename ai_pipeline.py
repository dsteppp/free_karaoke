import os
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["PYTORCH_ALLOC_CONF"]       = "expandable_segments:True"

import subprocess
import re
import json
import traceback
import gc
import unicodedata
import base64
import io
import requests
import torch

import lyricsgenius
from dotenv import load_dotenv
from tinytag import TinyTag
from mutagen import File as MutagenFile
from mutagen.id3 import ID3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from audio_separator.separator import Separator

# Наш обновленный безотказный выравниватель
from karaoke_aligner import KaraokeAligner
from app_logger import get_logger, dump_debug_text

log = get_logger("pipeline")

# ──────────────────────────────────────────────────────────────────────────────
# Утилиты: URL → base64 обложек
# ──────────────────────────────────────────────────────────────────────────────
def url_to_base64(url: str, max_size: int = 5 * 1024 * 1024) -> str | None:
    """Скачивает изображение по URL и возвращает data:image/...;base64,..."""
    if not url or not url.startswith("http"):
        return None
    try:
        resp = requests.get(url, timeout=15, stream=True)
        resp.raise_for_status()
        # Проверяем размер
        total = int(resp.headers.get("content-length", 0))
        if total > max_size:
            log.warning("Изображение слишком большое: %d байт", total)
            return None
        data = resp.content
        # Определяем MIME по Content-Type или первым байтам
        content_type = resp.headers.get("content-type", "")
        if "png" in content_type:
            mime = "png"
        elif "gif" in content_type:
            mime = "gif"
        elif "webp" in content_type:
            mime = "webp"
        elif data[:4] == b'\x89PNG':
            mime = "png"
        elif data[:3] == b'GIF':
            mime = "gif"
        else:
            mime = "jpeg"
        return f"data:image/{mime};base64,{base64.b64encode(data).decode()}"
    except Exception as e:
        log.warning("Не удалось скачать обложку %s: %s", url[:80], e)
        return None


def download_and_embed_covers(library_dir: str):
    """
    При запуске: находит все _meta.json, скачивает URL-обложки → вшивает в base64.
    """
    if not os.path.exists(library_dir):
        return

    count = 0
    for fname in os.listdir(library_dir):
        if not fname.endswith("_meta.json"):
            continue

        meta_path = os.path.join(library_dir, fname)
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)

            updated = False

            # Обложка трека
            cover = meta.get("cover", "")
            if cover and cover.startswith("http") and not cover.startswith("data:"):
                b64 = url_to_base64(cover)
                if b64:
                    meta["cover"] = b64
                    meta["cover_genius"] = b64
                    updated = True
                    log.info("   🖼️ Вшита обложка: %s", fname)

            # Фон плеера
            bg = meta.get("bg", "")
            if bg and bg.startswith("http") and not bg.startswith("data:"):
                b64 = url_to_base64(bg)
                if b64:
                    meta["bg"] = b64
                    meta["bg_genius"] = b64
                    updated = True
                    log.info("   🖼️ Вшит фон: %s", fname)

            if updated:
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False)
                count += 1
        except Exception as e:
            log.warning("Ошибка обработки %s: %s", fname, e)

    if count > 0:
        log.info("✅ Встроено обложек: %d", count)

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
         "-map_metadata", "0",  # Копируем теги из оригинала
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
# Автоустановка GPU-провайдера ONNX для AMD
# ──────────────────────────────────────────────────────────────────────────────
def _ensure_amd_onnx():
    """Если AMD GPU + нет ROCM provider → устанавливаем onnxruntime-rocm."""
    import subprocess
    # Проверяем AMD
    try:
        result = subprocess.run(["lspci"], capture_output=True, text=True)
        has_amd = "radeon" in result.stdout.lower() or "amd" in result.stdout.lower()
    except Exception:
        has_amd = False

    if not has_amd:
        return False  # Не AMD — не нужно

    # Проверяем ONNX провайдеры
    import onnxruntime as ort
    if "ROCMExecutionProvider" in ort.get_available_providers():
        return False  # Уже установлен

    # Проверяем интернет
    import socket
    try:
        socket.create_connection(("pypi.org", 443), timeout=3)
        has_internet = True
    except Exception:
        has_internet = False

    if not has_internet:
        log.warning("⚠️ AMD GPU обнаружен, но нет интернета. Сепарация на CPU (медленно).")
        log.warning("   Для ускорения: подключите интернет и запустите: pip install onnxruntime-rocm")
        return False

    # Устанавливаем
    log.info("🔧 AMD GPU: устанавливаю onnxruntime-rocm для ускорения сепарации...")
    try:
        subprocess.run(
            ["pip", "install", "-q", "onnxruntime-rocm"],
            capture_output=True, timeout=300
        )
        log.info("   ✅ onnxruntime-rocm установлен!")
        log.info("   ⚠️ Перезапустите приложение для активации GPU-ускорения")
        return True
    except Exception as e:
        log.warning("   ⚠️ Не удалось установить onnxruntime-rocm: %s", e)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Разделение вокала (audio-separator с GPU)
# ──────────────────────────────────────────────────────────────────────────────
def separate_vocals(mp3_path: str) -> tuple[str, str]:
    import time
    t_start = time.time()
    log.info("Запуск сепарации аудио...")

    # Автоустановка ROCM если AMD
    _ensure_amd_onnx()

    basedir  = os.path.dirname(mp3_path)
    basename = os.path.splitext(os.path.basename(mp3_path))[0]

    vocals_final       = os.path.join(basedir, f"{basename}_(Vocals).mp3")
    instrumental_final = os.path.join(basedir, f"{basename}_(Instrumental).mp3")

    # Определяем провайдеры ONNX
    providers = []
    try:
        import onnxruntime as ort
        available = ort.get_available_providers()

        if "ROCMExecutionProvider" in available:
            providers = ["ROCMExecutionProvider"]
            log.info("   🟢 GPU: AMD ROCM (ONNX)")
        elif "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider"]
            log.info("   🟢 GPU: NVIDIA CUDA (ONNX)")
        elif "DmlExecutionProvider" in available:
            providers = ["DmlExecutionProvider"]
            log.info("   🟢 GPU: DirectML")
        else:
            log.info("   ⚪ CPU (без GPU-ускорения)")
    except Exception:
        log.info("   ⚪ CPU (без GPU-ускорения)")

    t_model = time.time()
    separator = Separator(
        model_file_dir=MODELS_DIR,
        output_dir=basedir,
        output_format="MP3",
        normalization_threshold=0.9,
    )
    separator.load_model(model_filename="MDX23C-8KFFT-InstVoc_HQ.ckpt")
    log.info("   ⏱️ Загрузка модели: %.1fс", time.time() - t_model)

    t_infer = time.time()
    output_files = separator.separate(mp3_path)
    log.info("   ⏱️ Inference: %.1fс", time.time() - t_infer)

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

    t_compress = time.time()
    log.info("Сжатие стемов...")
    compress_stem_mp3(vocals_final)
    compress_stem_mp3(instrumental_final)
    log.info("   ⏱️ Сжатие: %.1fс", time.time() - t_compress)

    total = time.time() - t_start
    log.info("   ⏱️ СЕПАРАЦИЯ ЗАВЕРШЕНА: %.1fс", total)

    return vocals_final, instrumental_final

# ──────────────────────────────────────────────────────────────────────────────
# Метаданные (mutagen: artist, title, lyrics, cover)
# ──────────────────────────────────────────────────────────────────────────────
def extract_tags_from_file(file_path: str) -> dict:
    """
    Извлекает ВСЕ доступные теги из аудиофайла через mutagen.
    Возвращает: {artist, title, lyrics, cover_base64}
    """
    result = {"artist": "", "title": "", "lyrics": "", "cover_base64": ""}
    if not file_path or not os.path.exists(file_path):
        return result

    try:
        # Пробуем ID3 (MP3)
        if file_path.lower().endswith(".mp3"):
            tags = ID3(file_path)
            # Artist
            if "TPE1" in tags:
                result["artist"] = clean_metadata_string(str(tags["TPE1"]))
            # Title
            if "TIT2" in tags:
                result["title"] = clean_metadata_string(str(tags["TIT2"]))
            # Lyrics (USLT)
            for key in tags:
                if key.startswith("USLT"):
                    result["lyrics"] = str(tags[key].text).strip()
                    break
            # Cover (APIC)
            for key in tags:
                if key.startswith("APIC"):
                    img = tags[key]
                    mime = img.mime.split("/")[1]  # jpeg → jpg
                    result["cover_base64"] = f"data:image/{mime};base64,{base64.b64encode(img.data).decode()}"
                    break

        # FLAC
        elif file_path.lower().endswith(".flac"):
            tags = FLAC(file_path)
            if tags.get("artist"):
                result["artist"] = clean_metadata_string(tags["artist"][0])
            if tags.get("title"):
                result["title"] = clean_metadata_string(tags["title"][0])
            if tags.get("lyrics"):
                result["lyrics"] = tags["lyrics"][0].strip()
            # FLAC cover — через pictures
            if hasattr(tags, 'pictures') and tags.pictures:
                pic = tags.pictures[0]
                mime = pic.mime.split("/")[1]
                result["cover_base64"] = f"data:image/{mime};base64,{base64.b64encode(pic.data).decode()}"

        # M4A / ALAC
        elif file_path.lower().endswith((".m4a", ".alac")):
            tags = MP4(file_path)
            if tags.get("\xa9ART"):
                result["artist"] = clean_metadata_string(tags["\xa9ART"][0])
            if tags.get("\xa9nam"):
                result["title"] = clean_metadata_string(tags["\xa9nam"][0])
            # Lyrics
            if tags.get("\xa9lyr"):
                result["lyrics"] = tags["\xa9lyr"][0].strip()
            # Cover
            if tags.get("covr"):
                cover_data = tags["covr"][0]
                # Определяем формат по первым байтам
                if cover_data[:4] == b'\x89PNG':
                    mime = "png"
                else:
                    mime = "jpeg"
                result["cover_base64"] = f"data:image/{mime};base64,{base64.b64encode(cover_data).decode()}"

        # OGG
        elif file_path.lower().endswith(".ogg"):
            tags = OggVorbis(file_path)
            if tags.get("artist"):
                result["artist"] = clean_metadata_string(tags["artist"][0])
            if tags.get("title"):
                result["title"] = clean_metadata_string(tags["title"][0])
            if tags.get("lyrics"):
                result["lyrics"] = tags["lyrics"][0].strip()

        # Fallback: generic mutagen
        else:
            mfile = MutagenFile(file_path)
            if mfile and mfile.tags:
                # Пробуем стандартные ключи
                for key in ("artist", "Artist", "ARTIST", "performer", "PERFORMER"):
                    if key in mfile.tags:
                        val = mfile.tags[key]
                        result["artist"] = clean_metadata_string(val[0] if isinstance(val, list) else str(val))
                        break
                for key in ("title", "Title", "TITLE", "name", "NAME"):
                    if key in mfile.tags:
                        val = mfile.tags[key]
                        result["title"] = clean_metadata_string(val[0] if isinstance(val, list) else str(val))
                        break

    except Exception as e:
        log.warning("Ошибка чтения тегов mutagen: %s", e)

    return result


def strip_technical_suffix(text: str) -> str:
    return _TECHNICAL_SUFFIXES_RE.sub('', text).strip()


def get_audio_metadata(file_path: str, original_filename: str) -> tuple[str, str]:
    """
    Извлекает artist/title из тегов.
    Fallback на парсинг имени файла только если теги пустые.
    """
    tags = extract_tags_from_file(file_path)
    artist = tags["artist"]
    title = tags["title"]

    if artist and title:
        return artist, title

    # Fallback: парсим имя файла
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
# Genius и безопасная очистка текста
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
    """
    Приоритет:
    1. Genius (обложка + текст)
    2. Теги файла (обложка + текст) — если Genius недоступен/не нашёл
    """
    lyrics_file = f"{base_path}_(Genius Lyrics).txt"
    meta_file   = f"{base_path}_meta.json"

    # ── Попытка 1: Genius ──
    token = os.getenv("GENIUS_ACCESS_TOKEN")
    if token:
        try:
            genius = lyricsgenius.Genius(token, verbose=False, timeout=15)
            genius.remove_section_headers = False
            song = genius.search_song(title, artist)

            if song:
                g_artist = clean_metadata_string(song.artist)
                g_title  = clean_metadata_string(song.title)

                # Скачиваем обложку сразу как base64
                cover_url = getattr(song, "song_art_image_url", "") or ""
                bg_url    = getattr(song, "header_image_url",   "") or ""
                cover_b64 = url_to_base64(cover_url) if cover_url else ""
                bg_b64    = url_to_base64(bg_url) if bg_url else cover_b64

                meta = {
                    "cover":        cover_b64 or cover_url,
                    "bg":           bg_b64 or bg_url,
                    "cover_genius": cover_b64 or cover_url,
                    "bg_genius":    bg_b64 or bg_url,
                }
                with open(meta_file, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False)

                track_stem = os.path.basename(base_path)
                dump_debug_text("0_GeniusRaw", song.lyrics, track_stem)

                cleaned_lyrics = clean_genius_lyrics(song.lyrics)
                dump_debug_text("0_GeniusCleaned", cleaned_lyrics, track_stem)

                with open(lyrics_file, "w", encoding="utf-8") as f:
                    f.write(cleaned_lyrics)

                log.info("Genius: текст найден для %s - %s (обложка вшита: %s)",
                         g_artist, g_title, "✓" if cover_b64 else "URL")
                return lyrics_file, g_artist, g_title
            else:
                log.info("Genius: текст не найден для %s - %s, пробуем теги", artist, title)
        except Exception as e:
            log.warning("Genius ошибка: %s, пробуем теги", e)

    # ── Попытка 2: Теги файла (обложка + текст) ──
    log.info("📂 Пытаемся извлечь обложку и текст из тегов файла...")

    # Находим исходный файл — он мог быть удалён после конвертации в MP3
    # Ищем по base_name все возможные расширения
    source_file = None
    for ext in (".mp3", ".flac", ".m4a", ".alac", ".wav", ".ogg", ".aac"):
        candidate = f"{base_path}{ext}"
        if os.path.exists(candidate):
            source_file = candidate
            break

    if not source_file:
        # Может быть MP3 сконвертированный
        source_file = f"{base_path}.mp3"
        if not os.path.exists(source_file):
            log.warning("Исходный файл не найден, теги недоступны")
            return None, None, None

    tags = extract_tags_from_file(source_file)
    meta = {}

    # Обложка из тегов
    if tags["cover_base64"]:
        meta["cover"] = tags["cover_base64"]
        meta["cover_genius"] = tags["cover_base64"]
        meta["bg"] = tags["cover_base64"]
        meta["bg_genius"] = tags["cover_base64"]
        log.info("   🖼️ Обложка из тегов: %s", tags["cover_base64"][:50] + "...")

    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    # Текст из тегов
    if tags["lyrics"]:
        with open(lyrics_file, "w", encoding="utf-8") as f:
            f.write(tags["lyrics"])
        log.info("   📝 Текст из тегов: %d символов", len(tags["lyrics"]))
        return lyrics_file, artist, title

    log.info("   ⚠️ Текст в тегах не найден")
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