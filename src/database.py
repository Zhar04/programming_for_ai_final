"""
Шаг 8. База данных SQLite: создание нормализованной схемы, загрузка данных,
выполнение аналитических SQL-запросов и поиск POI.

Схема описана в sql/schema.sql, запросы — в sql/queries.sql.
Результаты запросов загружаются в pandas через pd.read_sql_query.
"""
import re
import sqlite3
from pathlib import Path

import pandas as pd

from src import config
from src.categories import CATEGORY_NAMES_RU, SERVICE_CATEGORIES
from src.utils import log


def connect(db_path: Path = config.DB_PATH) -> sqlite3.Connection:
    """Открывает соединение с БД и включает проверку внешних ключей."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    # Встроенный LOWER в SQLite понимает только латиницу; регистрируем Python-функцию,
    # чтобы поиск без учёта регистра работал и для кириллицы ("магнум" = "Магнум")
    conn.create_function("PYLOWER", 1, lambda s: s.lower() if isinstance(s, str) else s,
                         deterministic=True)
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Создаёт таблицы по скрипту sql/schema.sql (старые таблицы удаляются)."""
    script = (config.SQL_DIR / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(script)


def load_all(conn: sqlite3.Connection, regions, cities, pois: pd.DataFrame,
             raw_summary: pd.DataFrame) -> dict:
    """
    Заполняет таблицы. Порядок важен из-за внешних ключей:
    сначала справочники (regions, categories, poi_types, cities), затем факты (pois).
    Возвращает словарь {таблица: число строк}.
    """
    # --- regions
    reg = pd.DataFrame(regions.drop(columns="geometry")).sort_values("iso_code").reset_index(drop=True)
    reg["region_id"] = range(1, len(reg) + 1)
    reg_table = pd.DataFrame({
        "region_id": reg["region_id"], "iso_code": reg["iso_code"], "name_ru": reg["region_ru"],
        "name_kk": reg["name"], "name_en": reg["name_en"], "region_type": reg["region_type"],
        "area_km2": reg["area_km2"].round(1), "pop_total": reg["pop_total"],
        "pop_urban": reg["pop_urban"], "pop_rural": reg["pop_rural"],
    })
    reg_table.to_sql("regions", conn, if_exists="append", index=False)
    iso_to_id = dict(zip(reg_table["iso_code"], reg_table["region_id"]))

    # --- categories
    cats = pd.DataFrame({"code": list(CATEGORY_NAMES_RU)})
    cats["category_id"] = range(1, len(cats) + 1)
    cats["name_ru"] = cats["code"].map(CATEGORY_NAMES_RU)
    cats["is_service"] = cats["code"].isin(SERVICE_CATEGORIES).astype(int)
    cats[["category_id", "code", "name_ru", "is_service"]].to_sql(
        "categories", conn, if_exists="append", index=False)
    cat_to_id = dict(zip(cats["code"], cats["category_id"]))

    # --- poi_types: уникальные пары (ключ, значение)
    types = (pois[["feature_key", "feature_value", "category"]].astype(str)
             .drop_duplicates(subset=["feature_key", "feature_value"])
             .sort_values(["feature_key", "feature_value"]).reset_index(drop=True))
    types["type_id"] = range(1, len(types) + 1)
    types["category_id"] = types["category"].map(cat_to_id)
    types.rename(columns={"feature_key": "osm_key", "feature_value": "osm_value"})[
        ["type_id", "osm_key", "osm_value", "category_id"]].to_sql(
        "poi_types", conn, if_exists="append", index=False)
    type_to_id = {(k, v): i for k, v, i in zip(types["feature_key"], types["feature_value"],
                                               types["type_id"])}

    # --- cities
    city_table = pd.DataFrame(cities.drop(columns="geometry"))
    city_table["region_id"] = city_table["iso_code"].map(iso_to_id)
    city_table["area_km2"] = city_table["area_km2"].round(1)
    city_table["population"] = city_table["population"].astype(int)
    city_table[["city_id", "name", "name_ru", "name_en", "region_id", "city_group", "population",
                "population_source", "area_km2"]].to_sql("cities", conn, if_exists="append",
                                                         index=False)

    # --- pois (таблица фактов)
    fact = pd.DataFrame({
        "poi_id": pois["poi_id"].astype(int),
        "osm_type": pois["osm_type"].astype(str),
        "osm_id": pois["osm_id"],
        "type_id": [type_to_id[(k, v)] for k, v in zip(pois["feature_key"].astype(str),
                                                        pois["feature_value"].astype(str))],
        "region_id": pois["region_iso"].astype(str).map(iso_to_id),
        "city_id": pois["city_id"].astype("Int64"),
        "name": pois["name"].astype(object),
        "name_kk": pois["name_kk"].astype(object),
        "name_ru": pois["name_ru"].astype(object),
        "brand": pois["brand"].astype(object),
        "lon": pois["lon"].round(7),
        "lat": pois["lat"].round(7),
        "has_opening_hours": pois["oh_valid"].astype(int),
        "has_phone": pois["phone_valid"].astype(int),
        "has_website": pois["website_valid"].astype(int),
        "name_script": pois["name_script"].astype(object),
        "last_edit": pois["timestamp"].dt.strftime("%Y-%m-%d"),
        "version": pois["version"].astype(int),
    })
    fact.to_sql("pois", conn, if_exists="append", index=False, chunksize=20_000)

    # --- building_stats (агрегаты по зданиям)
    b = raw_summary[raw_summary["is_building"]].copy()
    b["region_id"] = b["region_iso"].astype(str).map(iso_to_id)
    b[["region_id", "n_objects", "n_with_levels"]].rename(
        columns={"n_objects": "n_buildings"}).to_sql("building_stats", conn,
                                                     if_exists="append", index=False)
    conn.commit()

    counts = {}
    for table in ["regions", "categories", "poi_types", "cities", "pois", "building_stats"]:
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    log(f"Загружено в SQLite: {counts}")
    return counts


def load_clusters(conn: sqlite3.Connection, runs: pd.DataFrame, labels: pd.DataFrame) -> None:
    """Записывает результаты кластеризации: таблицу запусков и метки POI."""
    conn.execute("DELETE FROM poi_clusters")
    conn.execute("DELETE FROM clustering_runs")
    runs.to_sql("clustering_runs", conn, if_exists="append", index=False)
    labels.to_sql("poi_clusters", conn, if_exists="append", index=False, chunksize=50_000)
    conn.commit()


def parse_queries(path: Path = config.SQL_DIR / "queries.sql") -> list[dict]:
    """
    Разбирает файл queries.sql на отдельные запросы.
    Возвращает список словарей {"name": ..., "desc": ..., "sql": ...}.
    """
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"^-- name:\s*", text, flags=re.MULTILINE)[1:]
    queries = []
    for block in blocks:
        lines = block.strip().splitlines()
        name = lines[0].strip()
        desc = ""
        if len(lines) > 1 and lines[1].startswith("-- desc:"):
            desc = lines[1].replace("-- desc:", "").strip()
        sql = "\n".join(line for line in lines[1:] if not line.startswith("--")).strip()
        queries.append({"name": name, "desc": desc, "sql": sql.rstrip(";")})
    return queries


def run_query(conn: sqlite3.Connection, name: str) -> pd.DataFrame:
    """Выполняет один запрос по имени и возвращает результат как DataFrame."""
    for query in parse_queries():
        if query["name"] == name:
            return pd.read_sql_query(query["sql"], conn)
    raise KeyError(f"Запрос {name} не найден в sql/queries.sql")


def run_all_queries(conn: sqlite3.Connection, save: bool = True) -> dict[str, pd.DataFrame]:
    """Выполняет все запросы из queries.sql, сохраняет каждый результат в CSV."""
    results = {}
    for query in parse_queries():
        try:
            df = pd.read_sql_query(query["sql"], conn)
        except (sqlite3.OperationalError, pd.errors.DatabaseError) as err:
            # например, кластеризация ещё не выполнена — таблица clustering_runs пуста
            log(f"  {query['name']}: ошибка выполнения — {err}")
            continue
        results[query["name"]] = df
        if save:
            df.to_csv(config.TABLES_DIR / f"sql_{query['name']}.csv", index=False)
        log(f"  {query['name']}: {len(df)} строк — {query['desc']}")
    return results


def search_pois(conn: sqlite3.Connection, text: str, city: str | None = None,
                category: str | None = None, limit: int = 20) -> pd.DataFrame:
    """
    Поиск POI по части названия (без учёта регистра), с необязательными фильтрами
    по городу и категории. Используются параметры "?" — это защищает от SQL-инъекций.
    """
    sql = """
        SELECT p.name, c.name_ru AS category, t.osm_value AS type,
               COALESCE(ci.name_ru, ci.name, r.name_ru) AS place, p.lat, p.lon,
               CASE p.has_opening_hours WHEN 1 THEN 'да' ELSE 'нет' END AS has_hours
        FROM pois p
        JOIN poi_types  t  ON t.type_id = p.type_id
        JOIN categories c  ON c.category_id = t.category_id
        JOIN regions    r  ON r.region_id = p.region_id
        LEFT JOIN cities ci ON ci.city_id = p.city_id
        WHERE p.name IS NOT NULL
          AND (PYLOWER(p.name) LIKE ? OR PYLOWER(p.name_ru) LIKE ? OR PYLOWER(p.name_kk) LIKE ?)
    """
    pattern = f"%{text.lower()}%"
    params: list = [pattern, pattern, pattern]
    if city:
        sql += (" AND (PYLOWER(ci.name) LIKE ? OR PYLOWER(ci.name_ru) LIKE ?"
                " OR PYLOWER(ci.name_en) LIKE ?)")
        params += [f"%{city.lower()}%"] * 3
    if category:
        sql += " AND c.code = ?"
        params.append(category)
    sql += " ORDER BY p.name LIMIT ?"
    params.append(limit)
    return pd.read_sql_query(sql, conn, params=params)
