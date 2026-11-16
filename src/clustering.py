"""
Шаг 9. Пространственная кластеризация POI (DBSCAN) и сравнение подходов.

Подходы:
  baseline  — сеточная плотность: страна делится на клетки 1×1 км, "плотные" клетки
              (≥ min_pts POI) склеиваются с соседними в кластеры (связные компоненты);
  DBSCAN    — кластер = область, где у точки ≥ min_samples соседей в радиусе eps;
  HDBSCAN   — иерархический DBSCAN, сам подбирает "eps" для каждой плотности.

Координаты переводятся в метры (равновеликая проекция), поэтому eps задаётся в метрах.

Как оцениваем без "правильных ответов":
  * пространственное разбиение без утечки: eps подбирается на 10 регионах (tune),
    итоговое сравнение методов — на других 10 регионах (test);
  * внутренние метрики — силуэт (выше лучше) и индекс Дэвиса–Боулдина (ниже лучше);
  * внешняя проверка по населённым пунктам OSM (place=city/town/village):
      precision — доля кластеров, центр которых ближе 3 км к населённому пункту;
      recall    — доля городов и посёлков (city/town), рядом с которыми (≤ 3 км) есть кластер;
      F1        — гармоническое среднее precision и recall;
  * время работы и пиковая память (tracemalloc).
"""
import time
import tracemalloc

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.cluster import DBSCAN, HDBSCAN
from sklearn.metrics import davies_bouldin_score, silhouette_score
from sklearn.neighbors import NearestNeighbors

from src import config
from src.spatial import to_meters
from src.utils import log

MATCH_RADIUS_M = 3000      # радиус "совпадения" кластера с населённым пунктом
MIN_SAMPLES = 10           # минимальное число POI для плотной области (общий для всех подходов)


def settlement_points(regions: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Населённые пункты Казахстана (place=city/town/village) с координатами в метрах
    и кодом региона — "псевдо-разметка" для внешней оценки кластеров.
    """
    places = pd.read_parquet(config.PLACES_PATH)
    gdf = gpd.GeoDataFrame(places, geometry=gpd.points_from_xy(places["lon"], places["lat"]),
                           crs="EPSG:4326")
    inside = gpd.sjoin(gdf, regions[["iso_code", "geometry"]], predicate="within")
    xy = to_meters(inside["lon"], inside["lat"])
    return pd.DataFrame({"x": xy[:, 0], "y": xy[:, 1], "place": inside["place"].to_numpy(),
                         "iso_code": inside["iso_code"].to_numpy()})


def split_regions(iso_codes, seed: int = config.RANDOM_STATE) -> tuple[set, set]:
    """
    Пространственное разбиение без утечки: 10 регионов — для подбора eps (tune),
    другие 10 — для финального сравнения методов (test).
    """
    codes = sorted(str(c) for c in iso_codes)
    rng = np.random.default_rng(seed)
    shuffled = [str(c) for c in rng.permutation(codes)]
    half = len(shuffled) // 2
    return set(shuffled[:half]), set(shuffled[half:])


def grid_baseline(xy: np.ndarray, cell_m: float = 1000, min_pts: int = MIN_SAMPLES) -> np.ndarray:
    """
    Baseline: сеточная кластеризация.
    1) номер клетки для каждой точки; 2) клетки с ≥ min_pts точек — плотные;
    3) обход в ширину (BFS) склеивает соседние плотные клетки (8-связность) в кластеры.
    """
    cells = np.floor(xy / cell_m).astype(np.int64)
    keys, inverse, counts = np.unique(cells, axis=0, return_inverse=True, return_counts=True)
    inverse = inverse.ravel()
    dense = {tuple(k): i for i, k in enumerate(keys) if counts[i] >= min_pts}
    cell_label = {}
    current = 0
    for start in dense:                         # перебираем плотные клетки
        if start in cell_label:
            continue
        queue = [start]
        cell_label[start] = current
        while queue:                            # BFS по соседним клеткам
            cx, cy = queue.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nb = (cx + dx, cy + dy)
                    if nb in dense and nb not in cell_label:
                        cell_label[nb] = current
                        queue.append(nb)
        current += 1
    labels_per_cell = np.array([cell_label.get(tuple(k), -1) for k in keys])
    return labels_per_cell[inverse]


def k_distance(xy: np.ndarray, k: int = MIN_SAMPLES) -> np.ndarray:
    """Расстояние до k-го соседа для каждой точки (отсортировано) — график для выбора eps."""
    nn = NearestNeighbors(n_neighbors=k + 1).fit(xy)   # +1, т.к. первый сосед — сама точка
    distances, _ = nn.kneighbors(xy)
    return np.sort(distances[:, -1])


def evaluate(xy: np.ndarray, labels: np.ndarray, poi_regions: np.ndarray,
             settlements: pd.DataFrame, eval_regions: set, sample: int = 10_000) -> dict:
    """
    Считает метрики качества кластеризации.
    Внутренние (силуэт, Дэвис–Боулдин) — по всем точкам: они не используют разметку.
    Внешние (precision/recall по населённым пунктам) — только по регионам eval_regions.
    """
    clustered = labels >= 0
    cluster_ids = np.unique(labels[clustered])
    result = {
        "n_clusters": int(len(cluster_ids)),
        "noise_share": float(1 - clustered.mean()),
    }
    if len(cluster_ids) < 2:
        result.update(silhouette=np.nan, davies_bouldin=np.nan, settlement_precision=np.nan,
                      settlement_recall=np.nan, settlement_f1=np.nan)
        return result

    # Силуэт на случайной подвыборке (на всех 100+ тыс. точек это O(n²) — слишком долго)
    rng = np.random.default_rng(config.RANDOM_STATE)
    idx = np.flatnonzero(clustered)
    if len(idx) > sample:
        idx = rng.choice(idx, sample, replace=False)
    result["silhouette"] = float(silhouette_score(xy[idx], labels[idx]))
    result["davies_bouldin"] = float(davies_bouldin_score(xy[clustered], labels[clustered]))

    # Центр каждого кластера и его "главный" регион (где больше всего его точек)
    frame = pd.DataFrame({"x": xy[clustered, 0], "y": xy[clustered, 1],
                          "label": labels[clustered], "region": poi_regions[clustered]})
    centers = frame.groupby("label")[["x", "y"]].mean()
    main_region = (frame.groupby(["label", "region"]).size().reset_index(name="n")
                   .sort_values("n", ascending=False).drop_duplicates("label")
                   .set_index("label")["region"])
    centers = centers[main_region.reindex(centers.index).isin(eval_regions)]

    # precision: центр кластера ближе 3 км к любому населённому пункту
    dist_to_settlement, _ = cKDTree(settlements[["x", "y"]].to_numpy()).query(centers.to_numpy())
    precision = float((dist_to_settlement <= MATCH_RADIUS_M).mean()) if len(centers) else 0.0
    # recall: у города/посёлка в радиусе 3 км есть хотя бы одна кластеризованная POI
    towns = settlements[settlements["place"].isin(["city", "town"]) &
                        settlements["iso_code"].isin(eval_regions)]
    dist_to_cluster, _ = cKDTree(xy[clustered]).query(towns[["x", "y"]].to_numpy())
    recall = float((dist_to_cluster <= MATCH_RADIUS_M).mean())
    result["settlement_precision"] = precision
    result["settlement_recall"] = recall
    result["settlement_f1"] = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return result


def timed_run(func, *args, **kwargs) -> tuple[np.ndarray, float, float]:
    """Запускает алгоритм, возвращает (метки, секунды, пиковая память МБ по tracemalloc)."""
    tracemalloc.start()
    start = time.perf_counter()
    labels = func(*args, **kwargs)
    seconds = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return labels, seconds, peak / 1024 ** 2


def dbscan_labels(xy: np.ndarray, eps: float, min_samples: int = MIN_SAMPLES) -> np.ndarray:
    """DBSCAN с KD-деревом (евклидово расстояние в метрах)."""
    return DBSCAN(eps=eps, min_samples=min_samples, algorithm="kd_tree", n_jobs=-1).fit_predict(xy)


def hdbscan_labels(xy: np.ndarray, min_cluster_size: int = MIN_SAMPLES,
                   min_samples: int = MIN_SAMPLES) -> np.ndarray:
    """HDBSCAN (встроен в scikit-learn ≥ 1.3)."""
    return HDBSCAN(min_cluster_size=min_cluster_size, min_samples=min_samples,
                   copy=True, n_jobs=-1).fit_predict(xy)


def eps_sensitivity(xy, poi_regions, settlements, tune_regions,
                    eps_values=(150, 250, 400, 600, 1000, 1500, 2000, 3000, 5000)) -> pd.DataFrame:
    """Подбор eps: DBSCAN для нескольких значений, метрики только по регионам tune."""
    rows = []
    for eps in eps_values:
        labels, seconds, peak = timed_run(dbscan_labels, xy, eps)
        metrics = evaluate(xy, labels, poi_regions, settlements, tune_regions)
        rows.append({"eps_m": eps, **metrics, "seconds": round(seconds, 2)})
        log(f"  DBSCAN eps={eps} м: кластеров {metrics['n_clusters']}, "
            f"шум {metrics['noise_share']:.1%}, F1 {metrics['settlement_f1']:.3f}")
    table = pd.DataFrame(rows)
    table.to_csv(config.TABLES_DIR / "dbscan_eps_sensitivity.csv", index=False)
    return table


def run_clustering(pois: pd.DataFrame, regions: gpd.GeoDataFrame) -> dict:
    """
    Главная функция шага: кластеризует сервисные POI тремя подходами,
    считает метрики и возвращает таблицы для БД и отчёта.
    """
    service = pois[pois["is_service"]].reset_index(drop=True)
    xy = to_meters(service["lon"].to_numpy(), service["lat"].to_numpy())
    poi_regions = service["region_iso"].astype(str).to_numpy()
    settlements = settlement_points(regions)
    tune_regions, test_regions = split_regions(regions["iso_code"])
    log(f"Кластеризация: {len(xy):,} POI, населённых пунктов {len(settlements):,}; "
        f"регионы для подбора eps: {sorted(tune_regions)}")

    kdist = k_distance(xy)
    np.save(config.INTERIM_DIR / "k_distance.npy", kdist)

    sens = eps_sensitivity(xy, poi_regions, settlements, tune_regions)
    best_eps = int(sens.sort_values(["settlement_f1", "silhouette"], ascending=False)
                   .iloc[0]["eps_m"])
    log(f"Выбран eps = {best_eps} м (максимум F1 на регионах подбора)")

    # Три подхода с одинаковым порогом плотности MIN_SAMPLES
    approaches = [
        ("Grid baseline", f"cell=1000 м, min_pts={MIN_SAMPLES}", grid_baseline, {}),
        ("DBSCAN", f"eps={best_eps} м, min_samples={MIN_SAMPLES}", dbscan_labels, {"eps": best_eps}),
        ("HDBSCAN", f"min_cluster_size={MIN_SAMPLES}, min_samples={MIN_SAMPLES}", hdbscan_labels, {}),
    ]
    runs, label_frames = [], []
    for run_id, (method, params, func, kwargs) in enumerate(approaches, start=1):
        labels, seconds, peak = timed_run(func, xy, **kwargs)
        metrics = evaluate(xy, labels, poi_regions, settlements, test_regions)
        runs.append({"run_id": run_id, "method": method, "params": params, **metrics,
                     "seconds": round(seconds, 2), "peak_mb": round(peak, 1)})
        label_frames.append(pd.DataFrame({"poi_id": service["poi_id"].astype(int),
                                          "run_id": run_id, "cluster_label": labels}))
        log(f"  {method}: кластеров {metrics['n_clusters']}, шум {metrics['noise_share']:.1%}, "
            f"F1 {metrics['settlement_f1']:.3f}, {seconds:.1f} с, {peak:.0f} МБ")

    runs_df = pd.DataFrame(runs)
    labels_df = pd.concat(label_frames, ignore_index=True)
    runs_df.to_csv(config.TABLES_DIR / "clustering_comparison.csv", index=False)
    labels_df.to_parquet(config.CLUSTERS_PATH, index=False)

    # Анализ ошибок: кластеры DBSCAN, центр которых далеко от населённых пунктов
    dbscan_run = labels_df[labels_df["run_id"] == 2]
    errors = cluster_error_analysis(service, xy, dbscan_run["cluster_label"].to_numpy(),
                                    settlements[["x", "y"]].to_numpy())
    return {"runs": runs_df, "labels": labels_df, "eps_table": sens, "best_eps": best_eps,
            "k_distance": kdist, "errors": errors,
            "tune_regions": sorted(tune_regions), "test_regions": sorted(test_regions)}


def cluster_error_analysis(service: pd.DataFrame, xy: np.ndarray, labels: np.ndarray,
                           settle_all: np.ndarray) -> pd.DataFrame:
    """
    Error analysis: какие кластеры НЕ совпали с населёнными пунктами и почему.
    Для каждого такого кластера — размер, регион, доминирующий тип POI и пример названия.
    """
    frame = service[["region_iso", "feature_value", "name", "category"]].copy()
    frame["label"] = labels
    frame["x"], frame["y"] = xy[:, 0], xy[:, 1]
    frame = frame[frame["label"] >= 0]
    centers = frame.groupby("label")[["x", "y"]].mean()
    dist, _ = cKDTree(settle_all).query(centers.to_numpy())
    centers["dist_km"] = dist / 1000
    far = centers[centers["dist_km"] > MATCH_RADIUS_M / 1000].index
    rows = []
    for label in far:
        members = frame[frame["label"] == label]
        rows.append({
            "cluster": int(label),
            "size": len(members),
            "region": config.REGION_SHORT_RU.get(str(members["region_iso"].mode().iloc[0]), "?"),
            "dist_to_settlement_km": round(float(centers.loc[label, "dist_km"]), 1),
            "top_type": str(members["feature_value"].mode().iloc[0]),
            "top_category": str(members["category"].mode().iloc[0]),
            "example_name": next((str(n) for n in members["name"] if pd.notna(n)), "—"),
        })
    table = pd.DataFrame(rows)
    if len(table):
        table = table.sort_values("size", ascending=False)
    table.to_csv(config.TABLES_DIR / "clustering_error_analysis.csv", index=False)
    return table


def city_hotspots(pois: pd.DataFrame, city_id: int, eps: float = 100,
                  min_samples: int = 8) -> pd.DataFrame:
    """
    "Горячие точки" общепита и торговли внутри города (например, Алматы):
    DBSCAN с маленьким радиусом выделяет торговые улицы, ТРЦ и рынки.
    eps = 100 м подобран так, чтобы центр города не сливался в один кластер
    (при 150 м крупнейший кластер Алматы — 1130 точек, при 100 м — около 300).
    """
    subset = pois[(pois["city_id"] == city_id) &
                  (pois["category"].astype(str).isin(["food", "retail"]))].copy()
    xy = to_meters(subset["lon"].to_numpy(), subset["lat"].to_numpy())
    subset["hotspot"] = dbscan_labels(xy, eps=eps, min_samples=min_samples)
    return subset


def hotspot_summary(hotspots: pd.DataFrame, city: str, top: int = 5) -> pd.DataFrame:
    """
    Крупнейшие горячие точки города: размер, частый тип и самая частая улица
    (по тегу addr:street) — по улице хотспот легко узнать на карте.
    """
    rows = []
    clustered = hotspots[hotspots["hotspot"] >= 0]
    for label, group in clustered.groupby("hotspot"):
        streets = group["addr_street"].dropna().astype(str)
        names = group["name"].dropna().astype(str)
        rows.append({"city": city, "hotspot": int(label), "size": len(group),
                     "top_type": group["feature_value"].astype(str).value_counts().index[0],
                     "main_street": streets.value_counts().index[0] if len(streets) else "—",
                     "frequent_name": names.value_counts().index[0] if len(names) else "—",
                     "lat": round(group["lat"].mean(), 5), "lon": round(group["lon"].mean(), 5)})
    return pd.DataFrame(rows).sort_values("size", ascending=False).head(top)
