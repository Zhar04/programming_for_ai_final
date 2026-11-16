"""
Шаг 2. Потоковое чтение PBF и фильтрация объектов по тегам.

Почему потоково: в файле 34,5 млн узлов и 4,3 млн линий. Если загрузить всё
в DataFrame/GeoDataFrame, понадобится 5+ ГБ ОЗУ. Библиотека pyosmium (osmium)
читает файл объект за объектом, а фильтр KeyFilter отбрасывает ненужные
объекты ещё на стороне C++ — до Python доходят только ~3,2 млн подходящих.

Отобранные объекты копятся в списке-буфере и каждые CHUNK_SIZE строк
сбрасываются на диск в партиционированный Parquet (папка на каждое значение
feature_key: amenity, shop, building, ...). Так в памяти одновременно
находится не больше одного чанка.
"""
import shutil
import time
from pathlib import Path

import osmium
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src import config
from src.utils import log, peak_memory_mb, human_size

# Явная схема таблицы. Без неё чанки могли бы получить разные типы
# (например, столбец, где в чанке одни пропуски, стал бы типа null).
FEATURE_SCHEMA = pa.schema([
    ("osm_type", pa.string()),        # 'node' (точка) или 'way' (линия/полигон)
    ("osm_id", pa.int64()),
    ("lon", pa.float64()),            # долгота (для way — центр по узлам)
    ("lat", pa.float64()),            # широта
    ("feature_key", pa.string()),     # основной ключ: amenity, shop, ..., building
    ("feature_value", pa.string()),   # значение ключа: cafe, supermarket, yes, ...
    ("name", pa.string()),
    ("name_kk", pa.string()),         # название на казахском
    ("name_ru", pa.string()),         # название на русском
    ("name_en", pa.string()),
    ("brand", pa.string()),           # сеть (Magnum, Small, Kaspi ...)
    ("opening_hours", pa.string()),
    ("phone", pa.string()),
    ("website", pa.string()),
    ("addr_city", pa.string()),
    ("addr_street", pa.string()),
    ("addr_housenumber", pa.string()),
    ("building", pa.string()),        # значение тега building (если есть)
    ("building_levels", pa.string()), # этажность — строка, т.к. в OSM бывает "5;9" и т.п.
    ("start_date", pa.string()),      # дата открытия/постройки в свободном формате
    ("n_tags", pa.int32()),           # сколько всего тегов у объекта
    ("version", pa.int32()),          # номер версии объекта в OSM
    ("timestamp", pa.timestamp("s", tz="UTC")),  # время последней правки
])

# Какой тег OSM → какой столбец таблицы. Для телефона/сайта есть два варианта тега.
TAG_COLUMNS = {
    "name": ["name"],
    "name_kk": ["name:kk"],
    "name_ru": ["name:ru"],
    "name_en": ["name:en"],
    "brand": ["brand"],
    "opening_hours": ["opening_hours"],
    "phone": ["phone", "contact:phone"],
    "website": ["website", "contact:website"],
    "addr_city": ["addr:city"],
    "addr_street": ["addr:street"],
    "addr_housenumber": ["addr:housenumber"],
    "building": ["building"],
    "building_levels": ["building:levels"],
    "start_date": ["start_date"],
}


def classify_feature(tags) -> tuple[str, str] | None:
    """
    Определяет основной ключ объекта по приоритету из config.POI_KEYS.
    Возвращает (ключ, значение) или None, если объект нам не интересен.
    """
    for key in config.POI_KEYS:
        value = tags.get(key)
        if value:                       # пустые значения пропускаем
            return key, value
    if "building" in tags:              # объект без POI-тегов, но это здание
        return "building", tags.get("building")
    return None


def way_center(way) -> tuple[float, float] | None:
    """
    Центр линии/полигона = среднее координат его узлов.
    Для замкнутого контура последний узел совпадает с первым — его не учитываем.
    Если у какого-то узла нет координат (обрезан границей выгрузки) — None.
    """
    lons, lats = [], []
    for node_ref in way.nodes:
        loc = node_ref.location
        if not loc.valid():
            return None
        lons.append(loc.lon)
        lats.append(loc.lat)
    if len(lons) > 1 and way.nodes[0].ref == way.nodes[len(way.nodes) - 1].ref:
        lons.pop()
        lats.pop()
    if not lons:
        return None
    return sum(lons) / len(lons), sum(lats) / len(lats)


def build_row(obj, key: str, value: str, lon: float, lat: float) -> dict:
    """Собирает словарь-строку будущей таблицы из объекта OSM."""
    tags = obj.tags
    row = {
        "osm_type": "node" if obj.is_node() else "way",
        "osm_id": obj.id,
        "lon": lon,
        "lat": lat,
        "feature_key": key,
        "feature_value": value,
        "n_tags": len(tags),
        "version": obj.version,
        "timestamp": obj.timestamp,
    }
    for column, tag_names in TAG_COLUMNS.items():
        row[column] = None
        for tag in tag_names:          # берём первый найденный вариант тега
            if tag in tags:
                row[column] = tags.get(tag)
                break
    return row


def flush_chunk(rows: list[dict], out_dir: Path, chunk_no: int) -> None:
    """
    Записывает накопленный чанк в партиционированный Parquet.
    pq.write_to_dataset сам раскладывает строки по папкам feature_key=<значение>.
    """
    table = pa.Table.from_pylist(rows, schema=FEATURE_SCHEMA)
    pq.write_to_dataset(
        table,
        root_path=str(out_dir),
        partition_cols=["feature_key"],
        basename_template=f"chunk{chunk_no:04d}-{{i}}.parquet",
        existing_data_behavior="overwrite_or_ignore",
        compression="zstd",
    )


def extract_features(pbf_path: Path = config.PBF_PATH,
                     out_dir: Path = config.FEATURES_DIR,
                     chunk_size: int = config.CHUNK_SIZE) -> dict:
    """
    Главная функция шага: читает PBF, отбирает POI и здания, пишет Parquet чанками.
    Возвращает словарь со статистикой (строк, чанков, время, пиковая память).
    """
    if not pbf_path.exists():
        raise FileNotFoundError(f"Нет файла {pbf_path}. Сначала скачайте данные (пункт 1 меню).")
    if out_dir.exists():
        shutil.rmtree(out_dir)          # удаляем старый результат, иначе строки задвоятся
    out_dir.mkdir(parents=True)

    start = time.perf_counter()
    # with_locations() — кэш координат узлов, нужен чтобы посчитать центр для way.
    # KeyFilter пропускает только объекты, у которых есть хотя бы один из ключей.
    processor = (
        osmium.FileProcessor(str(pbf_path), osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()
        .with_filter(osmium.filter.KeyFilter(*config.EXTRACT_KEYS))
    )

    buffer: list[dict] = []
    stats = {"rows": 0, "chunks": 0, "skipped_no_geometry": 0, "by_type": {"node": 0, "way": 0}}
    for obj in processor:
        kind = classify_feature(obj.tags)
        if kind is None:
            continue
        key, value = kind
        if obj.is_node():
            if not obj.location.valid():
                stats["skipped_no_geometry"] += 1
                continue
            lon, lat = obj.location.lon, obj.location.lat
        else:
            center = way_center(obj)
            if center is None:
                stats["skipped_no_geometry"] += 1
                continue
            lon, lat = center
        buffer.append(build_row(obj, key, value, lon, lat))
        stats["by_type"]["node" if obj.is_node() else "way"] += 1

        # Буфер заполнен — сбрасываем чанк на диск и очищаем список
        if len(buffer) >= chunk_size:
            flush_chunk(buffer, out_dir, stats["chunks"])
            stats["rows"] += len(buffer)
            stats["chunks"] += 1
            log(f"  чанк {stats['chunks']}: всего {stats['rows']:,} строк, "
                f"пиковая память {peak_memory_mb():.0f} МБ")
            buffer = []

    if buffer:                           # не забываем последний неполный чанк
        flush_chunk(buffer, out_dir, stats["chunks"])
        stats["rows"] += len(buffer)
        stats["chunks"] += 1

    stats["seconds"] = round(time.perf_counter() - start, 1)
    stats["peak_memory_mb"] = round(peak_memory_mb(), 1)
    stats["pbf_size_mb"] = round(human_size(pbf_path), 1)
    stats["parquet_size_mb"] = round(human_size(out_dir), 1)
    log(f"Извлечено {stats['rows']:,} объектов за {stats['seconds']} с; "
        f"Parquet {stats['parquet_size_mb']} МБ")
    return stats


def extract_boundaries(pbf_path: Path = config.PBF_PATH,
                       boundaries_path: Path = config.BOUNDARIES_PATH,
                       places_path: Path = config.PLACES_PATH) -> dict:
    """
    Отдельный проход по PBF: собирает полигоны (osmium "areas")
      * 20 регионов Казахстана — boundary=administrative, admin_level=4, ISO3166-2 = KZ-*
      * городов и посёлков — place=city / place=town (если они нарисованы полигоном)
    и точки населённых пунктов place=city/town/village (с тегом population).
    Геометрия сохраняется в формате WKB внутри Parquet.
    """
    wkb_factory = osmium.geom.WKBFactory()
    wanted = (("boundary", "administrative"), ("place", "city"),
              ("place", "town"), ("place", "village"))
    processor = (
        osmium.FileProcessor(str(pbf_path))
        .with_areas(osmium.filter.TagFilter(*wanted[:3]))
        .with_filter(osmium.filter.TagFilter(*wanted))
    )
    areas, places, failed = [], [], 0
    for obj in processor:
        tags = obj.tags
        if obj.is_area():
            iso = tags.get("ISO3166-2", "")
            if tags.get("boundary") == "administrative" and tags.get("admin_level") == "4" \
                    and iso.startswith("KZ-"):
                kind = "region"
            elif tags.get("place") in ("city", "town"):
                kind = tags.get("place")
            else:
                continue
            try:
                geometry = wkb_factory.create_multipolygon(obj)
            except RuntimeError:
                failed += 1                 # битая геометрия (незамкнутый контур)
                continue
            areas.append({
                "kind": kind,
                "osm_type": "way" if obj.from_way() else "relation",
                "osm_id": obj.orig_id(),
                "name": tags.get("name"),
                "name_kk": tags.get("name:kk"),
                "name_ru": tags.get("name:ru"),
                "name_en": tags.get("name:en"),
                "iso_code": iso or None,
                "osm_population": tags.get("population"),
                "wkb": geometry,
            })
        elif obj.is_node() and tags.get("place") in ("city", "town", "village"):
            places.append({
                "osm_id": obj.id,
                "place": tags.get("place"),
                "name": tags.get("name"),
                "name_en": tags.get("name:en"),
                "osm_population": tags.get("population"),
                "lon": obj.location.lon,
                "lat": obj.location.lat,
            })

    pd.DataFrame(areas).to_parquet(boundaries_path, index=False)
    pd.DataFrame(places).to_parquet(places_path, index=False)
    stats = {
        "regions": sum(1 for a in areas if a["kind"] == "region"),
        "settlement_polygons": sum(1 for a in areas if a["kind"] != "region"),
        "place_points": len(places),
        "failed_geometries": failed,
    }
    log(f"Границы: {stats}")
    return stats
