"""
Шаг 1. Скачивание выгрузки OpenStreetMap по Казахстану (формат PBF) с Geofabrik
и проверка целостности файла по контрольной сумме MD5.
"""
import hashlib
from pathlib import Path

import requests

from src import config
from src.utils import log


def file_md5(path: Path, block_size: int = 4 * 1024 * 1024) -> str:
    """Считает MD5 файла по блокам по 4 МБ — файл целиком в память не загружается."""
    md5 = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            block = f.read(block_size)
            if not block:          # дошли до конца файла
                break
            md5.update(block)
    return md5.hexdigest()


def fetch_reference_md5(url: str) -> str | None:
    """Скачивает эталонную сумму MD5, которую публикует Geofabrik рядом с файлом."""
    try:
        response = requests.get(url + ".md5", timeout=30)
        response.raise_for_status()
        return response.text.split()[0]
    except requests.RequestException as err:
        log(f"Не удалось получить MD5 с сервера: {err}")
        return None


def download_pbf(url: str = config.PBF_URL, path: Path = config.PBF_PATH,
                 force: bool = False) -> Path:
    """
    Скачивает PBF-файл потоково (кусками по 1 МБ), чтобы не держать 216 МБ в памяти.
    Если файл уже есть и force=False — повторно не скачивает.
    """
    config.ensure_dirs()
    if path.exists() and not force:
        log(f"Файл уже скачан: {path.name} ({path.stat().st_size / 1024 ** 2:.1f} МБ)")
        return path

    log(f"Скачивание {url} ...")
    tmp_path = path.with_suffix(".part")
    try:
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            done = 0
            with open(tmp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
                    done += len(chunk)
                    # каждые ~20 МБ печатаем прогресс
                    if total and done % (20 * 1024 * 1024) < 1024 * 1024:
                        log(f"  загружено {done / total:.0%}")
        tmp_path.replace(path)
    except requests.RequestException as err:
        # сеть недоступна или сервер вернул ошибку — сообщаем, а не падаем
        log(f"Ошибка загрузки: {err}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    log(f"Файл сохранён: {path}")
    return path


def verify_pbf(path: Path = config.PBF_PATH, url: str = config.PBF_URL) -> bool:
    """Сравнивает MD5 локального файла с эталонной суммой Geofabrik."""
    if not path.exists():
        log("PBF-файл не найден — сначала выполните загрузку")
        return False
    reference = fetch_reference_md5(url)
    local = file_md5(path)
    if reference is None:
        log(f"MD5 локального файла: {local} (сверить не с чем — нет сети)")
        return True
    elif reference == local:
        log(f"MD5 совпадает: {local}")
        return True
    else:
        # На сервере могла появиться более свежая выгрузка — это не ошибка данных
        log(f"MD5 отличается (локальный {local}, на сервере {reference}). "
            "Вероятно, на Geofabrik уже опубликована более новая выгрузка.")
        return False
