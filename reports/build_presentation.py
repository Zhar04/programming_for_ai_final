"""
Сборка презентации reports/presentation_osm_kz_poi.pptx (12 слайдов, 16:9).

Числа берутся из outputs/ (как и в отчёте). В заметках к каждому слайду — текст
для выступления и кто из команды рассказывает этот слайд.

Запуск:  python reports/build_presentation.py
"""
import json
import sys
from pathlib import Path

import pandas as pd
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_TICK_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import config  # noqa: E402

T, M, F = config.TABLES_DIR, config.METRICS_DIR, config.FIG_DIR
OUT = ROOT / "reports" / "presentation_osm_kz_poi.pptx"
SHOT = ROOT / "reports" / "dashboard_screenshot.png"

# --- палитра: небо и золото флага Казахстана + тёмно-бирюзовый фон
NAVY = RGBColor(0x0B, 0x2E, 0x3F)
SKY = RGBColor(0x00, 0x9C, 0xBD)
GOLD = RGBColor(0xF2, 0xB7, 0x05)
INK = RGBColor(0x1A, 0x1F, 0x24)
MUTED = RGBColor(0x5A, 0x64, 0x70)
CARD = RGBColor(0xEC, 0xF5, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GRAY = RGBColor(0x8C, 0x8B, 0x86)
GREEN = RGBColor(0x0C, 0x8A, 0x3E)
RED = RGBColor(0xC2, 0x3B, 0x3B)
FONT = "Calibri"
TEAM = ["Zharken Utegenov", "Yergaliev Aron", "Temirgalin Dinmukhammed"]


def j(name):
    return json.loads((M / name).read_text(encoding="utf-8"))


def num(v, d=0):
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",")


ext, mem, audit_pois = j("extract_stats.json"), j("memory_optimization.json"), j("audit_pois.json")
audit_full, clus = j("audit_full.json"), j("clustering.json")
regions = pd.read_csv(T / "region_stats.csv").sort_values("poi_per_100k", ascending=False)
cities = pd.read_csv(T / "city_stats.csv")
bench = pd.read_csv(T / "benchmark_tools.csv")
hyp = pd.read_csv(T / "hypotheses.csv", dtype={"p_value_fmt": str})
clu = pd.read_csv(T / "clustering_comparison.csv")
rules = pd.read_csv(T / "cleaning_rules.csv")
mega = pd.read_csv(T / "megacity_comparison.csv", index_col=0)
city = {n: cities[cities["name"] == n].iloc[0] for n in ["Астана", "Алматы", "Шымкент"]}
q06 = pd.read_csv(T / "sql_q06_pareto_cumulative.csv")
regions_50 = int((q06["cumulative_pct"] < 50).sum()) + 1   # сколько регионов дают половину POI

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
W, H = 13.333, 7.5


# ------------------------------------------------------------------ helpers
def text(slide, x, y, w, h, content, size=16, color=INK, bold=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, font=FONT, italic=False):
    """Текстовое поле; content — строка или список строк (каждая — отдельный абзац)."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.02)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    lines = content if isinstance(content, list) else [content]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        run = p.add_run()
        run.text = line
        run.font.size, run.font.bold, run.font.italic = Pt(size), bold, italic
        run.font.color.rgb = color
        run.font.name = font
    return box


def rich(slide, x, y, w, h, paragraphs, size=15, space_after=8):
    """Абзацы с жирным началом: [("Жирно", " обычный текст"), ...]."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.02)
    for i, (head, tail) in enumerate(paragraphs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(space_after)
        r1 = p.add_run()
        r1.text = head
        r1.font.bold, r1.font.size, r1.font.color.rgb, r1.font.name = True, Pt(size), INK, FONT
        r2 = p.add_run()
        r2.text = tail
        r2.font.size, r2.font.color.rgb, r2.font.name = Pt(size), MUTED, FONT
    return box


def card(slide, x, y, w, h, fill=CARD):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.adjustments[0] = 0.08
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def stat(slide, x, y, w, value, label, value_color=SKY, h=1.45):
    """Карточка с крупным числом и подписью."""
    card(slide, x, y, w, h)
    text(slide, x + 0.2, y + 0.12, w - 0.4, 0.75, value, size=34, color=value_color, bold=True)
    text(slide, x + 0.2, y + 0.85, w - 0.4, h - 0.9, label, size=13, color=MUTED)


def title(slide, content, subtitle=None):
    text(slide, 0.6, 0.35, W - 1.2, 0.8, content, size=32, bold=True, color=NAVY)
    if subtitle:
        text(slide, 0.6, 1.08, W - 1.2, 0.45, subtitle, size=15, color=MUTED)


def footer(slide, number, presenter):
    text(slide, 0.6, H - 0.42, 8, 0.3, f"OSM Kazakhstan · POI Analytics · докладчик: {presenter}",
         size=10, color=MUTED)
    text(slide, W - 1.4, H - 0.42, 0.8, 0.3, str(number), size=10, color=MUTED, align=PP_ALIGN.RIGHT)


def notes(slide, content):
    slide.notes_slide.notes_text_frame.text = content


def picture(slide, path, x, y, w=None, h=None):
    kwargs = {}
    if w:
        kwargs["width"] = Inches(w)
    if h:
        kwargs["height"] = Inches(h)
    return slide.shapes.add_picture(str(path), Inches(x), Inches(y), **kwargs)


def bar_chart(slide, x, y, w, h, categories, values, chart_title, number_format, colors):
    data = CategoryChartData()
    data.categories = categories
    data.add_series(chart_title, values)
    gf = slide.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(x), Inches(y), Inches(w), Inches(h), data)
    chart = gf.chart
    chart.has_legend = False
    chart.has_title = True
    chart.chart_title.text_frame.text = chart_title
    tp = chart.chart_title.text_frame.paragraphs[0]
    tp.runs[0].font.size, tp.runs[0].font.bold, tp.runs[0].font.color.rgb = Pt(14), True, INK
    plot = chart.plots[0]
    plot.gap_width = 60
    plot.has_data_labels = True
    labels = plot.data_labels
    labels.number_format, labels.number_format_is_linked = number_format, False
    labels.position = XL_LABEL_POSITION.OUTSIDE_END
    labels.font.size, labels.font.color.rgb = Pt(12), INK
    for i, point in enumerate(plot.series[0].points):
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = colors[i]
    cat_ax, val_ax = chart.category_axis, chart.value_axis
    cat_ax.tick_labels.font.size, cat_ax.tick_labels.font.color.rgb = Pt(12), INK
    cat_ax.format.line.color.rgb = RGBColor(0xD6, 0xD5, 0xD0)
    cat_ax.reverse_order = True
    val_ax.visible = False
    val_ax.has_major_gridlines = False
    return chart


# ================================================================== 1. Титульный
s = prs.slides.add_slide(BLANK)
s.background.fill.solid()
s.background.fill.fore_color.rgb = NAVY
text(s, 0.8, 0.9, 9, 0.5, "ИТОГОВЫЙ ПРОЕКТ · PROGRAMMING FOR DATA ANALYSIS AND DATABASE", size=14, color=GOLD, bold=True)
text(s, 0.8, 1.7, 11.5, 2.2, ["OpenStreetMap Kazakhstan:", "Points of Interest Analytics"], size=48, bold=True, color=WHITE)
text(s, 0.8, 3.95, 11, 0.5, "Тема №47 · Cluster 8: Large-Scale Data Processing", size=20, color=RGBColor(0xBF, 0xE6, 0xEF))
for i, name in enumerate(TEAM):
    x = 0.8 + i * 3.9
    circle = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(5.35), Inches(0.55), Inches(0.55))
    circle.fill.solid()
    circle.fill.fore_color.rgb = SKY
    circle.line.fill.background()
    circle.text_frame.text = "".join(part[0] for part in name.split()[:2])
    circle.text_frame.word_wrap = False
    for side in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(circle.text_frame, side, 0)
    circle.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    run = circle.text_frame.paragraphs[0].runs[0]
    run.font.size, run.font.bold, run.font.color.rgb, run.font.name = Pt(14), True, WHITE, FONT
    circle.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
    text(s, x + 0.7, 5.42, 3.1, 0.45, name, size=16, color=WHITE, bold=True)
text(s, 0.8, 6.45, 11, 0.4, "Applied Artificial Intelligence, магистратура · группа AAI-2605M · 2026",
     size=13, color=RGBColor(0xBF, 0xE6, 0xEF))
notes(s, "Докладчик: Zharken Utegenov.\nЗдравствуйте! Мы — команда из трёх человек, тема №47: аналитика точек интереса "
         "OpenStreetMap по Казахстану. Тема относится к кластеру 8 — обработка больших данных. Я расскажу про данные и "
         "конвейер обработки, Арон — про качество данных, базу SQLite и дашборд, Динмухаммед — про результаты анализа, "
         "кластеризацию и гипотезы.")

# ================================================================== 2. Задача и данные
s = prs.slides.add_slide(BLANK)
title(s, "Задача и данные", "Насколько равномерно точки интереса OSM распределены по Казахстану?")
rich(s, 0.6, 1.85, 5.6, 4.5, [
    ("Цель. ", "плотность и типы POI по 20 регионам и крупным городам"),
    ("1. ", "POI на 100 тыс. жителей по регионам"),
    ("2. ", "Астана vs Алматы vs другие города"),
    ("3. ", "пространственная кластеризация DBSCAN"),
    ("Данные. ", "OSM (Geofabrik, 15.11.2026) + население stat.gov.kz на 01.01.2026"),
], size=17, space_after=12)
stat(s, 6.6, 1.85, 3.0, f"{num(ext['features']['pbf_size_mb'])} МБ", "PBF-файл OpenStreetMap")
stat(s, 9.8, 1.85, 3.0, "34,5 млн", "узлов + 4,25 млн линий")
stat(s, 6.6, 3.5, 3.0, f"{num(ext['features']['rows'] / 1e6, 1)} млн", "объектов извлечено (POI + здания)")
stat(s, 9.8, 3.5, 3.0, f"{num(audit_pois['n_service_poi'] / 1000, 1)} тыс.", "сервисных POI после очистки")
stat(s, 6.6, 5.15, 6.2, "20 регионов · 21 город", "17 областей + Астана, Алматы, Шымкент; города ≥ 100 тыс. жителей")
footer(s, 2, TEAM[0])
notes(s, "Докладчик: Zharken Utegenov.\nЦель — понять, как распределены магазины, школы, кафе, больницы и другие "
         "объекты по регионам. Данные — полная выгрузка OpenStreetMap по Казахстану: файл PBF 216 МБ, 34,5 миллиона "
         "узлов. В память такой объём целиком не помещается, поэтому мы читаем его потоково. Население берём из "
         "официальной статистики на 1 января 2026 года. Связываем два источника по коду ISO региона, например KZ-71 — Астана.")

# ================================================================== 3. Конвейер
s = prs.slides.add_slide(BLANK)
title(s, "Конвейер обработки", "11 шагов, 17 модулей в src/; запуск одной командой: python main.py --all")
steps = [("PBF", "поток osmium\nKeyFilter по тегам"),
         ("Parquet", "чанки по 200 тыс.\nпартиции по ключу"),
         ("Регионы", "sjoin по чанкам\n500 тыс. строк"),
         ("Аудит", "Polars lazy\nправила очистки"),
         ("Анализ", "POI на 100 тыс.\nгорода, категории"),
         ("Вывод", "SQLite · DBSCAN\nменю · Streamlit")]
bw, gap, y0 = 1.85, 0.25, 2.0
for i, (head, body) in enumerate(steps):
    x = 0.6 + i * (bw + gap)
    card(s, x, y0, bw, 1.75, fill=NAVY if i in (0, 5) else CARD)
    color = WHITE if i in (0, 5) else NAVY
    text(s, x + 0.15, y0 + 0.2, bw - 0.3, 0.5, head, size=20, bold=True, color=GOLD if i in (0, 5) else SKY)
    text(s, x + 0.15, y0 + 0.85, bw - 0.3, 1.2, body.split("\n"), size=13, color=color)
    if i < len(steps) - 1:
        arrow = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x + bw + 0.03), Inches(y0 + 0.72),
                                   Inches(gap - 0.06), Inches(0.3))
        arrow.fill.solid()
        arrow.fill.fore_color.rgb = GOLD
        arrow.line.fill.background()
rich(s, 0.6, 4.3, 12, 2.4, [
    ("Модульность: ", "download → extract → spatial → optimize → quality/aggregates → analysis → database → "
                      "benchmark → clustering → hypotheses → visualize"),
    ("Воспроизводимость: ", "каждый шаг пишет результат на диск и в outputs/run_state.json — "
                            "шаги можно запускать по отдельности из меню"),
    ("Инструменты: ", "osmium, pyarrow, pandas, Polars, DuckDB, GeoPandas, scikit-learn, SQLite, Plotly, Folium, Streamlit"),
], size=15)
footer(s, 3, TEAM[0])
notes(s, "Докладчик: Zharken Utegenov.\nКонвейер состоит из 11 шагов. Первый — потоковое чтение PBF библиотекой osmium: "
         "фильтр KeyFilter работает на стороне C++ и отбрасывает лишние объекты, до Python доходит меньше 10%. Строки "
         "копятся в буфере и каждые 200 тысяч записываются в Parquet, разбитый на папки по ключу OSM. Затем по чанкам "
         "в 500 тысяч строк делаем пространственное соединение с полигонами регионов. Каждый шаг пишет результат "
         "на диск, поэтому шаги можно перезапускать по отдельности.")

# ================================================================== 4. Память и инструменты
s = prs.slides.add_slide(BLANK)
title(s, "Большие данные: память и выбор инструмента",
      f"Одна задача на {num(ext['features']['rows'])} строк, каждый подход — в отдельном процессе, медиана 3 запусков")
stat(s, 0.6, 1.85, 3.6, f"−{num(mem['saving_pct'], 1)} %",
     f"память таблицы: {num(mem['mb_before'])} → {num(mem['mb_after'])} МБ (category, downcast, float32)")
stat(s, 0.6, 3.5, 3.6, f"{num(ext['features']['peak_memory_mb'])} МБ",
     "пиковая память при чтении PBF целиком — потоково, чанками")
stat(s, 0.6, 5.15, 3.6, f"{num(mem['float32_max_error_m'], 1)} м",
     "макс. ошибка координат во float32 — несущественна")
b = bench.set_index("approach")
order = ["pandas_csv", "pandas_csv_chunks", "pandas_parquet", "duckdb_sql", "polars_lazy"]
names = {"pandas_csv": "pandas + CSV (baseline)", "pandas_csv_chunks": "pandas + CSV чанками",
         "pandas_parquet": "pandas + Parquet", "duckdb_sql": "DuckDB SQL", "polars_lazy": "Polars lazy"}
colors = [GRAY if a == "pandas_csv" else SKY for a in order]
bar_chart(s, 4.5, 1.75, 4.3, 4.9, [names[a] for a in order], [float(b.loc[a, "median_seconds"]) for a in order],
          "Время, с", '0.00', colors)
mem_chart = bar_chart(s, 8.95, 1.75, 3.9, 4.9, [names[a] for a in order],
                      [float(b.loc[a, "peak_mb"]) for a in order], "Пиковая память, МБ", '0', colors)
# подписи подходов уже есть слева — у второго графика их скрываем, столбцы стоят на тех же строках
mem_chart.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.NONE
text(s, 4.6, 6.62, 8.4, 0.4, "Все 5 подходов дали идентичный результат (сверка с эталоном). Parquet в "
     f"{num(b.loc['pandas_csv', 'input_size_mb'] / b.loc['pandas_parquet', 'input_size_mb'], 1)} раза меньше CSV.",
     size=12, color=MUTED)
footer(s, 4, TEAM[0])
fast = bench.sort_values("median_seconds").iloc[0]
notes(s, "Докладчик: Zharken Utegenov.\n"
         f"Оптимизация типов: строки с повторяющимися значениями переводим в category, целые — в минимальный int, "
         f"координаты — во float32. Память таблицы падает с {num(mem['mb_before'])} до {num(mem['mb_after'])} МБ. "
         f"Затем одну и ту же агрегацию решили пятью способами, каждый в отдельном процессе, чтобы честно мерить "
         f"пиковую память. Быстрее всех — Polars lazy и DuckDB по Parquet, примерно в 6–7 раз быстрее baseline; "
         f"между собой они равны в пределах разброса замеров, DuckDB экономнее по памяти. Чтение CSV по чанкам "
         f"даёт минимальную память — так можно обработать файл любого размера. Результаты всех подходов совпали.")

# ================================================================== 5. Аудит
s = prs.slides.add_slide(BLANK)
title(s, "Аудит качества и правила очистки",
      f"POI: {num(audit_pois['rows_before'])} → {num(audit_pois['rows_after'])} строк; каждое правило обосновано")
show = rules[rules["rows"] > 0].head(7)
tbl = s.shapes.add_table(len(show) + 1, 3, Inches(0.6), Inches(1.8), Inches(7.6), Inches(4.4)).table
tbl.columns[0].width, tbl.columns[1].width, tbl.columns[2].width = Inches(4.3), Inches(1.0), Inches(2.3)
for c, head in enumerate(["Правило", "Строк", "Действие"]):
    cell = tbl.cell(0, c)
    cell.text = head
    cell.fill.solid()
    cell.fill.fore_color.rgb = NAVY
    run = cell.text_frame.paragraphs[0].runs[0]
    run.font.size, run.font.bold, run.font.color.rgb, run.font.name = Pt(13), True, WHITE, FONT
for r, row in enumerate(show.itertuples(), start=1):
    for c, value in enumerate([row.rule, num(row.rows), row.action]):
        cell = tbl.cell(r, c)
        cell.text = str(value)
        cell.fill.solid()
        cell.fill.fore_color.rgb = CARD if r % 2 else WHITE
        run = cell.text_frame.paragraphs[0].runs[0]
        run.font.size, run.font.color.rgb, run.font.name = Pt(12), INK, FONT
        if c == 1:
            cell.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT
card(s, 8.6, 1.8, 4.15, 2.15, fill=NAVY)
text(s, 8.85, 1.95, 3.7, 0.4, "Найденная аномалия", size=14, color=GOLD, bold=True)
text(s, 8.85, 2.4, 3.7, 1.95,
     f"amenity=public_building: {num(audit_pois['public_building_top_share'] * 100)} % таких объектов — "
     f"безымянные здания в одном регионе ({audit_pois['public_building_top_region']}). "
     "Без правила область стала бы «лидером по госуслугам».", size=13, color=WHITE)
af = audit_full["audit"]
rich(s, 8.6, 4.2, 4.2, 2.6, [
    ("Даты: ", f"0 правок раньше 2004 г. и позже снимка; {af['start_date']['bad_format']} start_date в нестандартном формате"),
    ("Этажность: ", f"{af['building_levels']['non_positive'] + af['building_levels']['not_numeric']} некорректных значений; IQR вырожден (Q1=Q3=1) → порог P99"),
    ("Вне РК: ", f"{num(af['rows_outside_kz'])} объектов приграничья"),
], size=13, space_after=8)
footer(s, 5, TEAM[1])
notes(s, "Докладчик: Yergaliev Aron.\nАудит проверяет пропуски, дубликаты, некорректные значения и даты, выбросы. "
         "Точных дубликатов нет. Смысловые дубликаты — когда кафе отмечено и точкой, и контуром здания рядом — "
         "ищем KD-деревом: тот же тип и название ближе 50 метров. Телефоны и часы работы в неверном формате не "
         "удаляем, а помечаем флагом. Главная находка — тег amenity=public_building: тысячи безымянных зданий в "
         "одной области. Тег устаревший и не говорит, какая это услуга, поэтому мы его не считаем сервисом.")

# ================================================================== 6. SQLite
s = prs.slides.add_slide(BLANK)
title(s, "База SQLite: нормализованная схема и 11 запросов", "8 таблиц, внешние ключи, индексы; результаты → pandas (read_sql_query)")
picture(s, F / "er_diagram.png", 0.5, 1.65, w=7.6)
rich(s, 8.45, 1.8, 4.4, 5.0, [
    ("JOIN: ", "pois → poi_types → categories → regions"),
    ("GROUP BY / HAVING: ", "регионы с долей общепита выше средней (подзапрос)"),
    ("CTE + ROW_NUMBER: ", "топ-3 категории каждого региона"),
    ("RANK, NTILE, LAG: ", "рейтинг и квартили регионов"),
    ("SUM() OVER: ", f"накопленная доля — 50 % POI дают {regions_50} регионов из 20"),
    ("Коррелированный подзапрос: ", "города выше среднего по своей области"),
    ("Поиск: ", "параметры «?» против SQL-инъекций, кириллица без учёта регистра"),
], size=14, space_after=9)
footer(s, 6, TEAM[1])
notes(s, "Докладчик: Yergaliev Aron.\nСхема нормализована: справочники регионов, категорий, типов POI и городов "
         "отдельно, таблица фактов pois хранит только внешние ключи. Результаты кластеризации — в отдельных "
         "таблицах, это связь многие-ко-многим. Запросов 11, используются JOIN, HAVING с подзапросом, CTE, "
         "оконные функции ROW_NUMBER, RANK, NTILE, LAG и накопленная сумма. Все результаты загружаются в pandas "
         "и сохраняются в CSV.")

# ================================================================== 7. Регионы
s = prs.slides.add_slide(BLANK)
top, bottom = regions.iloc[0], regions.iloc[-1]
title(s, "Обеспеченность POI по регионам: разрыв в 3,4 раза",
      f"Сервисные POI на 100 тыс. жителей; в среднем по РК — {num(audit_pois['national_poi_per_100k'])}")
picture(s, F / "fig02_map_poi_per_100k.png", 0.4, 1.6, w=8.6)
stat(s, 9.3, 1.75, 3.5, num(top["poi_per_100k"]), f"максимум — {top['region_ru']}")
stat(s, 9.3, 3.35, 3.5, num(bottom["poi_per_100k"]), f"минимум — {bottom['region_ru']}", value_color=GOLD)
text(s, 9.3, 5.0, 3.5, 1.9, ["Север и запад обеспечены лучше густонаселённого юга.",
                             "Сравнение отражает и полноту картирования OSM."], size=14, color=MUTED)
footer(s, 7, TEAM[2])
notes(s, "Докладчик: Temirgalin Dinmukhammed.\n"
         f"В среднем по стране {num(audit_pois['national_poi_per_100k'])} сервисных точек на 100 тысяч жителей. "
         f"Максимум — {top['region_ru']}, {num(top['poi_per_100k'])}, минимум — {bottom['region_ru']}, "
         f"{num(bottom['poi_per_100k'])}. Северные и западные области с небольшим населением обеспечены лучше, "
         "чем густонаселённый юг. Важно: OSM отражает активность картографов, поэтому часть разрыва — это полнота "
         "карты, а не реальная инфраструктура. Интерактивная версия карты — в HTML на Plotly.")

# ================================================================== 8. Мегаполисы
s = prs.slides.add_slide(BLANK)
title(s, "Астана vs Алматы vs другие города",
      "POI на 100 тыс. жителей по категориям; Астана, Алматы, Шымкент — официальное население")
picture(s, F / "fig04_megacities_categories.png", 0.4, 1.55, w=7.9)
others = mega.loc["Другие города ≥100 тыс.", "Все категории"]
for i, (name, color) in enumerate([("Алматы", RGBColor(0xEB, 0x68, 0x34)), ("Астана", RGBColor(0x2A, 0x78, 0xD6)),
                                   ("Шымкент", RGBColor(0x1B, 0xAF, 0x7A))]):
    row = city[name]
    card(s, 8.6, 1.7 + i * 1.3, 4.2, 1.15)
    text(s, 8.8, 1.78 + i * 1.3, 1.9, 0.5, name, size=18, bold=True, color=INK)
    text(s, 8.8, 2.22 + i * 1.3, 2.0, 0.6, f"{num(row['n_service_poi'])} POI", size=13, color=MUTED)
    text(s, 10.6, 1.8 + i * 1.3, 2.0, 0.9, num(row["poi_per_100k"]), size=32, bold=True, color=color,
         align=PP_ALIGN.RIGHT)
text(s, 8.6, 5.65, 4.2, 1.3, [f"Другие 18 городов ≥100 тыс.: {num(others)} на 100 тыс.",
                              f"Часы работы указаны: Астана {num(city['Астана']['opening_hours_share'] * 100)} %, "
                              f"Алматы {num(city['Алматы']['opening_hours_share'] * 100)} %"], size=13, color=MUTED)
footer(s, 8, TEAM[2])
notes(s, "Докладчик: Temirgalin Dinmukhammed.\n"
         f"Алматы — {num(city['Алматы']['poi_per_100k'])} точек на 100 тысяч, Астана — {num(city['Астана']['poi_per_100k'])}, "
         f"Шымкент — {num(city['Шымкент']['poi_per_100k'])}. Алматы опережает Астану почти во всех категориях, "
         "сильнее всего — в спорте и досуге, питании и торговле. Зато у Астаны полнее атрибуты: часы работы указаны "
         "чаще. Шымкент заметно недокартирован. Интересно, что крупные областные города в сумме обеспечены лучше "
         "мегаполисов.")

# ================================================================== 9. DBSCAN
s = prs.slides.add_slide(BLANK)
title(s, "Кластеризация: DBSCAN vs baseline vs HDBSCAN",
      f"eps подобран на 10 регионах (tune), сравнение — на других 10 (test): без утечки; eps = {clus['best_eps']} м")
picture(s, F / "fig05_dbscan_clusters_kz.png", 0.4, 1.6, w=6.9)
cols = ["Метод", "F1", "Шум", "Силуэт", "Время"]
tbl = s.shapes.add_table(4, 5, Inches(7.55), Inches(1.75), Inches(5.3), Inches(2.0)).table
widths = [1.6, 0.9, 0.9, 1.0, 0.9]
for c, wdt in enumerate(widths):
    tbl.columns[c].width = Inches(wdt)
for c, head in enumerate(cols):
    cell = tbl.cell(0, c)
    cell.text = head
    cell.fill.solid()
    cell.fill.fore_color.rgb = NAVY
    run = cell.text_frame.paragraphs[0].runs[0]
    run.font.size, run.font.bold, run.font.color.rgb, run.font.name = Pt(13), True, WHITE, FONT
best_f1 = clu["settlement_f1"].max()
for r, row in enumerate(clu.itertuples(), start=1):
    values = [row.method, num(row.settlement_f1, 3), f"{num(row.noise_share * 100)} %",
              num(row.silhouette, 2), f"{num(row.seconds, 1)} с"]
    for c, value in enumerate(values):
        cell = tbl.cell(r, c)
        cell.text = value
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor(0xFF, 0xF4, 0xD1) if row.settlement_f1 == best_f1 else WHITE
        run = cell.text_frame.paragraphs[0].runs[0]
        run.font.size, run.font.color.rgb, run.font.name = Pt(13), INK, FONT
        run.font.bold = row.settlement_f1 == best_f1
rich(s, 7.55, 4.1, 5.3, 2.9, [
    ("Метрика: ", "F1 совпадения кластеров с населёнными пунктами OSM (радиус 3 км)"),
    ("DBSCAN ", f"— лучший F1 и мало шума, {num(clu.set_index('method').loc['DBSCAN', 'seconds'], 1)} с"),
    ("HDBSCAN ", "— лучший силуэт, но дробит города на кварталы и в десятки раз медленнее"),
    ("Анализ ошибок: ", "базы отдыха, Чарын, Кольсай, петроглифы — нет точки place=*; "
                       "56 резервуаров нефтебазы размечены как АЗС"),
], size=13, space_after=6)
footer(s, 9, TEAM[2])
dbr = clu.set_index("method").loc["DBSCAN"]
notes(s, "Докладчик: Temirgalin Dinmukhammed.\nСравниваем три подхода с одинаковым порогом плотности 10 точек: "
         "сеточный baseline — клетки 1 км, DBSCAN и HDBSCAN. Правильных ответов нет, поэтому используем "
         "псевдо-разметку — точки населённых пунктов OSM. Чтобы не было утечки, eps подбирали на одной половине "
         "регионов, а сравнивали методы на другой. "
         f"DBSCAN с eps {clus['best_eps']} метров даёт F1 {num(dbr['settlement_f1'], 3)} — лучший результат. "
         "HDBSCAN выигрывает по силуэту, но дробит города на кварталы и работает намного дольше. Анализ ошибок: "
         "кластеры вдали от населённых пунктов — базы отдыха, Чарынский каньон, Кольсайские озёра, петроглифы. "
         "В OSM у них нет точки населённого пункта. А один кластер — артефакт разметки: 56 резервуаров нефтебазы "
         "под Алматы отмечены как АЗС одной правкой.")

# ================================================================== 10. Гипотезы
s = prs.slides.add_slide(BLANK)
title(s, "Проверка гипотез", "α = 0,05; для направленных гипотез — односторонние тесты")
for i, row in enumerate(hyp.itertuples()):
    x, y = 0.6 + (i % 2) * 6.2, 1.75 + (i // 2) * 2.55
    confirmed = row.decision.startswith("H0 отвергается")
    card(s, x, y, 5.95, 2.3)
    badge = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x + 0.25), Inches(y + 0.25), Inches(1.9), Inches(0.42))
    badge.fill.solid()
    badge.fill.fore_color.rgb = GREEN if confirmed else RED
    badge.line.fill.background()
    badge.text_frame.text = "подтверждена" if confirmed else "не подтверждена"
    br = badge.text_frame.paragraphs[0].runs[0]
    br.font.size, br.font.bold, br.font.color.rgb, br.font.name = Pt(12), True, WHITE, FONT
    badge.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
    text(s, x + 2.35, y + 0.22, 3.4, 0.5, row.id, size=20, bold=True, color=NAVY)
    text(s, x + 0.25, y + 0.8, 5.5, 0.85, row.hypothesis, size=15, color=INK, bold=True)
    p_label = f"p {row.p_value_fmt}" if str(row.p_value_fmt).startswith("<") else f"p = {row.p_value_fmt}"
    # неразрывные пробел и дефис: «p < 1e-300» не разрывается между строками
    p_label = p_label.replace(" ", " ").replace("-", "‑")
    text(s, x + 0.25, y + 1.55, 5.5, 0.6, f"{row.test} · {row.effect} · {p_label}", size=13, color=MUTED)
footer(s, 10, TEAM[2])
notes(s, "Докладчик: Temirgalin Dinmukhammed.\nПроверили четыре гипотезы. Структура категорий Астаны и Алматы "
         "различается значимо — хи-квадрат, но сила связи по V Крамера небольшая. В мегаполисах у объектов чаще "
         "указаны часы работы — z-тест для долей. А вот связь обеспеченности с урбанизацией региона и с числом "
         "зданий в OSM не подтвердилась: корреляция Спирмена слабая и незначимая. Это тоже результат: обеспеченность "
         "в OSM зависит прежде всего от активности сообщества картографов.")

# ================================================================== 11. Демонстрация
s = prs.slides.add_slide(BLANK)
title(s, "Интерфейс: консольное меню и дашборд Streamlit", "python main.py  ·  streamlit run app.py")
if SHOT.exists():
    pic = picture(s, SHOT, 5.3, 1.6, w=7.5)
    pic.line.color.rgb = RGBColor(0xD6, 0xD5, 0xD0)
card(s, 0.6, 1.6, 4.4, 5.25, fill=NAVY)
menu_lines = ["1–11  шаги конвейера", "12  поиск POI по названию", "13  ближайшие POI к точке",
              "14  карточка региона", "15  любой SQL-запрос", "16  состояние проекта", "A   весь конвейер",
              "0   выход"]
text(s, 0.85, 1.8, 4.0, 0.4, "Консольное меню", size=16, bold=True, color=GOLD)
text(s, 0.85, 2.35, 4.0, 3.3, menu_lines, size=16, color=WHITE, font="Consolas")
text(s, 0.85, 5.55, 4.0, 1.2, ["try/except на каждом вводе;", "состояние — в run_state.json"], size=13,
     color=RGBColor(0xBF, 0xE6, 0xEF))
footer(s, 11, TEAM[1])
notes(s, "Докладчик: Yergaliev Aron.\nДва интерфейса. Консольное меню: шаги конвейера, поиск по названию — "
         "параметризованный SQL, поиск ближайших объектов к точке — BallTree с метрикой haversine, карточка "
         "региона и выполнение любого запроса. Некорректный ввод перехватывается try/except. Дашборд Streamlit: "
         "фильтры по региону, категории, городу, году правки; вкладки с картой, городами, SQL-запросами и поиском. "
         "Здесь можно показать живую демонстрацию.")

# ================================================================== 12. Выводы и вклад
s = prs.slides.add_slide(BLANK)
s.background.fill.solid()
s.background.fill.fore_color.rgb = NAVY
text(s, 0.6, 0.35, 12, 0.8, "Выводы и вклад участников", size=32, bold=True, color=WHITE)
fast = bench.sort_values("median_seconds").iloc[0]
conclusions = [
    f"Поток + чанки + Parquet: 34,5 млн узлов при пике ~{num(ext['features']['peak_memory_mb'] / 1000, 1)} ГБ; типы −{num(mem['saving_pct'])} % памяти",
    f"Обеспеченность POI неравномерна: {num(bottom['poi_per_100k'])}–{num(top['poi_per_100k'])} на 100 тыс.; Алматы > Астана > Шымкент",
    f"Polars lazy и DuckDB — в {num(min(b.loc['polars_lazy', 'speedup_vs_baseline'], b.loc['duckdb_sql', 'speedup_vs_baseline']), 1)}–"
    f"{num(max(b.loc['polars_lazy', 'speedup_vs_baseline'], b.loc['duckdb_sql', 'speedup_vs_baseline']), 1)} раза быстрее baseline; "
    f"DBSCAN — лучший F1 ({num(clu['settlement_f1'].max(), 3)})",
    "OSM отражает активность картографов: H1 и H4 не подтвердились",
]
for i, line in enumerate(conclusions):
    text(s, 0.6, 1.35 + i * 0.62, 12.2, 0.55, f"—  {line}", size=17, color=WHITE)
roles = [(TEAM[0], "Данные и производительность", "download, extract, optimize, aggregates, benchmark, pipeline, меню"),
         (TEAM[1], "Пространство, качество и БД", "spatial, quality, SQLite + ER, 11 SQL-запросов, поиск, Streamlit"),
         (TEAM[2], "Аналитика и ML", "категории, показатели, DBSCAN, гипотезы, графики, отчёт")]
for i, (name, role, mods) in enumerate(roles):
    x = 0.6 + i * 4.1
    card(s, x, 4.15, 3.85, 2.65, fill=RGBColor(0x15, 0x45, 0x5C))
    text(s, x + 0.2, 4.28, 3.5, 0.45, name, size=17, bold=True, color=GOLD)
    text(s, x + 0.2, 4.75, 3.5, 0.45, role, size=14, bold=True, color=WHITE)
    text(s, x + 0.2, 5.25, 3.5, 1.2, mods, size=13, color=RGBColor(0xBF, 0xE6, 0xEF))
    text(s, x + 0.2, 6.35, 3.5, 0.35, "вклад ≈ 33 %", size=12, color=WHITE, italic=True)
text(s, 0.6, 6.95, 12, 0.35, "github.com/Zhar04/programming_for_ai_final", size=12, color=RGBColor(0xBF, 0xE6, 0xEF))
notes(s, "Докладчик: Zharken Utegenov (выводы), затем каждый участник одной фразой — свой вклад.\n"
         "Итоги: потоковая обработка позволяет работать с данными больше памяти; обеспеченность POI в OSM сильно "
         "различается между регионами; для агрегатов лучший инструмент — Polars, для кластеризации — DBSCAN. "
         "Работу разделили поровну, по трети на каждого. Спасибо за внимание, готовы ответить на вопросы.")

prs.save(OUT)
print(f"Презентация сохранена: {OUT}")
