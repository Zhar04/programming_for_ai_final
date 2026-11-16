"""
Шаг 7. Подготовка итогового набора POI и расчёт показателей:
  * POI на 100 тыс. жителей и на 1000 км² по 20 регионам;
  * сравнение Астана / Алматы / Шымкент / другие крупные города;
  * структура категорий по регионам.
"""
import re

import geopandas as gpd
import numpy as np
import pandas as pd

from src import config, quality, spatial
from src.categories import categorize, CATEGORY_NAMES_RU, SERVICE_CATEGORIES
from src.optimize import optimize_dtypes, to_naive_dtypes
from src.utils import log, df_memory_mb

KAZAKH_LETTERS = re.compile(r"[әғқңөұүһіӘҒҚҢӨҰҮҺІ]")  # буквы, которых нет в русском алфавите
CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")
LATIN = re.compile(r"[a-zA-Z]")


def name_script(name) -> str | None:
    """
    Определяет "язык" названия по алфавиту:
      kazakh   — есть специфические казахские буквы (ә, ғ, қ, ң, ө, ұ, ү, һ, і);
      cyrillic — кириллица без казахских букв (обычно русский);
      latin    — латиница (бренды, английские названия).
    """
    if name is None or pd.isna(name):
        return None
    text = str(name)
    if KAZAKH_LETTERS.search(text):
        return "kazakh"
    elif CYRILLIC.search(text):
        return "cyrillic"
    elif LATIN.search(text):
        return "latin"
    else:
        return "other"


def prepare_pois(regions: gpd.GeoDataFrame, cities: gpd.GeoDataFrame) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """
    Загружает POI, присваивает категории и города, проводит аудит/очистку,
    оптимизирует типы и сохраняет итог в data/processed/pois_clean.parquet.
    """
    pois = quality.load_pois()
    pois["feature_key"] = pois["feature_key"].astype(str)
    pois["region_iso"] = pois["region_iso"].astype(str)
    # тематическая категория по паре (ключ, значение)
    pois["category"] = [categorize(k, v) for k, v in zip(pois["feature_key"], pois["feature_value"])]

    clean, report, rules = quality.audit_and_clean_pois(pois)

    clean["is_service"] = clean["category"].isin(SERVICE_CATEGORIES)
    clean["has_name"] = clean["name"].notna()
    clean["name_script"] = clean["name"].map(name_script)
    clean["edit_year"] = clean["timestamp"].dt.year
    clean["city_id"] = spatial.assign_cities(clean, cities)
    clean = clean.reset_index(drop=True)
    clean.insert(0, "poi_id", np.arange(1, len(clean) + 1))

    # замер памяти до и после оптимизации типов на итоговом наборе POI
    before = df_memory_mb(clean.apply(to_naive_dtypes))
    clean = optimize_dtypes(clean, keep_float64=("lon", "lat"))
    after = df_memory_mb(clean)
    report["memory_mb_before"], report["memory_mb_after"] = round(before, 1), round(after, 1)
    log(f"Память набора POI: {before:.1f} МБ → {after:.1f} МБ")

    clean.to_parquet(config.POIS_CLEAN_PATH, index=False)
    return clean, report, rules


def region_stats(pois: pd.DataFrame, regions: gpd.GeoDataFrame,
                 raw_summary: pd.DataFrame) -> pd.DataFrame:
    """Сводная таблица по 20 регионам — главный результат проекта."""
    service = pois[pois["is_service"]]
    grouped = service.groupby("region_iso", observed=True)
    stats = pd.DataFrame({
        "n_service_poi": grouped.size(),
        "named_share": grouped["has_name"].mean(),
        "opening_hours_share": grouped["oh_valid"].mean(),
        "phone_share": grouped["phone_valid"].mean(),
        "website_share": grouped["website_valid"].mean(),
        "kazakh_name_share": grouped["name_script"].apply(
            lambda s: (s == "kazakh").sum() / max(s.notna().sum(), 1)),
    })
    stats["n_all_poi"] = pois.groupby("region_iso", observed=True).size()
    buildings = raw_summary[raw_summary["is_building"]].set_index("region_iso")["n_objects"]
    stats["n_buildings"] = buildings
    stats = stats.reset_index().rename(columns={"index": "region_iso"})

    base = pd.DataFrame(regions.drop(columns="geometry"))
    out = base.merge(stats, left_on="iso_code", right_on="region_iso", how="left")
    out["poi_per_100k"] = out["n_service_poi"] / out["pop_total"] * 1e5
    out["poi_per_1000km2"] = out["n_service_poi"] / out["area_km2"] * 1000
    out["buildings_per_100k"] = out["n_buildings"] / out["pop_total"] * 1e5
    out = out.drop(columns=["region_iso"]).sort_values("poi_per_100k", ascending=False)
    out.to_parquet(config.REGION_STATS_PATH, index=False)
    out.to_csv(config.TABLES_DIR / "region_stats.csv", index=False)
    return out.reset_index(drop=True)


def city_stats(pois: pd.DataFrame, cities: gpd.GeoDataFrame) -> pd.DataFrame:
    """Показатели по городам (Астана, Алматы, Шымкент и города ≥100 тыс.)."""
    service = pois[pois["is_service"] & pois["city_id"].notna()]
    grouped = service.groupby("city_id")
    stats = pd.DataFrame({
        "n_service_poi": grouped.size(),
        "named_share": grouped["has_name"].mean(),
        "opening_hours_share": grouped["oh_valid"].mean(),
        "food_share": grouped["category"].apply(lambda s: (s == "food").mean()),
        "retail_share": grouped["category"].apply(lambda s: (s == "retail").mean()),
    }).reset_index()
    base = pd.DataFrame(cities.drop(columns="geometry"))
    out = base.merge(stats, on="city_id", how="left")
    out["poi_per_100k"] = out["n_service_poi"] / out["population"] * 1e5
    out["poi_per_km2"] = out["n_service_poi"] / out["area_km2"]
    out = out.sort_values("poi_per_100k", ascending=False).reset_index(drop=True)
    out.to_parquet(config.CITY_STATS_PATH, index=False)
    out.to_csv(config.TABLES_DIR / "city_stats.csv", index=False)
    return out


def category_matrix(pois: pd.DataFrame, regions: gpd.GeoDataFrame,
                    per_100k: bool = True) -> pd.DataFrame:
    """Матрица регион × категория: число POI на 100 тыс. жителей (или доли)."""
    service = pois[pois["is_service"]]
    table = pd.crosstab(service["region_iso"].astype(str), service["category"].astype(str))
    table = table[[c for c in SERVICE_CATEGORIES if c in table.columns]]
    pop = regions.set_index("iso_code")["pop_total"]
    if per_100k:
        table = table.div(pop.reindex(table.index), axis=0) * 1e5
    else:
        table = table.div(table.sum(axis=1), axis=0)
    table.index = [config.REGION_SHORT_RU[i] for i in table.index]
    table.columns = [CATEGORY_NAMES_RU[c] for c in table.columns]
    return table


def megacity_comparison(pois: pd.DataFrame, cities: pd.DataFrame,
                        total_population: int) -> pd.DataFrame:
    """
    Астана vs Алматы vs Шымкент vs "другие города ≥100 тыс." (вместе) vs остальная страна:
    POI на 100 тыс. по каждой категории.
    """
    city_group = cities.set_index("city_id")["city_group"]
    service = pois[pois["is_service"]].copy()
    service["group"] = service["city_id"].map(city_group).fillna("Остальная территория")
    population = cities.groupby("city_group")["population"].sum()
    population["Остальная территория"] = total_population - population.sum()
    table = pd.crosstab(service["group"], service["category"].astype(str))
    table = table.div(population.reindex(table.index), axis=0) * 1e5
    table["Все категории"] = table.sum(axis=1)
    order = ["Астана", "Алматы", "Шымкент", "Другие города ≥100 тыс.", "Остальная территория"]
    table = table.reindex(order)
    table.columns = [CATEGORY_NAMES_RU.get(c, c) for c in table.columns]
    table.round(1).to_csv(config.TABLES_DIR / "megacity_comparison.csv")
    return table
