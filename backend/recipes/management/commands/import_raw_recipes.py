import ast
import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from recipes.models import (
    Ingredient,
    Recipe,
    RecipeIngredient,
    RecipeStep,
    RecipeTag,
    Tag,
)


DEFAULT_CSV_PATH = (
    "/Users/jake/College/Yr4S1/FinalYearProject/Dataset/"
    "KaggleDataset/RecipesAndInteractions/RAW_recipes.csv"
)


@dataclass
class ParsedRecipeRow:
    recipe: Recipe
    ingredient_names: list[str]
    steps: list[str]
    tag_names: list[str]


class Command(BaseCommand):
    help = "Import recipes from RAW_recipes.csv into normalized recipe tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv-path",
            default=DEFAULT_CSV_PATH,
            help=f"Path to RAW_recipes.csv (default: {DEFAULT_CSV_PATH})",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of recipes to flush per batch.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional row limit (useful for quick tests).",
        )
        parser.add_argument(
            "--truncate",
            action="store_true",
            help="Delete all recipe/tag/ingredient data before importing.",
        )
        parser.add_argument(
            "--refresh-existing",
            action="store_true",
            help=(
                "Re-import recipes that already exist by external_id "
                "(old related steps/ingredients/tags are replaced)."
            ),
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv_path"]).expanduser().resolve()
        batch_size = options["batch_size"]
        limit = options["limit"]
        truncate = options["truncate"]
        refresh_existing = options["refresh_existing"]

        if batch_size < 1:
            raise CommandError("--batch-size must be >= 1")

        if limit is not None and limit < 1:
            raise CommandError("--limit must be >= 1 when provided")

        if not csv_path.exists():
            raise CommandError(f"CSV not found: {csv_path}")

        if truncate:
            self._truncate_tables()

        self.stdout.write(self.style.NOTICE(f"Importing from: {csv_path}"))
        imported, skipped = self._import_file(
            csv_path=csv_path,
            batch_size=batch_size,
            limit=limit,
            refresh_existing=refresh_existing,
        )

        self.stdout.write(self.style.SUCCESS(f"Import complete. Imported: {imported}"))
        self.stdout.write(self.style.SUCCESS(f"Skipped existing: {skipped}"))

    def _truncate_tables(self):
        self.stdout.write(self.style.WARNING("Truncating recipe tables..."))
        with transaction.atomic():
            RecipeIngredient.objects.all().delete()
            RecipeStep.objects.all().delete()
            RecipeTag.objects.all().delete()
            Recipe.objects.all().delete()
            Ingredient.objects.all().delete()
            Tag.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("Truncate complete."))

    def _import_file(
        self,
        *,
        csv_path: Path,
        batch_size: int,
        limit: int | None,
        refresh_existing: bool,
    ) -> tuple[int, int]:
        ingredient_cache = dict(Ingredient.objects.values_list("name", "id"))
        tag_cache = dict(Tag.objects.values_list("name", "id"))

        existing_external_ids = set(
            Recipe.objects.exclude(external_id__isnull=True).values_list(
                "external_id",
                flat=True,
            )
        )

        imported_count = 0
        skipped_count = 0
        processed = 0
        chunk: list[ParsedRecipeRow] = []

        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)

            for row in reader:
                processed += 1
                if limit is not None and processed > limit:
                    break

                parsed = self._parse_row(row)
                if parsed is None:
                    continue

                external_id = parsed.recipe.external_id
                assert external_id is not None

                if (external_id in existing_external_ids) and not refresh_existing:
                    skipped_count += 1
                    continue

                chunk.append(parsed)

                if len(chunk) >= batch_size:
                    self._flush_chunk(
                        chunk,
                        ingredient_cache=ingredient_cache,
                        tag_cache=tag_cache,
                        refresh_existing=refresh_existing,
                    )
                    imported_count += len(chunk)
                    chunk.clear()
                    self.stdout.write(f"Processed rows: {processed} | Imported: {imported_count}")

        if chunk:
            self._flush_chunk(
                chunk,
                ingredient_cache=ingredient_cache,
                tag_cache=tag_cache,
                refresh_existing=refresh_existing,
            )
            imported_count += len(chunk)

        return imported_count, skipped_count

    def _flush_chunk(
        self,
        chunk: list[ParsedRecipeRow],
        *,
        ingredient_cache: dict[str, int],
        tag_cache: dict[str, int],
        refresh_existing: bool,
    ):
        external_ids = [item.recipe.external_id for item in chunk if item.recipe.external_id is not None]

        with transaction.atomic():
            if refresh_existing:
                self._bulk_upsert_recipes(chunk)
                recipe_id_map = dict(
                    Recipe.objects.filter(external_id__in=external_ids).values_list("external_id", "id")
                )
                recipe_ids = list(recipe_id_map.values())
                RecipeIngredient.objects.filter(recipe_id__in=recipe_ids).delete()
                RecipeStep.objects.filter(recipe_id__in=recipe_ids).delete()
                RecipeTag.objects.filter(recipe_id__in=recipe_ids).delete()
            else:
                Recipe.objects.bulk_create(
                    [item.recipe for item in chunk],
                    ignore_conflicts=True,
                )
                recipe_id_map = dict(
                    Recipe.objects.filter(external_id__in=external_ids).values_list("external_id", "id")
                )

            self._ensure_lookup_cache(
                names=self._collect_unique_names(item.ingredient_names for item in chunk),
                cache=ingredient_cache,
                model=Ingredient,
            )
            self._ensure_lookup_cache(
                names=self._collect_unique_names(item.tag_names for item in chunk),
                cache=tag_cache,
                model=Tag,
            )

            recipe_ingredients: list[RecipeIngredient] = []
            recipe_steps: list[RecipeStep] = []
            recipe_tags: list[RecipeTag] = []

            for item in chunk:
                external_id = item.recipe.external_id
                if external_id is None:
                    continue
                recipe_id = recipe_id_map.get(external_id)
                if recipe_id is None:
                    continue

                for pos, ingredient_name in enumerate(item.ingredient_names, start=1):
                    ingredient_id = ingredient_cache.get(ingredient_name)
                    if ingredient_id is None:
                        continue
                    recipe_ingredients.append(
                        RecipeIngredient(
                            recipe_id=recipe_id,
                            ingredient_id=ingredient_id,
                            position=pos,
                        )
                    )

                for step_number, step_text in enumerate(item.steps, start=1):
                    if not step_text:
                        continue
                    recipe_steps.append(
                        RecipeStep(
                            recipe_id=recipe_id,
                            step_number=step_number,
                            instruction=step_text,
                        )
                    )

                for tag_name in item.tag_names:
                    tag_id = tag_cache.get(tag_name)
                    if tag_id is None:
                        continue
                    recipe_tags.append(
                        RecipeTag(
                            recipe_id=recipe_id,
                            tag_id=tag_id,
                        )
                    )

            RecipeIngredient.objects.bulk_create(recipe_ingredients, ignore_conflicts=True)
            RecipeStep.objects.bulk_create(recipe_steps, ignore_conflicts=True)
            RecipeTag.objects.bulk_create(recipe_tags, ignore_conflicts=True)

    def _bulk_upsert_recipes(self, chunk: list[ParsedRecipeRow]):
        for item in chunk:
            recipe = item.recipe
            if recipe.external_id is None:
                continue
            Recipe.objects.update_or_create(
                external_id=recipe.external_id,
                defaults={
                    "name": recipe.name,
                    "minutes": recipe.minutes,
                    "contributor_id": recipe.contributor_id,
                    "submitted_date": recipe.submitted_date,
                    "description": recipe.description,
                    "n_steps": recipe.n_steps,
                    "n_ingredients": recipe.n_ingredients,
                    "ingredients": recipe.ingredients,
                    "instructions": recipe.instructions,
                    "calories": recipe.calories,
                    "total_fat_pdv": recipe.total_fat_pdv,
                    "sugar_pdv": recipe.sugar_pdv,
                    "sodium_pdv": recipe.sodium_pdv,
                    "protein_pdv": recipe.protein_pdv,
                    "saturated_fat_pdv": recipe.saturated_fat_pdv,
                    "carbohydrates_pdv": recipe.carbohydrates_pdv,
                },
            )

    def _ensure_lookup_cache(
        self,
        *,
        names: set[str],
        cache: dict[str, int],
        model: type[Ingredient] | type[Tag],
    ):
        missing = [name for name in names if name and name not in cache]
        if not missing:
            return

        existing_rows = model.objects.filter(name__in=missing).values_list("name", "id")
        for name, obj_id in existing_rows:
            cache[name] = obj_id

        still_missing = [name for name in missing if name not in cache]
        if still_missing:
            model.objects.bulk_create([model(name=name) for name in still_missing], ignore_conflicts=True)
            created_rows = model.objects.filter(name__in=still_missing).values_list("name", "id")
            for name, obj_id in created_rows:
                cache[name] = obj_id

    @staticmethod
    def _collect_unique_names(groups: Iterable[list[str]]) -> set[str]:
        names: set[str] = set()
        for group in groups:
            names.update(group)
        return names

    def _parse_row(self, row: dict[str, str]) -> ParsedRecipeRow | None:
        try:
            external_id = int(row["id"])
            minutes = self._to_int(row.get("minutes"))
            contributor_id = self._to_int(row.get("contributor_id"))
            submitted_date = self._to_date(row.get("submitted"))
            name = (row.get("name") or "").strip()
            description = (row.get("description") or "").strip()

            ingredients_list = self._parse_list(row.get("ingredients"))
            steps_list = self._parse_list(row.get("steps"))
            tags_list = self._parse_list(row.get("tags"))
            nutrition = self._parse_list(row.get("nutrition"))
        except Exception as exc:
            self.stderr.write(self.style.WARNING(f"Skipping malformed row: {exc!r}"))
            return None

        if not name:
            return None

        ingredient_names = []
        for item in ingredients_list:
            normalized = self._normalize_name(item)
            if normalized:
                ingredient_names.append(normalized)

        steps = []
        for step in steps_list:
            clean_step = self._clean_text(step)
            if clean_step:
                steps.append(clean_step)

        tag_names = []
        for tag in tags_list:
            normalized = self._normalize_name(tag)
            if normalized:
                tag_names.append(normalized)

        calories, fat, sugar, sodium, protein, sat_fat, carbs = self._parse_nutrition(nutrition)

        recipe = Recipe(
            external_id=external_id,
            name=name[:200],
            minutes=minutes,
            contributor_id=contributor_id,
            submitted_date=submitted_date,
            description=description,
            n_steps=self._to_int(row.get("n_steps")) or len(steps),
            n_ingredients=self._to_int(row.get("n_ingredients")) or len(ingredient_names),
            ingredients=", ".join(ingredient_names),
            instructions="\n".join(steps),
            calories=calories,
            total_fat_pdv=fat,
            sugar_pdv=sugar,
            sodium_pdv=sodium,
            protein_pdv=protein,
            saturated_fat_pdv=sat_fat,
            carbohydrates_pdv=carbs,
        )

        return ParsedRecipeRow(
            recipe=recipe,
            ingredient_names=ingredient_names,
            steps=steps,
            tag_names=tag_names,
        )

    @staticmethod
    def _parse_list(value: str | None) -> list:
        if not value:
            return []
        parsed = ast.literal_eval(value)
        if isinstance(parsed, list):
            return parsed
        return []

    @staticmethod
    def _parse_nutrition(nutrition: list) -> tuple[float | None, ...]:
        values = []
        for idx in range(7):
            raw = nutrition[idx] if idx < len(nutrition) else None
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                values.append(None)
        return tuple(values)  # type: ignore[return-value]

    @staticmethod
    def _to_int(value: str | None) -> int | None:
        try:
            if value is None or value == "":
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _normalize_name(value) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().lower().split())

    @staticmethod
    def _clean_text(value) -> str:
        if value is None:
            return ""
        return str(value).strip()
