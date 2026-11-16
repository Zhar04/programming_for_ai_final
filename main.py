"""
Точка входа: консольное меню проекта
«OpenStreetMap Kazakhstan: Points of Interest Analytics».

Запуск:
    python main.py            — интерактивное меню
    python main.py --all      — выполнить весь конвейер без меню
    python main.py --step pois — выполнить один шаг (ключи шагов см. в src/pipeline.py)
"""
import argparse
import sys

import pandas as pd

from src import config, database, pipeline
from src.categories import CATEGORY_NAMES_RU
from src.search import nearest_pois
from src.utils import load_json, log

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 12)


def print_menu() -> None:
    """Печатает пункты меню. Номера 1–11 соответствуют шагам конвейера."""
    print("\n" + "=" * 64)
    print("  OpenStreetMap Kazakhstan: Points of Interest Analytics")
    print("=" * 64)
    for number, (_, _, description) in enumerate(pipeline.STEPS, start=1):
        print(f"  {number:>2} – {description}")
    print("  12 – Поиск POI по названию (SQL)")
    print("  13 – Ближайшие POI к точке (широта/долгота)")
    print("  14 – Показатели региона")
    print("  15 – Выполнить SQL-запрос из sql/queries.sql")
    print("  16 – Состояние проекта (какие шаги выполнены)")
    print("   A – Запустить весь конвейер")
    print("   0 – Выход")


def ask_int(prompt: str, low: int, high: int) -> int:
    """Запрашивает целое число в диапазоне, пока пользователь не введёт корректное."""
    while True:
        raw = input(prompt).strip()
        try:
            value = int(raw)
        except ValueError:
            print("  Нужно ввести целое число.")
            continue
        if low <= value <= high:
            return value
        print(f"  Число должно быть от {low} до {high}.")


def ask_float(prompt: str) -> float:
    """Запрашивает дробное число (допускается запятая вместо точки)."""
    while True:
        raw = input(prompt).strip().replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            print("  Некорректное число, попробуйте ещё раз (например 43.2389).")


def menu_search() -> None:
    """Пункт 12: поиск по названию с фильтром по городу."""
    if not config.DB_PATH.exists():
        print("  База ещё не создана — выполните пункт 7.")
        return
    text = input("  Часть названия (например «Магнум»): ").strip()
    if not text:
        print("  Пустой запрос.")
        return
    city = input("  Город (Enter — любой): ").strip() or None
    conn = database.connect()
    try:
        result = database.search_pois(conn, text, city=city)
    finally:
        conn.close()
    print(result.to_string(index=False) if len(result) else "  Ничего не найдено.")


def menu_nearest() -> None:
    """Пункт 13: k ближайших POI к введённой точке."""
    print("  Пример: Астана, Байтерек — 51.1283, 71.4305; Алматы, пл. Республики — 43.2380, 76.9450")
    lat = ask_float("  Широта: ")
    lon = ask_float("  Долгота: ")
    codes = list(CATEGORY_NAMES_RU)
    for i, code in enumerate(codes, start=1):
        print(f"    {i:>2} – {CATEGORY_NAMES_RU[code]}")
    choice = ask_int("  Категория (0 — любая): ", 0, len(codes))
    category = codes[choice - 1] if choice > 0 else None
    try:
        result = nearest_pois(lat, lon, category=category, k=10)
    except (ValueError, FileNotFoundError) as err:
        print(f"  Ошибка: {err}")
        return
    print(result.to_string(index=False) if len(result) else "  Ничего не найдено.")


def menu_region() -> None:
    """Пункт 14: карточка региона по коду ISO или части названия."""
    try:
        stats = pd.read_parquet(config.REGION_STATS_PATH)
    except FileNotFoundError:
        print("  Нет файла с показателями — выполните пункт 6.")
        return
    query = input("  Код (KZ-71) или часть названия региона: ").strip().lower()
    found = stats[(stats["iso_code"].str.lower() == query) |
                  stats["region_ru"].str.lower().str.contains(query, regex=False)]
    if found.empty:
        print("  Регион не найден.")
    elif len(found) > 1:
        print("  Найдено несколько регионов: " + ", ".join(found["region_ru"]))
    else:
        row = found.iloc[0]
        print(f"\n  {row['region_ru']} ({row['iso_code']})")
        print(f"  Население (01.01.2026): {row['pop_total']:,}".replace(",", " "))
        print(f"  Площадь: {row['area_km2']:,.0f} км²".replace(",", " "))
        print(f"  Сервисных POI: {row['n_service_poi']:,}".replace(",", " "))
        print(f"  POI на 100 тыс. жителей: {row['poi_per_100k']:.1f}")
        print(f"  POI на 1000 км²: {row['poi_per_1000km2']:.1f}")
        print(f"  Доля POI с часами работы: {row['opening_hours_share']:.1%}")
        rank = int((stats["poi_per_100k"] > row["poi_per_100k"]).sum()) + 1
        print(f"  Место среди 20 регионов: {rank}")


def menu_sql() -> None:
    """Пункт 15: выбрать и выполнить один из запросов из файла queries.sql."""
    if not config.DB_PATH.exists():
        print("  База ещё не создана — выполните пункт 7.")
        return
    queries = database.parse_queries()
    for i, q in enumerate(queries, start=1):
        print(f"    {i:>2} – {q['name']}: {q['desc']}")
    choice = ask_int("  Номер запроса: ", 1, len(queries))
    conn = database.connect()
    try:
        df = database.run_query(conn, queries[choice - 1]["name"])
    finally:
        conn.close()
    print(df.head(25).to_string(index=False))


def menu_state() -> None:
    """Пункт 16: какие шаги уже выполнены (читается из outputs/run_state.json)."""
    state = load_json(config.RUN_STATE_PATH, default={})
    for key, _, description in pipeline.STEPS:
        mark = state.get(key, {}).get("finished_at", "— не выполнялся")
        print(f"  {description:<52} {mark}")


def run_menu() -> None:
    """Главный цикл меню: работает, пока пользователь не выберет 0."""
    actions = {12: menu_search, 13: menu_nearest, 14: menu_region, 15: menu_sql, 16: menu_state}
    while True:
        print_menu()
        choice = input("Выберите пункт: ").strip().upper()
        if choice == "0":
            print("До свидания!")
            break
        if choice == "A":
            pipeline.run_all()
            continue
        try:
            number = int(choice)
        except ValueError:
            print("  Введите номер пункта из меню.")
            continue
        try:
            if 1 <= number <= len(pipeline.STEPS):
                key, func, description = pipeline.STEPS[number - 1]
                log(f"=== {description} ===")
                func()
            elif number in actions:
                actions[number]()
            else:
                print("  Такого пункта нет.")
        except FileNotFoundError as err:
            # чаще всего — не выполнен предыдущий шаг конвейера
            print(f"  Не найден файл: {err}. Выполните предыдущие шаги.")
        except KeyboardInterrupt:
            print("\n  Операция прервана пользователем.")


def main() -> None:
    parser = argparse.ArgumentParser(description="OSM Kazakhstan POI Analytics")
    parser.add_argument("--all", action="store_true", help="выполнить весь конвейер")
    parser.add_argument("--step", choices=[key for key, _, _ in pipeline.STEPS],
                        help="выполнить один шаг конвейера")
    args = parser.parse_args()
    config.ensure_dirs()
    if args.all:
        pipeline.run_all()
    elif args.step:
        dict((k, f) for k, f, _ in pipeline.STEPS)[args.step]()
    else:
        run_menu()


if __name__ == "__main__":
    # Чтобы кириллица корректно печаталась в консоли Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
