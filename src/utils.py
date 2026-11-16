"""
Вспомогательные функции: замер времени и памяти, работа с JSON, логирование,
сохранение состояния программы.
"""
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import psutil

from src import config


def log(message: str) -> None:
    """Печатает сообщение с текущим временем — удобно следить за долгими шагами."""
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def current_memory_mb() -> float:
    """Текущий объём памяти процесса (RSS) в мегабайтах."""
    return psutil.Process(os.getpid()).memory_info().rss / 1024 ** 2


def peak_memory_mb() -> float:
    """
    Пиковая память процесса с момента запуска, МБ.

    На разных ОС пиковое значение берётся по-разному, поэтому здесь
    используется условная логика if / elif / else.
    """
    if sys.platform.startswith("win"):
        # В Windows psutil отдаёт "peak working set" — максимум за жизнь процесса
        return psutil.Process(os.getpid()).memory_info().peak_wset / 1024 ** 2
    elif sys.platform == "darwin":
        import resource
        # В macOS ru_maxrss измеряется в байтах
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 ** 2
    else:
        import resource
        # В Linux (и Google Colab) ru_maxrss измеряется в килобайтах
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


@contextmanager
def timer(label: str, results: dict | None = None):
    """
    Контекстный менеджер для замера времени блока кода:

        with timer("чтение файла", stats):
            ...

    Если передан словарь results — время (сек) запишется в results[label].
    """
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    if results is not None:
        results[label] = round(elapsed, 3)
    log(f"{label}: {elapsed:.2f} с")


def df_memory_mb(df) -> float:
    """Память, занимаемая DataFrame (с учётом строк — deep=True), МБ."""
    return float(df.memory_usage(deep=True).sum()) / 1024 ** 2


def save_json(data, path: Path) -> None:
    """Сохраняет словарь/список в JSON (UTF-8, с отступами, кириллица без экранирования)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def load_json(path: Path, default=None):
    """
    Читает JSON. Если файла нет или он повреждён — возвращает значение
    по умолчанию, а не падает (обработка ошибок try / except).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as err:
        log(f"Файл {path.name} повреждён ({err}), используется значение по умолчанию")
        return default


def update_run_state(step: str, info: dict | None = None) -> None:
    """
    Запоминает в outputs/run_state.json, какой шаг конвейера и когда был выполнен.
    Так меню может показать пользователю текущее состояние проекта.
    """
    state = load_json(config.RUN_STATE_PATH, default={})
    state[step] = {"finished_at": datetime.now().isoformat(timespec="seconds")}
    if info:
        state[step].update(info)
    save_json(state, config.RUN_STATE_PATH)


def iter_parquet_chunks(dataset_dir: Path, batch_size: int, columns: list | None = None):
    """
    Генератор: читает партиционированный Parquet и отдаёт pandas DataFrame
    примерно по batch_size строк.

    pyarrow отдаёт батчи отдельно по каждому файлу-фрагменту (они бывают мелкими),
    поэтому батчи складываются в список, пока не наберётся batch_size строк,
    и только потом склеиваются в один DataFrame. В памяти — не больше одного чанка.
    """
    import pyarrow as pa
    import pyarrow.dataset as ds

    dataset = ds.dataset(str(dataset_dir), format="parquet", partitioning="hive")
    pending, pending_rows = [], 0
    for batch in dataset.to_batches(columns=columns, batch_size=batch_size):
        pending.append(batch)
        pending_rows += batch.num_rows
        if pending_rows >= batch_size:
            # combine_chunks склеивает мелкие куски в один непрерывный массив —
            # иначе при записи каждый кусок стал бы отдельной row group в Parquet
            yield pa.Table.from_batches(pending).combine_chunks().to_pandas()
            pending, pending_rows = [], 0
    if pending:                                  # остаток последнего неполного чанка
        yield pa.Table.from_batches(pending).combine_chunks().to_pandas()


def human_size(path: Path) -> float:
    """Размер файла или папки (суммарно по всем файлам) в мегабайтах."""
    path = Path(path)
    if path.is_file():
        return path.stat().st_size / 1024 ** 2
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            total += os.path.getsize(os.path.join(root, name))
    return total / 1024 ** 2
