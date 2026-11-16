"""
Мини-дашборд Streamlit с фильтрами.

Запуск (после выполнения конвейера: python main.py --all):
    streamlit run app.py

Фильтры (боковая панель): регионы, категории, город, год последней правки,
"только с названием". Все вкладки перестраиваются по одному и тому же срезу данных.
"""
import json

import pandas as pd
import plotly.express as px
import streamlit as st

from src import config, database
from src.categories import CATEGORY_NAMES_RU, SERVICE_CATEGORIES
from src.search import nearest_pois

BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#8c8b86"
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

st.set_page_config(page_title="OSM Kazakhstan POI", layout="wide")


@st.cache_data
def load_data():
    """Загружает очищенные POI, показатели регионов/городов и границы (кэшируется)."""
    pois = pd.read_parquet(config.POIS_CLEAN_PATH)
    pois = pois[pois["is_service"]].copy()
    pois["category_ru"] = pois["category"].astype(str).map(CATEGORY_NAMES_RU)
    pois["region_ru"] = pois["region_iso"].astype(str).map(config.REGION_SHORT_RU)
    regions = pd.read_parquet(config.REGION_STATS_PATH)
    cities = pd.read_parquet(config.CITY_STATS_PATH)
    with open(config.REGIONS_GEOJSON, encoding="utf-8") as f:
        geojson = json.load(f)
    return pois, regions, cities, geojson


try:
    pois, regions, cities, geojson = load_data()
except FileNotFoundError:
    st.error("Нет обработанных данных. Сначала выполните конвейер: `python main.py --all`.")
    st.stop()

# ------------------------------------------------------------------ фильтры
st.sidebar.header("Фильтры")
region_options = sorted(regions["region_ru"])
# пустой выбор = "все" — так боковая панель остаётся компактной
sel_regions = st.sidebar.multiselect("Регион (пусто — все)", region_options) or region_options
cat_options = [CATEGORY_NAMES_RU[c] for c in SERVICE_CATEGORIES]
sel_cats = st.sidebar.multiselect("Категория (пусто — все)", cat_options) or cat_options
city_names = ["Все"] + cities.sort_values("population", ascending=False)["name_ru"].fillna(
    cities["name"]).tolist()
sel_city = st.sidebar.selectbox("Город", city_names)
year_min, year_max = int(pois["edit_year"].min()), int(pois["edit_year"].max())
sel_years = st.sidebar.slider("Год последней правки", year_min, year_max, (year_min, year_max))
only_named = st.sidebar.checkbox("Только POI с названием", value=False)

mask = (pois["region_ru"].isin(sel_regions) & pois["category_ru"].isin(sel_cats) &
        pois["edit_year"].between(*sel_years))
if sel_city != "Все":
    city_row = cities[(cities["name_ru"] == sel_city) | (cities["name"] == sel_city)].iloc[0]
    mask &= pois["city_id"] == city_row["city_id"]
if only_named:
    mask &= pois["has_name"]
view = pois[mask]

# ------------------------------------------------------------------ KPI
st.title("OpenStreetMap Kazakhstan: Points of Interest Analytics")
st.caption("Данные: OpenStreetMap (Geofabrik, ноябрь 2026), население — stat.gov.kz на 01.01.2026. "
           "Учитываются сервисные POI (без скамеек, урн, парковок).")
pop = regions[regions["region_ru"].isin(sel_regions)]["pop_total"].sum()
if sel_city != "Все":
    pop = city_row["population"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("POI в выборке", f"{len(view):,}".replace(",", " "))
c2.metric("POI на 100 тыс. жителей", f"{len(view) / pop * 1e5:.0f}" if pop else "—")
c3.metric("С названием", f"{view['has_name'].mean():.0%}" if len(view) else "—")
c4.metric("С часами работы", f"{view['oh_valid'].mean():.0%}" if len(view) else "—")

tab_regions, tab_map, tab_cities, tab_sql, tab_search = st.tabs(
    ["Регионы", "Карта точек", "Города", "SQL-запросы", "Поиск"])

# ------------------------------------------------------------------ вкладка "Регионы"
with tab_regions:
    by_region = view.groupby("region_iso", observed=True).size().rename("n").reset_index()
    by_region["region_iso"] = by_region["region_iso"].astype(str)
    data = regions.merge(by_region, left_on="iso_code", right_on="region_iso", how="inner")
    data["per_100k"] = (data["n"] / data["pop_total"] * 1e5).round(1)
    data["Тип"] = data["region_type"].map({"oblast": "Область", "city": "Город респ. значения"})
    left, right = st.columns(2)
    with left:
        fig = px.bar(data, x="per_100k", y="region_ru", orientation="h", color="Тип",
                     color_discrete_map={"Область": BLUE, "Город респ. значения": ORANGE},
                     labels={"per_100k": "POI на 100 тыс. жителей", "region_ru": ""},
                     title="POI на 100 тыс. жителей")
        # сортировка по значению (иначе Plotly группирует столбцы по цвету)
        fig.update_yaxes(categoryorder="total ascending")
        fig.update_layout(height=560, legend={"orientation": "h", "y": -0.15})
        st.plotly_chart(fig, use_container_width=True)
    with right:
        fig = px.choropleth(data, geojson=geojson, locations="iso_code",
                            featureidkey="properties.iso_code", color="per_100k",
                            color_continuous_scale=BLUE_RAMP, hover_name="region_ru",
                            labels={"per_100k": "на 100 тыс."}, title="Карта обеспеченности")
        fig.update_geos(fitbounds="locations", visible=False)
        fig.update_layout(height=560, margin={"l": 0, "r": 0, "t": 40, "b": 0})
        st.plotly_chart(fig, use_container_width=True)
    st.dataframe(data[["region_ru", "n", "pop_total", "per_100k"]]
                 .rename(columns={"region_ru": "Регион", "n": "POI", "pop_total": "Население",
                                  "per_100k": "На 100 тыс."})
                 .sort_values("На 100 тыс.", ascending=False), hide_index=True)

# ------------------------------------------------------------------ вкладка "Карта"
with tab_map:
    sample = view.sample(min(len(view), 15_000), random_state=config.RANDOM_STATE)
    st.caption(f"Показано {len(sample):,} из {len(view):,} точек (случайная выборка для скорости).")
    if 0 < len(sel_cats) <= 3:
        # цвет по категории — только если категорий ≤ 3 (иначе цвета неразличимы)
        palette = dict(zip(sel_cats, [BLUE, ORANGE, AQUA]))
        fig = px.scatter_map(sample, lat="lat", lon="lon", color="category_ru",
                             color_discrete_map=palette, hover_name="name",
                             hover_data={"feature_value": True, "lat": False, "lon": False},
                             zoom=4, height=620, map_style="carto-positron")
    else:
        fig = px.scatter_map(sample, lat="lat", lon="lon", hover_name="name",
                             hover_data={"category_ru": True, "feature_value": True,
                                         "lat": False, "lon": False},
                             color_discrete_sequence=[BLUE], zoom=4, height=620,
                             map_style="carto-positron")
    fig.update_traces(marker={"size": 5})
    st.plotly_chart(fig, use_container_width=True)
    st.download_button("Скачать выборку (CSV)",
                       view[["name", "category_ru", "feature_value", "region_ru", "lat", "lon"]]
                       .to_csv(index=False).encode("utf-8-sig"), "pois_filtered.csv", "text/csv")

# ------------------------------------------------------------------ вкладка "Города"
with tab_cities:
    show = cities.copy()
    show["Город"] = show["name_ru"].fillna(show["name"])
    fig = px.scatter(show, x="population", y="poi_per_100k", size="n_service_poi",
                     color="city_group", text="Город", log_x=True,
                     color_discrete_map={"Астана": BLUE, "Алматы": ORANGE, "Шымкент": AQUA,
                                         "Другие города ≥100 тыс.": GRAY},
                     labels={"population": "Население (лог.)", "poi_per_100k": "POI на 100 тыс.",
                             "city_group": "Группа"}, height=520)
    fig.update_traces(textposition="top center")
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(show[["Город", "city_group", "population", "n_service_poi", "poi_per_100k",
                       "poi_per_km2", "population_source"]].round(1), hide_index=True)

# ------------------------------------------------------------------ вкладка "SQL"
with tab_sql:
    queries = database.parse_queries()
    names = [f"{q['name']} — {q['desc']}" for q in queries]
    chosen = st.selectbox("Запрос", names)
    query = queries[names.index(chosen)]
    st.code(query["sql"], language="sql")
    try:
        conn = database.connect()
        st.dataframe(pd.read_sql_query(query["sql"], conn), hide_index=True)
        conn.close()
    except Exception as err:          # база не создана или запрос не выполнился
        st.warning(f"Не удалось выполнить запрос: {err}")

# ------------------------------------------------------------------ вкладка "Поиск"
with tab_search:
    left, right = st.columns(2)
    with left:
        st.subheader("По названию")
        text = st.text_input("Часть названия", "Magnum")
        city = st.text_input("Город (необязательно)", "")
        if text:
            conn = database.connect()
            st.dataframe(database.search_pois(conn, text, city=city or None, limit=50),
                         hide_index=True)
            conn.close()
    with right:
        st.subheader("Ближайшие к точке")
        lat = st.number_input("Широта", value=51.1283, format="%.4f")
        lon = st.number_input("Долгота", value=71.4305, format="%.4f")
        cat = st.selectbox("Категория", ["любая"] + cat_options)
        code = None if cat == "любая" else [k for k, v in CATEGORY_NAMES_RU.items() if v == cat][0]
        try:
            st.dataframe(nearest_pois(lat, lon, category=code, k=10, pois=pois), hide_index=True)
        except ValueError as err:
            st.warning(str(err))
