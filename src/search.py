"""
Пользовательский поиск: ближайшие POI к заданной точке.

Используется BallTree с метрикой haversine (расстояние по сфере Земли):
дерево строится один раз, запрос k ближайших соседей — O(log n).
"""
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

from src import config
from src.categories import CATEGORY_NAMES_RU

EARTH_RADIUS_KM = 6371.0


def nearest_pois(lat: float, lon: float, category: str | None = None, k: int = 10,
                 pois: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Возвращает k ближайших сервисных POI к точке (lat, lon), опционально — одной категории.
    Расстояние — в километрах по поверхности Земли.
    """
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Широта должна быть в [-90; 90], долгота — в [-180; 180]")
    if pois is None:
        pois = pd.read_parquet(config.POIS_CLEAN_PATH)
    data = pois[pois["is_service"]]
    if category:
        if category not in CATEGORY_NAMES_RU:
            raise ValueError(f"Неизвестная категория: {category}")
        data = data[data["category"].astype(str) == category]
    if data.empty:
        return pd.DataFrame()
    coords = np.radians(data[["lat", "lon"]].to_numpy())
    tree = BallTree(coords, metric="haversine")
    k = min(k, len(data))
    dist, idx = tree.query(np.radians([[lat, lon]]), k=k)
    result = data.iloc[idx[0]][["name", "feature_value", "category", "lat", "lon"]].copy()
    result["category"] = result["category"].astype(str).map(CATEGORY_NAMES_RU)
    result["distance_km"] = (dist[0] * EARTH_RADIUS_KM).round(2)
    return result.reset_index(drop=True)
