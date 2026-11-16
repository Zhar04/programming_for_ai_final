"""
Шаг 4. Аудит качества данных и очистка.

Что проверяем (обязательная задача Cluster 8):
  * пропуски по столбцам;
  * дубликаты — точные (один и тот же объект OSM дважды) и смысловые
    (одна и та же точка нарисована и узлом, и контуром здания рядом);
  * некорректные значения — этажность, часы работы, телефоны, сайты;
  * некорректные даты — время правки раньше основания OSM или позже снимка,
    start_date в непонятном формате или в будущем;
  * выбросы — правило IQR (межквартильный размах) для этажности и числа тегов.

Большой набор (3,2 млн объектов вместе со зданиями) проверяется через Polars
в ленивом режиме (scan_parquet) — данные читаются по частям и только нужные столбцы.
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from scipy.spatial import cKDTree

from src import config
from src.spatial import to_meters
from src.utils import log

SNAPSHOT_DATE = pd.Timestamp("2026-11-16", tz="UTC")  # дата выгрузки Geofabrik (+1 день запаса)
OSM_START = pd.Timestamp(config.OSM_PROJECT_START, tz="UTC")

# Регулярные выражения для проверки форматов
RE_DATE = re.compile(r"^(\d{4})(-\d{2}(-\d{2})?)?$")          # 1995 / 1995-05 / 1995-05-17
RE_OPENING_HOURS = re.compile(r"^[0-9A-Za-z:;,\-+ /\[\]\.\"]+$")  # латиница по стандарту OSM
RE_URL = re.compile(r"^(https?://)?(www\.)?[\w\-]+(\.[\w\-]+)+(/\S*)?$", re.IGNORECASE)


def iqr_bounds(series: pd.Series, k: float = 1.5) -> tuple[float, float]:
    """Границы выбросов по правилу IQR: [Q1 − k·IQR, Q3 + k·IQR]."""
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr


def audit_full_dataset(dataset_dir: Path = config.FEATURES_REGION_DIR) -> dict:
    """
    Аудит всех 3,2 млн объектов через Polars LazyFrame.
    Ничего не вычисляется, пока не вызван .collect() — Polars сам оптимизирует план
    (читает только нужные столбцы, может обрабатывать данные потоково).
    """
    lf = pl.scan_parquet(str(dataset_dir / "**" / "*.parquet"), hive_partitioning=True)

    total = lf.select(pl.len()).collect().item()

    # Пропуски: доля null в каждом столбце — одним проходом
    columns = [c for c in lf.collect_schema().names() if c not in ("region_iso",)]
    nulls = lf.select([pl.col(c).null_count().alias(c) for c in columns]).collect()
    missing = (nulls.transpose(include_header=True, header_name="column",
                               column_names=["null_count"])
               .with_columns((pl.col("null_count") / total * 100).round(2).alias("null_pct"))
               .sort("null_pct", descending=True))

    # Точные дубликаты: один и тот же (osm_type, osm_id) встречается больше 1 раза
    exact_dups = (lf.group_by(["osm_type", "osm_id"]).len()
                  .filter(pl.col("len") > 1).select(pl.len()).collect().item())

    # Даты правок: раньше основания OSM или позже даты снимка
    ts = lf.select(
        (pl.col("timestamp") < OSM_START).sum().alias("before_osm_start"),
        (pl.col("timestamp") > SNAPSHOT_DATE).sum().alias("after_snapshot"),
        pl.col("timestamp").min().alias("min_ts"),
        pl.col("timestamp").max().alias("max_ts"),
    ).collect().to_dicts()[0]

    # Этажность: строка → число; нечисловые, <=0 и >100 этажей считаем некорректными
    levels = (lf.filter(pl.col("building_levels").is_not_null())
              .select(pl.col("building_levels"),
                      pl.col("building_levels").str.strip_chars()
                      .cast(pl.Float64, strict=False).alias("levels_num"))
              .collect())
    lv_num = levels["levels_num"]
    levels_report = {
        "filled": levels.height,
        "not_numeric": int(lv_num.is_null().sum()),
        "non_positive": int((lv_num <= 0).sum()),
        # самое высокое здание РК (Abu Dhabi Plaza, Астана) — 75 этажей; выше 80 — ошибка
        "above_80": int((lv_num > 80).sum()),
    }
    valid_levels = lv_num.drop_nulls().filter((lv_num.drop_nulls() > 0) &
                                              (lv_num.drop_nulls() <= 80)).to_pandas()
    low, high = iqr_bounds(valid_levels)
    levels_report["iqr_low"], levels_report["iqr_high"] = float(low), float(high)
    if high - low == 0:
        # Q1 = Q3 (большинство зданий одноэтажные) → правило IQR вырождено,
        # поэтому выбросами считаем значения выше 99-го перцентиля
        high = float(valid_levels.quantile(0.99))
        levels_report["outlier_rule"] = f"IQR=0 → порог P99 = {high:.0f} этажей"
    else:
        levels_report["outlier_rule"] = f"IQR: > {high:.1f} этажей"
    levels_report["outliers"] = int((valid_levels > high).sum())
    levels_report["quantiles"] = {f"p{int(q * 100)}": float(valid_levels.quantile(q))
                                  for q in (0.5, 0.9, 0.99)}
    levels_report["max"] = float(valid_levels.max())

    # start_date: проверяем формат ГГГГ[-ММ[-ДД]] и что дата не в будущем
    sd = (lf.filter(pl.col("start_date").is_not_null()).select("start_date").collect()
          .to_series().to_pandas())
    sd_format_ok = sd.str.strip().str.match(RE_DATE)
    sd_year = pd.to_numeric(sd.str.slice(0, 4), errors="coerce")
    start_date_report = {
        "filled": int(len(sd)),
        "bad_format": int((~sd_format_ok).sum()),
        "future_year": int((sd_format_ok & (sd_year > SNAPSHOT_DATE.year)).sum()),
        "examples_bad": sd[~sd_format_ok].value_counts().head(8).to_dict(),
    }

    outside = lf.filter(pl.col("region_iso") == "OUT").select(pl.len()).collect().item()

    report = {
        "rows_total": total,
        "rows_outside_kz": outside,
        "exact_duplicates": exact_dups,
        "timestamps": ts,
        "building_levels": levels_report,
        "start_date": start_date_report,
    }
    missing.write_csv(config.TABLES_DIR / "audit_missing_full.csv")
    log(f"Аудит полного набора: {total:,} строк, вне РК {outside:,}, "
        f"точных дублей {exact_dups}")
    return report


def load_pois(dataset_dir: Path = config.FEATURES_REGION_DIR) -> pd.DataFrame:
    """
    Загружает только POI (без зданий) внутри Казахстана.
    Фильтр выполняется при чтении (predicate pushdown) — в pandas попадает ~150 тыс. строк,
    а не 3,2 млн.
    """
    lf = (pl.scan_parquet(str(dataset_dir / "**" / "*.parquet"), hive_partitioning=True)
          .filter((pl.col("feature_key") != "building") & (pl.col("region_iso") != "OUT")))
    pois = lf.collect().to_pandas()
    log(f"Загружено POI: {len(pois):,}")
    return pois


def valid_opening_hours(value) -> bool:
    """Часы работы по стандарту OSM пишутся латиницей: 'Mo-Fr 09:00-18:00', '24/7'."""
    if value is None or pd.isna(value):
        return False
    text = str(value).strip()
    return bool(RE_OPENING_HOURS.match(text)) and (any(ch.isdigit() for ch in text) or
                                                   text in ("off", "closed"))


def valid_phone(value) -> bool:
    """Телефон корректен, если каждый номер (через ';') содержит 10–12 цифр."""
    if value is None or pd.isna(value):
        return False
    for part in str(value).split(";"):
        digits = re.sub(r"\D", "", part)
        if not 10 <= len(digits) <= 12:
            return False
    return True


def valid_website(value) -> bool:
    """Сайт корректен, если похож на URL/домен."""
    if value is None or pd.isna(value):
        return False
    return bool(RE_URL.match(str(value).strip().split(";")[0]))


def find_semantic_duplicates(pois: pd.DataFrame, radius_m: float = 50.0) -> pd.Index:
    """
    Смысловые дубликаты: два объекта с одинаковым значением тега и одинаковым названием,
    стоящие ближе radius_m метров (типично: точка-кафе внутри контура здания-кафе).
    Ищем соседей через KD-дерево (cKDTree.query_pairs) — это O(n log n), а не O(n²).
    Из пары удаляем объект с меньшим числом тегов (менее подробный).
    """
    named = pois[pois["name"].notna()].copy()
    named["name_norm"] = named["name"].str.lower().str.strip()
    xy = to_meters(named["lon"].to_numpy(), named["lat"].to_numpy())
    pairs = cKDTree(xy).query_pairs(r=radius_m, output_type="ndarray")
    if len(pairs) == 0:
        return pd.Index([])
    a, b = pairs[:, 0], pairs[:, 1]
    same = ((named["feature_value"].to_numpy()[a] == named["feature_value"].to_numpy()[b]) &
            (named["name_norm"].to_numpy()[a] == named["name_norm"].to_numpy()[b]))
    a, b = a[same], b[same]
    tags = named["n_tags"].to_numpy()
    # удаляем того, у кого тегов меньше; при равенстве — второй объект пары
    drop_positions = np.where(tags[a] < tags[b], a, b)
    return named.index[np.unique(drop_positions)]


def audit_and_clean_pois(pois: pd.DataFrame) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """
    Аудит POI и применение правил очистки.
    Возвращает (очищенный DataFrame, отчёт аудита, таблицу правил очистки).
    """
    report = {"rows_before": len(pois)}
    rules = []  # список словарей: правило, обоснование, сколько строк затронуто

    # --- пропуски по ключевым атрибутам
    attr_cols = ["name", "name_kk", "name_ru", "name_en", "brand", "opening_hours",
                 "phone", "website", "addr_street", "addr_housenumber", "start_date"]
    missing = (pois[attr_cols].isna().mean() * 100).round(2).sort_values(ascending=False)
    missing.rename("null_pct").to_frame().to_csv(config.TABLES_DIR / "audit_missing_pois.csv")
    report["missing_pct"] = missing.to_dict()

    # --- правило 1: точные дубликаты (osm_type, osm_id)
    exact = pois.duplicated(subset=["osm_type", "osm_id"])
    rules.append({"rule": "Удалить точные дубликаты (osm_type, osm_id)",
                  "reason": "один объект OSM не может учитываться дважды",
                  "rows": int(exact.sum()), "action": "удаление"})
    pois = pois[~exact]

    # --- правило 2: пустые/служебные значения тега (amenity=yes, shop=no и т.п.)
    bad_value = pois["feature_value"].str.lower().isin(["yes", "no", "none", "unknown", ""])
    rules.append({"rule": "Удалить объекты со значением тега yes/no/unknown",
                  "reason": "тип объекта не определён — нельзя отнести к категории",
                  "rows": int(bad_value.sum()), "action": "удаление"})
    pois = pois[~bad_value]

    # --- правило 3: смысловые дубликаты (одинаковые тип+название ближе 50 м)
    dup_index = find_semantic_duplicates(pois)
    rules.append({"rule": "Удалить смысловые дубликаты: тот же тип и название ближе 50 м",
                  "reason": "типичная ошибка OSM: POI отмечен и точкой, и контуром здания",
                  "rows": int(len(dup_index)), "action": "удаление (остаётся более подробный)"})
    pois = pois.drop(index=dup_index)

    # --- правило 4: даты правок вне допустимого диапазона
    bad_ts = (pois["timestamp"] < OSM_START) | (pois["timestamp"] > SNAPSHOT_DATE)
    rules.append({"rule": "Время правки раньше 2004-08-09 или позже даты снимка → пропуск",
                  "reason": "OSM основан в 2004 г.; будущие даты невозможны",
                  "rows": int(bad_ts.sum()), "action": "замена на NaT"})
    pois.loc[bad_ts, "timestamp"] = pd.NaT

    # --- правило 5: start_date в неверном формате или в будущем
    sd = pois["start_date"].astype("string").str.strip()
    sd_ok = sd.str.match(RE_DATE).fillna(False).astype(bool)
    sd_year = pd.to_numeric(sd.str.slice(0, 4), errors="coerce")
    sd_bad = sd.notna() & (~sd_ok | (sd_year > SNAPSHOT_DATE.year))
    rules.append({"rule": "start_date не в формате ГГГГ[-ММ[-ДД]] или в будущем → пропуск",
                  "reason": "дату нельзя однозначно интерпретировать",
                  "rows": int(sd_bad.sum()), "action": "замена на NaN"})
    pois["start_year"] = sd_year.where(~sd_bad)

    # --- правило 6: некорректные часы работы / телефоны / сайты — только флаг
    pois["oh_valid"] = pois["opening_hours"].map(valid_opening_hours)
    pois["phone_valid"] = pois["phone"].map(valid_phone)
    pois["website_valid"] = pois["website"].map(valid_website)
    for col, flag in [("opening_hours", "oh_valid"), ("phone", "phone_valid"),
                      ("website", "website_valid")]:
        n_bad = int((pois[col].notna() & ~pois[flag]).sum())
        rules.append({"rule": f"Некорректный формат {col} → флаг {flag}=False",
                      "reason": "объект существует, но атрибут не пригоден для анализа полноты",
                      "rows": n_bad, "action": "флаг, без удаления"})
        report[f"invalid_{col}"] = n_bad

    # --- правило 7: устаревший тег amenity=public_building не считается сервисом
    public_building = pois["feature_value"].eq("public_building")
    top_share = pois.loc[public_building, "region_iso"].astype(str).value_counts(normalize=True)
    top_region = config.REGION_SHORT_RU.get(top_share.index[0], top_share.index[0]) \
        if len(top_share) else "—"
    rules.append({"rule": "amenity=public_building → не сервис (категория urban)",
                  "reason": f"устаревший тег без типа услуги; {top_share.iloc[0]:.0%} таких "
                            f"объектов — безымянные здания в одном регионе ({top_region})"
                  if len(top_share) else "устаревший тег без типа услуги",
                  "rows": int(public_building.sum()), "action": "переклассификация"})
    report["public_building_top_region"] = top_region
    report["public_building_top_share"] = float(top_share.iloc[0]) if len(top_share) else 0.0

    # --- выбросы: число тегов (IQR) — не удаляем, это просто очень подробные объекты
    low, high = iqr_bounds(pois["n_tags"])
    n_out = int(((pois["n_tags"] < low) | (pois["n_tags"] > high)).sum())
    rules.append({"rule": f"Выбросы по числу тегов (IQR: > {high:.0f})",
                  "reason": "подробно описанные объекты — это не ошибка, оставляем",
                  "rows": n_out, "action": "без изменений"})
    report["n_tags_iqr_high"] = float(high)

    report["rows_after"] = len(pois)
    rules_df = pd.DataFrame(rules)
    rules_df.to_csv(config.TABLES_DIR / "cleaning_rules.csv", index=False)
    log(f"Очистка POI: {report['rows_before']:,} → {report['rows_after']:,} строк")
    return pois, report, rules_df
