import logging
import json
import os
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
from recipes.planning import build_plan_queryset, parse_prompt_to_query
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


def _query_with_fallbacks(parsed_query: dict) -> tuple[list, dict]:
    attempts = []
    base = dict(parsed_query)

    def run_attempt(label: str, query_payload: dict):
        queryset = build_plan_queryset(_base_queryset(), query_payload)
        recipes = list(queryset[: query_payload["num_meals"]])
        attempts.append({"stage": label, "count": len(recipes)})
        return recipes

    recipes = run_attempt("initial", base)
    if recipes:
        return recipes, {"attempts": attempts, "resolved_stage": "initial"}

    q1 = dict(base)
    q1["search_text"] = ""
    recipes = run_attempt("relax_search_text", q1)
    if recipes:
        return recipes, {"attempts": attempts, "resolved_stage": "relax_search_text"}

    q2 = dict(q1)
    q2["max_calories"] = None
    q2["min_protein_pdv"] = None
    q2["max_carbs_pdv"] = None
    recipes = run_attempt("relax_nutrition", q2)
    if recipes:
        return recipes, {"attempts": attempts, "resolved_stage": "relax_nutrition"}

    q3 = dict(q2)
    if q3.get("max_minutes") is not None:
        q3["max_minutes"] = q3["max_minutes"] + 20
    recipes = run_attempt("widen_minutes", q3)
    if recipes:
        return recipes, {"attempts": attempts, "resolved_stage": "widen_minutes"}

    return [], {"attempts": attempts, "resolved_stage": "none"}


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
                "user": {"id": user.id, "email": user.email},
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
        prompt = str(request.data.get("prompt") or "").strip()
        if not prompt:
            return Response({"error": "prompt is required"}, status=status.HTTP_400_BAD_REQUEST)

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
        if include_tags_override or exclude_tags_override:
            parsed_query = _apply_tag_overrides(
                parsed_query,
                include_tags=include_tags_override,
                exclude_tags=exclude_tags_override,
            )
        recipes, fallback_meta = _query_with_fallbacks(parsed_query)

        parser_warnings = list(parsed_query.get("parser_warnings", []))
        if not recipes:
            parser_warnings.append("No recipes found after fallback stages. Try broadening constraints.")

        parsed_query["parser_warnings"] = parser_warnings

        with transaction.atomic():
            title = f"Plan {MealPlan.objects.filter(user=request.user).count() + 1}"
            meal_plan = MealPlan.objects.create(
                user=request.user,
                title=title,
                source_prompt=prompt,
                parsed_query=parsed_query,
            )
            for idx, recipe in enumerate(recipes, start=1):
                MealPlanItem.objects.create(meal_plan=meal_plan, position=idx, recipe=recipe)

        logger.info(
            "plan_generated user=%s parser_source=%s result_count=%s fallback_stage=%s",
            request.user.id,
            parsed_query.get("parser_source"),
            len(recipes),
            fallback_meta.get("resolved_stage"),
        )

        return Response(
            {
                "meal_plan": MealPlanSerializer(meal_plan).data,
                "query": {
                    **parsed_query,
                    "ingredient_keyword": parsed_query.get("ingredient_keywords", [""])[0]
                    if parsed_query.get("ingredient_keywords")
                    else "",
                    "fallback": fallback_meta,
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
