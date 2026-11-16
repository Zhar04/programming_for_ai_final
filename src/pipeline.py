"""
Конвейер проекта: каждая функция step_* — один шаг обработки.

Шаги читают входные данные с диска и пишут результаты на диск, поэтому их можно
запускать по отдельности из меню (main.py) или все сразу (run_all).
Метрики каждого шага сохраняются в outputs/metrics/*.json.
"""
import time

import pandas as pd

from src import (aggregates, analysis, benchmark, clustering, config, database, download,
                 extract, hypotheses, optimize, quality, spatial, visualize)
from src.utils import load_json, log, save_json, update_run_state


def step_download() -> dict:
    """1. Скачать PBF (если его ещё нет) и сверить контрольную сумму."""
    download.download_pbf()
    ok = download.verify_pbf()
    info = {"md5_ok": ok, "size_mb": round(config.PBF_PATH.stat().st_size / 1024 ** 2, 1)}
    update_run_state("download", info)
    return info


def step_extract() -> dict:
    """2. Потоковое чтение PBF → партиционированный Parquet + границы и населённые пункты."""
    stats = {"boundaries": extract.extract_boundaries(), "features": extract.extract_features()}
    save_json(stats, config.METRICS_DIR / "extract_stats.json")
    update_run_state("extract", {"rows": stats["features"]["rows"]})
    return stats


def step_regions() -> dict:
    """3. Регионы + население, чанковая привязка 3,1 млн объектов к регионам."""
    regions = spatial.load_regions()
    spatial.save_regions_geojson(regions)
    start = time.perf_counter()
    stats = spatial.assign_regions_chunked(regions)
    stats["seconds"] = round(time.perf_counter() - start, 1)
    regions.drop(columns="geometry").to_csv(config.TABLES_DIR / "regions_population.csv", index=False)
    save_json(stats, config.METRICS_DIR / "regions_assign.json")
    update_run_state("regions", stats)
    return stats


def step_optimize() -> dict:
    """4. Замер памяти до/после оптимизации типов на полном наборе."""
    table = optimize.measure_memory_by_columns()
    error_m = optimize.float32_error_meters()
    total = table[table["column"] == "ИТОГО"].iloc[0]
    info = {"mb_before": float(total["mb_before"]), "mb_after": float(total["mb_after"]),
            "saving_pct": float(total["saving_pct"]), "float32_max_error_m": round(error_m, 3)}
    save_json(info, config.METRICS_DIR / "memory_optimization.json")
    update_run_state("optimize", info)
    return info


def step_audit_and_aggregates() -> dict:
    """5. Аудит полного набора (Polars lazy) + основные агрегаты двумя способами."""
    audit = quality.audit_full_dataset()
    _, timings = aggregates.build_region_summary()
    info = {"audit": audit, "aggregates": timings}
    save_json(info, config.METRICS_DIR / "audit_full.json")
    update_run_state("audit", {"rows_total": audit["rows_total"],
                               "results_match": timings["results_match"]})
    return info


def step_pois() -> dict:
    """6. Очистка POI, привязка к городам, показатели по регионам и городам."""
    regions = spatial.load_regions()
    cities = spatial.load_city_polygons(regions)
    pois, report, rules = analysis.prepare_pois(regions, cities)
    raw_summary = pd.read_parquet(config.PROCESSED_DIR / "region_raw_summary.parquet")
    reg_stats = analysis.region_stats(pois, regions, raw_summary)
    analysis.city_stats(pois, cities)
    analysis.megacity_comparison(pois, cities, int(regions["pop_total"].sum()))
    analysis.category_matrix(pois, regions, per_100k=False).round(4).to_csv(
        config.TABLES_DIR / "category_shares_by_region.csv")
    cities.drop(columns="geometry").to_parquet(config.PROCESSED_DIR / "cities.parquet", index=False)
    cities[["city_id", "name", "geometry"]].to_file(config.PROCESSED_DIR / "cities.geojson",
                                                     driver="GeoJSON")
    report["n_service_poi"] = int(pois["is_service"].sum())
    report["national_poi_per_100k"] = round(
        report["n_service_poi"] / regions["pop_total"].sum() * 1e5, 1)
    save_json(report, config.METRICS_DIR / "audit_pois.json")
    update_run_state("pois", {"rows": len(pois), "service": report["n_service_poi"]})
    return report


def step_database() -> dict:
    """7. Загрузка в SQLite и выполнение аналитических SQL-запросов."""
    regions = spatial.load_regions()
    cities = spatial.load_city_polygons(regions)
    pois = pd.read_parquet(config.POIS_CLEAN_PATH)
    raw_summary = pd.read_parquet(config.PROCESSED_DIR / "region_raw_summary.parquet")
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()                 # пересоздаём базу с нуля
    conn = database.connect()
    try:
        database.create_schema(conn)
        counts = database.load_all(conn, regions, cities, pois, raw_summary)
        # если кластеризация уже выполнялась — загружаем и её результаты
        if config.CLUSTERS_PATH.exists():
            runs = pd.read_csv(config.TABLES_DIR / "clustering_comparison.csv")
            database.load_clusters(conn, runs, pd.read_parquet(config.CLUSTERS_PATH))
        results = database.run_all_queries(conn)
    finally:
        conn.close()
    info = {"tables": counts, "queries": list(results)}
    update_run_state("database", info)
    return info


def step_benchmark() -> pd.DataFrame:
    """8. Сравнение Pandas / Polars / DuckDB на одной задаче."""
    table = benchmark.run_benchmark()
    update_run_state("benchmark", {"approaches": len(table)})
    return table


def step_clustering() -> dict:
    """9. Кластеризация (baseline, DBSCAN, HDBSCAN) + хотспоты в Алматы и Астане."""
    regions = spatial.load_regions()
    pois = pd.read_parquet(config.POIS_CLEAN_PATH)
    result = clustering.run_clustering(pois, regions)
    cities = pd.read_parquet(config.PROCESSED_DIR / "cities.parquet")
    city_ids = dict(zip(cities["name"], cities["city_id"]))   # название → city_id
    summaries = []
    for name_ru, city in [("Алматы", "Almaty"), ("Астана", "Astana")]:
        hot = clustering.city_hotspots(pois, city_ids[name_ru])
        hot[["poi_id", "hotspot"]].to_csv(config.TABLES_DIR / f"hotspots_{city.lower()}.csv",
                                          index=False)
        summaries.append(clustering.hotspot_summary(hot, name_ru))
        visualize.plot_hotspots_folium(hot, city)
    pd.concat(summaries).to_csv(config.TABLES_DIR / "hotspots_summary.csv", index=False)
    # записываем результаты в базу (если она уже создана)
    if config.DB_PATH.exists():
        conn = database.connect()
        try:
            database.load_clusters(conn, result["runs"], result["labels"])
            df = database.run_query(conn, "q11_largest_dbscan_clusters")
            df.to_csv(config.TABLES_DIR / "sql_q11_largest_dbscan_clusters.csv", index=False)
        finally:
            conn.close()
    info = {"best_eps": result["best_eps"], "runs": result["runs"].to_dict("records"),
            "tune_regions": result["tune_regions"], "test_regions": result["test_regions"],
            "far_clusters": int(len(result["errors"]))}
    save_json(info, config.METRICS_DIR / "clustering.json")
    update_run_state("clustering", {"best_eps": result["best_eps"]})
    return info


def step_hypotheses() -> pd.DataFrame:
    """10. Статистическая проверка гипотез H1–H4."""
    pois = pd.read_parquet(config.POIS_CLEAN_PATH)
    stats = pd.read_parquet(config.REGION_STATS_PATH)
    results, _ = hypotheses.run_all(pois, stats)
    update_run_state("hypotheses", {"n": len(results)})
    return results


def step_visualize() -> list:
    """11. Все графики (PNG для отчёта и HTML для интерактивного просмотра)."""
    visualize.setup_style()
    pois = pd.read_parquet(config.POIS_CLEAN_PATH)
    stats = pd.read_parquet(config.REGION_STATS_PATH)
    city_stats = pd.read_parquet(config.CITY_STATS_PATH)
    regions = spatial.load_regions()
    paths = [
        visualize.plot_region_density(stats),
        visualize.plot_region_map(stats),
        visualize.plot_region_map_interactive(stats),
        visualize.plot_category_heatmap(analysis.category_matrix(pois, regions, per_100k=False)),
        visualize.plot_megacities(pd.read_csv(config.TABLES_DIR / "megacity_comparison.csv",
                                              index_col=0)),
        visualize.plot_edit_years(pois),
        visualize.plot_missing(pois),
        visualize.plot_cities_interactive(city_stats),
        visualize.plot_er_diagram(),
    ]
    hyp_path = config.TABLES_DIR / "hypotheses.csv"
    if hyp_path.exists():
        paths.append(visualize.plot_hypotheses(stats, pd.read_csv(hyp_path)))
    bench_path = config.TABLES_DIR / "benchmark_tools.csv"
    if bench_path.exists():
        paths.append(visualize.plot_benchmark(pd.read_csv(bench_path)))
    clus = load_json(config.METRICS_DIR / "clustering.json")
    if clus and config.CLUSTERS_PATH.exists():
        import numpy as np
        labels = pd.read_parquet(config.CLUSTERS_PATH)
        dbscan_run = [r for r in clus["runs"] if r["method"] == "DBSCAN"][0]
        paths.append(visualize.plot_clusters_map(pois[pois["is_service"]], labels,
                                                 dbscan_run["run_id"], dbscan_run["params"]))
        paths.append(visualize.plot_kdistance(np.load(config.K_DISTANCE_PATH),
                                              pd.read_csv(config.TABLES_DIR / "dbscan_eps_sensitivity.csv"),
                                              clus["best_eps"]))
    update_run_state("visualize", {"figures": len(paths)})
    return paths


# Порядок шагов полного прогона: (ключ, функция, описание для меню)
STEPS = [
    ("download", step_download, "Скачать и проверить PBF (Geofabrik)"),
    ("extract", step_extract, "Извлечь POI и здания из PBF → Parquet"),
    ("regions", step_regions, "Привязать объекты к регионам (чанки)"),
    ("optimize", step_optimize, "Оптимизация типов и замер памяти"),
    ("audit", step_audit_and_aggregates, "Аудит качества + агрегаты (Polars lazy / чанки)"),
    ("pois", step_pois, "Очистка POI, показатели регионов и городов"),
    ("database", step_database, "Загрузка в SQLite и SQL-запросы"),
    ("benchmark", step_benchmark, "Бенчмарк Pandas / Polars / DuckDB"),
    ("clustering", step_clustering, "Кластеризация DBSCAN vs baseline vs HDBSCAN"),
    ("hypotheses", step_hypotheses, "Проверка гипотез H1–H4"),
    ("visualize", step_visualize, "Построить графики"),
]


def run_all(skip: tuple = ()) -> None:
    """Запускает все шаги по порядку и печатает общее время."""
    config.ensure_dirs()
    start = time.perf_counter()
    for key, func, description in STEPS:
        if key in skip:
            continue
        log(f"=== {description} ===")
        func()
    log(f"Конвейер завершён за {time.perf_counter() - start:.0f} с")
