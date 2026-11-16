"""
Справочник тематических категорий POI.

В OSM сотни значений тегов (amenity=cafe, shop=supermarket, leisure=park ...).
Для анализа их удобно свести в 12 понятных групп. Словари ниже — это
"правила перевода" пары (ключ, значение) OSM в нашу категорию.
"""

# Код категории → русское название (используется в графиках, SQL и дашборде)
CATEGORY_NAMES_RU = {
    "food": "Питание",
    "retail": "Торговля",
    "education": "Образование",
    "health": "Здравоохранение",
    "finance": "Финансы",
    "transport": "Транспорт и авто",
    "tourism": "Туризм и размещение",
    "leisure": "Спорт и досуг",
    "culture": "Культура и религия",
    "public": "Госуслуги и безопасность",
    "services": "Офисы и услуги",
    "urban": "Городская инфраструктура",
}

# Категория "urban" (скамейки, урны, парковки, туалеты) — это элементы среды,
# а не сервисы. В основных показателях плотности её не учитываем.
SERVICE_CATEGORIES = [c for c in CATEGORY_NAMES_RU if c != "urban"]

# Значения amenity=* по группам (всё, что не перечислено, попадает в "urban")
AMENITY_GROUPS = {
    "food": ["restaurant", "cafe", "fast_food", "bar", "pub", "food_court",
             "ice_cream", "biergarten", "canteen", "confectionery"],
    "education": ["school", "kindergarten", "college", "university", "library",
                  "language_school", "driving_school", "music_school", "training",
                  "childcare", "prep_school", "research_institute", "dancing_school",
                  "toy_library", "education_centre"],
    "health": ["hospital", "clinic", "doctors", "dentist", "pharmacy", "veterinary",
               "nursing_home", "social_facility", "health_post", "baby_hatch"],
    "finance": ["bank", "atm", "bureau_de_change", "payment_terminal", "money_transfer",
                "payment_centre", "money_lender"],
    "transport": ["fuel", "bus_station", "taxi", "car_wash", "car_rental",
                  "charging_station", "ferry_terminal", "vehicle_inspection",
                  "bicycle_rental", "car_sharing", "boat_rental", "compressed_air",
                  "weighbridge", "driver_training"],
    "culture": ["place_of_worship", "theatre", "cinema", "arts_centre", "community_centre",
                "events_venue", "music_venue", "planetarium", "exhibition_centre",
                "social_centre", "conference_centre", "studio", "nightclub", "casino",
                "monastery"],
    # amenity=public_building сюда НЕ входит: это устаревший тег OSM, который не говорит,
    # какая услуга оказывается (аудит: 72% таких объектов — безымянные здания в одной
    # Алматинской области, массовая разметка 2018–2019 гг.) → попадает в "urban"
    "public": ["police", "fire_station", "post_office", "townhall", "courthouse", "prison",
               "ranger_station", "customs", "border_control",
               "post_depot", "embassy", "rescue_station"],
    "retail": ["marketplace", "parcel_locker"],   # постаматы (Kaspi, Ozon) — пункты выдачи
    "services": ["internet_cafe", "coworking_space", "funeral_hall", "crematorium",
                 "public_bath"],
}

# Обратный словарь: значение amenity → категория (строится один раз циклом)
AMENITY_TO_CATEGORY = {}
for _category, _values in AMENITY_GROUPS.items():
    for _value in _values:
        AMENITY_TO_CATEGORY[_value] = _category

TRANSPORT_SHOPS = {"car_repair", "car", "car_parts", "tyres", "motorcycle", "fuel"}
CULTURE_TOURISM = {"museum", "gallery", "artwork"}


def categorize(key: str, value: str) -> str:
    """
    Возвращает код тематической категории для пары тегов OSM.
    Пример: ("amenity", "cafe") → "food"; ("shop", "car_repair") → "transport".
    """
    if value is None:
        return "urban"
    # В OSM встречаются множественные значения "cafe;restaurant" — берём первое
    value = str(value).split(";")[0].strip().lower()

    if key == "amenity":
        return AMENITY_TO_CATEGORY.get(value, "urban")
    elif key == "shop":
        return "transport" if value in TRANSPORT_SHOPS else "retail"
    elif key == "healthcare":
        return "health"
    elif key == "tourism":
        return "culture" if value in CULTURE_TOURISM else "tourism"
    elif key in ("leisure", "sport"):
        return "leisure"
    elif key == "office":
        return "public" if value == "government" else "services"
    elif key == "craft":
        return "services"
    elif key == "historic":
        # межевые камни (boundary_stone) — геодезические знаки, а не объекты культуры
        return "urban" if value == "boundary_stone" else "culture"
    elif key == "emergency":
        return "health" if value == "ambulance_station" else "urban"
    else:
        return "urban"
