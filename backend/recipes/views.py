import json
import os
import re

from django.db.models import Prefetch, Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Ingredient, Recipe, RecipeIngredient, RecipeStep, RecipeTag

from openai import OpenAI

# Creating OpenAI client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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
    "serve",
    "serves",
    "serving",
    "servings",
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


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, minimum, maximum):
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _prompt_tokens(prompt):
    return [token.lower() for token in re.findall(r"[a-zA-Z0-9']+", prompt)]


def _token_to_int(token):
    if token is None:
        return None
    if token.isdigit():
        try:
            return int(token)
        except ValueError:
            return None
    return NUMBER_WORDS.get(token.lower())


def _extract_num_meals(prompt, default=3):
    tokens = _prompt_tokens(prompt)
    for index in range(len(tokens) - 1):
        number = _token_to_int(tokens[index])
        if number is None:
            continue
        if tokens[index + 1].startswith(("meal", "recipe", "dish")):
            return number
    return default


def _extract_serves(prompt, default=2):
    tokens = _prompt_tokens(prompt)
    for index in range(len(tokens) - 1):
        number = _token_to_int(tokens[index])
        if number is None:
            continue
        next_token = tokens[index + 1]
        if next_token in {"people", "person", "servings"}:
            return number

    for index in range(len(tokens) - 1):
        if tokens[index] in {"for", "feed", "serves", "serve", "serving", "servings"}:
            number = _token_to_int(tokens[index + 1])
            if number is not None:
                return number
    return default


def _extract_ingredient_keyword(prompt):
    tokens = _prompt_tokens(prompt)
    if not tokens:
        return ""

    candidates = []
    for n in (3, 2, 1):
        for idx in range(len(tokens) - n + 1):
            phrase = " ".join(tokens[idx : idx + n]).strip()
            if not phrase:
                continue
            phrase_parts = phrase.split()
            if all(part in STOPWORDS for part in phrase_parts):
                continue
            candidates.append(phrase)

    # Remove duplicates while preserving order.
    seen = set()
    ordered_candidates = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        ordered_candidates.append(candidate)

    if ordered_candidates:
        existing = set(
            Ingredient.objects.filter(name__in=ordered_candidates).values_list("name", flat=True)
        )
        for candidate in ordered_candidates:
            if candidate in existing:
                return candidate

    for token in tokens:
        if token in COMMON_INGREDIENT_FALLBACKS:
            return token

    for token in reversed(tokens):
        if token not in STOPWORDS:
            return token

    return ""


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


def _recipe_ingredients(recipe):
    if hasattr(recipe, "prefetched_recipe_ingredients"):
        ingredient_rows = recipe.prefetched_recipe_ingredients
        return [row.ingredient.name for row in ingredient_rows]

    ingredient_rows = recipe.recipe_ingredients.select_related("ingredient").order_by("position")
    return [row.ingredient.name for row in ingredient_rows]


def _recipe_steps(recipe):
    if hasattr(recipe, "prefetched_steps"):
        return [row.instruction for row in recipe.prefetched_steps]

    return [row.instruction for row in recipe.steps.order_by("step_number")]


def _recipe_tags(recipe):
    if hasattr(recipe, "prefetched_recipe_tags"):
        return [row.tag.name for row in recipe.prefetched_recipe_tags]

    tag_rows = recipe.recipe_tags.select_related("tag")
    return [row.tag.name for row in tag_rows]


def _fallback_ingredients(recipe):
    return [item.strip() for item in recipe.ingredients.split(",") if item.strip()]


def _fallback_steps(recipe):
    return [item.strip() for item in recipe.instructions.split("\n") if item.strip()]


def _serialize_recipe(recipe, include_steps=True):
    ingredients = _recipe_ingredients(recipe)
    if not ingredients:
        ingredients = _fallback_ingredients(recipe)

    steps = _recipe_steps(recipe) if include_steps else []
    if include_steps and not steps:
        steps = _fallback_steps(recipe)

    return {
        "id": recipe.id,
        "external_id": recipe.external_id,
        "name": recipe.name,
        "description": recipe.description,
        "minutes": recipe.minutes,
        "serves": recipe.serves,
        "n_ingredients": recipe.n_ingredients,
        "n_steps": recipe.n_steps,
        "ingredients": ingredients,
        "instructions": steps,
        "tags": _recipe_tags(recipe),
        "nutrition": {
            "calories": recipe.calories,
            "total_fat_pdv": recipe.total_fat_pdv,
            "sugar_pdv": recipe.sugar_pdv,
            "sodium_pdv": recipe.sodium_pdv,
            "protein_pdv": recipe.protein_pdv,
            "saturated_fat_pdv": recipe.saturated_fat_pdv,
            "carbohydrates_pdv": recipe.carbohydrates_pdv,
        },
    }


def sample_plan(request):
    """
    Temporary endpoint:
    - Returns up to 3 recipes that contain 'chicken' in ingredients.
    - This is just to test the backend <-> DB <-> frontend flow.
    """
    recipes_qs = (
        _base_queryset()
        .filter(
            Q(recipe_ingredients__ingredient__name__icontains="chicken")
            | Q(ingredients__icontains="chicken")
        )
        .distinct()[:3]
    )

    recipes_data = [_serialize_recipe(recipe) for recipe in recipes_qs]

    return JsonResponse({"recipes": recipes_data})


@csrf_exempt  # dev-only: disable CSRF for this endpoint so React can POST
def plan_meals(request):
    """
    Endpoint:
    - Accepts POST with JSON body: { "user_prompt": "..." }
    - Sends the prompt to OpenAI to extract:
        - num_meals (int)
        - serves (int)
        - ingredient_keyword (string, e.g. "beef")
    - Uses that info to query Recipe objects.
    - Returns JSON: { "query": {..parsed..}, "recipes": [...] }
    """
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    # 1. Parse JSON body
    try:
        body = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    user_prompt = body.get("user_prompt", "").strip()

    if not user_prompt:
        return JsonResponse({"error": "user_prompt is required"}, status=400)

    # 2. Call OpenAI to parse the prompt into structured JSON
    parsed = {}
    use_openai_parser = os.environ.get("USE_OPENAI_PARSER", "0") == "1"
    if use_openai_parser and os.environ.get("OPENAI_API_KEY"):
        try:
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a meal planning parser. "
                            "Extract the requested fields from user prompts. "
                            "ALWAYS respond with a single JSON object only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Extract these fields from the request:\n"
                            "- num_meals: integer\n"
                            "- serves: integer\n"
                            "- ingredient_keyword: single keyword ingredient. "
                            "If missing, return blank string.\n\n"
                            f"User request: {user_prompt}"
                        ),
                    },
                ],
            )
            raw_content = completion.choices[0].message.content
            parsed = json.loads(raw_content)
        except Exception as e:
            print("OpenAI error:", repr(e))

    # 3. Extract fields with defaults + clamp values.
    parsed_num_meals = _to_int(parsed.get("num_meals"), None)
    if parsed_num_meals is None:
        parsed_num_meals = _extract_num_meals(user_prompt, default=3)
    num_meals = _clamp(parsed_num_meals, 1, 10)

    parsed_serves = _to_int(parsed.get("serves"), None)
    if parsed_serves is None:
        parsed_serves = _extract_serves(user_prompt, default=2)
    serves = _clamp(parsed_serves, 1, 10)

    ingredient_keyword = (parsed.get("ingredient_keyword") or "").strip().lower()
    if ingredient_keyword in STOPWORDS:
        ingredient_keyword = ""

    # Fallback parser if OpenAI is unavailable or omitted an ingredient.
    if not ingredient_keyword:
        ingredient_keyword = _extract_ingredient_keyword(user_prompt)

    if not ingredient_keyword:
        ingredient_keyword = "chicken"

    # 4. Query recipes by normalized ingredient relationship.
    recipes_qs = (
        _base_queryset()
        .filter(
            Q(recipe_ingredients__ingredient__name__icontains=ingredient_keyword)
            | Q(ingredients__icontains=ingredient_keyword)
        )
        .distinct()
    )

    serves_matches = recipes_qs.filter(serves=serves)
    if serves_matches.exists():
        recipes_qs = serves_matches

    recipes_qs = recipes_qs[:num_meals]
    recipes_data = [_serialize_recipe(recipe) for recipe in recipes_qs]

    no_results = len(recipes_data) == 0

    # 5. Return both the parsed query info and the recipes
    return JsonResponse(
        {
            "query": {
                "num_meals": num_meals,
                "serves": serves,
                "ingredient_keyword": ingredient_keyword,
            },
            "no_results": no_results,
            "recipes": recipes_data,
        }
    )


def search_recipes(request):
    if request.method != "GET":
        return JsonResponse({"error": "Only GET allowed"}, status=405)

    query = request.GET.get("q", "").strip()
    ingredient = request.GET.get("ingredient", "").strip().lower()
    tag = request.GET.get("tag", "").strip().lower()
    max_minutes = _to_int(request.GET.get("max_minutes"), None)
    limit = _clamp(_to_int(request.GET.get("limit"), 20), 1, 100)
    offset = max(_to_int(request.GET.get("offset"), 0), 0)

    recipes_qs = _base_queryset()

    if query:
        recipes_qs = recipes_qs.filter(Q(name__icontains=query) | Q(description__icontains=query))

    if ingredient:
        recipes_qs = recipes_qs.filter(
            Q(recipe_ingredients__ingredient__name__icontains=ingredient)
            | Q(ingredients__icontains=ingredient)
        )

    if tag:
        recipes_qs = recipes_qs.filter(recipe_tags__tag__name__icontains=tag)

    if max_minutes is not None and max_minutes >= 0:
        recipes_qs = recipes_qs.filter(minutes__lte=max_minutes)

    recipes_qs = recipes_qs.distinct().order_by("id")

    total = recipes_qs.count()
    recipes = recipes_qs[offset : offset + limit]

    return JsonResponse(
        {
            "total": total,
            "offset": offset,
            "limit": limit,
            "count": len(recipes),
            "recipes": [_serialize_recipe(recipe, include_steps=False) for recipe in recipes],
        }
    )


def recipe_detail(request, recipe_id):
    if request.method != "GET":
        return JsonResponse({"error": "Only GET allowed"}, status=405)

    recipe = _base_queryset().filter(id=recipe_id).first()
    if recipe is None:
        return JsonResponse({"error": "Recipe not found"}, status=404)

    return JsonResponse({"recipe": _serialize_recipe(recipe, include_steps=True)})
