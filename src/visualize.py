"""
Шаг 11. Визуализации.

Статические графики (PNG, matplotlib/seaborn) идут в отчёт и презентацию,
интерактивные (HTML, Plotly и Folium) — открываются в браузере.

Правила оформления (едины для всех графиков):
  * цвета категорий — из проверенной на дальтонизм палитры, в фиксированном порядке;
  * величины (карта, тепловая карта) — один оттенок синего от светлого к тёмному;
  * тонкие столбцы, светлая сетка, подписи только у важных точек;
  * никогда не используем две оси Y на одном графике.
"""
import json

import folium
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")                     # рисуем в файлы, без окна (работает и в консоли)
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd
import plotly.express as px
import seaborn as sns
from scipy.spatial import cKDTree
from shapely.geometry import MultiPoint

from src import config
from src.categories import CATEGORY_NAMES_RU
from src.utils import log

# --- палитра (проверена validate_palette.js: CVD ΔE ≥ 9 для первых трёх цветов)
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GRAY, LIGHT_GRAY = "#8c8b86", "#d6d5d0"
TEXT, TEXT_2 = "#0b0b0b", "#52514e"
SURFACE, GRID = "#fcfcfb", "#e8e7e3"
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SEQ_CMAP = LinearSegmentedColormap.from_list("kz_blue", BLUE_RAMP)

# Подложки для интерактивных карт (Esri отдаёт тайлы без ключа и без Referer)
ESRI_BASE = "https://server.arcgisonline.com/ArcGIS/rest/services"
ESRI_TILES = {
    "gray": ESRI_BASE + "/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    "labels": ESRI_BASE + "/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
    "streets": ESRI_BASE + "/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
}
ESRI_ATTR = "Tiles &copy; Esri; данные POI &copy; OpenStreetMap contributors"


def setup_style() -> None:
    """Общий стиль matplotlib: светлый фон, тонкая сетка, шрифт с кириллицей."""
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": "DejaVu Sans", "font.size": 10,
        "axes.edgecolor": GRID, "axes.linewidth": 0.8, "axes.labelcolor": TEXT_2,
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlecolor": TEXT,
        "axes.titlelocation": "left", "axes.grid": True, "grid.color": GRID,
        "grid.linewidth": 0.8, "xtick.color": TEXT_2, "ytick.color": TEXT_2,
        "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
        "axes.axisbelow": True,          # сетка рисуется ПОД столбцами, а не поверх
    })


def save(fig, name: str) -> str:
    """Сохраняет фигуру в outputs/figures и закрывает её (освобождает память)."""
    path = config.FIG_DIR / name
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    log(f"  график: {name}")
    return str(path)


def plot_region_density(stats: pd.DataFrame) -> str:
    """1. POI на 100 тыс. жителей по регионам: области — синие, мегаполисы — оранжевые."""
    data = stats.sort_values("poi_per_100k")
    colors = [ORANGE if t == "city" else BLUE for t in data["region_type"]]
    fig, ax = plt.subplots(figsize=(8.5, 7))
    ax.barh(data["region_ru"], data["poi_per_100k"], color=colors, height=0.6)
    national = stats["n_service_poi"].sum() / stats["pop_total"].sum() * 1e5
    ax.axvline(national, color=TEXT_2, linewidth=1)
    ax.text(national + 8, len(data) - 0.35, f"в среднем по РК: {national:.0f}",
            color=TEXT_2, fontsize=9)
    ax.set_ylim(-0.7, len(data) + 0.2)
    # подписываем значения только у мегаполисов, лидера и аутсайдера
    for i, (_, row) in enumerate(data.iterrows()):
        if row["region_type"] == "city" or i in (0, len(data) - 1):
            ax.text(row["poi_per_100k"] + 8, i, f"{row['poi_per_100k']:.0f}",
                    va="center", fontsize=9, color=TEXT)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Сервисных POI на 100 тыс. жителей")
    ax.set_title("Обеспеченность точками интереса по регионам Казахстана")
    handles = [plt.Rectangle((0, 0), 1, 1, color=BLUE), plt.Rectangle((0, 0), 1, 1, color=ORANGE)]
    ax.legend(handles, ["Область", "Город респ. значения"], loc="lower right")
    return save(fig, "fig01_poi_per_100k_regions.png")


def plot_region_map(stats: pd.DataFrame) -> str:
    """2а. Статическая карта-хороплет (для отчёта)."""
    regions = gpd.read_file(config.REGIONS_GEOJSON).merge(
        stats[["iso_code", "poi_per_100k"]], on="iso_code")
    regions = regions.to_crs(config.KZ_EQUAL_AREA_CRS)
    fig, ax = plt.subplots(figsize=(10, 6))
    regions.plot(column="poi_per_100k", cmap=SEQ_CMAP, linewidth=0.8, edgecolor=SURFACE, ax=ax,
                 legend=True, legend_kwds={"label": "POI на 100 тыс. жителей", "shrink": 0.6})
    # три мегаполиса на карте очень маленькие — подписываем их выносками за контуром страны
    minx, miny, maxx, maxy = regions.total_bounds
    for _, row in regions.iterrows():
        point = row.geometry.representative_point()
        if row["iso_code"] in config.MEGACITIES:
            # куда вынести подпись: Астана — над картой, Алматы и Шымкент — под картой
            offsets = {"KZ-71": (point.x, maxy + 120_000),
                       "KZ-75": (point.x + 250_000, miny - 90_000),
                       "KZ-79": (point.x - 250_000, miny - 170_000)}
            ax.plot(point.x, point.y, "o", markersize=5, markerfacecolor=ORANGE,
                    markeredgecolor=SURFACE, markeredgewidth=1.5)
            ax.annotate(f"{config.MEGACITIES[row['iso_code']]}: {row['poi_per_100k']:.0f}",
                        xy=(point.x, point.y), xytext=offsets[row["iso_code"]], fontsize=9,
                        color=TEXT, ha="center",
                        arrowprops={"arrowstyle": "-", "color": TEXT_2, "linewidth": 0.8})
        else:
            ax.text(point.x, point.y, f"{row['poi_per_100k']:.0f}", fontsize=8, ha="center",
                    color="white" if row["poi_per_100k"] > 600 else TEXT)
    ax.set_ylim(miny - 250_000, maxy + 220_000)
    ax.set_axis_off()
    ax.set_title("Сервисные POI на 100 тыс. жителей (OSM, ноябрь 2026; население на 01.01.2026)")
    return save(fig, "fig02_map_poi_per_100k.png")


def plot_region_map_interactive(stats: pd.DataFrame) -> str:
    """2б. Интерактивная карта Plotly: наведение показывает показатели региона."""
    with open(config.REGIONS_GEOJSON, encoding="utf-8") as f:
        geojson = json.load(f)
    data = stats.copy()
    data["poi_per_100k"] = data["poi_per_100k"].round(1)
    data["poi_per_1000km2"] = data["poi_per_1000km2"].round(1)
    fig = px.choropleth(
        data, geojson=geojson, locations="iso_code", featureidkey="properties.iso_code",
        color="poi_per_100k", color_continuous_scale=BLUE_RAMP,
        hover_name="region_ru",
        hover_data={"iso_code": False, "n_service_poi": ":,", "pop_total": ":,",
                    "poi_per_100k": True, "poi_per_1000km2": True},
        labels={"poi_per_100k": "POI на 100 тыс.", "n_service_poi": "POI",
                "pop_total": "Население", "poi_per_1000km2": "POI на 1000 км²"},
        title="Казахстан: сервисные точки интереса OSM на 100 тыс. жителей",
    )
    fig.update_geos(fitbounds="locations", visible=False)
    fig.update_layout(margin={"l": 0, "r": 0, "t": 50, "b": 0}, paper_bgcolor=SURFACE)
    path = config.FIG_DIR / "fig02_map_poi_per_100k.html"
    fig.write_html(path, include_plotlyjs="cdn")
    log("  график: fig02_map_poi_per_100k.html (интерактивный)")
    return str(path)


def plot_category_heatmap(shares: pd.DataFrame) -> str:
    """3. Структура категорий по регионам (доля, %) — тепловая карта одного оттенка."""
    data = (shares * 100).round(0)
    data = data.loc[data.index.sort_values()]
    fig, ax = plt.subplots(figsize=(11, 7.5))
    sns.heatmap(data, cmap=SEQ_CMAP, annot=True, fmt=".0f", annot_kws={"fontsize": 8},
                linewidths=1.5, linecolor=SURFACE, cbar_kws={"label": "доля категории, %"}, ax=ax)
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.tick_params(axis="x", rotation=35)
    plt.setp(ax.get_xticklabels(), ha="right")
    ax.set_title("Структура сервисных POI: доля каждой категории в регионе, %")
    return save(fig, "fig03_category_structure_heatmap.png")


def plot_megacities(table: pd.DataFrame) -> str:
    """4. Астана vs Алматы vs Шымкент vs другие города — точечная диаграмма по категориям."""
    data = table.drop(columns=["Все категории"]).T
    data = data.sort_values("Алматы")
    y = np.arange(len(data))
    fig, ax = plt.subplots(figsize=(9, 6.3))
    for name, color in [("Астана", BLUE), ("Алматы", ORANGE), ("Шымкент", AQUA)]:
        ax.scatter(data[name], y, s=55, color=color, edgecolors=SURFACE, linewidths=1.5,
                   label=name, zorder=3)
    ax.scatter(data["Другие города ≥100 тыс."], y, s=70, facecolors="none", edgecolors=GRAY,
               linewidths=1.5, label="Другие города ≥100 тыс.", zorder=2)
    ax.set_yticks(y, data.index)
    ax.grid(axis="y", visible=False)
    for yi in y:
        ax.axhline(yi, color=GRID, linewidth=0.6, zorder=1)
    totals = table["Все категории"]
    ax.set_xlabel("POI на 100 тыс. жителей")
    # pad — отступ заголовка вверх, чтобы под ним поместилась строка с итогами
    ax.set_title("Мегаполисы и другие крупные города: обеспеченность по категориям", pad=26)
    ax.text(0, 1.015, (f"Всего на 100 тыс. жителей: Астана {totals['Астана']:.0f} · "
                      f"Алматы {totals['Алматы']:.0f} · Шымкент {totals['Шымкент']:.0f} · "
                      f"другие города ≥100 тыс. {totals['Другие города ≥100 тыс.']:.0f}"),
            transform=ax.transAxes, fontsize=9, color=TEXT_2)
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, -0.1), ncol=4)
    return save(fig, "fig04_megacities_categories.png")


def plot_clusters_map(pois: pd.DataFrame, labels: pd.DataFrame, run_id: int,
                      title_params: str) -> str:
    """5а. Кластеры DBSCAN на карте страны: кластеры — синие точки, шум — серые."""
    regions = gpd.read_file(config.REGIONS_GEOJSON).to_crs(config.KZ_EQUAL_AREA_CRS)
    lab = labels[labels["run_id"] == run_id][["poi_id", "cluster_label"]]
    data = pois[["poi_id", "lon", "lat"]].merge(lab, on="poi_id")
    from src.spatial import to_meters
    xy = to_meters(data["lon"], data["lat"])
    noise = data["cluster_label"].to_numpy() < 0
    fig, ax = plt.subplots(figsize=(11, 6.5))
    regions.boundary.plot(ax=ax, color=LIGHT_GRAY, linewidth=0.7)
    ax.scatter(xy[noise, 0], xy[noise, 1], s=1.5, color=GRAY, alpha=0.5, label="шум", linewidths=0)
    ax.scatter(xy[~noise, 0], xy[~noise, 1], s=1.5, color=BLUE, label="в кластере", linewidths=0)
    # подписываем 6 крупнейших кластеров: ближайший город + число POI
    places = pd.read_parquet(config.PLACES_PATH)
    towns = places[places["place"].isin(["city", "town"])]
    town_tree = cKDTree(to_meters(towns["lon"], towns["lat"]))
    sizes = data[~noise].groupby("cluster_label").size().sort_values(ascending=False).head(6)
    for label, size in sizes.items():
        pts = xy[data["cluster_label"].to_numpy() == label]
        cx, cy = pts.mean(axis=0)
        _, nearest = town_tree.query([cx, cy])
        town = towns["name"].iloc[nearest]
        ax.annotate(f"{town}: {size:,} POI".replace(",", " "), xy=(cx, cy),
                    xytext=(cx + 60_000, cy + 90_000),
                    fontsize=8.5, color=TEXT,
                    arrowprops={"arrowstyle": "-", "color": TEXT_2, "linewidth": 0.8})
    ax.set_axis_off()
    ax.legend(loc="lower left", markerscale=6)
    ax.set_title(f"DBSCAN по 106 тыс. сервисных POI ({title_params})")
    return save(fig, "fig05_dbscan_clusters_kz.png")


def plot_hotspots_folium(hotspots: pd.DataFrame, city_name: str) -> str:
    """
    5б. Интерактивная карта Folium: "горячие точки" общепита и торговли в городе.
    Каждый кластер обведён выпуклой оболочкой, во всплывающей подсказке — размер и тип.
    """
    center = [hotspots["lat"].mean(), hotspots["lon"].mean()]
    # Подложка — Esri. Почему не другие:
    #  * tile.openstreetmap.org блокирует (403) браузерные запросы без заголовка Referer,
    #    а у HTML, открытого как локальный файл, Referer нет;
    #  * CARTO теперь требует API-ключ (вместо карты приходит надпись "API KEY REQUIRED").
    fmap = folium.Map(location=center, zoom_start=12, tiles=None)
    folium.TileLayer(tiles=ESRI_TILES["gray"], attr=ESRI_ATTR, name="Светлая (Esri)",
                     max_zoom=16).add_to(fmap)
    folium.TileLayer(tiles=ESRI_TILES["streets"], attr=ESRI_ATTR, name="Улицы (Esri)",
                     max_zoom=19, show=False).add_to(fmap)
    folium.TileLayer(tiles=ESRI_TILES["labels"], attr=ESRI_ATTR, name="Подписи",
                     overlay=True, max_zoom=16).add_to(fmap)
    noise = hotspots[hotspots["hotspot"] < 0]
    for _, row in noise.iterrows():
        folium.CircleMarker([row["lat"], row["lon"]], radius=1.5, color=GRAY, fill=True,
                            fill_opacity=0.5, weight=0).add_to(fmap)
    clustered = hotspots[hotspots["hotspot"] >= 0]
    for label, group in clustered.groupby("hotspot"):
        top = group["feature_value"].astype(str).value_counts().index[0]
        hull = MultiPoint(list(zip(group["lon"], group["lat"]))).convex_hull
        if hull.geom_type == "Polygon":
            folium.Polygon([(lat, lon) for lon, lat in hull.exterior.coords], color=ORANGE,
                           weight=2, fill=True, fill_opacity=0.12,
                           tooltip=f"Хотспот {label}: {len(group)} объектов, чаще всего — {top}"
                           ).add_to(fmap)
        for _, row in group.iterrows():
            folium.CircleMarker([row["lat"], row["lon"]], radius=2, color=BLUE, fill=True,
                                fill_opacity=0.8, weight=0,
                                tooltip=f"{row['name'] if pd.notna(row['name']) else row['feature_value']}"
                                ).add_to(fmap)
    folium.LayerControl(collapsed=True).add_to(fmap)   # переключатель подложек (правый верхний угол)
    path = config.FIG_DIR / f"fig05_hotspots_{city_name.lower()}.html"
    fmap.save(str(path))
    log(f"  график: {path.name} (интерактивный)")
    return str(path)


def plot_hypotheses(stats: pd.DataFrame, hyp: pd.DataFrame) -> str:
    """6. Две диаграммы рассеяния для гипотез H1 и H4 (одна ось Y у каждой)."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    panels = [("urban_share", "Доля городского населения", "H1", 100),
              ("buildings_per_100k", "Зданий в OSM на 100 тыс. жителей", "H4", 1)]
    for ax, (col, xlabel, hid, scale) in zip(axes, panels):
        x = stats[col] * scale
        ax.scatter(x, stats["poi_per_100k"], s=50, color=BLUE, edgecolors=SURFACE, linewidths=1.5)
        for _, row in stats.iterrows():
            if row["region_type"] == "city" or row["poi_per_100k"] in (
                    stats["poi_per_100k"].max(), stats["poi_per_100k"].min()):
                ax.annotate(row["region_ru"], (row[col] * scale, row["poi_per_100k"]),
                            xytext=(5, 4), textcoords="offset points", fontsize=8, color=TEXT_2)
        r = hyp.set_index("id").loc[hid]
        ax.set_title(f"{hid}: {r['effect']}, p = {r['p_value_fmt']}")
        ax.set_xlabel(xlabel + (", %" if scale == 100 else ""))
    axes[0].set_ylabel("Сервисных POI на 100 тыс. жителей")
    return save(fig, "fig06_hypotheses_scatter.png")


def plot_edit_years(pois: pd.DataFrame) -> str:
    """7. EDA дат: в каком году POI правились последний раз (актуальность данных)."""
    counts = pois["edit_year"].value_counts().sort_index()
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(counts.index, counts.values, color=BLUE, width=0.6)
    ax.grid(axis="x", visible=False)
    recent = counts[counts.index >= counts.index.max() - 2].sum() / counts.sum()
    ax.set_title(f"Год последней правки POI: {recent:.0%} объектов обновлены за последние 3 года")
    ax.set_ylabel("Число POI")
    ax.set_xticks(counts.index[::2])
    return save(fig, "fig07_last_edit_year.png")


def plot_benchmark(bench: pd.DataFrame) -> str:
    """8. Бенчмарк инструментов: время и пиковая память — два отдельных графика."""
    data = bench.sort_values("median_seconds", ascending=True)
    colors = [GRAY if a == "pandas_csv" else BLUE for a in data["approach"]]
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8), sharey=True)
    axes[0].barh(data["approach"], data["median_seconds"], color=colors, height=0.55)
    axes[1].barh(data["approach"], data["peak_mb"], color=colors, height=0.55)
    for ax, col, unit in [(axes[0], "median_seconds", "с"), (axes[1], "peak_mb", "МБ")]:
        for i, v in enumerate(data[col]):
            ax.text(v, i, f" {v:.1f} {unit}" if unit == "с" else f" {v:.0f} {unit}",
                    va="center", fontsize=8.5, color=TEXT)
        ax.grid(axis="y", visible=False)
    axes[0].set_title("Время (медиана 3 запусков)")
    axes[1].set_title("Пиковая память процесса")
    fig.suptitle("Одна задача на 3,1 млн строк: агрегаты по региону и ключу OSM "
                 "(серый — baseline)", x=0.01, ha="left", fontsize=11, color=TEXT_2)
    return save(fig, "fig08_benchmark_tools.png")


def plot_kdistance(kdist: np.ndarray, eps_table: pd.DataFrame, best_eps: int) -> str:
    """9. Выбор eps: k-distance график и F1 по населённым пунктам (два отдельных графика)."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].plot(np.arange(len(kdist)), kdist, color=BLUE, linewidth=2)
    axes[0].set_yscale("log")
    axes[0].axhline(best_eps, color=ORANGE, linewidth=1)
    axes[0].text(len(kdist) * 0.02, best_eps * 1.15, f"выбранный eps = {best_eps} м", color=TEXT_2,
                 fontsize=9)
    axes[0].set_xlabel("POI, отсортированные по расстоянию")
    axes[0].set_ylabel("Расстояние до 10-го соседа, м (лог.)")
    axes[0].set_title("k-distance (k = 10)")
    positions = np.arange(len(eps_table))         # значения eps — равномерно по оси X
    axes[1].plot(positions, eps_table["settlement_f1"], color=BLUE, linewidth=2,
                 marker="o", markersize=6, markeredgecolor=SURFACE)
    axes[1].set_xticks(positions, [str(v) for v in eps_table["eps_m"]])
    axes[1].set_xlabel("eps, м")
    axes[1].set_ylabel("F1 по населённым пунктам")
    axes[1].set_title("Подбор eps на регионах tune")
    best_pos = int(np.flatnonzero(eps_table["eps_m"].to_numpy() == best_eps)[0])
    best_f1 = float(eps_table["settlement_f1"].iloc[best_pos])
    axes[1].annotate(f"max F1 = {best_f1:.3f}", (best_pos, best_f1), xytext=(0, 10),
                     textcoords="offset points", ha="center", fontsize=9, color=TEXT_2)
    axes[1].set_ylim(eps_table["settlement_f1"].min() - 0.01, best_f1 + 0.02)
    return save(fig, "fig09_eps_selection.png")


def plot_missing(pois: pd.DataFrame) -> str:
    """10. Аудит: доля пропусков по атрибутам POI."""
    cols = {"name": "название", "opening_hours": "часы работы", "phone": "телефон",
            "website": "сайт", "addr_street": "улица", "addr_housenumber": "номер дома",
            "name_ru": "name:ru", "name_kk": "name:kk", "brand": "бренд"}
    service = pois[pois["is_service"]]
    missing = (service[list(cols)].isna().mean() * 100).rename(cols).sort_values()
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.barh(missing.index, missing.values, color=BLUE, height=0.55)
    for i, v in enumerate(missing.values):
        ax.text(v + 1, i, f"{v:.0f}%", va="center", fontsize=8.5, color=TEXT)
    ax.set_xlim(0, 110)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Пропусков, % от сервисных POI")
    ax.set_title("Аудит качества: заполненность атрибутов POI")
    return save(fig, "fig10_missing_attributes.png")


def plot_cities_interactive(city_stats: pd.DataFrame) -> str:
    """11. Интерактивная диаграмма Plotly: население города vs POI на 100 тыс."""
    data = city_stats.copy()
    data["label"] = data["name_ru"].fillna(data["name"])
    fig = px.scatter(
        data, x="population", y="poi_per_100k", size="n_service_poi", color="city_group",
        hover_name="label", log_x=True, text="label",
        color_discrete_map={"Астана": BLUE, "Алматы": ORANGE, "Шымкент": AQUA,
                            "Другие города ≥100 тыс.": GRAY},
        hover_data={"population": ":,", "n_service_poi": ":,", "poi_per_100k": ":.0f",
                    "poi_per_km2": ":.1f", "label": False, "city_group": False},
        labels={"population": "Население (лог. шкала)", "poi_per_100k": "POI на 100 тыс.",
                "n_service_poi": "POI", "poi_per_km2": "POI на км²", "city_group": "Группа"},
        title="Города Казахстана: население и обеспеченность POI (размер точки — число POI)",
    )
    fig.update_traces(textposition="top center", textfont_size=10)
    fig.update_layout(paper_bgcolor=SURFACE, plot_bgcolor=SURFACE)
    path = config.FIG_DIR / "fig11_cities_interactive.html"
    fig.write_html(path, include_plotlyjs="cdn")
    log("  график: fig11_cities_interactive.html (интерактивный)")
    return str(path)


def plot_er_diagram() -> str:
    """ER-диаграмма базы данных (рисуется matplotlib, чтобы не зависеть от Graphviz)."""
    # таблица: (x, y нижнего левого угла, список полей)
    tables = {
        "regions": (0.02, 0.50, ["PK region_id", "iso_code", "name_ru / name_kk / name_en",
                                 "region_type", "area_km2", "pop_total / urban / rural"]),
        "pois": (0.38, 0.47, ["PK poi_id", "osm_type, osm_id", "FK type_id", "FK region_id",
                              "FK city_id", "name, brand", "lon, lat", "has_opening_hours ...",
                              "last_edit, version"]),
        "poi_types": (0.76, 0.64, ["PK type_id", "osm_key", "osm_value", "FK category_id"]),
        "categories": (0.76, 0.30, ["PK category_id", "code", "name_ru", "is_service"]),
        "building_stats": (0.02, 0.10, ["PK,FK region_id", "n_buildings", "n_with_levels"]),
        "cities": (0.26, 0.03, ["PK city_id", "name / name_ru / name_en", "FK region_id",
                                "city_group", "population", "area_km2"]),
        "poi_clusters": (0.51, 0.03, ["PK,FK poi_id", "PK,FK run_id", "cluster_label"]),
        "clustering_runs": (0.76, 0.00, ["PK run_id", "method, params", "n_clusters",
                                         "silhouette, F1 ...", "seconds, peak_mb"]),
    }
    row_h, width = 0.042, 0.2
    fig, ax = plt.subplots(figsize=(13, 7.5))
    ax.set_axis_off()
    boxes = {}
    for name, (x, y, fields) in tables.items():
        h = row_h * (len(fields) + 1)
        ax.add_patch(plt.Rectangle((x, y), width, h, facecolor="white", edgecolor=BLUE,
                                   linewidth=1.2, zorder=2))
        ax.add_patch(plt.Rectangle((x, y + h - row_h), width, row_h, facecolor=BLUE,
                                   edgecolor=BLUE, zorder=2))
        ax.text(x + 0.01, y + h - row_h / 2, name, color="white", fontsize=10,
                fontweight="bold", va="center", zorder=3)
        for i, field in enumerate(fields):
            ax.text(x + 0.01, y + h - row_h * (i + 1.5), field, fontsize=8.5, va="center",
                    zorder=3, color="#184f95" if field.startswith(("PK", "FK")) else TEXT)
        boxes[name] = (x, y, width, h)

    def anchor(name: str, side: str, frac: float = 0.5) -> tuple[float, float]:
        """Точка на стороне таблицы: side = left/right/top/bottom, frac — доля вдоль стороны."""
        x, y, w, h = boxes[name]
        if side == "left":
            return x, y + h * frac
        elif side == "right":
            return x + w, y + h * frac
        elif side == "top":
            return x + w * frac, y + h
        else:
            return x + w * frac, y

    def link(a, a_side, a_frac, b, b_side, b_frac, label):
        """Связь "многие → один": стрелка от таблицы a к таблице b, подпись посередине."""
        start, end = anchor(a, a_side, a_frac), anchor(b, b_side, b_frac)
        ax.annotate("", xy=end, xytext=start, zorder=1,
                    arrowprops={"arrowstyle": "-|>", "color": GRAY, "linewidth": 1.1})
        ax.text((start[0] + end[0]) / 2, (start[1] + end[1]) / 2, label, fontsize=8.5,
                color=TEXT_2, ha="center", va="center", zorder=3,
                bbox={"boxstyle": "round,pad=0.2", "facecolor": SURFACE, "edgecolor": "none"})

    link("pois", "left", 0.62, "regions", "right", 0.62, "N : 1")
    link("pois", "right", 0.75, "poi_types", "left", 0.5, "N : 1")
    link("poi_types", "bottom", 0.5, "categories", "top", 0.5, "N : 1")
    link("pois", "bottom", 0.15, "cities", "top", 0.8, "N : 0..1")
    link("cities", "left", 0.75, "regions", "bottom", 0.8, "N : 1")
    link("building_stats", "top", 0.5, "regions", "bottom", 0.3, "1 : 1")
    link("poi_clusters", "top", 0.6, "pois", "bottom", 0.75, "N : 1")
    link("poi_clusters", "right", 0.5, "clustering_runs", "left", 0.5, "N : 1")
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.02, 0.96)
    ax.set_title("ER-диаграмма базы kz_poi.db (SQLite): стрелка ведёт от «многих» к «одному»")
    path = config.FIG_DIR / "er_diagram.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    log("  график: er_diagram.png")
    return str(path)
