import json
import re
from typing import Any

from django.db.models import Q, QuerySet

from .models import Ingredient, Recipe, Tag

STOPWORDS = {
    "a",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "create",
    "dinner",
    "dinners",
    "dish",
    "dishes",
    "feed",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "main",
    "meal",
    "meals",
    "my",
    "no",
    "of",
    "on",
    "or",
    "people",
    "person",
    "please",
    "recipe",
    "recipes",
    "that",
    "the",
    "there",
    "to",
    "want",
    "with",
    "without",
    "allergy",
    "allergies",
}

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

COMMON_INGREDIENT_FALLBACKS = {
    "chicken",
    "beef",
    "pork",
    "tofu",
    "salmon",
    "turkey",
    "lamb",
    "shrimp",
    "fish",
    "rice",
    "pasta",
}

NEGATION_TOKENS = {"no", "without", "exclude", "excluding", "avoid"}
ALLERGY_TOKENS = {"allergy", "allergies", "allergic"}
ALLERGY_FILLER_TOKENS = {"to", "against", "with", "from", "i", "am", "very", "really", "extremely"}

TOKEN_ALIASES = {
    "vegeterian": "vegetarian",
    "vegatarian": "vegetarian",
    "vegitarian": "vegetarian",
    "chicen": "chicken",
    "alergies": "allergies",
}


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _to_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _prompt_tokens(prompt: str) -> list[str]:
    raw_tokens = [token.lower() for token in re.findall(r"[a-zA-Z0-9']+", prompt)]
    normalized = []
    for token in raw_tokens:
        alias = TOKEN_ALIASES.get(token, token)
        # Catch common vegetarian/vegan typo variants.
        if alias.startswith("veget"):
            alias = "vegetarian"
        normalized.append(alias)
    return normalized


def _token_to_int(token: str | None) -> int | None:
    if token is None:
        return None
    if token.isdigit():
        return _to_int(token, None)
    return NUMBER_WORDS.get(token.lower())


def _extract_num_meals(prompt: str, default: int = 3) -> int:
    tokens = _prompt_tokens(prompt)
    for index in range(len(tokens) - 1):
        number = _token_to_int(tokens[index])
        if number is None:
            continue
        if tokens[index + 1].startswith(("meal", "recipe", "dish", "dinner")):
            return number

        # Handles "2 vegetarian meals" (one token between number and meal noun).
        if index + 2 < len(tokens) and tokens[index + 2].startswith(("meal", "recipe", "dish", "dinner")):
            return number
    return default


def _normalize_item_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []

    normalized = []
    seen = set()
    for item in value:
        cleaned = str(item).strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _terms_conflict(a: str, b: str) -> bool:
    left = a.strip().lower()
    right = b.strip().lower()
    if not left or not right:
        return False
    return left == right or left in right or right in left


def _extract_numeric_constraint(prompt: str, key_terms: tuple[str, ...]) -> float | None:
    lower_prompt = prompt.lower()
    for term in key_terms:
        pattern = rf"(?:under|less than|below|max(?:imum)?|<=?)\s*(\d+(?:\.\d+)?)\s*{term}"
        match = re.search(pattern, lower_prompt)
        if match:
            return _to_float(match.group(1), None)
    return None


def _collect_ngrams(tokens: list[str], max_n: int = 3) -> list[str]:
    grams: list[str] = []
    for n in range(max_n, 0, -1):
        for i in range(len(tokens) - n + 1):
            phrase = " ".join(tokens[i : i + n]).strip().lower()
            if phrase:
                grams.append(phrase)
    return grams


def _lookup_known_terms(candidates: list[str], *, ingredient_lookup: set[str], tag_lookup: set[str]) -> tuple[list[str], list[str]]:
    includes_ingredients = []
    includes_tags = []

    for candidate in candidates:
        tag_variant = candidate.replace(" ", "-")
        if candidate in ingredient_lookup:
            includes_ingredients.append(candidate)
        if tag_variant in tag_lookup:
            includes_tags.append(tag_variant)

    # de-dup keep order
    def unique_keep_order(items: list[str]) -> list[str]:
        out = []
        seen = set()
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    return unique_keep_order(includes_ingredients), unique_keep_order(includes_tags)


def _infer_exclusions(tokens: list[str], *, ingredient_lookup: set[str], tag_lookup: set[str]) -> tuple[list[str], list[str]]:
    excluded_ingredients: list[str] = []
    excluded_tags: list[str] = []

    for i, token in enumerate(tokens):
        if token not in NEGATION_TOKENS:
            continue

        for span in (3, 2, 1):
            if i + span >= len(tokens):
                continue
            phrase = " ".join(tokens[i + 1 : i + 1 + span]).strip()
            if not phrase:
                continue
            if phrase in STOPWORDS:
                continue

            tag_variant = phrase.replace(" ", "-")
            # Ingredient exclusions should work even for partial terms like "seed".
            excluded_ingredients.append(phrase)
            if tag_variant in tag_lookup:
                excluded_tags.append(tag_variant)

    # Allergy phrasing should always be treated as exclusions.
    # Examples: "allergic to fish", "allergy to nuts", "allergies with dairy".
    for i, token in enumerate(tokens):
        if token not in ALLERGY_TOKENS:
            continue

        start = i + 1
        while start < len(tokens) and tokens[start] in ALLERGY_FILLER_TOKENS:
            start += 1

        for span in (3, 2, 1):
            end = start + span
            if end > len(tokens):
                continue
            phrase = " ".join(tokens[start:end]).strip()
            if not phrase or phrase in STOPWORDS:
                continue

            tag_variant = phrase.replace(" ", "-")
            excluded_ingredients.append(phrase)
            if tag_variant in tag_lookup:
                excluded_tags.append(tag_variant)

    def unique_keep_order(items: list[str]) -> list[str]:
        out = []
        seen = set()
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    return unique_keep_order(excluded_ingredients), unique_keep_order(excluded_tags)


def _default_query() -> dict[str, Any]:
    return {
        "num_meals": 3,
        "ingredient_keywords": [],
        "include_tags": [],
        "exclude_tags": [],
        "max_minutes": None,
        "max_calories": None,
        "min_protein_pdv": None,
        "max_carbs_pdv": None,
        "search_text": "",
        "exclude_ingredients": [],
        "parser_source": "rules",
    }


def _sanitize_query(raw_query: dict[str, Any]) -> dict[str, Any]:
    parsed = _default_query()

    parsed["num_meals"] = _clamp(_to_int(raw_query.get("num_meals"), 3) or 3, 1, 10)
    parsed["ingredient_keywords"] = _normalize_item_list(raw_query.get("ingredient_keywords"))
    parsed["include_tags"] = _normalize_item_list(raw_query.get("include_tags"))
    parsed["exclude_tags"] = _normalize_item_list(raw_query.get("exclude_tags"))
    parsed["exclude_ingredients"] = _normalize_item_list(raw_query.get("exclude_ingredients"))

    parsed["max_minutes"] = _to_int(raw_query.get("max_minutes"), None)
    parsed["max_calories"] = _to_float(raw_query.get("max_calories"), None)
    parsed["min_protein_pdv"] = _to_float(raw_query.get("min_protein_pdv"), None)
    parsed["max_carbs_pdv"] = _to_float(raw_query.get("max_carbs_pdv"), None)
    parsed["search_text"] = str(raw_query.get("search_text") or "").strip().lower()

    parser_source = str(raw_query.get("parser_source") or "rules")
    parsed["parser_source"] = parser_source if parser_source in {"rules", "openai"} else "rules"

    # Resolve include/exclude conflicts defensively.
    parsed["ingredient_keywords"] = [
        ingredient
        for ingredient in parsed["ingredient_keywords"]
        if not any(_terms_conflict(ingredient, excluded) for excluded in parsed["exclude_ingredients"])
    ]
    parsed["include_tags"] = [
        tag
        for tag in parsed["include_tags"]
        if not any(_terms_conflict(tag, excluded_tag) for excluded_tag in parsed["exclude_tags"])
    ]

    return parsed


def _infer_query_from_prompt(prompt: str, *, ingredient_lookup: set[str], tag_lookup: set[str]) -> dict[str, Any]:
    lower_prompt = prompt.lower()
    tokens = _prompt_tokens(prompt)
    ngrams = _collect_ngrams(tokens, max_n=3)

    ingredient_keywords, include_tags = _lookup_known_terms(
        ngrams,
        ingredient_lookup=ingredient_lookup,
        tag_lookup=tag_lookup,
    )

    exclude_ingredients, exclude_tags = _infer_exclusions(
        tokens,
        ingredient_lookup=ingredient_lookup,
        tag_lookup=tag_lookup,
    )

    ingredient_keywords = [item for item in ingredient_keywords if item not in exclude_ingredients]
    include_tags = [item for item in include_tags if item not in exclude_tags]

    if not ingredient_keywords:
        for token in tokens:
            if token in COMMON_INGREDIENT_FALLBACKS:
                ingredient_keywords.append(token)
                break

    max_minutes = None
    explicit_minutes = re.search(
        r"(?:under|less than|below|max(?:imum)?|within)\s*(\d+)\s*(?:mins?|minutes?)",
        lower_prompt,
    )
    if explicit_minutes:
        max_minutes = _to_int(explicit_minutes.group(1), None)
    elif "quick" in tokens or "fast" in tokens:
        max_minutes = 30
        if "30-minutes-or-less" in tag_lookup and "30-minutes-or-less" not in include_tags:
            include_tags.append("30-minutes-or-less")

    max_calories = _extract_numeric_constraint(lower_prompt, ("calories", "kcal"))
    protein_floor = _extract_numeric_constraint(lower_prompt, ("protein",))
    carb_cap = _extract_numeric_constraint(lower_prompt, ("carb", "carbs", "carbohydrates"))

    if protein_floor is None and "high protein" in lower_prompt:
        protein_floor = 20.0
    if carb_cap is None and "low carb" in lower_prompt:
        carb_cap = 15.0

    search_text = ""
    if not ingredient_keywords and not include_tags:
        content_tokens = [token for token in tokens if token not in STOPWORDS and not token.isdigit()]
        if content_tokens:
            search_text = " ".join(content_tokens[:4])

    return _sanitize_query(
        {
            "num_meals": _extract_num_meals(prompt, default=3),
            "ingredient_keywords": ingredient_keywords,
            "include_tags": include_tags,
            "exclude_tags": exclude_tags,
            "max_minutes": max_minutes,
            "max_calories": max_calories,
            "min_protein_pdv": protein_floor,
            "max_carbs_pdv": carb_cap,
            "search_text": search_text,
            "exclude_ingredients": exclude_ingredients,
            "parser_source": "rules",
        }
    )


def parse_prompt_to_query(
    *,
    user_prompt: str,
    use_openai_parser: bool,
    openai_client,
    openai_model: str = "gpt-4o-mini",
) -> dict[str, Any]:
    ingredient_lookup = set(Ingredient.objects.values_list("name", flat=True))
    tag_lookup = set(Tag.objects.values_list("name", flat=True))

    rule_query = _infer_query_from_prompt(
        user_prompt,
        ingredient_lookup=ingredient_lookup,
        tag_lookup=tag_lookup,
    )

    if not use_openai_parser:
        return rule_query

    try:
        completion = openai_client.chat.completions.create(
            model=openai_model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a meal planning parser. "
                        "Extract only structured query fields. "
                        "Return a single JSON object and no extra text."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Parse the request into this schema:\n"
                        "{\n"
                        '  "num_meals": int,\n'
                        '  "ingredient_keywords": string[],\n'
                        '  "include_tags": string[],\n'
                        '  "exclude_tags": string[],\n'
                        '  "max_minutes": int|null,\n'
                        '  "max_calories": number|null,\n'
                        '  "min_protein_pdv": number|null,\n'
                        '  "max_carbs_pdv": number|null,\n'
                        '  "search_text": string,\n'
                        '  "exclude_ingredients": string[]\n'
                        "}\n"
                        "If a value is unknown, leave null or empty array/string.\n\n"
                        f"User request: {user_prompt}"
                    ),
                },
            ],
        )
        raw_content = completion.choices[0].message.content
        openai_query = _sanitize_query(json.loads(raw_content))
        openai_query["parser_source"] = "openai"
    except Exception:
        return rule_query

    # Merge strategy: OpenAI first, rule-based fills gaps.
    merged = dict(openai_query)
    for key in (
        "ingredient_keywords",
        "include_tags",
        "exclude_tags",
        "exclude_ingredients",
    ):
        if not merged.get(key):
            merged[key] = rule_query.get(key, [])

    for key in ("max_minutes", "max_calories", "min_protein_pdv", "max_carbs_pdv"):
        if merged.get(key) is None:
            merged[key] = rule_query.get(key)

    if not merged.get("search_text"):
        merged["search_text"] = rule_query.get("search_text", "")

    if merged.get("num_meals") in (None, 0):
        merged["num_meals"] = rule_query.get("num_meals", 3)

    return _sanitize_query(merged)


def build_plan_queryset(base_queryset: QuerySet[Recipe], parsed_query: dict[str, Any]) -> QuerySet[Recipe]:
    qs = base_queryset

    search_text = parsed_query.get("search_text")
    if search_text:
        qs = qs.filter(Q(name__icontains=search_text) | Q(description__icontains=search_text))

    for ingredient in parsed_query.get("ingredient_keywords", []):
        qs = qs.filter(
            Q(recipe_ingredients__ingredient__name__icontains=ingredient)
            | Q(ingredients__icontains=ingredient)
        )

    for ingredient in parsed_query.get("exclude_ingredients", []):
        qs = qs.exclude(
            Q(recipe_ingredients__ingredient__name__icontains=ingredient)
            | Q(ingredients__icontains=ingredient)
        )

    for tag in parsed_query.get("include_tags", []):
        qs = qs.filter(recipe_tags__tag__name__icontains=tag)

    for tag in parsed_query.get("exclude_tags", []):
        qs = qs.exclude(recipe_tags__tag__name__icontains=tag)

    max_minutes = parsed_query.get("max_minutes")
    if max_minutes is not None and max_minutes >= 0:
        qs = qs.filter(minutes__lte=max_minutes)

    max_calories = parsed_query.get("max_calories")
    if max_calories is not None:
        qs = qs.filter(calories__lte=max_calories)

    min_protein_pdv = parsed_query.get("min_protein_pdv")
    if min_protein_pdv is not None:
        qs = qs.filter(protein_pdv__gte=min_protein_pdv)

    max_carbs_pdv = parsed_query.get("max_carbs_pdv")
    if max_carbs_pdv is not None:
        qs = qs.filter(carbohydrates_pdv__lte=max_carbs_pdv)

    return qs.distinct().order_by("id")
