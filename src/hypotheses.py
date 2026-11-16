"""
Шаг 10. Проверка содержательных гипотез на данных (уровень значимости α = 0,05).

H1. Чем выше доля городского населения в регионе, тем больше POI на 100 тыс. жителей.
    Тест: ранговая корреляция Спирмена (односторонняя, ρ > 0), n = 20 регионов.
H2. Структура POI в Астане и Алматы различается (разный "профиль" городов).
    Тест: хи-квадрат на таблице сопряжённости город × категория; сила связи — V Крамера.
H3. В трёх мегаполисах у POI чаще указаны часы работы, чем в остальных регионах.
    Тест: z-тест для двух долей (односторонний).
H4. Обеспеченность POI в OSM отражает полноту картирования: где больше зданий
    на 100 тыс. жителей, там больше и POI. Тест: корреляция Спирмена (ρ > 0).
"""
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.proportion import proportions_ztest

from src import config
from src.categories import CATEGORY_NAMES_RU

ALPHA = 0.05


def decision(p_value: float) -> str:
    """Решение по гипотезе: отвергаем H0, если p < α."""
    return "H0 отвергается (гипотеза подтверждается)" if p_value < ALPHA \
        else "H0 не отвергается (гипотеза не подтверждается)"


def h1_urbanization(region_stats: pd.DataFrame) -> dict:
    """H1: доля городского населения ↔ POI на 100 тыс."""
    rho, p = stats.spearmanr(region_stats["urban_share"], region_stats["poi_per_100k"],
                             alternative="greater")
    return {"id": "H1",
            "hypothesis": "Больше доля городского населения → больше POI на 100 тыс.",
            "test": "Спирмен, односторонний, n=20",
            "statistic": round(float(rho), 3), "p_value": float(p),
            "effect": f"ρ = {rho:.2f}", "decision": decision(p)}


def h2_astana_vs_almaty(pois: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """H2: различие структуры категорий Астаны и Алматы (хи-квадрат + V Крамера)."""
    service = pois[pois["is_service"] & pois["region_iso"].astype(str).isin(["KZ-71", "KZ-75"])]
    table = pd.crosstab(service["region_iso"].astype(str), service["category"].astype(str))
    chi2, p, dof, expected = stats.chi2_contingency(table)
    n = table.to_numpy().sum()
    cramers_v = np.sqrt(chi2 / (n * (min(table.shape) - 1)))
    # стандартизованные остатки: где именно города расходятся сильнее всего
    residuals = (table - expected) / np.sqrt(expected)
    shares = table.div(table.sum(axis=1), axis=0) * 100
    detail = pd.DataFrame({
        "Астана, %": shares.loc["KZ-71"].round(1),
        "Алматы, %": shares.loc["KZ-75"].round(1),
        "остаток Алматы": residuals.loc["KZ-75"].round(1),
    })
    detail.index = [CATEGORY_NAMES_RU[c] for c in detail.index]
    detail = detail.sort_values("остаток Алматы", ascending=False)
    detail.to_csv(config.TABLES_DIR / "h2_astana_almaty_categories.csv")
    return ({"id": "H2", "hypothesis": "Структура категорий POI в Астане и Алматы различается",
             "test": f"χ², df={dof}, n={n}", "statistic": round(float(chi2), 1),
             "p_value": float(p), "effect": f"V Крамера = {cramers_v:.3f}",
             "decision": decision(p)}, detail)


def h3_opening_hours(pois: pd.DataFrame) -> dict:
    """H3: доля POI с часами работы в мегаполисах выше, чем в остальных регионах."""
    service = pois[pois["is_service"]]
    is_mega = service["region_iso"].astype(str).isin(config.MEGACITIES)
    counts = np.array([service.loc[is_mega, "oh_valid"].sum(), service.loc[~is_mega, "oh_valid"].sum()])
    nobs = np.array([is_mega.sum(), (~is_mega).sum()])
    z, p = proportions_ztest(counts, nobs, alternative="larger")
    share_mega, share_rest = counts / nobs
    return {"id": "H3",
            "hypothesis": "В мегаполисах у POI чаще указаны часы работы",
            "test": "z-тест для двух долей, односторонний",
            "statistic": round(float(z), 2), "p_value": float(p),
            "effect": f"{share_mega:.1%} против {share_rest:.1%}", "decision": decision(p)}


def h4_mapping_completeness(region_stats: pd.DataFrame) -> dict:
    """H4: здания на 100 тыс. ↔ POI на 100 тыс. (полнота картирования OSM)."""
    rho, p = stats.spearmanr(region_stats["buildings_per_100k"], region_stats["poi_per_100k"],
                             alternative="greater")
    return {"id": "H4",
            "hypothesis": "Больше зданий в OSM на 100 тыс. → больше POI на 100 тыс.",
            "test": "Спирмен, односторонний, n=20",
            "statistic": round(float(rho), 3), "p_value": float(p),
            "effect": f"ρ = {rho:.2f}", "decision": decision(p)}


def run_all(pois: pd.DataFrame, region_stats: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Проверяет все гипотезы, сохраняет таблицу результатов в CSV."""
    h2, h2_detail = h2_astana_vs_almaty(pois)
    results = pd.DataFrame([
        h1_urbanization(region_stats),
        h2,
        h3_opening_hours(pois),
        h4_mapping_completeness(region_stats),
    ])
    # p = 0.0 означает «меньше машинной точности» — так и пишем, а не 0
    results["p_value_fmt"] = results["p_value"].map(
        lambda p: "< 1e-300" if p == 0 else (f"{p:.2e}" if p < 0.001 else f"{p:.3f}"))
    results.to_csv(config.TABLES_DIR / "hypotheses.csv", index=False)
    return results, h2_detail
