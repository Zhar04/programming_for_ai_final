-- =====================================================================
-- Аналитические SQL-запросы к kz_poi.db.
-- Каждый запрос начинается со строки "-- name: <имя>" и "-- desc: <описание>":
-- по ним модуль src/database.py разбирает файл и выполняет запросы по очереди,
-- а результаты загружает в pandas (pd.read_sql_query).
-- Во всех запросах считаются только сервисные POI (categories.is_service = 1).
-- =====================================================================

-- name: q01_region_density
-- desc: Обеспеченность POI по регионам: на 100 тыс. жителей и на 1000 км² (JOIN + GROUP BY)
SELECT r.iso_code,
       r.name_ru                                         AS region,
       COUNT(*)                                          AS n_poi,
       r.pop_total,
       ROUND(COUNT(*) * 100000.0 / r.pop_total, 1)       AS poi_per_100k,
       ROUND(COUNT(*) * 1000.0 / r.area_km2, 2)          AS poi_per_1000km2
FROM pois p
JOIN poi_types  t ON t.type_id = p.type_id
JOIN categories c ON c.category_id = t.category_id
JOIN regions    r ON r.region_id = p.region_id
WHERE c.is_service = 1
GROUP BY r.region_id
ORDER BY poi_per_100k DESC;

-- name: q02_top3_categories_per_region
-- desc: Три самые массовые категории в каждом регионе (CTE + ROW_NUMBER() OVER PARTITION BY)
WITH counts AS (
    SELECT r.name_ru AS region, c.name_ru AS category, COUNT(*) AS n
    FROM pois p
    JOIN poi_types  t ON t.type_id = p.type_id
    JOIN categories c ON c.category_id = t.category_id
    JOIN regions    r ON r.region_id = p.region_id
    WHERE c.is_service = 1
    GROUP BY r.name_ru, c.name_ru
),
ranked AS (
    SELECT region, category, n,
           ROW_NUMBER() OVER (PARTITION BY region ORDER BY n DESC)  AS rn,
           ROUND(100.0 * n / SUM(n) OVER (PARTITION BY region), 1)  AS share_pct
    FROM counts
)
SELECT region, rn AS place, category, n, share_pct
FROM ranked
WHERE rn <= 3
ORDER BY region, rn;

-- name: q03_food_share_above_national
-- desc: Регионы, где доля общепита выше средней по стране (GROUP BY + HAVING + подзапрос)
SELECT r.name_ru AS region,
       COUNT(*) AS n_poi,
       SUM(CASE WHEN c.code = 'food' THEN 1 ELSE 0 END) AS n_food,
       ROUND(100.0 * SUM(CASE WHEN c.code = 'food' THEN 1 ELSE 0 END) / COUNT(*), 2) AS food_share_pct
FROM pois p
JOIN poi_types  t ON t.type_id = p.type_id
JOIN categories c ON c.category_id = t.category_id
JOIN regions    r ON r.region_id = p.region_id
WHERE c.is_service = 1
GROUP BY r.region_id
HAVING 1.0 * SUM(CASE WHEN c.code = 'food' THEN 1 ELSE 0 END) / COUNT(*) > (
    SELECT 1.0 * SUM(CASE WHEN c2.code = 'food' THEN 1 ELSE 0 END) / COUNT(*)
    FROM pois p2
    JOIN poi_types  t2 ON t2.type_id = p2.type_id
    JOIN categories c2 ON c2.category_id = t2.category_id
    WHERE c2.is_service = 1
)
ORDER BY food_share_pct DESC;

-- name: q04_megacities_vs_other_cities
-- desc: Астана vs Алматы vs Шымкент vs другие города: POI на 100 тыс. и доля категории (CTE + оконная сумма)
WITH grp AS (
    SELECT ci.city_group, c.name_ru AS category, COUNT(*) AS n
    FROM pois p
    JOIN cities     ci ON ci.city_id = p.city_id
    JOIN poi_types  t  ON t.type_id = p.type_id
    JOIN categories c  ON c.category_id = t.category_id
    WHERE c.is_service = 1
    GROUP BY ci.city_group, c.name_ru
),
pop AS (
    SELECT city_group, SUM(population) AS population FROM cities GROUP BY city_group
)
SELECT g.city_group, g.category, g.n,
       ROUND(g.n * 100000.0 / pop.population, 1)                       AS per_100k,
       ROUND(100.0 * g.n / SUM(g.n) OVER (PARTITION BY g.city_group), 1) AS share_pct
FROM grp g
JOIN pop ON pop.city_group = g.city_group
ORDER BY g.city_group, g.n DESC;

-- name: q05_region_rank_quartiles
-- desc: Рейтинг регионов: RANK, квартили NTILE(4) и отставание от лидера/предыдущего (LAG)
WITH dens AS (
    SELECT r.name_ru AS region, r.region_type,
           COUNT(*) * 100000.0 / r.pop_total AS poi_per_100k
    FROM pois p
    JOIN poi_types  t ON t.type_id = p.type_id
    JOIN categories c ON c.category_id = t.category_id
    JOIN regions    r ON r.region_id = p.region_id
    WHERE c.is_service = 1
    GROUP BY r.region_id
)
SELECT region, region_type,
       ROUND(poi_per_100k, 1)                                          AS poi_per_100k,
       RANK()     OVER (ORDER BY poi_per_100k DESC)                    AS rank_all,
       RANK()     OVER (PARTITION BY region_type ORDER BY poi_per_100k DESC) AS rank_in_type,
       NTILE(4)   OVER (ORDER BY poi_per_100k DESC)                    AS quartile,
       ROUND(poi_per_100k - LAG(poi_per_100k) OVER (ORDER BY poi_per_100k DESC), 1) AS diff_to_previous,
       ROUND(poi_per_100k - FIRST_VALUE(poi_per_100k) OVER (ORDER BY poi_per_100k DESC), 1) AS diff_to_leader
FROM dens
ORDER BY rank_all;

-- name: q06_pareto_cumulative
-- desc: Накопленная доля POI по регионам — сколько регионов дают 50% и 80% всех точек (SUM() OVER)
WITH n_by_region AS (
    SELECT r.name_ru AS region, COUNT(*) AS n
    FROM pois p
    JOIN poi_types  t ON t.type_id = p.type_id
    JOIN categories c ON c.category_id = t.category_id
    JOIN regions    r ON r.region_id = p.region_id
    WHERE c.is_service = 1
    GROUP BY r.region_id
)
SELECT region, n,
       SUM(n) OVER (ORDER BY n DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_total,
       ROUND(100.0 * SUM(n) OVER (ORDER BY n DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
             / SUM(n) OVER (), 1) AS cumulative_pct
FROM n_by_region
ORDER BY n DESC;

-- name: q07_attribute_completeness
-- desc: Полнота атрибутов POI по регионам (AVG флагов, GROUP BY + HAVING COUNT > 2000)
SELECT r.name_ru AS region,
       COUNT(*)                                   AS n_poi,
       ROUND(100.0 * AVG(p.name IS NOT NULL), 1)  AS named_pct,
       ROUND(100.0 * AVG(p.has_opening_hours), 1) AS opening_hours_pct,
       ROUND(100.0 * AVG(p.has_phone), 1)         AS phone_pct,
       ROUND(100.0 * AVG(p.has_website), 1)       AS website_pct,
       ROUND(100.0 * AVG(p.name_kk IS NOT NULL), 1) AS name_kk_tag_pct
FROM pois p
JOIN poi_types  t ON t.type_id = p.type_id
JOIN categories c ON c.category_id = t.category_id
JOIN regions    r ON r.region_id = p.region_id
WHERE c.is_service = 1
GROUP BY r.region_id
HAVING COUNT(*) > 2000
ORDER BY opening_hours_pct DESC;

-- name: q08_chain_brands
-- desc: Сетевые бренды минимум в 5 регионах и их основная категория (HAVING + CTE + ROW_NUMBER)
WITH brand_cat AS (
    SELECT p.brand, c.name_ru AS category, COUNT(*) AS n,
           ROW_NUMBER() OVER (PARTITION BY p.brand ORDER BY COUNT(*) DESC) AS rn
    FROM pois p
    JOIN poi_types  t ON t.type_id = p.type_id
    JOIN categories c ON c.category_id = t.category_id
    WHERE p.brand IS NOT NULL
    GROUP BY p.brand, c.name_ru
)
SELECT p.brand,
       COUNT(*)                     AS n_points,
       COUNT(DISTINCT p.region_id)  AS n_regions,
       bc.category                  AS main_category
FROM pois p
JOIN brand_cat bc ON bc.brand = p.brand AND bc.rn = 1
WHERE p.brand IS NOT NULL
GROUP BY p.brand
HAVING COUNT(DISTINCT p.region_id) >= 5
ORDER BY n_points DESC
LIMIT 15;

-- name: q09_edits_by_year
-- desc: Год последней правки POI: количество, накопленный итог и прирост к прошлому году (LAG)
WITH by_year AS (
    SELECT CAST(strftime('%Y', last_edit) AS INTEGER) AS year, COUNT(*) AS n
    FROM pois
    WHERE last_edit IS NOT NULL
    GROUP BY year
)
SELECT year, n,
       SUM(n) OVER (ORDER BY year)                       AS cumulative,
       n - LAG(n) OVER (ORDER BY year)                   AS change_vs_prev_year,
       ROUND(100.0 * n / SUM(n) OVER (), 1)              AS share_pct
FROM by_year
ORDER BY year;

-- name: q10_cities_vs_own_region
-- desc: Города, у которых POI на 100 тыс. выше, чем в целом по их области (коррелированный подзапрос)
SELECT ci.name AS city,
       r.name_ru AS region,
       ROUND(COUNT(*) * 100000.0 / ci.population, 1) AS city_per_100k,
       ROUND((SELECT COUNT(*) * 100000.0 / r2.pop_total
              FROM pois p2
              JOIN poi_types  t2 ON t2.type_id = p2.type_id
              JOIN categories c2 ON c2.category_id = t2.category_id
              JOIN regions    r2 ON r2.region_id = p2.region_id
              WHERE c2.is_service = 1 AND p2.region_id = ci.region_id), 1) AS region_per_100k
FROM pois p
JOIN cities     ci ON ci.city_id = p.city_id
JOIN regions    r  ON r.region_id = ci.region_id
JOIN poi_types  t  ON t.type_id = p.type_id
JOIN categories c  ON c.category_id = t.category_id
WHERE c.is_service = 1 AND r.region_type = 'oblast'
GROUP BY ci.city_id
HAVING city_per_100k > region_per_100k
ORDER BY city_per_100k DESC;

-- name: q11_largest_dbscan_clusters
-- desc: Крупнейшие кластеры DBSCAN: размер, регион и доминирующая категория (CTE + JOIN + окно)
WITH best AS (
    SELECT run_id FROM clustering_runs WHERE method = 'DBSCAN' ORDER BY settlement_f1 DESC LIMIT 1
),
members AS (
    SELECT pc.cluster_label, p.region_id, c.name_ru AS category
    FROM poi_clusters pc
    JOIN best          ON best.run_id = pc.run_id
    JOIN pois       p  ON p.poi_id = pc.poi_id
    JOIN poi_types  t  ON t.type_id = p.type_id
    JOIN categories c  ON c.category_id = t.category_id
    WHERE pc.cluster_label >= 0
),
cat_counts AS (
    SELECT cluster_label, category, COUNT(*) AS n,
           ROW_NUMBER() OVER (PARTITION BY cluster_label ORDER BY COUNT(*) DESC) AS rn
    FROM members
    GROUP BY cluster_label, category
),
reg_counts AS (
    SELECT cluster_label, region_id,
           ROW_NUMBER() OVER (PARTITION BY cluster_label ORDER BY COUNT(*) DESC) AS rn
    FROM members
    GROUP BY cluster_label, region_id
),
sizes AS (
    SELECT cluster_label, COUNT(*) AS size, COUNT(DISTINCT region_id) AS n_regions
    FROM members
    GROUP BY cluster_label
)
SELECT s.cluster_label, s.size, s.n_regions,
       r.name_ru AS main_region,
       cc.category AS top_category,
       ROUND(100.0 * cc.n / s.size, 1) AS top_category_pct
FROM sizes s
JOIN cat_counts cc ON cc.cluster_label = s.cluster_label AND cc.rn = 1
JOIN reg_counts rc ON rc.cluster_label = s.cluster_label AND rc.rn = 1
JOIN regions    r  ON r.region_id = rc.region_id
ORDER BY s.size DESC
LIMIT 10;
