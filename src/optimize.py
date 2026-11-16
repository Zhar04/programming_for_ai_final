"""
Шаг 3. Оптимизация типов данных с замером памяти "до" и "после".

"До" — так, как типы получились бы при наивной загрузке (например, read_csv без
параметров): все строки — object, целые — int64, дробные — float64.
"После" — оптимизированные типы:
  * category — для строк с небольшим числом уникальных значений
    (osm_type, feature_key, feature_value, building, region_iso ...);
  * downcast целых: int64 → int32/int16/int8, если позволяет диапазон;
  * float64 → float32 для координат (ошибка округления считается в метрах).

Чтобы не держать в памяти все 3,2 млн строк × 24 столбца сразу, память
измеряется по столбцам: читаем один столбец, меряем, освобождаем.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from src import config
from src.utils import log


def to_naive_dtypes(series: pd.Series) -> pd.Series:
    """Приводит столбец к "наивным" типам, как после read_csv по умолчанию."""
    if pd.api.types.is_datetime64_any_dtype(series) or pd.api.types.is_bool_dtype(series):
        return series
    if pd.api.types.is_integer_dtype(series):
        return series.astype("int64")
    if pd.api.types.is_float_dtype(series):
        return series.astype("float64")
    return series.astype(object)   # строки и категории → object


def optimize_series(series: pd.Series, category_ratio: float = 0.5) -> pd.Series:
    """
    Подбирает компактный тип для одного столбца.
    category_ratio — если уникальных значений меньше 50% от непустых, строку
    выгоднее хранить как category (словарь значений + коды).
    """
    if pd.api.types.is_datetime64_any_dtype(series) or pd.api.types.is_bool_dtype(series):
        return series
    elif pd.api.types.is_integer_dtype(series):
        return pd.to_numeric(series, downcast="integer")
    elif pd.api.types.is_float_dtype(series):
        return series.astype("float32")
    else:
        non_null = series.dropna()
        if len(non_null) and non_null.nunique() / len(non_null) < category_ratio:
            return series.astype("category")
        return series.astype("string[pyarrow]")   # компактное хранение строк в Arrow


def optimize_dtypes(df: pd.DataFrame, keep_float64: tuple = ()) -> pd.DataFrame:
    """Оптимизирует все столбцы DataFrame (кроме перечисленных в keep_float64)."""
    out = df.copy()
    for col in out.columns:
        if col in keep_float64:
            continue
        out[col] = optimize_series(out[col])
    return out


def measure_memory_by_columns(dataset_dir: Path = config.FEATURES_REGION_DIR) -> pd.DataFrame:
    """
    Замер памяти по каждому столбцу полного набора (3,2 млн строк) до/после оптимизации.
    Возвращает таблицу: столбец, тип до, тип после, МБ до, МБ после, экономия %.
    """
    dataset = ds.dataset(str(dataset_dir), format="parquet", partitioning="hive")
    rows = []
    for col in dataset.schema.names:
        series = dataset.to_table(columns=[col]).column(0).to_pandas()
        naive = to_naive_dtypes(series)
        optimized = optimize_series(naive)
        before = naive.memory_usage(deep=True, index=False) / 1024 ** 2
        after = optimized.memory_usage(deep=True, index=False) / 1024 ** 2
        rows.append({
            "column": col,
            "dtype_before": str(naive.dtype),
            "dtype_after": str(optimized.dtype),
            "mb_before": round(before, 2),
            "mb_after": round(after, 2),
        })
        del series, naive, optimized          # освобождаем память перед следующим столбцом
    table = pd.DataFrame(rows)
    table["saving_pct"] = (100 * (1 - table["mb_after"] / table["mb_before"])).round(1)
    total = pd.DataFrame([{
        "column": "ИТОГО", "dtype_before": "", "dtype_after": "",
        "mb_before": round(table["mb_before"].sum(), 1),
        "mb_after": round(table["mb_after"].sum(), 1),
        "saving_pct": round(100 * (1 - table["mb_after"].sum() / table["mb_before"].sum()), 1),
    }])
    table = pd.concat([table, total], ignore_index=True)
    table.to_csv(config.TABLES_DIR / "memory_optimization.csv", index=False)
    log(f"Память полного набора: {total['mb_before'][0]} МБ → {total['mb_after'][0]} МБ "
        f"(экономия {total['saving_pct'][0]}%)")
    return table


def float32_error_meters(dataset_dir: Path = config.FEATURES_REGION_DIR) -> float:
    """
    Насколько теряем в точности, храня координаты во float32.
    Возвращает максимальную ошибку в метрах (1° широты ≈ 111 км).
    """
    dataset = ds.dataset(str(dataset_dir), format="parquet", partitioning="hive")
    coords = dataset.to_table(columns=["lon", "lat"]).to_pandas()
    err_lat = np.abs(coords["lat"] - coords["lat"].astype("float32").astype("float64")).max()
    err_lon = np.abs(coords["lon"] - coords["lon"].astype("float32").astype("float64")).max()
    # для долготы метры на градус меньше (cos широты), берём худший случай — экватор
    return float(max(err_lat, err_lon) * 111_320)
