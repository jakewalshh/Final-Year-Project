import logging
import json
import os
import random
import re

from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from recipes.models import Recipe, RecipeIngredient, RecipeStep, RecipeTag, Tag
from recipes.planning import build_plan_queryset, parse_prompt_to_query, sanitize_query
from recipes.views import _serialize_recipe

from .models import MealPlan, MealPlanItem, ShoppingList, UserPreference
from .serializers import (
    MealPlanListSerializer,
    MealPlanSerializer,
    RegisterSerializer,
    ShoppingListSerializer,
    SwapMealSerializer,
    UserPreferenceSerializer,
    UserSummarySerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _normalize_string_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []

    output = []
    seen = set()
    for item in value:
        token = str(item or "").strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        output.append(token)
    return output


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_optional_int(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _base_queryset():
    return Recipe.objects.prefetch_related(
        Prefetch(
            "recipe_ingredients",
            queryset=RecipeIngredient.objects.select_related("ingredient").order_by("position"),
            to_attr="prefetched_recipe_ingredients",
        ),
        Prefetch(
            "steps",
            queryset=RecipeStep.objects.order_by("step_number"),
            to_attr="prefetched_steps",
        ),
        Prefetch(
            "recipe_tags",
            queryset=RecipeTag.objects.select_related("tag"),
            to_attr="prefetched_recipe_tags",
        ),
    )


def _merge_preference_constraints(parsed_query: dict, preference: UserPreference | None) -> dict:
    merged = dict(parsed_query)
    warnings = list(merged.get("parser_warnings", []))

    if not preference:
        merged["parser_warnings"] = warnings
        return merged

    excluded_ingredients = list(merged.get("exclude_ingredients", []))
    include_tags = list(merged.get("include_tags", []))
    excluded_tags = list(merged.get("exclude_tags", []))

    for ingredient in preference.excluded_ingredients:
        ingredient = str(ingredient).strip().lower()
        if ingredient and ingredient not in excluded_ingredients:
            excluded_ingredients.append(ingredient)
            warnings.append(f"Applied preference exclusion ingredient: {ingredient}")

    for tag in preference.preferred_tags:
        tag = str(tag).strip().lower()
        if tag and tag not in include_tags:
            include_tags.append(tag)

    for tag in preference.excluded_tags:
        tag = str(tag).strip().lower()
        if tag and tag not in excluded_tags:
            excluded_tags.append(tag)

    if merged.get("max_minutes") is None and preference.max_minutes_default:
        merged["max_minutes"] = preference.max_minutes_default

    nutrition_defaults = preference.nutrition_defaults or {}
    if merged.get("max_calories") is None and nutrition_defaults.get("max_calories") is not None:
        merged["max_calories"] = nutrition_defaults.get("max_calories")
    if merged.get("min_protein_pdv") is None and nutrition_defaults.get("min_protein_pdv") is not None:
        merged["min_protein_pdv"] = nutrition_defaults.get("min_protein_pdv")
    if merged.get("max_carbs_pdv") is None and nutrition_defaults.get("max_carbs_pdv") is not None:
        merged["max_carbs_pdv"] = nutrition_defaults.get("max_carbs_pdv")

    merged["exclude_ingredients"] = excluded_ingredients
    merged["include_tags"] = include_tags
    merged["exclude_tags"] = excluded_tags
    merged["parser_warnings"] = warnings
    return merged


def _apply_tag_overrides(parsed_query: dict, include_tags: list[str], exclude_tags: list[str]) -> dict:
    updated = dict(parsed_query)
    warnings = list(updated.get("parser_warnings", []))

    include = _normalize_string_list(updated.get("include_tags")) + include_tags
    exclude = _normalize_string_list(updated.get("exclude_tags")) + exclude_tags
    include = _normalize_string_list(include)
    exclude = _normalize_string_list(exclude)

    conflicts = [tag for tag in include if tag in set(exclude)]
    if conflicts:
        include = [tag for tag in include if tag not in set(conflicts)]
        warnings.append(
            "Removed include tags that also appeared in exclusions: " + ", ".join(sorted(set(conflicts)))
        )

    updated["include_tags"] = include
    updated["exclude_tags"] = exclude
    updated["parser_warnings"] = warnings
    return updated


PROTEIN_FAMILY_MAP = {
    "chicken": "poultry",
    "turkey": "poultry",
    "duck": "poultry",
    "beef": "red_meat",
    "lamb": "red_meat",
    "pork": "pork",
    "ham": "pork",
    "bacon": "pork",
    "fish": "fish",
    "salmon": "fish",
    "tuna": "fish",
    "cod": "fish",
    "halibut": "fish",
    "shrimp": "seafood",
    "prawn": "seafood",
    "tofu": "plant_protein",
    "bean": "plant_protein",
    "lentil": "plant_protein",
    "chickpea": "plant_protein",
    "egg": "egg",
}

PROTEIN_AFFORDABILITY = {
    "plant_protein": 0.95,
    "egg": 0.9,
    "poultry": 0.8,
    "pork": 0.65,
    "fish": 0.55,
    "seafood": 0.45,
    "red_meat": 0.35,
}

PROTEIN_SUSTAINABILITY = {
    "plant_protein": 0.95,
    "egg": 0.8,
    "poultry": 0.6,
    "pork": 0.45,
    "fish": 0.52,
    "seafood": 0.4,
    "red_meat": 0.2,
}

NON_MEAL_NAME_HINTS = {
    "sauce",
    "dressing",
    "dip",
    "marinade",
    "gravy",
    "frosting",
    "icing",
    "syrup",
    "condiment",
    "rub",
    "shortcake",
    "muffin",
    "cookie",
    "brownie",
    "cupcake",
    "stuffing",
    "fritter",
    "salad",
    "slaw",
}

HARD_NON_MEAL_NAME_HINTS = {
    "dessert",
    "sauce",
    "dressing",
    "dip",
    "marinade",
    "frosting",
    "icing",
    "syrup",
    "condiment",
    "cookie",
    "brownie",
    "cupcake",
    "muffin",
    "shortcake",
}

NON_MEAL_TAG_HINTS = {
    "dessert",
    "desserts",
    "cookie",
    "cookies",
    "cakes",
    "cake",
    "cupcakes",
    "muffins",
    "quick-breads",
    "bread",
    "breads",
    "dips",
    "dip",
    "sauces",
    "sauce",
    "condiments",
    "appetizer",
    "appetizers",
    "snacks",
    "snack",
    "side-dishes",
    "side dish",
    "side",
    "beverages",
    "drinks",
    "cocktails",
}

MEAL_TAG_HINTS = {
    "main-dish",
    "main course",
    "main",
    "dinner",
    "lunch",
    "breakfast",
    "one-dish meal",
    "meat",
    "poultry",
    "seafood",
}

MEAL_NAME_HINTS = {
    "soup",
    "stew",
    "curry",
    "pasta",
    "sandwich",
    "burger",
    "pizza",
    "tacos",
    "bowl",
    "risotto",
    "chili",
    "roast",
    "stir fry",
    "stir-fry",
    "lasagna",
    "casserole",
    "kebab",
    "kabob",
}

OPTIMIZATION_PROFILES = {
    "balanced": {
        "base_weight": 0.58,
        "overlap_weight": 0.42,
        "diversity_penalty": 0.10,
        "component_weights": {
            "anchor": 0.40,
            "affordability": 0.28,
            "sustainability": 0.14,
            "meal_quality": 0.18,
        },
    },
    "budget": {
        "base_weight": 0.55,
        "overlap_weight": 0.45,
        "diversity_penalty": 0.08,
        "component_weights": {
            "anchor": 0.30,
            "affordability": 0.42,
            "sustainability": 0.10,
            "meal_quality": 0.18,
        },
    },
    "sustainability": {
        "base_weight": 0.55,
        "overlap_weight": 0.45,
        "diversity_penalty": 0.08,
        "component_weights": {
            "anchor": 0.30,
            "affordability": 0.14,
            "sustainability": 0.38,
            "meal_quality": 0.18,
        },
    },
}


def _clamp_float(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _normalize_optimize_mode(value: str | None) -> str:
    mode = str(value or "balanced").strip().lower()
    if mode in OPTIMIZATION_PROFILES:
        return mode
    return "balanced"


def _recipe_ingredient_names(recipe: Recipe) -> list[str]:
    if hasattr(recipe, "prefetched_recipe_ingredients") and recipe.prefetched_recipe_ingredients:
        return [ri.ingredient.name for ri in recipe.prefetched_recipe_ingredients]
    return [x.strip() for x in recipe.ingredients.split(",") if x.strip()]


def _canonicalize_terms(raw_name: str) -> set[str]:
    cleaned = str(raw_name or "").strip().lower()
    if not cleaned:
        return set()

    segments = [part.strip() for part in re.split(r"\band\b|&|/|\+", cleaned) if part.strip()]
    if not segments:
        segments = [cleaned]

    terms = set()
    for segment in segments:
        canonical = _canonical_ingredient_name(segment)
        if canonical:
            terms.add(canonical)
    return terms


def _protein_family(term: str) -> str | None:
    token = str(term or "").strip().lower()
    if not token:
        return None
    if token in PROTEIN_FAMILY_MAP:
        return PROTEIN_FAMILY_MAP[token]
    singular = token[:-1] if token.endswith("s") else token
    if singular in PROTEIN_FAMILY_MAP:
        return PROTEIN_FAMILY_MAP[singular]
    for key, family in PROTEIN_FAMILY_MAP.items():
        if key in token:
            return family
    return None


def _anchor_targets(parsed_query: dict) -> tuple[set[str], set[str]]:
    anchor_terms: set[str] = set()
    anchor_families: set[str] = set()
    for keyword in _normalize_string_list(parsed_query.get("ingredient_keywords")):
        terms = _canonicalize_terms(keyword)
        anchor_terms.update(terms)
        for term in terms:
            family = _protein_family(term)
            if family:
                anchor_families.add(family)
    return anchor_terms, anchor_families


def _meal_likelihood(
    *,
    name: str,
    tags: list[str],
    n_ingredients: int | None,
    n_steps: int | None,
    minutes: int | None,
    protein_families: set[str],
) -> float:
    score = 0.5
    lower_name = str(name or "").strip().lower()
    tag_tokens = [str(tag or "").strip().lower() for tag in tags]
    n_ing = n_ingredients or 0
    n_stp = n_steps or 0
    mins = minutes if minutes is not None else 45

    if any(hint in lower_name for hint in NON_MEAL_NAME_HINTS):
        score -= 0.55
    if any(any(hint in token for hint in NON_MEAL_TAG_HINTS) for token in tag_tokens):
        score -= 0.35
    if any(any(hint in token for hint in MEAL_TAG_HINTS) for token in tag_tokens):
        score += 0.2
    if any(hint in lower_name for hint in MEAL_NAME_HINTS):
        score += 0.1

    if n_ing >= 6:
        score += 0.1
    elif n_ing <= 3:
        score -= 0.2

    if n_stp >= 4:
        score += 0.1
    elif n_stp <= 2:
        score -= 0.2

    if mins < 6:
        score -= 0.15
    elif 10 <= mins <= 60:
        score += 0.05

    if protein_families:
        score += 0.12
    else:
        score -= 0.07

    return _clamp_float(score)


def _is_hard_non_meal(*, name: str, tags: list[str]) -> bool:
    lower_name = str(name or "").strip().lower()
    tag_tokens = [str(tag or "").strip().lower() for tag in tags]
    if any(hint in lower_name for hint in HARD_NON_MEAL_NAME_HINTS):
        return True
    if any(any(hint in token for hint in NON_MEAL_TAG_HINTS) for token in tag_tokens):
        return True
    return False


def _candidate_profile(recipe: Recipe) -> dict:
    ingredient_terms: set[str] = set()
    for raw_name in _recipe_ingredient_names(recipe):
        ingredient_terms.update(_canonicalize_terms(raw_name))
    protein_families = {family for family in (_protein_family(x) for x in ingredient_terms) if family}
    recipe_tags = []
    if hasattr(recipe, "prefetched_recipe_tags") and recipe.prefetched_recipe_tags:
        recipe_tags = [row.tag.name for row in recipe.prefetched_recipe_tags]
    hard_non_meal = _is_hard_non_meal(name=recipe.name, tags=recipe_tags)
    meal_likelihood = _meal_likelihood(
        name=recipe.name,
        tags=recipe_tags,
        n_ingredients=recipe.n_ingredients,
        n_steps=recipe.n_steps,
        minutes=recipe.minutes,
        protein_families=protein_families,
    )
    return {
        "recipe": recipe,
        "ingredients": ingredient_terms,
        "protein_families": protein_families,
        "meal_likelihood": meal_likelihood,
        "hard_non_meal": hard_non_meal,
    }


def _base_candidate_score(
    profile: dict,
    *,
    ingredient_frequency: dict[str, int],
    max_frequency: int,
    anchor_terms: set[str],
    anchor_families: set[str],
    component_weights: dict[str, float],
) -> dict[str, float]:
    ingredient_terms = profile["ingredients"]
    protein_families = profile["protein_families"]
    recipe = profile["recipe"]

    if anchor_terms:
        anchor_score = 1.0 if ingredient_terms & anchor_terms else 0.0
    elif anchor_families:
        anchor_score = 1.0 if protein_families & anchor_families else 0.0
    else:
        anchor_score = 0.5

    if ingredient_terms:
        ingredient_commonality = sum(ingredient_frequency.get(term, 0) / max_frequency for term in ingredient_terms) / len(
            ingredient_terms
        )
    else:
        ingredient_commonality = 0.35

    if protein_families:
        protein_affordability = sum(PROTEIN_AFFORDABILITY.get(family, 0.6) for family in protein_families) / len(
            protein_families
        )
        sustainability = sum(PROTEIN_SUSTAINABILITY.get(family, 0.6) for family in protein_families) / len(
            protein_families
        )
    else:
        protein_affordability = 0.7
        sustainability = 0.65

    minutes = recipe.minutes if recipe.minutes is not None else 45
    minutes_score = _clamp_float(1 - (min(max(minutes, 0), 120) / 120))
    affordability = _clamp_float(0.55 * ingredient_commonality + 0.35 * protein_affordability + 0.10 * minutes_score)
    meal_quality = profile.get("meal_likelihood", 0.5)

    total = _clamp_float(
        component_weights["anchor"] * anchor_score
        + component_weights["affordability"] * affordability
        + component_weights["sustainability"] * sustainability
        + component_weights["meal_quality"] * meal_quality
    )

    return {
        "anchor": anchor_score,
        "affordability": affordability,
        "sustainability": sustainability,
        "meal_quality": meal_quality,
        "base": total,
    }


def _overlap_score(candidate_terms: set[str], basket_terms: set[str]) -> float:
    if not basket_terms or not candidate_terms:
        return 0.0
    intersection = len(candidate_terms & basket_terms)
    if intersection == 0:
        return 0.0
    union = len(candidate_terms | basket_terms)
    coverage = intersection / max(1, len(candidate_terms))
    jaccard = intersection / max(1, union)
    return _clamp_float(0.6 * coverage + 0.4 * jaccard)


def _diversity_penalty(candidate_terms: set[str], selected_profiles: list[dict], *, penalty_scale: float) -> float:
    penalty = 0.0
    for selected in selected_profiles:
        existing_terms = selected["ingredients"]
        if not existing_terms:
            continue
        jaccard = len(candidate_terms & existing_terms) / max(1, len(candidate_terms | existing_terms))
        if jaccard > 0.82:
            penalty += penalty_scale
    return penalty


def _select_optimized_recipes(
    candidates: list[Recipe],
    parsed_query: dict,
    optimize_mode: str = "balanced",
    random_seed: int | None = None,
) -> tuple[list[Recipe], dict]:
    target_count = _to_int(parsed_query.get("num_meals"), 3)
    target_count = max(1, target_count)
    optimize_mode = _normalize_optimize_mode(optimize_mode)
    profile_config = OPTIMIZATION_PROFILES[optimize_mode]
    component_weights = profile_config["component_weights"]
    base_weight = profile_config["base_weight"]
    overlap_weight = profile_config["overlap_weight"]
    diversity_penalty_scale = profile_config["diversity_penalty"]

    if not candidates:
        return [], {
            "candidate_count": 0,
            "selected_count": 0,
            "avg_overlap": 0.0,
            "anchor_terms": [],
            "anchor_families": [],
            "optimize_mode": optimize_mode,
            "weights": profile_config,
            "selection_seed": random_seed,
        }

    profiles = [_candidate_profile(recipe) for recipe in candidates]
    ingredient_frequency: dict[str, int] = {}
    for profile in profiles:
        for term in profile["ingredients"]:
            ingredient_frequency[term] = ingredient_frequency.get(term, 0) + 1
    max_frequency = max(ingredient_frequency.values(), default=1)
    anchor_terms, anchor_families = _anchor_targets(parsed_query)

    for profile in profiles:
        profile["metrics"] = _base_candidate_score(
            profile,
            ingredient_frequency=ingredient_frequency,
            max_frequency=max_frequency,
            anchor_terms=anchor_terms,
            anchor_families=anchor_families,
            component_weights=component_weights,
        )

    rng = random.Random(random_seed) if random_seed is not None else random.SystemRandom()
    remaining = list(profiles)
    selected_profiles: list[dict] = []
    selected_recipes: list[Recipe] = []
    basket_terms: set[str] = set()
    score_trace = []

    while remaining and len(selected_recipes) < target_count:
        best_index = None
        best_meta = None
        scored_items = []

        for idx, profile in enumerate(remaining):
            overlap = _overlap_score(profile["ingredients"], basket_terms)
            penalty = _diversity_penalty(
                profile["ingredients"],
                selected_profiles,
                penalty_scale=diversity_penalty_scale,
            )
            base_score = profile["metrics"]["base"]
            if selected_profiles:
                combined = (base_weight * base_score) + (overlap_weight * overlap) - penalty
            else:
                combined = base_score
            combined = _clamp_float(combined, -1.0, 1.0)
            scored_items.append(
                {
                    "idx": idx,
                    "profile": profile,
                    "combined": combined,
                    "base": base_score,
                    "overlap": overlap,
                    "diversity_penalty": penalty,
                }
            )

        scored_items.sort(
            key=lambda item: (-item["combined"], item["profile"]["recipe"].id),
        )
        pool_size = min(len(scored_items), max(4, target_count * 4))
        exploration_pool = scored_items[:pool_size]
        floor = min(item["combined"] for item in exploration_pool)
        weights = [max(0.001, (item["combined"] - floor) + 0.03) for item in exploration_pool]
        chosen_item = rng.choices(exploration_pool, weights=weights, k=1)[0]
        best_index = chosen_item["idx"]
        best_meta = {
            "recipe_id": chosen_item["profile"]["recipe"].id,
            "base": round(chosen_item["base"], 4),
            "overlap": round(chosen_item["overlap"], 4),
            "diversity_penalty": round(chosen_item["diversity_penalty"], 4),
            "combined": round(chosen_item["combined"], 4),
            "pool_size": pool_size,
        }

        chosen = remaining.pop(best_index)
        selected_profiles.append(chosen)
        selected_recipes.append(chosen["recipe"])
        basket_terms.update(chosen["ingredients"])
        score_trace.append(best_meta)

    if len(selected_profiles) <= 1:
        avg_overlap = 0.0
    else:
        overlaps = []
        for idx, profile in enumerate(selected_profiles):
            for jdx, other in enumerate(selected_profiles):
                if jdx <= idx:
                    continue
                overlaps.append(_overlap_score(profile["ingredients"], other["ingredients"]))
        avg_overlap = round(sum(overlaps) / max(1, len(overlaps)), 4)

    return selected_recipes, {
        "candidate_count": len(candidates),
        "selected_count": len(selected_recipes),
        "avg_overlap": avg_overlap,
        "anchor_terms": sorted(anchor_terms),
        "anchor_families": sorted(anchor_families),
        "optimize_mode": optimize_mode,
        "weights": profile_config,
        "selection_seed": random_seed,
        "selection_trace": score_trace,
    }


def _filter_meal_candidates(candidates: list[Recipe], required_count: int) -> tuple[list[Recipe], dict]:
    if not candidates:
        return [], {"raw_candidate_count": 0, "strict_candidate_count": 0, "relaxed_candidate_count": 0}

    profiles = [_candidate_profile(recipe) for recipe in candidates]
    non_hard = [p for p in profiles if not p.get("hard_non_meal", False)]
    strict = [p for p in non_hard if p.get("meal_likelihood", 0) >= 0.55]
    relaxed = [p for p in non_hard if p.get("meal_likelihood", 0) >= 0.42]

    if len(strict) >= required_count:
        selected_profiles = strict
    elif len(relaxed) >= required_count:
        selected_profiles = relaxed
    else:
        selected_profiles = relaxed

    return [p["recipe"] for p in selected_profiles], {
        "raw_candidate_count": len(candidates),
        "hard_non_meal_removed": len(profiles) - len(non_hard),
        "strict_candidate_count": len(strict),
        "relaxed_candidate_count": len(relaxed),
    }


def _query_with_fallbacks(
    parsed_query: dict,
    optimize_mode: str = "balanced",
    selection_seed: int | None = None,
) -> tuple[list, dict]:
    attempts = []
    base = dict(parsed_query)
    required_count = max(1, _to_int(base.get("num_meals"), 3))
    best_result = {"recipes": [], "stage": "none", "optimizer": {}}

    def run_attempt(stage_index: int, label: str, query_payload: dict):
        candidate_limit = min(240, max(80, _to_int(query_payload.get("num_meals"), 3) * 25))
        queryset = build_plan_queryset(_base_queryset(), query_payload)
        raw_candidates = list(queryset[:candidate_limit])
        filtered_candidates, filter_meta = _filter_meal_candidates(raw_candidates, required_count=required_count)

        stage_seed = None
        if selection_seed is not None:
            stage_seed = selection_seed + stage_index

        selected, optimizer_meta = _select_optimized_recipes(
            filtered_candidates,
            query_payload,
            optimize_mode=optimize_mode,
            random_seed=stage_seed,
        )
        attempts.append(
            {
                "stage": label,
                "candidate_count": len(filtered_candidates),
                "raw_candidate_count": filter_meta.get("raw_candidate_count", len(raw_candidates)),
                "hard_non_meal_removed": filter_meta.get("hard_non_meal_removed", 0),
                "strict_candidate_count": filter_meta.get("strict_candidate_count", 0),
                "relaxed_candidate_count": filter_meta.get("relaxed_candidate_count", 0),
                "selected_count": len(selected),
                "avg_overlap": optimizer_meta.get("avg_overlap", 0.0),
                "optimize_mode": optimizer_meta.get("optimize_mode", optimize_mode),
                "selection_seed": optimizer_meta.get("selection_seed"),
            }
        )
        return selected, optimizer_meta

    stages = [("initial", base)]

    q1 = dict(base)
    q1["search_text"] = ""
    stages.append(("relax_search_text", q1))

    q2 = dict(q1)
    q2["max_calories"] = None
    q2["min_protein_pdv"] = None
    q2["max_carbs_pdv"] = None
    stages.append(("relax_nutrition", q2))

    q3 = dict(q2)
    if q3.get("max_minutes") is not None:
        q3["max_minutes"] = q3["max_minutes"] + 20
    stages.append(("widen_minutes", q3))

    for stage_index, (label, payload) in enumerate(stages):
        selected, optimizer_meta = run_attempt(stage_index, label, payload)
        if len(selected) > len(best_result["recipes"]):
            best_result = {"recipes": selected, "stage": label, "optimizer": optimizer_meta}
        if len(selected) >= required_count:
            return selected, {"attempts": attempts, "resolved_stage": label, "optimizer": optimizer_meta}

    if best_result["recipes"]:
        return best_result["recipes"], {
            "attempts": attempts,
            "resolved_stage": best_result["stage"],
            "optimizer": best_result["optimizer"],
        }

    return [], {"attempts": attempts, "resolved_stage": "none", "optimizer": {}}


INGREDIENT_CANONICAL_PATTERNS = [
    (r"\bchichken\b", "chicken"),
    (r"\bchicken\b", "chicken"),
    (r"\bturkey\b", "turkey"),
    (r"\bbeef\b|\bsteak\b", "beef"),
    (r"\bpork\b|\bham\b|\bbacon\b", "pork"),
    (r"\bsalmon\b|\btuna\b|\bcod\b|\bhalibut\b|\bfish\b", "fish"),
    (r"\bshrimp\b|\bprawn\b", "shrimp"),
    (r"\bgarlic\b", "garlic"),
    (r"\bonion\b|\bshallot\b|\bscallion\b", "onion"),
    (r"\bpotato\b", "potato"),
    (r"\btomato\b", "tomato"),
]

INGREDIENT_STOPWORDS = {
    "fresh",
    "chopped",
    "diced",
    "sliced",
    "large",
    "small",
    "extra",
    "virgin",
    "boneless",
    "skinless",
    "lean",
    "ground",
    "minced",
    "breast",
    "breasts",
    "thigh",
    "thighs",
    "fillet",
    "fillets",
    "halves",
}


def _canonical_ingredient_name(raw_name: str) -> str:
    cleaned = str(raw_name or "").strip().lower()
    if not cleaned:
        return ""

    cleaned = cleaned.replace("&", " and ")
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    for pattern, replacement in INGREDIENT_CANONICAL_PATTERNS:
        if re.search(pattern, cleaned):
            return replacement

    tokens = [token for token in cleaned.split() if token and token not in INGREDIENT_STOPWORDS]
    if not tokens:
        tokens = cleaned.split()
    if not tokens:
        return ""

    token = tokens[0]
    if token.endswith("es") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("s") and len(token) > 3:
        token = token[:-1]
    return token


def _collect_plan_ingredient_names(meal_plan: MealPlan) -> list[str]:
    names: list[str] = []
    items = meal_plan.items.select_related("recipe").prefetch_related(
        Prefetch(
            "recipe__recipe_ingredients",
            queryset=RecipeIngredient.objects.select_related("ingredient").order_by("position"),
            to_attr="prefetched_recipe_ingredients",
        )
    )

    for item in items:
        recipe = item.recipe
        if hasattr(recipe, "prefetched_recipe_ingredients") and recipe.prefetched_recipe_ingredients:
            names.extend([ri.ingredient.name for ri in recipe.prefetched_recipe_ingredients])
        else:
            names.extend([x.strip() for x in recipe.ingredients.split(",") if x.strip()])
    return names


def _aggregate_shopping_items(rows: list[dict]) -> list[dict]:
    ingredient_buckets: dict[str, dict] = {}
    for row in rows:
        source = str(row.get("source") or "").strip().lower()
        canonical_items = _normalize_string_list(row.get("canonical"))
        if not canonical_items:
            fallback = _canonical_ingredient_name(source)
            canonical_items = [fallback] if fallback else []

        for canonical in canonical_items:
            if not canonical:
                continue
            if canonical not in ingredient_buckets:
                ingredient_buckets[canonical] = {
                    "ingredient": canonical,
                    "count": 0,
                    "variants": set(),
                }
            ingredient_buckets[canonical]["count"] += 1
            if source:
                ingredient_buckets[canonical]["variants"].add(source)

    payload = []
    for ingredient in sorted(ingredient_buckets.keys()):
        bucket = ingredient_buckets[ingredient]
        payload.append(
            {
                "ingredient": bucket["ingredient"],
                "count": bucket["count"],
                "variants": sorted(bucket["variants"]),
            }
        )
    return payload


def _build_shopping_items_rules(ingredient_names: list[str]) -> list[dict]:
    rows = [{"source": name, "canonical": [_canonical_ingredient_name(name)]} for name in ingredient_names]
    return _aggregate_shopping_items(rows)


def _build_shopping_items_openai(ingredient_names: list[str], openai_client, model: str) -> list[dict] | None:
    try:
        completion = openai_client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a grocery list normalizer. "
                        "Return strict JSON only. "
                        "For each source item, output one normalized object in the same order."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Normalize these ingredients into canonical grocery labels.\n"
                        "Rules:\n"
                        "- Fix obvious typos (e.g., chichken -> chicken).\n"
                        "- Merge variants (e.g., chicken breast/chicken thighs -> chicken).\n"
                        "- Do NOT over-merge multi-ingredient phrases into one ingredient.\n"
                        "- If item is a combination phrase like 'salt and pepper', split into both ['salt', 'pepper'].\n"
                        "- Keep output minimal and practical for shopping.\n\n"
                        "Return this exact JSON schema:\n"
                        "{\n"
                        '  "normalized_items": [\n'
                        "    {\n"
                        '      "source": "<original input item>",\n'
                        '      "canonical": ["<one or more canonical ingredient labels>"]\n'
                        "    }\n"
                        "  ]\n"
                        "}\n\n"
                        f"Input items (ordered): {json.dumps(ingredient_names)}"
                    ),
                },
            ],
        )
        raw_content = completion.choices[0].message.content
        parsed = json.loads(raw_content)
        rows = parsed.get("normalized_items")
        if not isinstance(rows, list):
            return None
        if len(rows) != len(ingredient_names):
            return None

        normalized_rows = []
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                return None
            source = str(row.get("source") or ingredient_names[idx]).strip().lower()
            canonical = _normalize_string_list(row.get("canonical"))
            normalized_rows.append(
                {
                    "source": source or ingredient_names[idx],
                    "canonical": canonical,
                }
            )
        return _aggregate_shopping_items(normalized_rows)
    except Exception:
        return None


def _build_shopping_list_items(meal_plan: MealPlan):
    ingredient_names = _collect_plan_ingredient_names(meal_plan)
    if not ingredient_names:
        return []

    use_openai = os.environ.get("USE_OPENAI_SHOPPING_CONDENSER", "1") == "1"
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    openai_model = os.environ.get("SHOPPING_CONDENSER_MODEL", "gpt-4o-mini")

    if use_openai and openai_api_key:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=openai_api_key)
            condensed = _build_shopping_items_openai(ingredient_names, client, openai_model)
            if condensed is not None:
                return condensed
        except Exception:
            pass

    return _build_shopping_items_rules(ingredient_names)


class TagListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        query = str(request.GET.get("q") or "").strip().lower()
        limit = _to_int(request.GET.get("limit"), 120)
        limit = max(10, min(limit, 300))

        tags = Tag.objects.all()
        if query:
            tags = tags.filter(name__icontains=query)

        rows = list(
            tags.annotate(recipe_count=Count("recipe_tags"))
            .order_by("-recipe_count", "name")
            .values("name", "recipe_count")[:limit]
        )

        return Response(
            {
                "count": len(rows),
                "tags": [row["name"] for row in rows],
            }
        )


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"].lower().strip()
        user = User.objects.create_user(
            username=email,
            email=email,
            password=serializer.validated_data["password"],
        )

        token = TokenObtainPairSerializer.get_token(user)
        access = str(token.access_token)
        refresh = str(token)

        return Response(
            {
                "user_id": user.id,
                "email": user.email,
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
                "access": access,
                "refresh": refresh,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = str(request.data.get("email") or "").lower().strip()
        password = str(request.data.get("password") or "")

        if not email or not password:
            raise serializers.ValidationError({"detail": "email and password are required."})

        user = authenticate(username=email, password=password)
        if user is None:
            raise serializers.ValidationError({"detail": "Invalid credentials."})

        refresh = RefreshToken.for_user(user)
        refresh["email"] = user.email

        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "is_staff": user.is_staff,
                    "is_superuser": user.is_superuser,
                },
            }
        )


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSummarySerializer(request.user).data)


class PreferenceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        preference, _ = UserPreference.objects.get_or_create(user=request.user)
        return Response(UserPreferenceSerializer(preference).data)

    def put(self, request):
        preference, _ = UserPreference.objects.get_or_create(user=request.user)
        serializer = UserPreferenceSerializer(preference, data=request.data, partial=False)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class GenerateMealPlanView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        input_mode = str(request.data.get("input_mode") or "prompt").strip().lower()
        if input_mode not in {"prompt", "manual"}:
            return Response({"error": "input_mode must be 'prompt' or 'manual'."}, status=status.HTTP_400_BAD_REQUEST)

        prompt = str(request.data.get("prompt") or "").strip()
        if input_mode == "prompt" and not prompt:
            return Response({"error": "prompt is required"}, status=status.HTTP_400_BAD_REQUEST)

        if input_mode == "manual":
            raw_manual_query = request.data.get("manual_query")
            if not isinstance(raw_manual_query, dict):
                return Response({"error": "manual_query must be an object when input_mode is 'manual'."}, status=status.HTTP_400_BAD_REQUEST)
            parsed_query = sanitize_query({**raw_manual_query, "parser_source": "manual"})
        else:
            openai_api_key = os.environ.get("OPENAI_API_KEY")
            use_openai_parser = os.environ.get("USE_OPENAI_PARSER", "1") == "1" and bool(openai_api_key)
            client = None
            if use_openai_parser:
                from openai import OpenAI

                client = OpenAI(api_key=openai_api_key)

            parsed_query = parse_prompt_to_query(
                user_prompt=prompt,
                use_openai_parser=use_openai_parser,
                openai_client=client,
            )

        preference = UserPreference.objects.filter(user=request.user).first()
        parsed_query = _merge_preference_constraints(parsed_query, preference)
        include_tags_override = _normalize_string_list(request.data.get("include_tags"))
        exclude_tags_override = _normalize_string_list(request.data.get("exclude_tags"))
        optimize_mode = _normalize_optimize_mode(request.data.get("optimize_mode"))
        selection_seed = _to_optional_int(request.data.get("selection_seed"))
        if include_tags_override or exclude_tags_override:
            parsed_query = _apply_tag_overrides(
                parsed_query,
                include_tags=include_tags_override,
                exclude_tags=exclude_tags_override,
            )
        recipes, fallback_meta = _query_with_fallbacks(
            parsed_query,
            optimize_mode=optimize_mode,
            selection_seed=selection_seed,
        )

        parser_warnings = list(parsed_query.get("parser_warnings", []))
        if not recipes:
            parser_warnings.append("No recipes found after fallback stages. Try broadening constraints.")
        elif len(recipes) < parsed_query.get("num_meals", len(recipes)):
            parser_warnings.append(
                f"Only {len(recipes)} recipes found for requested {parsed_query.get('num_meals')} meals."
            )
        attempts = fallback_meta.get("attempts", [])
        if attempts:
            final_attempt = attempts[-1]
            if final_attempt.get("raw_candidate_count", 0) > final_attempt.get("candidate_count", 0):
                parser_warnings.append(
                    "Filtered out non-meal candidates (e.g., sauces/snacks/desserts) before final selection."
                )

        parsed_query["parser_warnings"] = parser_warnings

        with transaction.atomic():
            title = f"Plan {MealPlan.objects.filter(user=request.user).count() + 1}"
            meal_plan = MealPlan.objects.create(
                user=request.user,
                title=title,
                source_prompt=prompt if input_mode == "prompt" else "[manual criteria]",
                parsed_query=parsed_query,
            )
            for idx, recipe in enumerate(recipes, start=1):
                MealPlanItem.objects.create(meal_plan=meal_plan, position=idx, recipe=recipe)

        logger.info(
            "plan_generated user=%s parser_source=%s result_count=%s fallback_stage=%s candidate_count=%s overlap=%s optimize_mode=%s",
            request.user.id,
            parsed_query.get("parser_source"),
            len(recipes),
            fallback_meta.get("resolved_stage"),
            fallback_meta.get("optimizer", {}).get("candidate_count"),
            fallback_meta.get("optimizer", {}).get("avg_overlap"),
            fallback_meta.get("optimizer", {}).get("optimize_mode", optimize_mode),
        )

        return Response(
            {
                "meal_plan": MealPlanSerializer(meal_plan).data,
                "query": {
                    **parsed_query,
                    "ingredient_keyword": parsed_query.get("ingredient_keywords", [""])[0]
                    if parsed_query.get("ingredient_keywords")
                    else "",
                    "optimize_mode": fallback_meta.get("optimizer", {}).get("optimize_mode", optimize_mode),
                    "selection_seed": fallback_meta.get("optimizer", {}).get("selection_seed"),
                    "fallback": fallback_meta,
                    "input_mode": input_mode,
                },
                "recipes": [_serialize_recipe(recipe) for recipe in recipes],
                "no_results": len(recipes) == 0,
            }
        )


class MealPlanListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        plans = MealPlan.objects.filter(user=request.user).prefetch_related("items")
        return Response(MealPlanListSerializer(plans, many=True).data)


class MealPlanDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, plan_id: int):
        plan = get_object_or_404(MealPlan.objects.filter(user=request.user).prefetch_related("items__recipe"), id=plan_id)
        data = MealPlanSerializer(plan).data
        recipe_map = {}
        for item in plan.items.select_related("recipe").all():
            recipe_map[str(item.position)] = _serialize_recipe(item.recipe)
        data["recipe_cards_by_position"] = recipe_map
        return Response(data)

    def delete(self, request, plan_id: int):
        plan = get_object_or_404(MealPlan, id=plan_id, user=request.user)
        plan.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SwapMealView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, plan_id: int):
        plan = get_object_or_404(MealPlan.objects.filter(user=request.user).prefetch_related("items"), id=plan_id)
        serializer = SwapMealSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        position = serializer.validated_data["position"]
        plan_item = get_object_or_404(MealPlanItem, meal_plan=plan, position=position)

        parsed_query = dict(plan.parsed_query or {})
        existing_recipe_ids = set(plan.items.values_list("recipe_id", flat=True))

        qs = build_plan_queryset(_base_queryset(), parsed_query).exclude(id__in=existing_recipe_ids)
        replacement = qs.first()
        if replacement is None:
            return Response({"error": "No replacement recipe found."}, status=status.HTTP_404_NOT_FOUND)

        plan_item.recipe = replacement
        plan_item.save(update_fields=["recipe"])

        return Response(
            {
                "position": position,
                "recipe": _serialize_recipe(replacement),
            }
        )


class ShoppingListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, plan_id: int):
        plan = get_object_or_404(MealPlan, id=plan_id, user=request.user)
        shopping = ShoppingList.objects.filter(meal_plan=plan).first()
        if not shopping:
            return Response({"error": "Shopping list not generated yet."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ShoppingListSerializer(shopping).data)

    def post(self, request, plan_id: int):
        plan = get_object_or_404(MealPlan.objects.prefetch_related("items__recipe"), id=plan_id, user=request.user)

        items = _build_shopping_list_items(plan)
        shopping, _ = ShoppingList.objects.update_or_create(
            meal_plan=plan,
            defaults={"items": items},
        )

        return Response(ShoppingListSerializer(shopping).data)
