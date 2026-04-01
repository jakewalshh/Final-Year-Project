import os
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from recipes.models import Ingredient, Recipe, RecipeIngredient, RecipeTag, Tag

from .models import MealPlan, MealPlanItem, ShoppingList, UserPreference
from .views import _build_shopping_items_openai, _filter_meal_candidates, _select_optimized_recipes

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
        ingredient_tofu = Ingredient.objects.create(name="tofu")
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
                '{"normalized_items": ['
                '{"source": "salt and pepper", "canonical": ["salt", "pepper"]},'
                '{"source": "salt", "canonical": ["salt"]},'
                '{"source": "chicken breast", "canonical": ["chicken"]},'
                '{"source": "chichken thighs", "canonical": ["chicken"]}'
                "]}"
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
        item_map = {item["ingredient"]: item for item in items}
        self.assertEqual(item_map["salt"]["count"], 2)
        self.assertEqual(item_map["pepper"]["count"], 1)
        self.assertEqual(item_map["chicken"]["count"], 2)

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
