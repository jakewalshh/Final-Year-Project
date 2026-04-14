import os
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from recipes.models import Ingredient, Recipe, RecipeIngredient, RecipeTag, Tag

from .models import MealPlan, MealPlanItem, ShoppingList, UserPreference
from .views import _build_shopping_items_openai, _estimate_recipe_cost, _filter_meal_candidates, _select_optimized_recipes

User = get_user_model()


class PlannerApiTests(APITestCase):
    def setUp(self):
        self._old_use_openai_shopping = os.environ.get("USE_OPENAI_SHOPPING_CONDENSER")
        os.environ["USE_OPENAI_SHOPPING_CONDENSER"] = "0"
        self._old_use_openai_parser = os.environ.get("USE_OPENAI_PARSER")
        os.environ["USE_OPENAI_PARSER"] = "0"

        self.recipe = Recipe.objects.create(
            name="Quick Veg Stir Fry Dinner",
            ingredients="tofu, broccoli, soy sauce, rice, garlic, onion",
            instructions="Prep\nCook\nSimmer\nServe",
            minutes=20,
            description="Quick vegetarian meal",
            external_id=20001,
            calories=280,
            n_ingredients=6,
            n_steps=4,
        )
        ingredient_tofu = Ingredient.objects.create(name="tofu", estimated_unit_cost_eur=1.80)
        RecipeIngredient.objects.create(recipe=self.recipe, ingredient=ingredient_tofu, position=1)
        vegetarian = Tag.objects.create(name="vegetarian")
        RecipeTag.objects.create(recipe=self.recipe, tag=vegetarian)

    def tearDown(self):
        if self._old_use_openai_shopping is None:
            os.environ.pop("USE_OPENAI_SHOPPING_CONDENSER", None)
        else:
            os.environ["USE_OPENAI_SHOPPING_CONDENSER"] = self._old_use_openai_shopping
        if self._old_use_openai_parser is None:
            os.environ.pop("USE_OPENAI_PARSER", None)
        else:
            os.environ["USE_OPENAI_PARSER"] = self._old_use_openai_parser

    def _register_and_login(self):
        register_resp = self.client.post(
            reverse("auth-register"),
            {
                "email": "test@example.com",
                "password": "StrongPass123!",
                "confirm_password": "StrongPass123!",
            },
            format="json",
        )
        self.assertEqual(register_resp.status_code, 201)

        login_resp = self.client.post(
            reverse("auth-login"),
            {"email": "test@example.com", "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(login_resp.status_code, 200)
        token = login_resp.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_register_login_and_me(self):
        self._register_and_login()
        me_resp = self.client.get(reverse("auth-me"))
        self.assertEqual(me_resp.status_code, 200)
        self.assertEqual(me_resp.data["email"], "test@example.com")
        self.assertIn("is_staff", me_resp.data)
        self.assertIn("is_superuser", me_resp.data)
        self.assertFalse(me_resp.data["is_staff"])

    def test_preferences_crud(self):
        self._register_and_login()

        get_resp = self.client.get(reverse("preferences"))
        self.assertEqual(get_resp.status_code, 200)

        put_resp = self.client.put(
            reverse("preferences"),
            {
                "excluded_ingredients": ["fish"],
                "preferred_tags": ["vegetarian"],
                "excluded_tags": [],
                "max_minutes_default": 30,
                "nutrition_defaults": {"max_calories": 500},
            },
            format="json",
        )
        self.assertEqual(put_resp.status_code, 200)
        pref = UserPreference.objects.get(user__email="test@example.com")
        self.assertIn("fish", pref.excluded_ingredients)

    def test_generate_plan_and_shopping_list(self):
        self._register_and_login()

        gen_resp = self.client.post(
            reverse("meal-plan-generate"),
            {
                "prompt": "Create 2 vegetarian meals with tofu",
                "include_tags": ["vegetarian"],
                "optimize_mode": "budget",
            },
            format="json",
        )
        self.assertEqual(gen_resp.status_code, 200)
        self.assertFalse(gen_resp.data["no_results"])
        self.assertEqual(gen_resp.data["query"]["optimize_mode"], "budget")
        self.assertEqual(gen_resp.data["query"]["fallback"]["optimizer"]["optimize_mode"], "budget")
        self.assertIn("fallback", gen_resp.data["query"])
        self.assertIn("optimizer", gen_resp.data["query"]["fallback"])

        plan_id = gen_resp.data["meal_plan"]["id"]
        self.assertTrue(MealPlan.objects.filter(id=plan_id).exists())

        list_resp = self.client.post(reverse("shopping-list", args=[plan_id]), {}, format="json")
        self.assertEqual(list_resp.status_code, 200)
        self.assertTrue(ShoppingList.objects.filter(meal_plan_id=plan_id).exists())
        self.assertEqual(list_resp.data.get("total_source"), "plan_generation")
        self.assertAlmostEqual(
            float(list_resp.data["cost_summary"]["estimated_total"]),
            float(gen_resp.data["query"]["estimated_total"]),
            places=2,
        )
        self.assertIn("itemized_estimated_total", list_resp.data)

    def test_generate_plan_manual_mode(self):
        self._register_and_login()
        gen_resp = self.client.post(
            reverse("meal-plan-generate"),
            {
                "input_mode": "manual",
                "manual_query": {
                    "num_meals": 2,
                    "ingredient_keywords": ["tofu"],
                    "include_tags": ["vegetarian"],
                    "exclude_tags": [],
                    "exclude_ingredients": ["fish"],
                    "max_minutes": 30,
                    "max_calories": 600,
                    "min_protein_pdv": 10,
                    "max_carbs_pdv": 80,
                    "max_total_budget": 20,
                    "search_text": "",
                },
                "optimize_mode": "balanced",
            },
            format="json",
        )
        self.assertEqual(gen_resp.status_code, 200)
        self.assertEqual(gen_resp.data["query"]["input_mode"], "manual")
        self.assertEqual(gen_resp.data["query"]["parser_source"], "manual")
        self.assertFalse(gen_resp.data["no_results"])
        self.assertEqual(gen_resp.data["query"]["max_total_budget"], 20.0)
        self.assertEqual(gen_resp.data["query"]["budget_cap"], 20.0)
        self.assertTrue(gen_resp.data["query"]["within_budget"])

    def test_generate_plan_budget_cap_feasible(self):
        self._register_and_login()
        gen_resp = self.client.post(
            reverse("meal-plan-generate"),
            {
                "input_mode": "manual",
                "manual_query": {
                    "num_meals": 1,
                    "ingredient_keywords": ["tofu"],
                    "include_tags": ["vegetarian"],
                    "exclude_tags": [],
                    "exclude_ingredients": [],
                    "max_minutes": 30,
                    "max_total_budget": 10,
                },
                "optimize_mode": "budget",
            },
            format="json",
        )
        self.assertEqual(gen_resp.status_code, 200)
        self.assertFalse(gen_resp.data["no_results"])
        self.assertEqual(gen_resp.data["query"]["budget_cap"], 10.0)
        self.assertTrue(gen_resp.data["query"]["within_budget"])
        self.assertLessEqual(float(gen_resp.data["query"]["estimated_total"]), 10.0)
        self.assertEqual(float(gen_resp.data["meal_plan"]["parsed_query"]["budget_cap"]), 10.0)

    def test_generate_plan_prompt_mode_accepts_explicit_budget_cap(self):
        self._register_and_login()
        gen_resp = self.client.post(
            reverse("meal-plan-generate"),
            {
                "input_mode": "prompt",
                "prompt": "Create 1 vegetarian meal with tofu",
                "max_total_budget": 10,
                "optimize_mode": "budget",
            },
            format="json",
        )
        self.assertEqual(gen_resp.status_code, 200)
        self.assertFalse(gen_resp.data["no_results"])
        self.assertEqual(float(gen_resp.data["query"]["max_total_budget"]), 10.0)
        self.assertEqual(float(gen_resp.data["query"]["budget_cap"]), 10.0)

    def test_generate_plan_prompt_mode_uses_rules_parser_when_openai_disabled(self):
        self._register_and_login()
        gen_resp = self.client.post(
            reverse("meal-plan-generate"),
            {
                "input_mode": "prompt",
                "prompt": "Create 1 vegetarian meal with tofu under 30 minutes",
                "max_total_budget": 12,
                "optimize_mode": "balanced",
            },
            format="json",
        )
        self.assertEqual(gen_resp.status_code, 200)
        self.assertFalse(gen_resp.data["no_results"])
        self.assertEqual(gen_resp.data["query"]["parser_source"], "rules")
        self.assertEqual(float(gen_resp.data["query"]["budget_cap"]), 12.0)

    def test_generate_plan_budget_cap_infeasible_returns_warning(self):
        self._register_and_login()
        gen_resp = self.client.post(
            reverse("meal-plan-generate"),
            {
                "input_mode": "manual",
                "manual_query": {
                    "num_meals": 1,
                    "ingredient_keywords": ["tofu"],
                    "include_tags": ["vegetarian"],
                    "exclude_tags": [],
                    "exclude_ingredients": [],
                    "max_minutes": 30,
                    "max_total_budget": 1,
                },
                "optimize_mode": "budget",
            },
            format="json",
        )
        self.assertEqual(gen_resp.status_code, 200)
        self.assertFalse(gen_resp.data["no_results"])
        self.assertEqual(gen_resp.data["query"]["budget_cap"], 1.0)
        self.assertFalse(gen_resp.data["query"]["within_budget"])
        self.assertGreater(float(gen_resp.data["query"]["budget_overrun"]), 0.0)
        self.assertTrue(str(gen_resp.data["query"].get("budget_warning") or "").strip())

    def test_generate_plan_no_budget_cap_keeps_normal_behavior(self):
        self._register_and_login()
        gen_resp = self.client.post(
            reverse("meal-plan-generate"),
            {
                "input_mode": "manual",
                "manual_query": {
                    "num_meals": 1,
                    "ingredient_keywords": ["tofu"],
                    "include_tags": ["vegetarian"],
                    "exclude_tags": [],
                    "exclude_ingredients": [],
                    "max_minutes": 30,
                    "max_total_budget": None,
                },
                "optimize_mode": "balanced",
            },
            format="json",
        )
        self.assertEqual(gen_resp.status_code, 200)
        self.assertFalse(gen_resp.data["no_results"])
        self.assertIsNone(gen_resp.data["query"]["budget_cap"])
        self.assertTrue(gen_resp.data["query"]["within_budget"])

    def test_generate_plan_manual_mode_requires_manual_query_object(self):
        self._register_and_login()
        gen_resp = self.client.post(
            reverse("meal-plan-generate"),
            {
                "input_mode": "manual",
                "manual_query": "bad",
            },
            format="json",
        )
        self.assertEqual(gen_resp.status_code, 400)

    def test_tag_list_endpoint(self):
        self._register_and_login()
        resp = self.client.get(reverse("tag-list"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("tags", resp.data)
        self.assertIn("vegetarian", resp.data["tags"])

    def test_ingredient_pricing_report_endpoint(self):
        self._register_and_login()
        Ingredient.objects.update_or_create(
            name="report test ingredient",
            defaults={"estimated_unit_cost_eur": 1.23},
        )
        resp = self.client.get(reverse("ingredient-pricing-report"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("ingredient_total", resp.data)
        self.assertIn("priced_total", resp.data)
        self.assertIn("coverage_percent", resp.data)
        self.assertIn("price_stats_eur", resp.data)
        self.assertIn("most_common_prices", resp.data)
        self.assertIn("missing_examples", resp.data)
        self.assertIn("lowest_priced_examples", resp.data)
        self.assertIn("highest_priced_examples", resp.data)

    def test_shopping_list_condenses_ingredient_variants(self):
        self._register_and_login()
        user = User.objects.get(email="test@example.com")

        r1 = Recipe.objects.create(
            name="Chicken Bowl 1",
            ingredients="chicken breast, garlic",
            instructions="Cook",
            minutes=20,
            description="x",
            external_id=31001,
        )
        r2 = Recipe.objects.create(
            name="Chicken Bowl 2",
            ingredients="chichken thighs, onion",
            instructions="Cook",
            minutes=25,
            description="y",
            external_id=31002,
        )

        plan = MealPlan.objects.create(
            user=user,
            title="Condense Test",
            source_prompt="test",
            parsed_query={"num_meals": 2},
        )
        MealPlanItem.objects.create(meal_plan=plan, position=1, recipe=r1)
        MealPlanItem.objects.create(meal_plan=plan, position=2, recipe=r2)

        resp = self.client.post(reverse("shopping-list", args=[plan.id]), {}, format="json")
        self.assertEqual(resp.status_code, 200)

        items = {item["ingredient"]: item for item in resp.data["items"]}
        self.assertIn("chicken", items)
        self.assertEqual(items["chicken"]["count"], 2)
        self.assertIn("chicken breast", items["chicken"]["variants"])
        self.assertIn("chichken thighs", items["chicken"]["variants"])

    def test_unauthorized_blocked(self):
        resp = self.client.get(reverse("meal-plan-list"))
        self.assertEqual(resp.status_code, 401)

    def test_openai_condenser_keeps_salt_and_pepper_split(self):
        class _FakeMessage:
            content = (
                '{"items": ['
                '{"ingredient":"salt","count":2,"variants":["salt and pepper","salt"],"estimated_unit_cost":0.10,"estimated_subtotal":0.20,"currency":"EUR","confidence":0.8},'
                '{"ingredient":"pepper","count":1,"variants":["salt and pepper"],"estimated_unit_cost":0.30,"estimated_subtotal":0.30,"currency":"EUR","confidence":0.8},'
                '{"ingredient":"chicken","count":2,"variants":["chicken breast","chichken thighs"],"estimated_unit_cost":2.50,"estimated_subtotal":5.00,"currency":"EUR","confidence":0.9}'
                '], "cost_summary":{"estimated_total":999.99,"currency":"EUR","notes":"rough"}}'
            )

        class _FakeChoice:
            message = _FakeMessage()

        class _FakeCompletion:
            choices = [_FakeChoice()]

        class _FakeCompletions:
            @staticmethod
            def create(**kwargs):
                return _FakeCompletion()

        class _FakeChat:
            completions = _FakeCompletions()

        class _FakeOpenAI:
            chat = _FakeChat()

        items = _build_shopping_items_openai(
            ["salt and pepper", "salt", "chicken breast", "chichken thighs"],
            _FakeOpenAI(),
            "gpt-4o-mini",
        )
        self.assertIsNotNone(items)
        self.assertEqual(items["estimate_source"], "openai")
        self.assertIn("cost_summary", items)
        item_map = {item["ingredient"]: item for item in items["items"]}
        self.assertEqual(item_map["salt"]["count"], 2)
        self.assertEqual(item_map["pepper"]["count"], 1)
        self.assertEqual(item_map["chicken"]["count"], 2)
        self.assertAlmostEqual(items["cost_summary"]["estimated_total"], 5.50, places=2)

    def test_rate_meal_and_plan_completion(self):
        self._register_and_login()

        gen_resp = self.client.post(
            reverse("meal-plan-generate"),
            {"prompt": "Create 2 vegetarian meals with tofu"},
            format="json",
        )
        self.assertEqual(gen_resp.status_code, 200)
        plan_id = gen_resp.data["meal_plan"]["id"]

        plan_detail = self.client.get(reverse("meal-plan-detail", args=[plan_id]))
        self.assertEqual(plan_detail.status_code, 200)
        total_count = len(plan_detail.data["items"])
        self.assertGreaterEqual(total_count, 1)

        for item in plan_detail.data["items"]:
            rate_resp = self.client.post(
                reverse("meal-plan-rate", args=[plan_id]),
                {"position": item["position"], "rating": 4, "feedback_note": "good"},
                format="json",
            )
            self.assertEqual(rate_resp.status_code, 200)

        final_detail = self.client.get(reverse("meal-plan-detail", args=[plan_id]))
        self.assertEqual(final_detail.status_code, 200)
        self.assertEqual(final_detail.data["rated_count"], final_detail.data["total_count"])
        self.assertTrue(final_detail.data["is_completed"])

    def test_rate_meal_rejects_invalid_rating(self):
        self._register_and_login()
        gen_resp = self.client.post(
            reverse("meal-plan-generate"),
            {"prompt": "Create 1 vegetarian meal with tofu"},
            format="json",
        )
        self.assertEqual(gen_resp.status_code, 200)
        plan_id = gen_resp.data["meal_plan"]["id"]
        rate_resp = self.client.post(
            reverse("meal-plan-rate", args=[plan_id]),
            {"position": 1, "rating": 6},
            format="json",
        )
        self.assertEqual(rate_resp.status_code, 400)

    def test_rate_meal_blocks_other_user_plan(self):
        owner = User.objects.create_user(
            username="owner@example.com",
            email="owner@example.com",
            password="StrongPass123!",
        )
        recipe = Recipe.objects.create(
            name="Owner Meal",
            ingredients="tofu, rice",
            instructions="Cook",
            minutes=20,
            external_id=32910,
        )
        owner_plan = MealPlan.objects.create(
            user=owner,
            title="Owner Plan",
            source_prompt="owner",
            parsed_query={"num_meals": 1},
        )
        MealPlanItem.objects.create(meal_plan=owner_plan, position=1, recipe=recipe)

        self._register_and_login()
        rate_resp = self.client.post(
            reverse("meal-plan-rate", args=[owner_plan.id]),
            {"position": 1, "rating": 3},
            format="json",
        )
        self.assertEqual(rate_resp.status_code, 404)

    def test_swap_meal_blocks_other_user_plan(self):
        owner = User.objects.create_user(
            username="swapowner@example.com",
            email="swapowner@example.com",
            password="StrongPass123!",
        )
        replacement = Recipe.objects.create(
            name="Owner Replacement Meal",
            ingredients="tofu, broccoli",
            instructions="Cook",
            minutes=20,
            external_id=32911,
        )
        owner_plan = MealPlan.objects.create(
            user=owner,
            title="Owner Swap Plan",
            source_prompt="owner",
            parsed_query={"num_meals": 1},
        )
        MealPlanItem.objects.create(meal_plan=owner_plan, position=1, recipe=self.recipe)

        self._register_and_login()
        swap_resp = self.client.post(
            reverse("meal-plan-swap", args=[owner_plan.id]),
            {"position": 1},
            format="json",
        )
        self.assertEqual(swap_resp.status_code, 404)
        self.assertTrue(Recipe.objects.filter(id=replacement.id).exists())

    def test_delete_plan_blocks_other_user_plan(self):
        owner = User.objects.create_user(
            username="deleteowner@example.com",
            email="deleteowner@example.com",
            password="StrongPass123!",
        )
        owner_plan = MealPlan.objects.create(
            user=owner,
            title="Owner Delete Plan",
            source_prompt="owner",
            parsed_query={"num_meals": 1},
        )
        MealPlanItem.objects.create(meal_plan=owner_plan, position=1, recipe=self.recipe)

        self._register_and_login()
        delete_resp = self.client.delete(reverse("meal-plan-detail", args=[owner_plan.id]))
        self.assertEqual(delete_resp.status_code, 404)
        self.assertTrue(MealPlan.objects.filter(id=owner_plan.id).exists())

    def test_shopping_list_blocks_other_user_plan(self):
        owner = User.objects.create_user(
            username="shopowner@example.com",
            email="shopowner@example.com",
            password="StrongPass123!",
        )
        owner_plan = MealPlan.objects.create(
            user=owner,
            title="Owner Shopping Plan",
            source_prompt="owner",
            parsed_query={"num_meals": 1},
        )
        MealPlanItem.objects.create(meal_plan=owner_plan, position=1, recipe=self.recipe)

        ShoppingList.objects.create(
            meal_plan=owner_plan,
            items={
                "items": [{"ingredient": "tofu", "count": 1, "variants": ["tofu"]}],
                "cost_summary": {"estimated_total": 1.8, "currency": "EUR", "notes": "test"},
                "estimate_source": "rules",
                "is_rough_estimate": True,
            },
        )

        self._register_and_login()
        get_resp = self.client.get(reverse("shopping-list", args=[owner_plan.id]))
        post_resp = self.client.post(reverse("shopping-list", args=[owner_plan.id]), {}, format="json")
        self.assertEqual(get_resp.status_code, 404)
        self.assertEqual(post_resp.status_code, 404)

    def test_optimizer_applies_soft_rating_weight(self):
        low = Recipe.objects.create(
            name="Chicken Tray Bake Low",
            ingredients="chicken, potato, onion",
            instructions="Cook",
            minutes=25,
            external_id=32901,
        )
        high = Recipe.objects.create(
            name="Chicken Tray Bake High",
            ingredients="chicken, potato, onion",
            instructions="Cook",
            minutes=25,
            external_id=32902,
        )

        selected, _ = _select_optimized_recipes(
            [low, high],
            {"num_meals": 1, "ingredient_keywords": ["chicken"]},
            optimize_mode="balanced",
            random_seed=3,
            recipe_rating_map={low.id: 1.0, high.id: 5.0},
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].id, high.id)

    def test_optimizer_prefers_anchor_protein(self):
        chicken_1 = Recipe.objects.create(
            name="Chicken Rice Bowl",
            ingredients="chicken breast, rice, onion",
            instructions="Cook",
            minutes=25,
            external_id=32001,
        )
        chicken_2 = Recipe.objects.create(
            name="Chicken Curry",
            ingredients="chicken thighs, rice, garlic",
            instructions="Cook",
            minutes=30,
            external_id=32002,
        )
        beef = Recipe.objects.create(
            name="Beef Stir Fry",
            ingredients="beef, broccoli, soy sauce",
            instructions="Cook",
            minutes=20,
            external_id=32003,
        )
        tofu = Recipe.objects.create(
            name="Tofu Tray Bake",
            ingredients="tofu, peppers, olive oil",
            instructions="Cook",
            minutes=35,
            external_id=32004,
        )

        selected, meta = _select_optimized_recipes(
            [chicken_1, chicken_2, beef, tofu],
            {"num_meals": 2, "ingredient_keywords": ["chicken"]},
            random_seed=11,
        )
        self.assertEqual(len(selected), 2)
        self.assertEqual({recipe.name for recipe in selected}, {"Chicken Rice Bowl", "Chicken Curry"})
        self.assertIn("poultry", meta["anchor_families"])

    def test_recipe_cost_estimation_known_and_unknown(self):
        Ingredient.objects.create(name="chicken", estimated_unit_cost_eur=2.50)
        Ingredient.objects.create(name="rice", estimated_unit_cost_eur=0.55)
        known = Recipe.objects.create(
            name="Known Cost Recipe",
            ingredients="chicken, rice",
            instructions="Cook",
            minutes=20,
            external_id=32921,
        )
        unknown = Recipe.objects.create(
            name="Unknown Cost Recipe",
            ingredients="mystery powder",
            instructions="Cook",
            minutes=20,
            external_id=32922,
        )
        self.assertAlmostEqual(_estimate_recipe_cost(known), 3.05, places=2)
        self.assertAlmostEqual(_estimate_recipe_cost(unknown), 0.75, places=2)

    def test_optimizer_budget_metadata_estimated_total_matches_selected(self):
        cheap = Recipe.objects.create(
            name="Cheap Rice Bowl",
            ingredients="rice, onion",
            instructions="Cook",
            minutes=20,
            external_id=32931,
        )
        expensive = Recipe.objects.create(
            name="Premium Steak Bowl",
            ingredients="beef, rice, butter",
            instructions="Cook",
            minutes=20,
            external_id=32932,
        )

        selected, meta = _select_optimized_recipes(
            [cheap, expensive],
            {"num_meals": 1, "max_total_budget": 10},
            optimize_mode="budget",
            random_seed=5,
        )
        selected_total = sum(_estimate_recipe_cost(recipe) for recipe in selected)
        self.assertAlmostEqual(meta["estimated_total"], round(selected_total, 2), places=2)

    def test_optimizer_prefers_shared_budget_ingredients(self):
        bean_1 = Recipe.objects.create(
            name="Budget Bean Bowl",
            ingredients="beans, rice, onion",
            instructions="Cook",
            minutes=20,
            external_id=32101,
        )
        bean_2 = Recipe.objects.create(
            name="Bean Chili",
            ingredients="beans, tomato, onion",
            instructions="Cook",
            minutes=30,
            external_id=32102,
        )
        salmon = Recipe.objects.create(
            name="Salmon Plate",
            ingredients="salmon, asparagus, lemon",
            instructions="Cook",
            minutes=25,
            external_id=32103,
        )
        lamb = Recipe.objects.create(
            name="Lamb Roast",
            ingredients="lamb, potato, rosemary",
            instructions="Cook",
            minutes=60,
            external_id=32104,
        )

        selected, _ = _select_optimized_recipes(
            [bean_1, bean_2, salmon, lamb],
            {"num_meals": 2, "ingredient_keywords": []},
            random_seed=11,
        )
        self.assertEqual({recipe.name for recipe in selected}, {"Budget Bean Bowl", "Bean Chili"})

    def test_optimizer_mode_toggle_changes_tradeoff(self):
        bean = Recipe.objects.create(
            name="Bean Rice Bowl",
            ingredients="beans, rice, onion",
            instructions="Cook",
            minutes=25,
            external_id=32201,
        )
        pork = Recipe.objects.create(
            name="Pork Rice Bowl",
            ingredients="pork, rice, onion",
            instructions="Cook",
            minutes=25,
            external_id=32202,
        )
        fish = Recipe.objects.create(
            name="Fish Rice Bowl",
            ingredients="salmon, rice, onion",
            instructions="Cook",
            minutes=25,
            external_id=32203,
        )

        budget_selected, budget_meta = _select_optimized_recipes(
            [bean, pork, fish],
            {"num_meals": 2, "ingredient_keywords": []},
            optimize_mode="budget",
            random_seed=7,
        )
        sustainability_selected, sustainability_meta = _select_optimized_recipes(
            [bean, pork, fish],
            {"num_meals": 2, "ingredient_keywords": []},
            optimize_mode="sustainability",
            random_seed=7,
        )

        self.assertEqual(budget_meta["optimize_mode"], "budget")
        self.assertEqual(sustainability_meta["optimize_mode"], "sustainability")
        self.assertIn("Pork Rice Bowl", {recipe.name for recipe in budget_selected})
        self.assertIn("Fish Rice Bowl", {recipe.name for recipe in sustainability_selected})

    def test_meal_filter_excludes_non_meal_sauce_candidates(self):
        sauce = Recipe.objects.create(
            name="Easy Hollandaise Sauce",
            ingredients="butter, lemon juice, egg yolks",
            instructions="Whisk",
            minutes=10,
            n_steps=1,
            n_ingredients=3,
            external_id=32301,
        )
        meal = Recipe.objects.create(
            name="Chicken Rice Plate",
            ingredients="chicken, rice, onion, garlic, oil, salt",
            instructions="Cook\nServe",
            minutes=25,
            n_steps=4,
            n_ingredients=6,
            external_id=32302,
        )

        filtered, meta = _filter_meal_candidates([sauce, meal], required_count=1)
        filtered_names = {recipe.name for recipe in filtered}
        self.assertIn("Chicken Rice Plate", filtered_names)
        self.assertNotIn("Easy Hollandaise Sauce", filtered_names)
        self.assertEqual(meta["raw_candidate_count"], 2)

    def test_optimizer_introduces_seeded_variation(self):
        recipes = []
        for idx in range(8):
            recipes.append(
                Recipe.objects.create(
                    name=f"Chicken Meal {idx}",
                    ingredients=f"chicken, rice, onion, garlic, herb{idx}",
                    instructions="Cook\nServe",
                    minutes=25,
                    n_steps=4,
                    n_ingredients=5,
                    external_id=32400 + idx,
                )
            )

        selected_seed_1, _ = _select_optimized_recipes(
            recipes,
            {"num_meals": 4, "ingredient_keywords": ["chicken"]},
            optimize_mode="balanced",
            random_seed=1,
        )
        selected_seed_2, _ = _select_optimized_recipes(
            recipes,
            {"num_meals": 4, "ingredient_keywords": ["chicken"]},
            optimize_mode="balanced",
            random_seed=2,
        )

        ids_seed_1 = [recipe.id for recipe in selected_seed_1]
        ids_seed_2 = [recipe.id for recipe in selected_seed_2]
        self.assertNotEqual(ids_seed_1, ids_seed_2)
