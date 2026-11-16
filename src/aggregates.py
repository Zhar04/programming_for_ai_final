"""
Шаг 5. Основные показатели по регионам двумя способами:

  1) ленивые вычисления Polars (scan_parquet → group_by → collect):
     Polars строит план запроса и выполняет его потоково, читая только нужные столбцы;
  2) инкрементальные агрегаты по чанкам: читаем Parquet батчами по 500 тыс. строк,
     считаем частичные суммы в pandas и накапливаем их в словаре.

Оба способа должны дать одинаковый результат — это проверяется в compare_results().
"""
from pathlib import Path

import pandas as pd
import polars as pl

from src import config
from src.utils import log, iter_parquet_chunks

GROUP_COLS = ["region_iso", "is_building"]


def polars_lazy_summary(dataset_dir: Path = config.FEATURES_REGION_DIR) -> pd.DataFrame:
    """Сводка по регионам через Polars LazyFrame (ленивые вычисления)."""
    lf = (
        pl.scan_parquet(str(dataset_dir / "**" / "*.parquet"), hive_partitioning=True)
        .filter(pl.col("region_iso") != "OUT")
        .with_columns((pl.col("feature_key") == "building").alias("is_building"))
        .group_by(GROUP_COLS)
        .agg(
            pl.len().alias("n_objects"),
            pl.col("name").is_not_null().sum().alias("n_named"),
            pl.col("n_tags").sum().alias("sum_tags"),
            pl.col("building_levels").is_not_null().sum().alias("n_with_levels"),
        )
        .sort(GROUP_COLS)
    )
    # explain() показывает оптимизированный план: видно, что читаются только 5 столбцов
    plan = lf.explain()
    (config.TABLES_DIR / "polars_lazy_plan.txt").write_text(plan, encoding="utf-8")
    result = lf.collect(engine="streaming").to_pandas()
    result["mean_tags"] = result["sum_tags"] / result["n_objects"]
    return result


def chunked_summary(dataset_dir: Path = config.FEATURES_REGION_DIR,
                    batch_size: int = config.BATCH_SIZE) -> pd.DataFrame:
    """
    Та же сводка, но "вручную" — инкрементально по чанкам.
    В памяти одновременно только один батч + маленький словарь с частичными суммами.
    """
    columns = ["region_iso", "feature_key", "name", "n_tags", "building_levels"]
    totals: dict[tuple, dict] = {}   # ключ (регион, здание?) → накопленные суммы

    for chunk in iter_parquet_chunks(dataset_dir, batch_size, columns=columns):
        chunk = chunk[chunk["region_iso"] != "OUT"].copy()
        chunk["is_building"] = chunk["feature_key"] == "building"
        partial = chunk.groupby(GROUP_COLS, observed=True).agg(
            n_objects=("n_tags", "size"),
            n_named=("name", "count"),           # count считает только непустые
            sum_tags=("n_tags", "sum"),
            n_with_levels=("building_levels", "count"),
        )
        # складываем частичные результаты чанка с накопленными
        for key, row in partial.iterrows():
            acc = totals.setdefault(key, {"n_objects": 0, "n_named": 0,
                                          "sum_tags": 0, "n_with_levels": 0})
            for metric in acc:
                acc[metric] += int(row[metric])

    rows = [{"region_iso": k[0], "is_building": bool(k[1]), **v} for k, v in totals.items()]
    result = pd.DataFrame(rows).sort_values(GROUP_COLS).reset_index(drop=True)
    result["mean_tags"] = result["sum_tags"] / result["n_objects"]
    return result


def compare_results(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    """Проверяет, что две сводки совпадают (целые — точно, средние — до 1e-9)."""
    a = a.sort_values(GROUP_COLS).reset_index(drop=True)
    b = b.sort_values(GROUP_COLS).reset_index(drop=True)
    a["region_iso"], b["region_iso"] = a["region_iso"].astype(str), b["region_iso"].astype(str)
    same_keys = a[GROUP_COLS].astype(str).equals(b[GROUP_COLS].astype(str))
    same_counts = all((a[c].astype("int64") == b[c].astype("int64")).all()
                      for c in ["n_objects", "n_named", "sum_tags", "n_with_levels"])
    same_means = ((a["mean_tags"] - b["mean_tags"]).abs() < 1e-9).all()
    return bool(same_keys and same_counts and same_means)


def build_region_summary() -> tuple[pd.DataFrame, dict]:
    """Считает сводку обоими способами, сверяет и сохраняет в Parquet."""
    import time
    timings = {}
    t0 = time.perf_counter()
    lazy = polars_lazy_summary()
    timings["polars_lazy_s"] = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    chunked = chunked_summary()
    timings["pandas_chunks_s"] = round(time.perf_counter() - t0, 2)
    timings["results_match"] = compare_results(lazy, chunked)
    log(f"Сводка по регионам: Polars lazy {timings['polars_lazy_s']} с, "
        f"чанки pandas {timings['pandas_chunks_s']} с, совпадение: {timings['results_match']}")
    lazy.to_parquet(config.PROCESSED_DIR / "region_raw_summary.parquet", index=False)
    return lazy, timings
