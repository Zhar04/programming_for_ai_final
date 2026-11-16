"""
Шаг 6. Сравнение инструментов обработки на ОДНОЙ и той же задаче.

Задача: по всем 3,2 млн объектам посчитать для каждой пары (регион, ключ OSM)
  * число объектов, * число объектов с названием, * среднее число тегов,
  * дату последней правки.

Подходы:
  baseline      pandas_csv         — pandas.read_csv целиком (как делают "по умолчанию")
  подход 1      pandas_csv_chunks  — read_csv(chunksize=...) + инкрементальные агрегаты
  подход 2      pandas_parquet     — pandas.read_parquet только нужных столбцов
  подход 3      polars_lazy        — Polars scan_parquet (ленивый, потоковый движок)
  подход 4      duckdb_sql         — SQL-запрос DuckDB прямо по файлам Parquet

Каждый запуск выполняется в ОТДЕЛЬНОМ процессе (subprocess) — иначе пиковая
память одного подхода "испортила" бы замер следующего. Время — медиана 3 запусков.
Результаты каждого подхода сохраняются и сверяются с эталоном.
"""
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

from src import config
from src.utils import log, peak_memory_mb, current_memory_mb, human_size

BENCH_DIR = config.INTERIM_DIR / "benchmark_results"
PARQUET_GLOB = str(config.FEATURES_REGION_DIR / "**" / "*.parquet")
NEEDED = ["region_iso", "feature_key", "name", "n_tags", "timestamp"]
KEYS = ["region_iso", "feature_key"]


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    """Приводит результат любого подхода к единому виду для сравнения."""
    df = df.copy()
    df["region_iso"] = df["region_iso"].astype(str)
    df["feature_key"] = df["feature_key"].astype(str)
    df["n_objects"] = df["n_objects"].astype("int64")
    df["n_named"] = df["n_named"].astype("int64")
    df["mean_tags"] = df["mean_tags"].astype("float64").round(9)
    df["last_edit"] = pd.to_datetime(df["last_edit"], utc=True)
    return df.sort_values(KEYS).reset_index(drop=True)[
        KEYS + ["n_objects", "n_named", "mean_tags", "last_edit"]]


def run_pandas_csv() -> pd.DataFrame:
    """Baseline: читаем CSV целиком в память (только нужные столбцы) и группируем."""
    df = pd.read_csv(config.FEATURES_CSV, usecols=NEEDED, parse_dates=["timestamp"])
    out = df.groupby(KEYS).agg(n_objects=("n_tags", "size"), n_named=("name", "count"),
                               mean_tags=("n_tags", "mean"), last_edit=("timestamp", "max"))
    return out.reset_index()


def run_pandas_csv_chunks(chunksize: int = 500_000) -> pd.DataFrame:
    """CSV читается кусками; для каждого куска считаем частичные суммы и складываем."""
    parts = []
    for chunk in pd.read_csv(config.FEATURES_CSV, usecols=NEEDED, chunksize=chunksize,
                             parse_dates=["timestamp"]):
        parts.append(chunk.groupby(KEYS).agg(n_objects=("n_tags", "size"),
                                             n_named=("name", "count"),
                                             sum_tags=("n_tags", "sum"),
                                             last_edit=("timestamp", "max")))
    combined = pd.concat(parts).groupby(level=KEYS).agg(
        n_objects=("n_objects", "sum"), n_named=("n_named", "sum"),
        sum_tags=("sum_tags", "sum"), last_edit=("last_edit", "max"))
    combined["mean_tags"] = combined["sum_tags"] / combined["n_objects"]
    return combined.reset_index()


def run_pandas_parquet() -> pd.DataFrame:
    """pandas + Parquet: читаем только 5 нужных столбцов из 24 (колоночный формат)."""
    df = pd.read_parquet(config.FEATURES_REGION_DIR, columns=NEEDED)
    out = df.groupby(KEYS, observed=True).agg(
        n_objects=("n_tags", "size"), n_named=("name", "count"),
        mean_tags=("n_tags", "mean"), last_edit=("timestamp", "max"))
    return out.reset_index()


def run_polars_lazy() -> pd.DataFrame:
    """Polars: ленивый план + потоковое выполнение."""
    import polars as pl
    result = (pl.scan_parquet(PARQUET_GLOB, hive_partitioning=True)
              .group_by(KEYS)
              .agg(pl.len().alias("n_objects"),
                   pl.col("name").is_not_null().sum().alias("n_named"),
                   pl.col("n_tags").mean().alias("mean_tags"),
                   pl.col("timestamp").max().alias("last_edit"))
              .collect(engine="streaming"))
    return result.to_pandas()


def run_duckdb_sql() -> pd.DataFrame:
    """DuckDB: обычный SQL по файлам Parquet, без загрузки в базу."""
    import duckdb
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")   # без индикатора прогресса в консоли
    query = f"""
        SELECT region_iso, feature_key,
               COUNT(*)        AS n_objects,
               COUNT(name)     AS n_named,
               AVG(n_tags)     AS mean_tags,
               MAX("timestamp") AS last_edit
        FROM read_parquet('{PARQUET_GLOB.replace(chr(92), '/')}', hive_partitioning = true)
        GROUP BY region_iso, feature_key
    """
    result = con.sql(query).df()
    con.close()
    return result


# Реестр подходов: имя → (функция, описание). Словарь удобно перебирать циклом.
APPROACHES = {
    "pandas_csv": (run_pandas_csv, "Baseline: pandas + CSV целиком"),
    "pandas_csv_chunks": (run_pandas_csv_chunks, "pandas + CSV по чанкам (инкрементально)"),
    "pandas_parquet": (run_pandas_parquet, "pandas + Parquet (нужные столбцы)"),
    "polars_lazy": (run_polars_lazy, "Polars lazy + Parquet (streaming)"),
    "duckdb_sql": (run_duckdb_sql, "DuckDB SQL по Parquet"),
}


def run_single(name: str) -> dict:
    """
    Выполняет один подход в текущем процессе и возвращает метрики.
    Вызывается из дочернего процесса: python -m src.benchmark <name>
    """
    func, _ = APPROACHES[name]
    mem_before = current_memory_mb()
    start = time.perf_counter()
    result = _finish(func())
    seconds = time.perf_counter() - start
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    result.to_parquet(BENCH_DIR / f"{name}.parquet", index=False)
    return {"approach": name, "seconds": round(seconds, 3),
            "peak_mb": round(peak_memory_mb(), 1),
            "peak_delta_mb": round(peak_memory_mb() - mem_before, 1),
            "rows": len(result)}


def export_csv() -> float:
    """Один раз сохраняем копию набора в CSV — нужна для сравнения CSV и Parquet."""
    import polars as pl
    if not config.FEATURES_CSV.exists():
        log("Экспорт набора в CSV для бенчмарка ...")
        (pl.scan_parquet(PARQUET_GLOB, hive_partitioning=True)
         .select(NEEDED + ["osm_type", "osm_id", "lon", "lat", "feature_value"])
         .sink_csv(str(config.FEATURES_CSV)))
    return human_size(config.FEATURES_CSV)


def run_benchmark(repeats: int = 3) -> pd.DataFrame:
    """Запускает все подходы по repeats раз в отдельных процессах и сводит результаты."""
    csv_mb = export_csv()
    parquet_mb = human_size(config.FEATURES_REGION_DIR)
    records = []
    for name, (_, description) in APPROACHES.items():
        runs = []
        for attempt in range(repeats):
            proc = subprocess.run([sys.executable, "-m", "src.benchmark", name],
                                  cwd=config.ROOT, capture_output=True, text=True,
                                  encoding="utf-8")
            if proc.returncode != 0:
                log(f"Ошибка в подходе {name}: {proc.stderr[-500:]}")
                break
            runs.append(json.loads(proc.stdout.strip().splitlines()[-1]))
        if not runs:
            continue
        records.append({
            "approach": name,
            "description": description,
            "median_seconds": round(statistics.median(r["seconds"] for r in runs), 2),
            "peak_mb": round(max(r["peak_mb"] for r in runs), 0),
            "peak_delta_mb": round(max(r["peak_delta_mb"] for r in runs), 0),
            "input_format": "CSV" if "csv" in name else "Parquet",
            "input_size_mb": round(csv_mb if "csv" in name else parquet_mb, 1),
        })
        log(f"  {name}: {records[-1]['median_seconds']} с, пик {records[-1]['peak_mb']} МБ")

    table = pd.DataFrame(records)
    # Сверка результатов: всё сравниваем с подходом pandas_parquet
    reference = pd.read_parquet(BENCH_DIR / "pandas_parquet.parquet")
    matches = []
    for name in table["approach"]:
        other = pd.read_parquet(BENCH_DIR / f"{name}.parquet")
        same = (len(other) == len(reference) and
                other[KEYS + ["n_objects", "n_named"]].equals(reference[KEYS + ["n_objects", "n_named"]]) and
                ((other["mean_tags"] - reference["mean_tags"]).abs() < 1e-6).all() and
                (other["last_edit"] == reference["last_edit"]).all())
        matches.append(bool(same))
    table["result_matches_reference"] = matches
    baseline_time = table.loc[table["approach"] == "pandas_csv", "median_seconds"]
    if len(baseline_time):
        table["speedup_vs_baseline"] = (baseline_time.iloc[0] / table["median_seconds"]).round(1)
    table.to_csv(config.TABLES_DIR / "benchmark_tools.csv", index=False)
    return table


if __name__ == "__main__":
    # Режим дочернего процесса: выполнить один подход и напечатать JSON с метриками
    if len(sys.argv) != 2 or sys.argv[1] not in APPROACHES:
        print(f"Использование: python -m src.benchmark <{'|'.join(APPROACHES)}>")
        sys.exit(1)
    print(json.dumps(run_single(sys.argv[1])))
