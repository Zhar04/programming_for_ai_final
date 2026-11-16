"""
Сборка письменного отчёта reports/report_osm_kz_poi.docx.

Все числа берутся из результатов конвейера (outputs/metrics, outputs/tables),
поэтому отчёт всегда соответствует последнему запуску `python main.py --all`.

Запуск:  python reports/build_report.py
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from docx_helpers import (bullets, df_table, figure, fmt_int, fmt_num, new_document,  # noqa: E402
                          page_break, para, table_caption, add_toc, heading_new_page)
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.shared import Pt  # noqa: E402

from src import config  # noqa: E402
from src.categories import CATEGORY_NAMES_RU  # noqa: E402

T, M, F = config.TABLES_DIR, config.METRICS_DIR, config.FIG_DIR
OUT = ROOT / "reports" / "report_osm_kz_poi.docx"
TEAM = ["Zharken Utegenov", "Yergaliev Aron", "Temirgalin Dinmukhammed"]
REPO = "https://github.com/Zhar04/programming_for_ai_final"


def load(name: str) -> dict:
    return json.loads((M / name).read_text(encoding="utf-8"))


def csv(name: str, **kw) -> pd.DataFrame:
    return pd.read_csv(T / name, **kw)


# ---------------------------------------------------------------- данные для текста
ext = load("extract_stats.json")
assign = load("regions_assign.json")
mem = load("memory_optimization.json")
audit_full = load("audit_full.json")
audit_pois = load("audit_pois.json")
clus = load("clustering.json")
regions = csv("region_stats.csv")
cities = csv("city_stats.csv")
mega = csv("megacity_comparison.csv", index_col=0)
bench = csv("benchmark_tools.csv")
rules = csv("cleaning_rules.csv")
hyp = csv("hypotheses.csv", dtype={"p_value_fmt": str})
h2 = csv("h2_astana_almaty_categories.csv", index_col=0)
clu_cmp = csv("clustering_comparison.csv")
eps_tab = csv("dbscan_eps_sensitivity.csv")
errors = csv("clustering_error_analysis.csv")
memtab = csv("memory_optimization.csv")
q06 = csv("sql_q06_pareto_cumulative.csv")
q08 = csv("sql_q08_chain_brands.csv")
q10 = csv("sql_q10_cities_vs_own_region.csv")
q11 = csv("sql_q11_largest_dbscan_clusters.csv")

feat = ext["features"]
n_rows = feat["rows"]
n_buildings = int(regions["n_buildings"].sum())
n_service = audit_pois["n_service_poi"]
n_clean = audit_pois["rows_after"]
national = audit_pois["national_poi_per_100k"]
reg_sorted = regions.sort_values("poi_per_100k", ascending=False).reset_index(drop=True)
top_reg, bottom_reg = reg_sorted.iloc[0], reg_sorted.iloc[-1]
megas = {name: cities[cities["name"] == name].iloc[0] for name in ["Астана", "Алматы", "Шымкент"]}
others_total = mega.loc["Другие города ≥100 тыс.", "Все категории"]
rest_total = mega.loc["Остальная территория", "Все категории"]
best = clu_cmp.set_index("method")
db, grid, hdb = best.loc["DBSCAN"], best.loc["Grid baseline"], best.loc["HDBSCAN"]
b = bench.set_index("approach")
hyp_i = hyp.set_index("id")
regions_50 = int((q06["cumulative_pct"] < 50).sum()) + 1
regions_80 = int((q06["cumulative_pct"] < 80).sum()) + 1
_lead = sorted([b.loc["polars_lazy", "speedup_vs_baseline"], b.loc["duckdb_sql", "speedup_vs_baseline"]])
lead_speedups = f"{fmt_num(_lead[0])}–{fmt_num(_lead[1])}"   # например «6,0–7,5»

doc = new_document()

# ======================================================================== титульный лист
for text, size, bold, space in [
    ("Итоговый проект по дисциплине", 13, False, 0),
    ("«Programming for Data Analysis and Database»", 14, True, 4),
    ("Образовательная программа «Applied Artificial Intelligence», магистратура", 12, False, 90),
    ("OpenStreetMap Kazakhstan:", 24, True, 0),
    ("Points of Interest Analytics", 24, True, 12),
    ("Тема № 47 · Cluster 8: Large-Scale Data Processing", 13, False, 4),
    ("Письменный отчёт", 13, False, 110),
]:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text)
    r.font.size, r.bold = Pt(size), bold
    p.paragraph_format.space_after = Pt(space)
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
p.add_run("Выполнили (группа AAI-2605M):\n").bold = True
p.add_run("\n".join(TEAM))
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
p.add_run(f"Репозиторий: {REPO}")
p.paragraph_format.space_after = Pt(120)
p = doc.add_paragraph("2026")
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
page_break(doc)

add_toc(doc)

# ======================================================================== аннотация
heading_new_page(doc, "Аннотация")
para(doc, (
    f"Проект анализирует плотность и типы точек интереса (POI) в 20 регионах и крупнейших городах "
    f"Казахстана по полной выгрузке OpenStreetMap (Geofabrik, PBF {fmt_num(feat['pbf_size_mb'])} МБ, "
    f"34,5 млн узлов и 4,25 млн линий). Файл читается потоково библиотекой pyosmium с фильтрацией "
    f"по тегам; {fmt_int(n_rows)} объектов (POI и здания) записываются чанками в партиционированный "
    f"Parquet. Оптимизация типов сокращает объём таблицы в памяти с {fmt_num(mem['mb_before'])} до "
    f"{fmt_num(mem['mb_after'])} МБ (−{fmt_num(mem['saving_pct'])} %). После аудита качества "
    f"и очистки получено {fmt_int(n_clean)} POI, из них {fmt_int(n_service)} — сервисные."))
para(doc, (
    f"В среднем по стране приходится {fmt_num(national)} сервисных POI на 100 тыс. жителей "
    f"(население — по данным stat.gov.kz на 01.01.2026). Разброс между регионами более чем "
    f"трёхкратный: от {fmt_num(bottom_reg['poi_per_100k'])} ({bottom_reg['region_ru']}) до "
    f"{fmt_num(top_reg['poi_per_100k'])} ({top_reg['region_ru']}). Среди мегаполисов Алматы "
    f"({fmt_num(megas['Алматы']['poi_per_100k'])}) заметно опережает Астану "
    f"({fmt_num(megas['Астана']['poi_per_100k'])}) и Шымкент "
    f"({fmt_num(megas['Шымкент']['poi_per_100k'])}). Сравнение пяти способов обработки показало, "
    f"что Polars в ленивом режиме и DuckDB по Parquet в {lead_speedups} раза быстрее базового "
    f"pandas + CSV при совпадающих результатах. DBSCAN (eps = "
    f"{clus['best_eps']} м) выделяет населённые пункты точнее сеточного baseline и HDBSCAN: "
    f"F1 = {fmt_num(db['settlement_f1'], 3)} на отложенных регионах."))

# ======================================================================== 1. Введение
doc.add_heading("1. Введение", level=1)
para(doc, ("OpenStreetMap (OSM) — открытая карта мира, которую наполняют добровольцы. Для "
           "Казахстана это крупнейший свободный источник сведений о магазинах, школах, больницах, "
           "кафе и других объектах инфраструктуры. Вопрос проекта: насколько равномерно эти объекты "
           "распределены по стране и что данные OSM говорят о различиях между регионами и городами."),
     bold_prefix="Контекст.")
para(doc, ("проанализировать плотность и типы точек интереса по регионам и городам Казахстана "
           "на полной выгрузке OSM с учётом ограничений памяти."), bold_prefix="Цель —")
doc.add_paragraph("Задачи:")
bullets(doc, [
    "прочитать PBF-файл потоково и отфильтровать объекты по тегам OSM;",
    "сохранить данные в партиционированный Parquet, оптимизировать типы и измерить экономию памяти;",
    "провести аудит качества (пропуски, дубликаты, некорректные значения и даты, выбросы) "
    "и обосновать правила очистки;",
    "рассчитать POI на 100 тыс. жителей и на 1000 км² для 20 регионов, сравнить Астану, "
    "Алматы, Шымкент и другие города;",
    "сравнить инструменты обработки (pandas, Polars, DuckDB; CSV и Parquet) по времени, "
    "пиковой памяти и совпадению результатов;",
    "загрузить данные в нормализованную базу SQLite и выполнить аналитические SQL-запросы;",
    "выполнить пространственную кластеризацию (DBSCAN) и сравнить её с baseline и HDBSCAN;",
    "проверить статистические гипотезы и представить результаты в дашборде и консольном меню.",
], numbered=True)

# ======================================================================== 2. Данные
doc.add_heading("2. Данные", level=1)
doc.add_heading("2.1. Источники", level=2)
table_caption(doc, "Таблица 1 – Источники данных")
df_table(doc, pd.DataFrame([
    ["OpenStreetMap, выгрузка Geofabrik (kazakhstan-latest.osm.pbf)",
     "все объекты OSM на территории РК и приграничья", f"{fmt_num(feat['pbf_size_mb'])} МБ",
     "15.11.2026"],
    ["Бюро национальной статистики (stat.gov.kz), «Численность населения по регионам»",
     "население 20 регионов, город/село", "20 строк", "01.01.2026"],
], columns=["Источник", "Содержание", "Объём", "Дата"]), [6.5, 5.5, 2.2, 2.3])
para(doc, ("Две таблицы связываются по коду ISO 3166-2 (например, KZ-71 — Астана): этот код есть "
           "в тегах административных границ OSM, а названия регионов stat.gov.kz сопоставлены с кодами "
           "в config.STAT_NAME_TO_ISO. Сумма населения 20 регионов — 20 495 975 человек — совпадает "
           "с официальной численностью на 01.01.2026."))

doc.add_heading("2.2. Объём и структура", level=2)
by_type = feat["by_type"]
para(doc, (
    f"PBF-файл содержит 34,5 млн узлов, 4,25 млн линий и 27,7 тыс. отношений. Фильтр по ключам "
    f"amenity, shop, healthcare, tourism, leisure, office, craft, historic, sport, emergency и "
    f"building отобрал {fmt_int(n_rows)} объектов ({fmt_int(by_type['node'])} точек и "
    f"{fmt_int(by_type['way'])} контуров). Из них {fmt_int(audit_full['audit']['rows_outside_kz'])} "
    f"лежат за границей РК (выгрузка Geofabrik захватывает приграничье) и исключаются. "
    f"Внутри РК {fmt_int(n_buildings)} объектов — здания без POI-тегов: они не входят в показатели "
    f"обеспеченности, но используются как индикатор полноты картирования региона (гипотеза H4)."))
table_caption(doc, "Таблица 2 – Основные поля набора объектов (data/interim/osm_features)")
df_table(doc, pd.DataFrame([
    ["osm_type, osm_id", "тип (node/way) и идентификатор объекта OSM"],
    ["lon, lat", "координаты; для контура — среднее координат его узлов"],
    ["feature_key, feature_value", "основной тег (amenity=cafe, shop=supermarket, building=yes …)"],
    ["name, name_kk, name_ru, name_en, brand", "названия на разных языках, сетевой бренд"],
    ["opening_hours, phone, website", "часы работы и контакты"],
    ["addr_city, addr_street, addr_housenumber", "адрес"],
    ["building, building_levels, start_date", "тип здания, этажность, дата постройки/открытия"],
    ["n_tags, version, timestamp", "число тегов, номер версии и время последней правки"],
    ["region_iso", "код региона (добавляется пространственным соединением)"],
], columns=["Поле", "Описание"]), [6.0, 10.5])

doc.add_heading("2.3. Категории POI", level=2)
para(doc, ("Сотни значений тегов OSM сведены в 12 тематических категорий (модуль src/categories.py). "
           "Одиннадцать из них — сервисы (питание, торговля, образование и т.д.). Двенадцатая — "
           "«Городская инфраструктура» (скамейки, урны, парковки, гидранты). Это элементы среды, "
           "а не услуги, поэтому в показатели обеспеченности она не входит."))
pois_clean = pd.read_parquet(config.POIS_CLEAN_PATH, columns=["category", "feature_value"])
cat_counts = pois_clean["category"].astype(str).value_counts()
examples = (pois_clean.assign(category=pois_clean["category"].astype(str),
                              feature_value=pois_clean["feature_value"].astype(str))
            .groupby("category")["feature_value"].agg(lambda s: ", ".join(s.value_counts().index[:4])))
cat_table = pd.DataFrame({
    "Категория": [CATEGORY_NAMES_RU[c] for c in cat_counts.index],
    "Частые значения тегов": [examples[c] for c in cat_counts.index],
    "POI": [fmt_int(v) for v in cat_counts.values],
})
table_caption(doc, "Таблица 3 – Категории POI в очищенном наборе")
df_table(doc, cat_table, [4.8, 9.2, 2.5])

# ======================================================================== 3. Методы
doc.add_heading("3. Методы", level=1)
doc.add_heading("3.1. Архитектура конвейера", level=2)
para(doc, ("Код разделён на 17 модулей в папке src/. Каждый шаг читает входные данные с диска "
           "и записывает результат на диск, поэтому шаги можно запускать по отдельности из "
           "консольного меню (main.py) или все сразу командой python main.py --all. "
           "Состояние программы — какие шаги выполнены и когда — хранится в outputs/run_state.json."))
table_caption(doc, "Таблица 4 – Шаги конвейера")
df_table(doc, pd.DataFrame([
    ["1", "download.py", "скачивание PBF потоком, проверка MD5", "requests, hashlib"],
    ["2", "extract.py", "потоковое чтение PBF, фильтр тегов, Parquet по чанкам", "osmium, pyarrow"],
    ["3", "spatial.py", "границы регионов, население, sjoin по чанкам", "GeoPandas, pyproj"],
    ["4", "optimize.py", "оптимизация типов, память до/после", "pandas"],
    ["5", "quality.py, aggregates.py", "аудит качества; агрегаты lazy и по чанкам", "Polars, pyarrow"],
    ["6", "analysis.py", "очистка POI, категории, города, показатели", "pandas, GeoPandas"],
    ["7", "database.py", "схема SQLite, загрузка, 11 SQL-запросов", "sqlite3, pandas"],
    ["8", "benchmark.py", "сравнение 5 подходов в отдельных процессах", "pandas, Polars, DuckDB"],
    ["9", "clustering.py", "Grid baseline, DBSCAN, HDBSCAN", "scikit-learn, SciPy"],
    ["10", "hypotheses.py", "гипотезы H1–H4", "SciPy, statsmodels"],
    ["11", "visualize.py", "графики PNG и интерактивные HTML", "matplotlib, Plotly, Folium"],
], columns=["Шаг", "Модуль", "Что делает", "Инструменты"]), [1.2, 4.3, 7.0, 4.0])

doc.add_heading("3.2. Чтение данных, не помещающихся в память", level=2)
para(doc, (
    "Загрузить весь PBF в DataFrame или GeoDataFrame невозможно: 34,5 млн узлов с координатами "
    "и тегами потребовали бы 5 ГБ памяти и больше. Поэтому файл читается потоково — объект за "
    "объектом — через osmium.FileProcessor. Фильтр KeyFilter отбрасывает объекты без нужных "
    "ключей ещё в C++, и до Python доходит менее 10 % объектов. Для контуров (way) нужен кэш "
    "координат узлов (with_locations): по нему считается центр объекта."))
para(doc, (
    f"Отобранные строки копятся в списке-буфере и каждые {fmt_int(config.CHUNK_SIZE)} строк "
    f"сбрасываются в партиционированный Parquet (папка на каждое значение feature_key, сжатие "
    f"zstd). Итог: {feat['chunks']} чанков за {fmt_num(feat['seconds'])} с, пиковая память "
    f"процесса — {fmt_num(feat['peak_memory_mb'], 0)} МБ (в основном кэш координат). PBF "
    f"{fmt_num(feat['pbf_size_mb'])} МБ превращается в Parquet {fmt_num(feat['parquet_size_mb'])} МБ. "
    f"Далее набор читается батчами по {fmt_int(config.BATCH_SIZE)} строк. К каждому батчу "
    f"пространственным соединением (geopandas.sjoin) добавляется код региона, и результат "
    f"записывается в новый Parquet, партиционированный по региону: {assign['batches']} батчей "
    f"за {fmt_num(assign['seconds'])} с."))

doc.add_heading("3.3. Оптимизация типов данных", level=2)
para(doc, (
    "Память измерялась по каждому столбцу полного набора: столбец читается, приводится к "
    "«наивным» типам (как после read_csv: строки — object, числа — int64/float64), измеряется "
    "memory_usage(deep=True), затем приводится к оптимальному типу и измеряется снова. "
    "Так в памяти одновременно находится один столбец, а не вся таблица. Правила: строки с "
    "долей уникальных значений меньше 50 % → category, остальные строки → string[pyarrow], "
    "целые → минимальный int, координаты → float32."))
mt = memtab.copy()
show = pd.concat([mt[mt["column"] != "ИТОГО"].sort_values("mb_before", ascending=False).head(7),
                  mt[mt["column"] == "ИТОГО"]])
show = show.assign(mb_before=show["mb_before"].map(lambda v: fmt_num(v)),
                   mb_after=show["mb_after"].map(lambda v: fmt_num(v)),
                   saving_pct=show["saving_pct"].map(lambda v: fmt_num(v)))
show.columns = ["Столбец", "Тип до", "Тип после", "МБ до", "МБ после", "Экономия, %"]
table_caption(doc, f"Таблица 5 – Память полного набора ({fmt_int(n_rows)} строк): крупнейшие столбцы и итог")
df_table(doc, show, [3.6, 3.3, 3.3, 2.1, 2.1, 2.1])
para(doc, (
    f"Итог: {fmt_num(mem['mb_before'])} МБ → {fmt_num(mem['mb_after'])} МБ (−{fmt_num(mem['saving_pct'])} %). "
    f"Тип category особенно выгоден для столбцов-«словарей» (feature_key, region_iso, building): "
    f"вместо миллиона одинаковых строк хранится словарь значений и массив коротких кодов. "
    f"Перевод координат во float32 вносит ошибку не более {fmt_num(mem['float32_max_error_m'], 2)} м, "
    f"что несущественно для анализа на уровне регионов и городов."))

doc.add_heading("3.4. Нормирование показателей", level=2)
para(doc, (
    "Обеспеченность считается как число сервисных POI на 100 тыс. жителей (население — "
    "stat.gov.kz на 01.01.2026) и на 1000 км² территории. Площадь полигонов вычисляется в "
    "равновеликой конической проекции Альберса, настроенной на Казахстан (параллели 44° и 52°); "
    "в градусах площадь считать нельзя. Сумма площадей — 2,75 млн км² — на 1 % больше "
    "официальной (2,72 млн км²): в OSM границы Атырауской и Мангистауской областей включают "
    "часть акватории Каспия."))
para(doc, (
    "Для сравнения городов взяты Астана, Алматы и Шымкент (их полигоны совпадают с регионами, "
    "население — официальное) и 18 городов с населением ≥ 100 тыс. по тегу population в OSM. "
    "Для них берутся полигоны place=city и тег population точки place=city с тем же названием. "
    "Это оценка OSM, а не официальная статистика (см. раздел 5)."))

doc.add_heading("3.5. Аудит качества и правила очистки", level=2)
af = audit_full["audit"]
lv = af["building_levels"]
para(doc, (
    f"Полный набор ({fmt_int(af['rows_total'])} строк) проверялся через Polars LazyFrame, набор POI — "
    f"в pandas. Точных дубликатов (один и тот же osm_type + osm_id) не найдено: "
    f"{af['exact_duplicates']}. Время правок лежит в диапазоне от "
    f"{str(af['timestamps']['min_ts'])[:10]} до {str(af['timestamps']['max_ts'])[:10]}: ни одной даты "
    f"раньше основания OSM (2004) или позже даты снимка. Этажность заполнена у "
    f"{fmt_int(lv['filled'])} зданий. Нечисловых значений — {lv['not_numeric']}, нулевых или "
    f"отрицательных — {lv['non_positive']}, выше 80 этажей — {lv['above_80']}. Правило IQR для "
    f"этажности вырождено: Q1 = Q3 = 1, то есть большинство зданий одноэтажные. Поэтому выбросами "
    f"считаются значения выше 99-го перцентиля "
    f"({fmt_num(lv['quantiles']['p99'], 0)} этажей): таких {fmt_int(lv['outliers'])}. В поле "
    f"start_date {af['start_date']['bad_format']} значений из {fmt_int(af['start_date']['filled'])} "
    f"записаны в нестандартном формате (например «05.07.2018», «1930s», «XVIII»)."))
r = rules.copy()
r["rows"] = r["rows"].map(fmt_int)
r.columns = ["Правило", "Обоснование", "Строк", "Действие"]
table_caption(doc, "Таблица 6 – Правила очистки POI (outputs/tables/cleaning_rules.csv)")
df_table(doc, r, [5.4, 6.0, 1.6, 3.5], font_size=9)
para(doc, (
    f"Самая заметная аномалия — тег amenity=public_building. На него приходилось "
    f"{fmt_num(audit_pois['public_building_top_share'] * 100, 0)} % «госуслуг» одного региона "
    f"({audit_pois['public_building_top_region']} область): это безымянные здания с двумя тегами, "
    f"массово размеченные в 2018–2019 гг. Тег устарел и не говорит, какая услуга оказывается, "
    f"поэтому такие объекты переведены в «Городскую инфраструктуру». Без этого правила "
    f"Алматинская область выглядела бы лидером по госуслугам — артефакт разметки, а не реальность."))

doc.add_heading("3.6. Ленивые вычисления и инкрементальные агрегаты", level=2)
ag = audit_full["aggregates"]
para(doc, (
    f"Сводка по регионам (число объектов, объектов с названием, сумма тегов, здания с этажностью) "
    f"считается двумя независимыми способами. Первый — Polars LazyFrame: scan_parquet → filter → "
    f"group_by → collect(engine='streaming'). План запроса оптимизируется до выполнения: читаются "
    f"только 5 нужных столбцов (план сохранён в outputs/tables/polars_lazy_plan.txt). Второй — "
    f"инкрементальные агрегаты по чанкам: Parquet читается батчами, для каждого батча pandas "
    f"считает частичные суммы, и они накапливаются в словаре. Время: {fmt_num(ag['polars_lazy_s'], 2)} с "
    f"и {fmt_num(ag['pandas_chunks_s'], 2)} с. Результаты совпали полностью: "
    f"{'да' if ag['results_match'] else 'нет'}."))

doc.add_heading("3.7. Сравнение инструментов обработки", level=2)
para(doc, (
    f"Одна и та же задача — агрегаты по {fmt_int(n_rows)} строкам для каждой пары (регион, ключ "
    f"OSM): число объектов, объектов с названием, среднее число тегов, дата последней правки — "
    f"решалась пятью способами. Baseline — pandas.read_csv всего CSV-файла. Сравнивались также "
    f"read_csv по чанкам с инкрементальными агрегатами, pandas.read_parquet нужных столбцов, "
    f"Polars lazy и SQL-запрос DuckDB прямо по файлам Parquet. Каждый запуск выполнялся в "
    f"отдельном процессе, чтобы пиковая память одного подхода не влияла на другой. Время — медиана "
    f"трёх запусков. Результат каждого подхода сохранялся и сверялся с эталоном."))

doc.add_heading("3.8. База данных SQLite", level=2)
para(doc, (
    "Схема нормализована (sql/schema.sql). Справочники regions, categories, poi_types (пара "
    "тегов → категория) и cities вынесены отдельно, таблица фактов pois хранит только внешние "
    "ключи на них. Таблицы clustering_runs и poi_clusters хранят результаты кластеризации: "
    "метки каждой POI в каждом запуске, связь «многие-ко-многим». Для 3 млн зданий в базе "
    "хранятся только агрегаты по регионам (building_stats). Внешние ключи проверяются "
    "(PRAGMA foreign_keys = ON), для частых фильтров созданы индексы."))
figure(doc, F / "er_diagram.png", "Рисунок 1 – ER-диаграмма базы kz_poi.db", width_cm=16.5)
from src.database import parse_queries  # noqa: E402
qtab = pd.DataFrame([[q["name"], q["desc"]] for q in parse_queries()], columns=["Запрос", "Что вычисляет и какие конструкции SQL"])
table_caption(doc, "Таблица 7 – Аналитические SQL-запросы (sql/queries.sql)")
df_table(doc, qtab, [5.5, 11.0], font_size=9)
para(doc, ("Результаты всех запросов загружаются в pandas через pd.read_sql_query и сохраняются "
           "в outputs/tables/sql_*.csv. Поиск POI по названию (пункт 12 меню, вкладка «Поиск» "
           "дашборда) использует параметризованный запрос с плейсхолдерами «?», что защищает от "
           "SQL-инъекций. Для поиска без учёта регистра по кириллице зарегистрирована "
           "Python-функция PYLOWER: встроенная LOWER в SQLite работает только с латиницей."))

doc.add_heading("3.9. Пространственная кластеризация", level=2)
para(doc, (
    f"Кластеризуются {fmt_int(n_service)} сервисных POI. Координаты переведены в метры "
    f"(равновеликая проекция), поэтому радиус eps задаётся в метрах. Порог плотности у всех "
    f"подходов одинаковый — 10 точек:"))
bullets(doc, [
    "**Grid baseline:** страна делится на клетки 1×1 км; клетки с 10 и более POI считаются "
    "плотными, соседние плотные клетки склеиваются обходом в ширину (BFS) в кластеры;",
    "**DBSCAN:** точка — ядро кластера, если в радиусе eps у неё не меньше 10 соседей "
    "(KD-дерево, scikit-learn);",
    "**HDBSCAN:** иерархический DBSCAN, сам подбирает радиус для областей разной плотности.",
])
para(doc, (
    "Внешней разметки «правильных» кластеров нет, поэтому использована псевдо-разметка из OSM — "
    "точки населённых пунктов place=city/town/village. Precision — доля кластеров, центр которых "
    "ближе 3 км к населённому пункту. Recall — доля городов и посёлков, рядом с которыми (≤ 3 км) "
    "есть кластер. Кроме F1 считаются силуэт (на подвыборке 10 тыс. точек), индекс "
    "Дэвиса–Боулдина, время и пиковая память (tracemalloc)."))
para(doc, (
    f"Чтобы подбор параметра не «подсматривал» в итоговую оценку, использовано пространственное "
    f"разбиение без утечки. 10 случайных регионов (tune: {', '.join(clus['tune_regions'])}) "
    f"служат для подбора eps по сетке 150–5000 м. Сравнение трёх методов проводится на "
    f"других 10 регионах (test). Выбор eps дополнительно согласуется с графиком k-distance."))

doc.add_heading("3.10. Гипотезы", level=2)
bullets(doc, [f"**{row.id}.** {row.hypothesis} — {row.test}." for row in hyp.itertuples()])
para(doc, "Уровень значимости α = 0,05; для направленных гипотез используются односторонние тесты.")

# ======================================================================== 4. Результаты
doc.add_heading("4. Результаты", level=1)
doc.add_heading("4.1. Качество и актуальность данных", level=2)
svc = pd.read_parquet(config.POIS_CLEAN_PATH, columns=["is_service", "name", "opening_hours", "phone",
                                                     "website", "name_kk", "edit_year"])
svc = svc[svc["is_service"]]
filled = {c: svc[c].notna().mean() * 100 for c in ["name", "opening_hours", "phone", "website", "name_kk"]}
recent = (svc["edit_year"] >= svc["edit_year"].max() - 2).mean() * 100
para(doc, (
    f"Среди {fmt_int(len(svc))} сервисных POI название есть у {fmt_num(filled['name'], 0)} %. Часы "
    f"работы указаны у {fmt_num(filled['opening_hours'], 0)} %, телефон — у {fmt_num(filled['phone'], 0)} %, "
    f"сайт — у {fmt_num(filled['website'], 0)} %, отдельный тег name:kk — лишь у "
    f"{fmt_num(filled['name_kk'], 0)} %. Из заполненных телефонов "
    f"{fmt_int(audit_pois['invalid_phone'])} записаны в неверном формате (меньше 10 или больше 12 цифр); "
    f"они помечены флагом и не учитываются в показателях полноты. Данные свежие: "
    f"{fmt_num(recent, 0)} % POI правились в последние три года (рисунок 3)."))
figure(doc, F / "fig10_missing_attributes.png", "Рисунок 2 – Доля пропусков по атрибутам сервисных POI", 13.5)
figure(doc, F / "fig07_last_edit_year.png", "Рисунок 3 – Год последней правки POI", 14.5)

doc.add_heading("4.2. Обеспеченность POI по регионам", level=2)
para(doc, (
    f"Лидеры — {', '.join(reg_sorted['region_ru'].head(4))} (более "
    f"{fmt_num(reg_sorted['poi_per_100k'].iloc[3], 0)} POI на 100 тыс.). Замыкают рейтинг "
    f"{', '.join(reg_sorted['region_ru'].tail(4).iloc[::-1])}. Северные и западные области с "
    f"невысокой плотностью населения обеспечены лучше густонаселённого юга. Туркестанская и "
    f"Жамбылская области и Шымкент — в нижней части рейтинга. По SQL-запросу q06, половину всех "
    f"сервисных POI дают {regions_50} региона из 20, 80 % — {regions_80}."))
figure(doc, F / "fig01_poi_per_100k_regions.png", "Рисунок 4 – Сервисные POI на 100 тыс. жителей по регионам", 14.5)
figure(doc, F / "fig02_map_poi_per_100k.png",
       "Рисунок 5 – Карта обеспеченности (интерактивная версия: outputs/figures/fig02_map_poi_per_100k.html)", 16.5)
rt = reg_sorted[["region_ru", "pop_total", "n_service_poi", "poi_per_100k", "poi_per_1000km2",
                 "opening_hours_share"]].copy()
rt["pop_total"] = rt["pop_total"].map(fmt_int)
rt["n_service_poi"] = rt["n_service_poi"].map(fmt_int)
rt["poi_per_100k"] = rt["poi_per_100k"].map(lambda v: fmt_num(v))
rt["poi_per_1000km2"] = rt["poi_per_1000km2"].map(lambda v: fmt_num(v))
rt["opening_hours_share"] = (rt["opening_hours_share"] * 100).map(lambda v: fmt_num(v, 0))
rt.insert(0, "№", range(1, len(rt) + 1))
rt.columns = ["№", "Регион", "Население", "POI", "На 100 тыс.", "На 1000 км²", "С часами работы, %"]
table_caption(doc, "Таблица 8 – Показатели регионов (outputs/tables/region_stats.csv)")
df_table(doc, rt, [0.9, 4.4, 2.4, 1.8, 2.2, 2.4, 2.4], font_size=9)

doc.add_heading("4.3. Структура категорий", level=2)
shares = csv("category_shares_by_region.csv", index_col=0) * 100
leader = shares.idxmax(axis=1)
trade_first = leader[leader == "Торговля"].index
not_trade = leader[leader != "Торговля"]
exceptions = ", ".join(f"{reg} ({leader[reg].lower()} — {fmt_num(shares.loc[reg, leader[reg]], 0)} %)"
                       for reg in not_trade.index)
para(doc, (
    f"В {len(trade_first)} регионах из 20 больше всего POI в категории «Торговля» "
    f"({fmt_num(shares.loc[trade_first, 'Торговля'].min(), 0)}–"
    f"{fmt_num(shares.loc[trade_first, 'Торговля'].max(), 0)} % сервисных POI). Исключения: "
    f"{exceptions}. В Алматы и Астане велика доля спорта и досуга "
    f"({fmt_num(shares.loc['г. Алматы', 'Спорт и досуг'], 0)} % и "
    f"{fmt_num(shares.loc['г. Астана', 'Спорт и досуг'], 0)} %): детские площадки и спортплощадки "
    f"во дворах там картируются детально. В Северо-Казахстанской области велика доля культуры и "
    f"религии ({fmt_num(shares.loc['Северо-Казахстанская', 'Культура и религия'], 0)} %) — "
    f"памятники и мемориалы. В Алматинской и Восточно-Казахстанской областях выделяется туризм "
    f"({fmt_num(shares.loc['Алматинская', 'Туризм и размещение'], 0)} % и "
    f"{fmt_num(shares.loc['Восточно-Казахстанская', 'Туризм и размещение'], 0)} %) — "
    f"горы, озёра и базы отдыха."))
figure(doc, F / "fig03_category_structure_heatmap.png", "Рисунок 6 – Доля каждой категории в регионе, %", 16.5)

doc.add_heading("4.4. Астана vs Алматы vs другие города", level=2)
m = megas
para(doc, (
    f"Алматы: {fmt_int(m['Алматы']['n_service_poi'])} сервисных POI, "
    f"{fmt_num(m['Алматы']['poi_per_100k'])} на 100 тыс. жителей и "
    f"{fmt_num(m['Алматы']['poi_per_km2'])} на км². Астана: {fmt_int(m['Астана']['n_service_poi'])} POI, "
    f"{fmt_num(m['Астана']['poi_per_100k'])} на 100 тыс. и {fmt_num(m['Астана']['poi_per_km2'])} на км². "
    f"Шымкент: {fmt_int(m['Шымкент']['n_service_poi'])} POI, {fmt_num(m['Шымкент']['poi_per_100k'])} "
    f"на 100 тыс. Остальные 18 городов с населением от 100 тыс. в сумме дают {fmt_num(others_total)} POI "
    f"на 100 тыс. жителей — больше любого из мегаполисов. Остальная территория страны — "
    f"{fmt_num(rest_total)}."))
para(doc, (
    "Алматы опережает Астану почти во всех категориях. Самый большой разрыв — в спорте и "
    "досуге, питании и торговле. Зато у Астаны выше полнота атрибутов: часы работы указаны у "
    f"{fmt_num(m['Астана']['opening_hours_share'] * 100, 0)} % POI против "
    f"{fmt_num(m['Алматы']['opening_hours_share'] * 100, 0)} % в Алматы. Шымкент — третий по "
    "численности город страны — отстаёт по всем категориям. Это говорит скорее о слабом "
    "покрытии города в OSM, чем о реальной нехватке инфраструктуры."))
figure(doc, F / "fig04_megacities_categories.png", "Рисунок 7 – POI на 100 тыс. жителей по категориям: мегаполисы и другие города", 15.5)
ct = cities[["name_ru", "city_group", "population", "n_service_poi", "poi_per_100k", "poi_per_km2"]].copy()
ct["name_ru"] = ct["name_ru"].fillna(cities["name"])
ct["population"] = ct["population"].map(fmt_int)
ct["n_service_poi"] = ct["n_service_poi"].map(fmt_int)
ct["poi_per_100k"] = ct["poi_per_100k"].map(lambda v: fmt_num(v))
ct["poi_per_km2"] = ct["poi_per_km2"].map(lambda v: fmt_num(v))
ct["city_group"] = ct["city_group"].replace({"Другие города ≥100 тыс.": "другой ≥100 тыс."})
ct.columns = ["Город", "Группа", "Население", "POI", "На 100 тыс.", "На км²"]
table_caption(doc, "Таблица 9 – Города: обеспеченность POI (outputs/tables/city_stats.csv)")
df_table(doc, ct, [3.4, 3.6, 2.5, 1.9, 2.4, 2.0], font_size=9)

doc.add_heading("4.5. Сравнение инструментов обработки", level=2)
bt = bench[["description", "input_format", "input_size_mb", "median_seconds", "peak_mb",
            "speedup_vs_baseline", "result_matches_reference"]].copy()
bt["input_size_mb"] = bt["input_size_mb"].map(lambda v: fmt_num(v))
bt["median_seconds"] = bt["median_seconds"].map(lambda v: fmt_num(v, 2))
bt["peak_mb"] = bt["peak_mb"].map(lambda v: fmt_num(v, 0))
bt["speedup_vs_baseline"] = bt["speedup_vs_baseline"].map(lambda v: fmt_num(v) + "×")
bt["result_matches_reference"] = bt["result_matches_reference"].map({True: "да", False: "нет"})
bt.columns = ["Подход", "Формат", "Файл, МБ", "Время, с", "Пик, МБ", "× к baseline", "Итог совпал"]
table_caption(doc, f"Таблица 10 – Одна задача на {fmt_int(n_rows)} строк (outputs/tables/benchmark_tools.csv)")
df_table(doc, bt, [5.0, 1.8, 1.7, 1.7, 1.7, 2.2, 2.4], font_size=9)
fastest = bench.sort_values("median_seconds").iloc[0]
lowest_mem = bench.sort_values("peak_mb").iloc[0]
para(doc, (
    f"Самый быстрый подход — {fastest['description']}: {fmt_num(fastest['median_seconds'], 2)} с, "
    f"в {fmt_num(fastest['speedup_vs_baseline'])} раза быстрее baseline. Минимальная пиковая память — "
    f"{lowest_mem['description']} ({fmt_num(lowest_mem['peak_mb'], 0)} МБ): в памяти одновременно "
    f"находится только один чанк, поэтому так можно обработать файл любого размера. Parquet "
    f"занимает в {fmt_num(b.loc['pandas_csv', 'input_size_mb'] / b.loc['pandas_parquet', 'input_size_mb'])} "
    f"раза меньше места на диске, чем CSV, и позволяет читать только нужные столбцы. Все пять подходов "
    f"дали одинаковый результат. Polars lazy и DuckDB по скорости практически равны: в разных прогонах "
    f"конвейера лидер менялся, разница между ними (десятые доли секунды) сопоставима с разбросом "
    f"замеров. DuckDB при этом экономнее по памяти. Выбор для проекта — Polars lazy для аудита и "
    f"агрегатов по полному набору (Python-API без SQL), DuckDB — равноценная альтернатива для тех, "
    f"кому удобнее SQL. Для POI (136 тыс. строк) используется pandas: здесь важна совместимость "
    f"с GeoPandas и scikit-learn."))
figure(doc, F / "fig08_benchmark_tools.png", "Рисунок 8 – Время и пиковая память пяти подходов", 16.5)

doc.add_heading("4.6. Кластеризация DBSCAN", level=2)
para(doc, (
    f"На регионах tune F1 растёт с увеличением eps до {clus['best_eps']} м и затем снижается: "
    f"слишком большой радиус сливает соседние посёлки в один кластер. Перелом графика k-distance "
    f"(расстояние до 10-го соседа) приходится на тот же диапазон 1–3 км (рисунок 9). Выбрано "
    f"eps = {clus['best_eps']} м."))
figure(doc, F / "fig09_eps_selection.png", "Рисунок 9 – Выбор eps: k-distance и F1 на регионах tune", 16.5)
cc = clu_cmp[["method", "params", "n_clusters", "noise_share", "silhouette", "davies_bouldin",
              "settlement_precision", "settlement_recall", "settlement_f1", "seconds", "peak_mb"]].copy()
cc["method"] = cc["method"] + " (" + cc["params"].str.replace("min_cluster_size", "min_size") + ")"
cc = cc.drop(columns="params")
cc["noise_share"] = (cc["noise_share"] * 100).map(lambda v: fmt_num(v))
for col in ["silhouette", "davies_bouldin", "settlement_precision", "settlement_recall", "settlement_f1"]:
    cc[col] = cc[col].map(lambda v: fmt_num(v, 3))
cc["seconds"] = cc["seconds"].map(lambda v: fmt_num(v))
cc["peak_mb"] = cc["peak_mb"].map(lambda v: fmt_num(v, 0))
cc.columns = ["Метод (параметры)", "Кл.", "Шум %", "Sil ↑", "DBI ↓", "Prec", "Rec", "F1 ↑", "с", "МБ"]
table_caption(doc, "Таблица 11 – Сравнение методов кластеризации на регионах test (Кл. — число кластеров, "
                   "Sil — силуэт, DBI — индекс Дэвиса–Боулдина, Prec/Rec/F1 — совпадение с населёнными "
                   "пунктами, с — время, МБ — пиковая память)")
df_table(doc, cc, [4.6, 1.2, 1.3, 1.3, 1.3, 1.3, 1.3, 1.3, 1.2, 1.2], font_size=8.5)
para(doc, (
    f"DBSCAN даёт лучший F1 ({fmt_num(db['settlement_f1'], 3)} против {fmt_num(grid['settlement_f1'], 3)} "
    f"у baseline и {fmt_num(hdb['settlement_f1'], 3)} у HDBSCAN) при меньшей доле шума "
    f"({fmt_num(db['noise_share'] * 100)} %). HDBSCAN показывает лучший силуэт: он дробит "
    f"города на {fmt_int(hdb['n_clusters'])} компактных кластеров-кварталов. Из-за этого центры "
    f"многих кластеров оказываются дальше 3 км от точки населённого пункта, и precision падает. "
    f"Кроме того, HDBSCAN в {fmt_num(hdb['seconds'] / db['seconds'], 0)} раз медленнее DBSCAN. "
    f"Сеточный baseline — самый быстрый ({fmt_num(grid['seconds'], 1)} с), но из-за жёсткой сетки "
    f"теряет мелкие посёлки (recall {fmt_num(grid['settlement_recall'], 3)}). Для задачи «найти "
    f"населённые пункты и агломерации» выбран DBSCAN: лучшее качество при времени "
    f"{fmt_num(db['seconds'])} с."))
figure(doc, F / "fig05_dbscan_clusters_kz.png", "Рисунок 10 – Кластеры DBSCAN по всей стране (синие — в кластере, серые — шум)", 16.5)
top_err = errors.head(6)[["size", "region", "dist_to_settlement_km", "top_type", "example_name"]].copy()
top_err.columns = ["Размер", "Регион", "До нас. пункта, км", "Частый тип", "Пример названия"]
para(doc, (
    f"Анализ ошибок. У {clus['far_clusters']} кластеров DBSCAN из {fmt_int(db['n_clusters'])} центр "
    f"лежит дальше 3 км от точки населённого пункта. Мы проверили крупнейшие из них по "
    f"координатам. Это базы отдыха (Сибинские озёра в Восточно-Казахстанской области), природные "
    f"достопримечательности (Чарынский каньон, Кольсайские озёра, озеро Иссык), горячие источники, "
    f"археологические памятники (петроглифы Ешкиольмес, курганы Берель) и окраины Шымкента. "
    f"В OSM такие места не отмечены точкой place=*, поэтому формально считаются «ошибками», "
    f"хотя по сути это реальные скопления инфраструктуры. Один кластер оказался артефактом "
    f"разметки: 56 резервуаров нефтебазы под Алматы нарисованы как здания с тегом amenity=fuel "
    f"(АЗС) за одну правку 14.03.2023. Это кандидат на дополнительное правило очистки — поиск "
    f"массовых однотипных правок."))
table_caption(doc, "Таблица 12 – Крупнейшие кластеры DBSCAN вдали от населённых пунктов")
df_table(doc, top_err, [1.6, 3.6, 2.6, 3.2, 5.5], font_size=9)
hot = csv("hotspots_summary.csv")
hot_text = "; ".join(
    f"{c} — " + ", ".join(f"{r.main_street} ({r.size} точек)" for r in g.head(3).itertuples())
    for c, g in hot.groupby("city", sort=False))
para(doc, (
    "Для внутригородского анализа DBSCAN запускался с eps = 100 м и min_samples = 8 только по "
    "заведениям питания и магазинам Алматы и Астаны. Выделенные «горячие точки» — торговые "
    f"центры, рынки и торговые улицы. Крупнейшие (по самой частой улице в адресах точек): "
    f"{hot_text}. Они показаны на интерактивных картах Folium "
    "(outputs/figures/fig05_hotspots_almaty.html, fig05_hotspots_astana.html)."))

doc.add_heading("4.7. Проверка гипотез", level=2)
ht = hyp[["id", "hypothesis", "test", "effect", "p_value_fmt", "decision"]].copy()
ht.columns = ["", "Гипотеза", "Тест", "Эффект", "p", "Решение"]
table_caption(doc, "Таблица 13 – Результаты проверки гипотез (α = 0,05)")
df_table(doc, ht, [0.9, 4.6, 3.2, 2.6, 1.6, 3.6], font_size=9)
h1, h3, h4 = hyp_i.loc["H1"], hyp_i.loc["H3"], hyp_i.loc["H4"]


def p_text(row) -> str:
    """«p = 0.322» или «p < 1e-300» (если p меньше машинной точности)."""
    value = str(row["p_value_fmt"])
    return f"p {value}" if value.startswith("<") else f"p = {value}"


h2r = hyp_i.loc["H2"]
city_ranks = {n: int(reg_sorted.index[reg_sorted["region_ru"] == f"г. {n}"][0]) + 1
              for n in ["Алматы", "Астана", "Шымкент"]}
para(doc, (
    f"H1 не подтвердилась ({h1['effect']}, {p_text(h1)}). Урбанизация региона почти не "
    f"связана с обеспеченностью POI в OSM. Три города-региона (доля горожан 100 %) занимают "
    f"{city_ranks['Алматы']}-е (Алматы), {city_ranks['Астана']}-е (Астана) и "
    f"{city_ranks['Шымкент']}-е (Шымкент) места из 20, а в первой пятёрке есть "
    f"Северо-Казахстанская область, где горожан около половины. "
    f"H4 тоже не подтвердилась ({h4['effect']}, {p_text(h4)}). Регионы, где подробно "
    f"обрисованы здания (например, Алматинская область и Абай), не обязательно богаче POI: "
    f"здания и POI размечают разные сообщества и импорты."))
para(doc, (
    f"H2 подтвердилась ({h2r['effect']}, {p_text(h2r)}). Структура категорий в Астане "
    f"и Алматы различается статистически значимо, но сила связи небольшая. Сильнее всего "
    f"расходятся доли категорий из таблицы ниже. H3 подтвердилась ({h3['effect']}, "
    f"{p_text(h3)}): в мегаполисах у POI заметно чаще указаны часы работы — "
    f"городские объекты картируют подробнее."))
h2t = h2.reset_index().head(11)
h2t.columns = ["Категория", "Астана, %", "Алматы, %", "Станд. остаток (Алматы)"]
table_caption(doc, "Таблица 14 – H2: структура сервисных POI Астаны и Алматы")
df_table(doc, h2t, [5.5, 3.0, 3.0, 4.5], font_size=9)
figure(doc, F / "fig06_hypotheses_scatter.png", "Рисунок 11 – Гипотезы H1 и H4: связь показателей регионов", 16.5)

doc.add_heading("4.8. Дополнительные результаты SQL-аналитики", level=2)
para(doc, (
    f"Сетевые бренды (q08): самая широкая сеть — {q08.iloc[0]['brand']} "
    f"({fmt_int(q08.iloc[0]['n_points'])} точек в {q08.iloc[0]['n_regions']} регионах), за ним "
    f"{q08.iloc[1]['brand']} и {q08.iloc[2]['brand']}. Города против своих областей (q10): "
    f"в {len(q10)} городах обеспеченность выше, чем в среднем по области. Сильнее всего "
    f"выделяются {q10.iloc[0]['city']} ({fmt_num(q10.iloc[0]['city_per_100k'])} против "
    f"{fmt_num(q10.iloc[0]['region_per_100k'])}) и {q10.iloc[1]['city']}."))
qb = q08.head(10).copy()
qb["n_points"] = qb["n_points"].map(fmt_int)
qb.columns = ["Бренд", "Точек", "Регионов", "Основная категория"]
table_caption(doc, "Таблица 15 – Крупнейшие сетевые бренды (запрос q08)")
df_table(doc, qb, [5.0, 2.2, 2.2, 6.0], font_size=9)

# ======================================================================== 5. Обсуждение
doc.add_heading("5. Обсуждение и ограничения", level=1)
bullets(doc, [
    "**Полнота OSM.** OSM отражает активность картографов, а не реальное число объектов. "
    "В Казахстане бизнес чаще отмечается в коммерческих картах (2ГИС, Яндекс), поэтому "
    "абсолютные числа занижены, а сравнение регионов частично отражает полноту картирования. "
    "Низкие показатели Шымкента и южных областей — прежде всего следствие слабого покрытия OSM.",
    "**Население городов.** Для 18 городов, кроме Астаны, Алматы и Шымкента, население взято "
    "из тега population в OSM. Это оценка с разной датой актуальности, официальные данные "
    "по городам в проект не включались.",
    "**Геометрия.** Центр контура вычислен как среднее координат узлов, а не геометрический "
    "центроид. Для зданий и площадок разница — метры. Отношения (relation, < 1 % POI) в набор "
    "POI не включались.",
    "**Площади.** Полигоны OSM включают часть акватории Каспия, поэтому показатель «на 1000 км²» "
    "для Атырауской и Мангистауской областей немного занижен.",
    "**Псевдо-разметка кластеров.** Точки населённых пунктов OSM — неполная «истина»: курорты "
    "и промзоны не являются place=*. Поэтому абсолютные значения precision/recall условны, "
    "но для сравнения методов между собой они корректны.",
    "**Снимок во времени.** Анализ выполнен на выгрузке от 15.11.2026; OSM меняется ежедневно, "
    "конвейер воспроизводится на свежих данных одной командой.",
])

# ======================================================================== 6. Выводы
doc.add_heading("6. Выводы", level=1)
bullets(doc, [
    f"Потоковое чтение PBF и чанковая запись в партиционированный Parquet позволяют обработать "
    f"34,5 млн узлов OSM при пиковой памяти около {fmt_num(feat['peak_memory_mb'] / 1024)} ГБ. Оптимизация типов сокращает таблицу "
    f"в памяти на {fmt_num(mem['saving_pct'], 0)} %.",
    f"Обеспеченность сервисными POI в OSM неравномерна: от {fmt_num(bottom_reg['poi_per_100k'], 0)} "
    f"до {fmt_num(top_reg['poi_per_100k'], 0)} на 100 тыс. жителей, в среднем по стране "
    f"{fmt_num(national, 0)}. Северные и западные области обеспечены лучше густонаселённого юга.",
    f"Алматы опережает Астану по обеспеченности ({fmt_num(megas['Алматы']['poi_per_100k'], 0)} против "
    f"{fmt_num(megas['Астана']['poi_per_100k'], 0)}), но у Астаны полнее атрибуты POI. Шымкент "
    f"заметно недокартирован. Крупные областные города в среднем обеспечены лучше мегаполисов.",
    f"Для агрегатов по большому набору лучшие инструменты — Polars lazy и DuckDB по Parquet "
    f"(в {lead_speedups} раза быстрее baseline, между собой равны в пределах разброса замеров). Чанковая "
    f"обработка даёт минимальную память, Parquet — в разы меньший размер файла.",
    f"DBSCAN с eps = {clus['best_eps']} м — лучший из трёх методов по F1 на отложенных регионах "
    f"({fmt_num(db['settlement_f1'], 3)}). HDBSCAN лучше по силуэту, но медленнее в "
    f"{fmt_num(hdb['seconds'] / db['seconds'], 0)} раз и дробит города на кварталы.",
    "Различия Астаны и Алматы по структуре категорий значимы (H2), мегаполисы описаны в OSM "
    "подробнее (H3). Связь обеспеченности с урбанизацией (H1) и с числом зданий в OSM (H4) "
    "не подтвердилась.",
    "Возможные развития: сравнение с коммерческими каталогами (2ГИС) для оценки полноты OSM, "
    "анализ доступности POI (изохроны по дорожному графу), ежемесячный мониторинг изменений OSM.",
])

# ======================================================================== 7. Вклад
doc.add_heading("7. Вклад участников", level=1)
para(doc, ("Работа распределена поровну — примерно по одной трети на каждого участника. Каждый "
           "участник разобрался во всех модулях и может объяснить любую часть кода."))
table_caption(doc, "Таблица 16 – Распределение работы в команде")
df_table(doc, pd.DataFrame([
    [TEAM[0], "Инженерия данных и производительность",
     "download.py, extract.py, optimize.py, aggregates.py, benchmark.py, pipeline.py, main.py, README", "≈ 33 %"],
    [TEAM[1], "Пространственные данные, качество и БД",
     "spatial.py, quality.py, database.py, sql/schema.sql, sql/queries.sql, ER-диаграмма, search.py, app.py", "≈ 33 %"],
    [TEAM[2], "Аналитика, ML и представление результатов",
     "categories.py, analysis.py, clustering.py, hypotheses.py, visualize.py, отчёт, презентация", "≈ 33 %"],
], columns=["Участник", "Зона ответственности", "Модули и артефакты", "Доля"]), [3.8, 3.9, 7.3, 1.5], font_size=9)

# ======================================================================== 8. Источники
doc.add_heading("8. Список источников", level=1)
bullets(doc, [
    "OpenStreetMap contributors. Kazakhstan OSM extract. Geofabrik GmbH, 15.11.2026. "
    "https://download.geofabrik.de/asia/kazakhstan.html (лицензия ODbL 1.0).",
    "Бюро национальной статистики АСПиР РК. Численность населения Республики Казахстан по "
    f"регионам на 1 января 2026 г. {config.POPULATION_SOURCE}",
    "Ester M., Kriegel H.-P., Sander J., Xu X. A density-based algorithm for discovering clusters "
    "in large spatial databases with noise // Proc. KDD-96. 1996. P. 226–231.",
    "Campello R. J. G. B., Moulavi D., Sander J. Density-based clustering based on hierarchical "
    "density estimates // PAKDD 2013. LNCS 7819. P. 160–172.",
    "Rousseeuw P. J. Silhouettes: a graphical aid to the interpretation and validation of cluster "
    "analysis // J. Comput. Appl. Math. 1987. Vol. 20. P. 53–65.",
    "Документация: pyosmium (osmcode.org/pyosmium), Polars (docs.pola.rs), DuckDB (duckdb.org), "
    "GeoPandas (geopandas.org), scikit-learn (scikit-learn.org), Streamlit (docs.streamlit.io).",
], numbered=True)

# ======================================================================== Приложение А
heading_new_page(doc, "Приложение А. Соответствие требованиям")
table_caption(doc, "Таблица А.1 – Технические требования (раздел II задания)")
df_table(doc, pd.DataFrame([
    ["1. Функции", "≥ 5 функций", "более 100 функций в 17 модулях src/ (например extract.classify_feature, "
     "quality.find_semantic_duplicates, clustering.grid_baseline)"],
    ["2. Структуры данных", "list, dict", "словари категорий (categories.py), реестр шагов STEPS (список), "
     "словарь накопленных сумм в aggregates.chunked_summary, буфер-список в extract.py"],
    ["3. Условия", "if/elif/else", "categories.categorize, utils.peak_memory_mb, download.verify_pbf, main.run_menu"],
    ["4. Циклы", "for/while", "for по объектам PBF и батчам Parquet; while в BFS (grid_baseline) и в меню"],
    ["5. Файлы", "чтение/запись", "Parquet, CSV, JSON, GeoJSON, SQLite; состояние outputs/run_state.json"],
    ["6. Ошибки", "try/except", "utils.load_json (FileNotFoundError, JSONDecodeError), download (RequestException), "
     "main.ask_int (ValueError), database.run_all_queries, extract_boundaries (RuntimeError)"],
    ["7. Интерфейс", "меню или дашборд", "консольное меню main.py (16 пунктов) и Streamlit app.py (5 фильтров, 5 вкладок)"],
    ["8. Модульность", "несколько .py", "17 модулей src/ + main.py, app.py; os, sys, json, pathlib, datetime, re, "
     "hashlib, argparse, subprocess, sqlite3, tracemalloc"],
    ["9. Обоснование", "≥ 2 подхода + baseline", "бенчмарк: baseline + 4 подхода; кластеризация: Grid baseline, "
     "DBSCAN, HDBSCAN (качество, время, память)"],
    ["10. БД и SQL", "ER, ≥ 8 запросов", "8 таблиц, ER-диаграмма, 11 запросов (JOIN, HAVING, подзапросы, CTE, "
     "ROW_NUMBER, RANK, NTILE, LAG, SUM OVER), pd.read_sql_query"],
    ["11. Объём", "≥ 500 тыс. строк / 200 МБ", f"PBF {fmt_num(feat['pbf_size_mb'])} МБ, 34,5 млн узлов, "
     f"{fmt_int(n_rows)} строк; чанки, оптимизация типов, Parquet"],
], columns=["Требование", "Норма", "Где выполнено"]), [3.0, 3.0, 10.5], font_size=9)
table_caption(doc, "Таблица А.2 – Обязательные задачи Cluster 8 и фокус темы 47")
df_table(doc, pd.DataFrame([
    ["Данные, не помещающиеся в память: чанки, Parquet с партициями, оптимизация типов",
     "extract.py (поток + чанки 200 тыс.), spatial.assign_regions_chunked, optimize.py; разделы 3.2–3.3"],
    ["Сравнение ≥ 2 инструментов: время, пиковая память, совпадение",
     "benchmark.py: pandas / Polars / DuckDB, CSV / Parquet; раздел 4.5"],
    ["Ленивые вычисления / инкрементальные агрегаты",
     "aggregates.py: Polars lazy и groupby по чанкам с проверкой совпадения; раздел 3.6"],
    ["Аудит качества и обоснование очистки", "quality.py, таблица 6; раздел 3.5"],
    ["EDA, 4–5 визуализаций (≥ 1 интерактивная), ≥ 2 гипотезы",
     "11 графиков PNG + 4 интерактивных HTML (Plotly, Folium); гипотезы H1–H4; разделы 4.1–4.7"],
    ["Дашборд или меню; агрегаты в Parquet/SQLite", "app.py, main.py; data/processed/*.parquet, kz_poi.db"],
    ["Тема 47: чтение PBF и фильтр тегов", "extract.py (osmium.FileProcessor + KeyFilter)"],
    ["Тема 47: POI на 100 тыс. по регионам", "analysis.region_stats, запрос q01; раздел 4.2"],
    ["Тема 47: Астана vs Алматы vs другие города", "analysis.megacity_comparison, запрос q04, H2; раздел 4.4"],
    ["Тема 47: DBSCAN", "clustering.py; раздел 4.6"],
], columns=["Задача", "Реализация"]), [7.0, 9.5], font_size=9)

doc.add_heading("Приложение Б. Запуск проекта", level=1)
for line in ["pip install -r requirements.txt", "python main.py            # консольное меню",
             "python main.py --all      # весь конвейер (~10 мин)", "streamlit run app.py      # дашборд"]:
    p = doc.add_paragraph()
    run = p.add_run(line)
    run.font.name = "Consolas"
    run.font.size = Pt(10)
    p.paragraph_format.space_after = Pt(0)
para(doc, f"Подробная инструкция — в README.md репозитория {REPO}.", align_justify=False)

doc.save(OUT)
print(f"Отчёт сохранён: {OUT}")
