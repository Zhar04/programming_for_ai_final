"""
Пространственная часть: регионы, население, города и привязка объектов к ним.

Используется GeoPandas: точки POI "вкладываются" в полигоны регионов через
пространственное соединение sjoin(predicate="within").
"""
import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from pyproj import Transformer

from src import config
from src.utils import log, iter_parquet_chunks

# Преобразование WGS84 (градусы) → равновеликая проекция Казахстана (метры)
_TO_METERS = Transformer.from_crs("EPSG:4326", config.KZ_EQUAL_AREA_CRS, always_xy=True)


def to_meters(lon, lat) -> np.ndarray:
    """Переводит массивы долгот/широт в метры (x, y). Нужно для DBSCAN и площадей."""
    x, y = _TO_METERS.transform(np.asarray(lon), np.asarray(lat))
    return np.column_stack([x, y])


def load_population(xlsx_path: Path = config.POPULATION_XLSX) -> pd.DataFrame:
    """
    Читает таблицу stat.gov.kz "Численность населения по регионам" (на 01.01.2026)
    и возвращает DataFrame: iso_code, region_stat, pop_urban, pop_rural, pop_total, urban_share.
    """
    try:
        raw = pd.read_excel(xlsx_path, header=None)
    except FileNotFoundError:
        raise FileNotFoundError(f"Нет файла с населением: {xlsx_path}")

    rows = []
    for _, r in raw.iterrows():
        name = str(r[0]).strip()
        if name not in config.STAT_NAME_TO_ISO:   # пропускаем заголовки и пустые строки
            continue
        # Столбцы 1–2 в таблице даны в тысячах человек → переводим в человек
        urban = float(r[1]) * 1000 if pd.notna(r[1]) else 0.0
        rural = float(r[2]) * 1000 if pd.notna(r[2]) else 0.0
        rows.append({
            "iso_code": config.STAT_NAME_TO_ISO[name],
            "region_stat": name,
            "pop_urban": int(round(urban)),
            "pop_rural": int(round(rural)),
        })
    pop = pd.DataFrame(rows)
    pop["pop_total"] = pop["pop_urban"] + pop["pop_rural"]
    pop["urban_share"] = pop["pop_urban"] / pop["pop_total"]
    if len(pop) != 20:
        raise ValueError(f"Ожидалось 20 регионов, найдено {len(pop)}")
    log(f"Население РК на 01.01.2026: {pop['pop_total'].sum():,} чел. (20 регионов)")
    return pop


def load_regions() -> gpd.GeoDataFrame:
    """
    Полигоны 20 регионов из OSM + площадь (км²) + население stat.gov.kz.
    Связь двух источников — по коду ISO 3166-2 (KZ-71 = Астана и т.д.).
    """
    areas = pd.read_parquet(config.BOUNDARIES_PATH)
    regions = areas[areas["kind"] == "region"].copy()
    regions["geometry"] = shapely.from_wkb(regions["wkb"])
    gdf = gpd.GeoDataFrame(regions.drop(columns=["wkb"]), geometry="geometry", crs="EPSG:4326")
    # площадь считаем в равновеликой проекции (в градусах площадь считать нельзя)
    gdf["area_km2"] = gdf.to_crs(config.KZ_EQUAL_AREA_CRS).area / 1e6
    gdf["region_ru"] = gdf["iso_code"].map(config.REGION_SHORT_RU)
    gdf["region_type"] = np.where(gdf["iso_code"].isin(config.MEGACITIES), "city", "oblast")
    gdf = gdf.merge(load_population(), on="iso_code", how="left")
    return gdf[["iso_code", "region_ru", "name", "name_en", "region_type", "area_km2",
                "pop_total", "pop_urban", "pop_rural", "urban_share", "osm_id", "geometry"]]


def save_regions_geojson(regions: gpd.GeoDataFrame) -> None:
    """Сохраняет упрощённые границы (допуск ~1 км) — лёгкий GeoJSON для карт Plotly/Folium."""
    light = regions[["iso_code", "region_ru", "geometry"]].copy()
    light["geometry"] = light.geometry.simplify(0.01, preserve_topology=True)
    # Plotly (библиотека d3-geo) ждёт внешние контуры ПО часовой стрелке; иначе полигон
    # трактуется как "весь земной шар минус регион" и карта заливается целиком
    light["geometry"] = light.geometry.map(_orient_clockwise)
    light.to_file(config.REGIONS_GEOJSON, driver="GeoJSON")


def _orient_clockwise(geom):
    """Ориентирует внешние кольца полигонов по часовой стрелке (sign=-1)."""
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.geometry.polygon import orient
    if isinstance(geom, Polygon):
        return orient(geom, sign=-1.0)
    elif isinstance(geom, MultiPolygon):
        return MultiPolygon([orient(part, sign=-1.0) for part in geom.geoms])
    else:
        return geom


def assign_regions_chunked(regions: gpd.GeoDataFrame,
                           in_dir: Path = config.FEATURES_DIR,
                           out_dir: Path = config.FEATURES_REGION_DIR,
                           batch_size: int = config.BATCH_SIZE) -> dict:
    """
    Чанковая привязка ~3,2 млн объектов к регионам.
    Читаем партиционированный Parquet батчами (pyarrow Scanner), для каждого батча
    делаем sjoin с полигонами и дописываем результат в новый Parquet,
    партиционированный уже по региону (region_iso=KZ-71/...).
    Объекты вне Казахстана (выгрузка Geofabrik захватывает приграничье) получают "OUT".
    """
    if out_dir.exists():
        shutil.rmtree(out_dir)
    region_shapes = regions[["iso_code", "geometry"]]
    stats = {"batches": 0, "rows": 0, "outside_kz": 0}

    for df in iter_parquet_chunks(in_dir, batch_size):
        df["feature_key"] = df["feature_key"].astype(str)
        points = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]),
                                  crs="EPSG:4326")
        joined = gpd.sjoin(points, region_shapes, how="left", predicate="within")
        # если точка попала ровно на общую границу двух регионов — оставляем первый
        joined = joined[~joined.index.duplicated(keep="first")]
        df["region_iso"] = joined["iso_code"].fillna("OUT").to_numpy()
        stats["outside_kz"] += int((df["region_iso"] == "OUT").sum())

        # combine_chunks: одна непрерывная таблица → одна row group на файл (быстрее чтение)
        table = pa.Table.from_pandas(df, preserve_index=False).combine_chunks()
        pq.write_to_dataset(table, root_path=str(out_dir), partition_cols=["region_iso"],
                            basename_template=f"batch{stats['batches']:03d}-{{i}}.parquet",
                            existing_data_behavior="overwrite_or_ignore", compression="zstd")
        stats["batches"] += 1
        stats["rows"] += len(df)
        log(f"  батч {stats['batches']}: {stats['rows']:,} строк привязано к регионам")
    return stats


def load_city_polygons(regions: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Города для сравнения "Астана vs Алматы vs другие города":
      * Астана, Алматы, Шымкент — это отдельные регионы, берём их полигоны регионов
        и официальное население stat.gov.kz;
      * остальные — полигоны place=city из OSM, население из тега population
        точки place=city (оценка OSM, указана как ограничение в отчёте).
    """
    areas = pd.read_parquet(config.BOUNDARIES_PATH)
    places = pd.read_parquet(config.PLACES_PATH)

    city_nodes = places[places["place"] == "city"].copy()
    city_nodes["population"] = pd.to_numeric(
        city_nodes["osm_population"].astype(str).str.replace(r"[\s ]", "", regex=True),
        errors="coerce")
    polys = areas[areas["kind"] == "city"].copy()
    polys["geometry"] = shapely.from_wkb(polys["wkb"])
    polys = gpd.GeoDataFrame(polys.drop(columns=["wkb"]), geometry="geometry", crs="EPSG:4326")

    # Население берём у точки place=city с тем же названием, лежащей внутри полигона
    nodes_gdf = gpd.GeoDataFrame(city_nodes, geometry=gpd.points_from_xy(city_nodes["lon"],
                                                                          city_nodes["lat"]),
                                 crs="EPSG:4326")
    matched = gpd.sjoin(nodes_gdf[["name", "name_en", "population", "geometry"]],
                        polys[["osm_id", "name", "geometry"]], predicate="within",
                        lsuffix="node", rsuffix="poly")
    matched = matched[matched["name_node"] == matched["name_poly"]]
    polys = polys.merge(matched[["osm_id", "population", "name_en"]].rename(
        columns={"name_en": "name_en_node"}), on="osm_id", how="inner")
    polys["name_en"] = polys["name_en"].fillna(polys["name_en_node"])

    # Только казахстанские города: центр полигона должен лежать внутри одного из регионов
    centers = gpd.GeoDataFrame(polys[["osm_id"]], geometry=polys.representative_point(),
                               crs="EPSG:4326")
    inside = gpd.sjoin(centers, regions[["iso_code", "geometry"]], predicate="within")
    # у полигонов городов свой столбец iso_code пустой — заменяем кодом региона
    polys = polys.drop(columns=["iso_code"]).merge(inside[["osm_id", "iso_code"]],
                                                   on="osm_id", how="inner")

    # Мегаполисы заменяем полигонами регионов (они точнее и с официальным населением)
    polys = polys[~polys["iso_code"].isin(config.MEGACITIES)]
    polys = polys[polys["population"] >= config.CITY_MIN_POPULATION]
    mega = regions[regions["iso_code"].isin(config.MEGACITIES)].copy()
    mega_rows = gpd.GeoDataFrame({
        "osm_id": mega["osm_id"],
        "name": mega["iso_code"].map(config.MEGACITIES),
        "name_ru": mega["iso_code"].map(config.MEGACITIES),
        "name_en": mega["name_en"],
        "population": mega["pop_total"],
        "iso_code": mega["iso_code"],
        "geometry": mega["geometry"],
    }, crs="EPSG:4326")
    polys["name_ru"] = polys["name_ru"].fillna(polys["name"])
    cities = pd.concat([mega_rows, polys[["osm_id", "name", "name_ru", "name_en", "population",
                                          "iso_code", "geometry"]]], ignore_index=True)
    cities = gpd.GeoDataFrame(cities, geometry="geometry", crs="EPSG:4326")
    cities["area_km2"] = cities.to_crs(config.KZ_EQUAL_AREA_CRS).area / 1e6
    cities["city_group"] = np.where(cities["iso_code"].isin(config.MEGACITIES) &
                                    cities["name"].isin(config.MEGACITIES.values()),
                                    cities["name"], "Другие города ≥100 тыс.")
    cities["population_source"] = np.where(cities["city_group"] == "Другие города ≥100 тыс.",
                                           "OSM tag population", "stat.gov.kz 01.01.2026")
    cities = cities.sort_values("population", ascending=False).reset_index(drop=True)
    cities.insert(0, "city_id", range(1, len(cities) + 1))
    log(f"Городов для сравнения: {len(cities)}")
    return cities


def assign_cities(pois: pd.DataFrame, cities: gpd.GeoDataFrame) -> pd.Series:
    """Возвращает city_id для каждой POI (или NaN, если POI вне городов из списка)."""
    points = gpd.GeoDataFrame(pois[["lon", "lat"]].copy(),
                              geometry=gpd.points_from_xy(pois["lon"], pois["lat"]),
                              crs="EPSG:4326")
    joined = gpd.sjoin(points, cities[["city_id", "geometry"]], how="left", predicate="within")
    joined = joined[~joined.index.duplicated(keep="first")]
    return joined["city_id"].reindex(pois.index)
