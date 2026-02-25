import json
import os

from django.db.models import Prefetch, Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Recipe, RecipeIngredient, RecipeStep, RecipeTag
from .planning import build_plan_queryset, parse_prompt_to_query

from openai import OpenAI

# Creating OpenAI client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


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
    - Parses structured query constraints from prompt.
    - Uses parsed dataset-backed variables to query Recipe objects.
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

    use_openai_parser = os.environ.get("USE_OPENAI_PARSER", "1") == "1"
    parsed_query = parse_prompt_to_query(
        user_prompt=user_prompt,
        use_openai_parser=use_openai_parser and bool(os.environ.get("OPENAI_API_KEY")),
        openai_client=client,
    )

    recipes_qs = build_plan_queryset(_base_queryset(), parsed_query)
    recipes_qs = recipes_qs[: parsed_query["num_meals"]]
    recipes_data = [_serialize_recipe(recipe) for recipe in recipes_qs]

    no_results = len(recipes_data) == 0

    primary_ingredient = parsed_query["ingredient_keywords"][0] if parsed_query["ingredient_keywords"] else ""

    # Return parsed query + compatibility alias for legacy frontend expectations.
    return JsonResponse(
        {
            "query": {
                **parsed_query,
                "ingredient_keyword": primary_ingredient,
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
