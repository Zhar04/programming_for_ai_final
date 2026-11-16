-- =====================================================================
-- Нормализованная схема базы SQLite (kz_poi.db)
-- Справочники (regions, categories, poi_types, cities) вынесены отдельно,
-- в таблице фактов pois хранятся только внешние ключи на них.
-- =====================================================================
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS poi_clusters;
DROP TABLE IF EXISTS clustering_runs;
DROP TABLE IF EXISTS pois;
DROP TABLE IF EXISTS building_stats;
DROP TABLE IF EXISTS cities;
DROP TABLE IF EXISTS poi_types;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS regions;

-- 20 регионов РК: 17 областей + 3 города республиканского значения
CREATE TABLE regions (
    region_id    INTEGER PRIMARY KEY,
    iso_code     TEXT NOT NULL UNIQUE,          -- KZ-71 = Астана и т.д.
    name_ru      TEXT NOT NULL,
    name_kk      TEXT,
    name_en      TEXT,
    region_type  TEXT NOT NULL CHECK (region_type IN ('oblast', 'city')),
    area_km2     REAL NOT NULL,
    pop_total    INTEGER NOT NULL,              -- население на 01.01.2026 (stat.gov.kz)
    pop_urban    INTEGER NOT NULL,
    pop_rural    INTEGER NOT NULL
);

-- 12 тематических категорий POI
CREATE TABLE categories (
    category_id  INTEGER PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,          -- food, retail, ...
    name_ru      TEXT NOT NULL,
    is_service   INTEGER NOT NULL               -- 1 = сервис, 0 = элемент городской среды
);

-- Типы POI = пара тегов OSM (ключ, значение) → категория
CREATE TABLE poi_types (
    type_id      INTEGER PRIMARY KEY,
    osm_key      TEXT NOT NULL,                 -- amenity, shop, ...
    osm_value    TEXT NOT NULL,                 -- cafe, supermarket, ...
    category_id  INTEGER NOT NULL REFERENCES categories(category_id),
    UNIQUE (osm_key, osm_value)
);

-- Города для сравнения (Астана, Алматы, Шымкент и города ≥100 тыс.)
CREATE TABLE cities (
    city_id            INTEGER PRIMARY KEY,
    name               TEXT NOT NULL,               -- название в OSM (обычно на казахском)
    name_ru            TEXT,
    name_en            TEXT,
    region_id          INTEGER NOT NULL REFERENCES regions(region_id),
    city_group         TEXT NOT NULL,
    population         INTEGER NOT NULL,
    population_source  TEXT NOT NULL,
    area_km2           REAL NOT NULL
);

-- Таблица фактов: очищенные точки интереса
CREATE TABLE pois (
    poi_id             INTEGER PRIMARY KEY,
    osm_type           TEXT NOT NULL CHECK (osm_type IN ('node', 'way')),
    osm_id             INTEGER NOT NULL,
    type_id            INTEGER NOT NULL REFERENCES poi_types(type_id),
    region_id          INTEGER NOT NULL REFERENCES regions(region_id),
    city_id            INTEGER REFERENCES cities(city_id),   -- NULL, если вне городов списка
    name               TEXT,
    name_kk            TEXT,
    name_ru            TEXT,
    brand              TEXT,
    lon                REAL NOT NULL,
    lat                REAL NOT NULL,
    has_opening_hours  INTEGER NOT NULL,        -- 1, если часы работы заполнены корректно
    has_phone          INTEGER NOT NULL,
    has_website        INTEGER NOT NULL,
    name_script        TEXT,                    -- kazakh / cyrillic / latin / other
    last_edit          TEXT,                    -- дата последней правки (ISO 8601)
    version            INTEGER
);

-- Агрегаты по зданиям (3 млн зданий в БД не грузим — только итоги по регионам)
CREATE TABLE building_stats (
    region_id      INTEGER PRIMARY KEY REFERENCES regions(region_id),
    n_buildings    INTEGER NOT NULL,
    n_with_levels  INTEGER NOT NULL
);

-- Запуски кластеризации (baseline, DBSCAN, HDBSCAN) и их метрики
CREATE TABLE clustering_runs (
    run_id                INTEGER PRIMARY KEY,
    method                TEXT NOT NULL,
    params                TEXT NOT NULL,
    n_clusters            INTEGER,
    noise_share           REAL,
    silhouette            REAL,
    davies_bouldin        REAL,
    settlement_precision  REAL,
    settlement_recall     REAL,
    settlement_f1         REAL,
    seconds               REAL,
    peak_mb               REAL
);

-- Метка кластера для каждой POI в каждом запуске (связь "многие-ко-многим")
CREATE TABLE poi_clusters (
    poi_id         INTEGER NOT NULL REFERENCES pois(poi_id),
    run_id         INTEGER NOT NULL REFERENCES clustering_runs(run_id),
    cluster_label  INTEGER NOT NULL,            -- -1 = шум
    PRIMARY KEY (poi_id, run_id)
);

CREATE INDEX idx_pois_region ON pois(region_id);
CREATE INDEX idx_pois_type   ON pois(type_id);
CREATE INDEX idx_pois_city   ON pois(city_id);
CREATE INDEX idx_pois_name   ON pois(name);
