"""
Конфигурация проекта: пути к файлам, константы и справочники.

Все остальные модули импортируют настройки отсюда, поэтому "магические"
значения (пути, размеры чанков, ключи тегов OSM) не размазаны по коду.
"""
from pathlib import Path

# ---------------------------------------------------------------------------
# Пути. ROOT — корень репозитория (папка, где лежат main.py и README.md)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"              # исходный PBF (в git не кладём — 216 МБ)
EXTERNAL_DIR = DATA_DIR / "external"    # внешние данные (население stat.gov.kz)
INTERIM_DIR = DATA_DIR / "interim"      # промежуточные данные (большие, в git не кладём)
PROCESSED_DIR = DATA_DIR / "processed"  # очищенные данные и итоговые агрегаты

OUTPUTS_DIR = ROOT / "outputs"
FIG_DIR = OUTPUTS_DIR / "figures"       # графики PNG и интерактивные HTML
TABLES_DIR = OUTPUTS_DIR / "tables"     # таблицы CSV (результаты SQL, аудит и т.д.)
METRICS_DIR = OUTPUTS_DIR / "metrics"   # JSON с метриками (время, память, качество)
SQL_DIR = ROOT / "sql"

# ---------------------------------------------------------------------------
# Источник данных — выгрузка OpenStreetMap по Казахстану от Geofabrik
# ---------------------------------------------------------------------------
PBF_URL = "https://download.geofabrik.de/asia/kazakhstan-latest.osm.pbf"
PBF_PATH = RAW_DIR / "kazakhstan-latest.osm.pbf"

# Официальная численность населения на 1 января 2026 г. (Бюро национальной статистики)
POPULATION_XLSX = EXTERNAL_DIR / "stat_gov_kz_population_by_region_2026-01-01.xlsx"
POPULATION_SOURCE = (
    "https://stat.gov.kz/ru/industries/social-statistics/demography/publications/475780/"
)

# ---------------------------------------------------------------------------
# Промежуточные и итоговые файлы
# ---------------------------------------------------------------------------
FEATURES_DIR = INTERIM_DIR / "osm_features"          # сырые объекты, Parquet с партициями по ключу
FEATURES_REGION_DIR = INTERIM_DIR / "features_by_region"  # те же объекты + регион, партиции по региону
FEATURES_CSV = INTERIM_DIR / "features_by_region.csv"     # CSV-копия только для бенчмарка CSV vs Parquet
# Границы и населённые пункты небольшие (~3 МБ), поэтому лежат в processed и попадают в git:
# шаги database / clustering / hypotheses / visualize работают сразу после клонирования
BOUNDARIES_PATH = PROCESSED_DIR / "boundaries.parquet"    # полигоны регионов и городов (WKB)
PLACES_PATH = PROCESSED_DIR / "places.parquet"            # точки населённых пунктов (city/town/village)
K_DISTANCE_PATH = PROCESSED_DIR / "k_distance.npy"        # расстояния до 10-го соседа (выбор eps)

REGIONS_GEOJSON = PROCESSED_DIR / "regions_kz.geojson"    # упрощённые границы для карт
POIS_CLEAN_PATH = PROCESSED_DIR / "pois_clean.parquet"    # очищенные POI (основной набор анализа)
REGION_STATS_PATH = PROCESSED_DIR / "region_stats.parquet"
CITY_STATS_PATH = PROCESSED_DIR / "city_stats.parquet"
CLUSTERS_PATH = PROCESSED_DIR / "poi_clusters.parquet"
DB_PATH = PROCESSED_DIR / "kz_poi.db"                     # база SQLite
RUN_STATE_PATH = OUTPUTS_DIR / "run_state.json"           # состояние программы (какие шаги выполнены)

# ---------------------------------------------------------------------------
# Параметры обработки
# ---------------------------------------------------------------------------
CHUNK_SIZE = 200_000      # сколько объектов держим в памяти перед сбросом чанка в Parquet
BATCH_SIZE = 500_000      # размер батча при потоковом чтении Parquet
RANDOM_STATE = 42         # фиксируем случайность для воспроизводимости

# Проекция "равновеликая коническая Альберса" под территорию Казахстана:
# в ней координаты в метрах, поэтому можно корректно считать площади и расстояния.
KZ_EQUAL_AREA_CRS = (
    "+proj=aea +lat_0=48 +lon_0=68 +lat_1=44 +lat_2=52 "
    "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
)

# ---------------------------------------------------------------------------
# Какие теги OSM считаем точками интереса (POI).
# Порядок важен: если у объекта несколько ключей (например amenity и shop),
# основным считается тот, что стоит раньше в списке.
# ---------------------------------------------------------------------------
POI_KEYS = [
    "amenity", "shop", "healthcare", "tourism", "leisure",
    "office", "craft", "historic", "sport", "emergency",
]
# Здания извлекаем дополнительно: они дают объём данных (~3 млн строк)
# и служат индикатором "полноты картирования" региона.
EXTRA_KEYS = ["building"]
EXTRACT_KEYS = POI_KEYS + EXTRA_KEYS

# Дата снимка данных (из описания выгрузки Geofabrik) — даты правок позже неё некорректны
OSM_PROJECT_START = "2004-08-09"  # дата основания проекта OpenStreetMap

# Три города республиканского значения — сравниваем их между собой и с остальными
MEGACITIES = {"KZ-71": "Астана", "KZ-75": "Алматы", "KZ-79": "Шымкент"}

# Соответствие названий регионов в таблице stat.gov.kz и кодов ISO 3166-2 в OSM
STAT_NAME_TO_ISO = {
    "Абай": "KZ-10",
    "Акмолинская": "KZ-11",
    "Актюбинская": "KZ-15",
    "Алматинская": "KZ-19",
    "Атырауская": "KZ-23",
    "Западно-Казахстанская": "KZ-27",
    "Жамбылская": "KZ-31",
    "Жетісу": "KZ-33",
    "Карагандинская": "KZ-35",
    "Костанайская": "KZ-39",
    "Кызылординская": "KZ-43",
    "Мангистауская": "KZ-47",
    "Павлодарская": "KZ-55",
    "Северо-Казахстанская": "KZ-59",
    "Туркестанская": "KZ-61",
    "Ұлытау": "KZ-62",
    "Восточно-Казахстанская": "KZ-63",
    "г. Астана": "KZ-71",
    "г. Алматы": "KZ-75",
    "г. Шымкент": "KZ-79",
}

# Короткие русские названия регионов для подписей на графиках
REGION_SHORT_RU = {
    "KZ-10": "Абай", "KZ-11": "Акмолинская", "KZ-15": "Актюбинская",
    "KZ-19": "Алматинская", "KZ-23": "Атырауская", "KZ-27": "Западно-Казахстанская",
    "KZ-31": "Жамбылская", "KZ-33": "Жетісу", "KZ-35": "Карагандинская",
    "KZ-39": "Костанайская", "KZ-43": "Кызылординская", "KZ-47": "Мангистауская",
    "KZ-55": "Павлодарская", "KZ-59": "Северо-Казахстанская", "KZ-61": "Туркестанская",
    "KZ-62": "Ұлытау", "KZ-63": "Восточно-Казахстанская",
    "KZ-71": "г. Астана", "KZ-75": "г. Алматы", "KZ-79": "г. Шымкент",
}

# Минимальная численность (по тегу population в OSM), чтобы город попал в сравнение
CITY_MIN_POPULATION = 100_000


def ensure_dirs() -> None:
    """Создаёт все рабочие папки, если их ещё нет (os.makedirs с exist_ok)."""
    for folder in [RAW_DIR, EXTERNAL_DIR, INTERIM_DIR, PROCESSED_DIR,
                   FIG_DIR, TABLES_DIR, METRICS_DIR]:
        folder.mkdir(parents=True, exist_ok=True)
