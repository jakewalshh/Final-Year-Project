from django.db import models


class Recipe(models.Model):
    # Legacy fields kept so the current frontend continues to work.
    name = models.CharField(max_length=200, db_index=True)
    serves = models.IntegerField(null=True, blank=True, db_index=True)
    ingredients = models.TextField(blank=True, default="")
    instructions = models.TextField(blank=True, default="")

    # Full dataset fields from RAW_recipes.csv.
    external_id = models.BigIntegerField(unique=True, null=True, blank=True, db_index=True)
    minutes = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    contributor_id = models.BigIntegerField(null=True, blank=True)
    submitted_date = models.DateField(null=True, blank=True, db_index=True)
    description = models.TextField(blank=True, default="")
    n_steps = models.PositiveIntegerField(default=0)
    n_ingredients = models.PositiveIntegerField(default=0)
    calories = models.FloatField(null=True, blank=True)
    total_fat_pdv = models.FloatField(null=True, blank=True)
    sugar_pdv = models.FloatField(null=True, blank=True)
    sodium_pdv = models.FloatField(null=True, blank=True)
    protein_pdv = models.FloatField(null=True, blank=True)
    saturated_fat_pdv = models.FloatField(null=True, blank=True)
    carbohydrates_pdv = models.FloatField(null=True, blank=True)

    def __str__(self):
        if self.external_id is not None:
            return f"{self.name} ({self.external_id})"
        return self.name


class Ingredient(models.Model):
    name = models.CharField(max_length=128, unique=True, db_index=True)

    def __str__(self):
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True, db_index=True)

    def __str__(self):
        return self.name


class RecipeIngredient(models.Model):
    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="recipe_ingredients",
    )
    ingredient = models.ForeignKey(
        Ingredient,
        on_delete=models.CASCADE,
        related_name="recipe_ingredients",
    )
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipe", "position"],
                name="uniq_recipe_ingredient_position",
            ),
        ]
        indexes = [
            models.Index(fields=["recipe", "ingredient"]),
            models.Index(fields=["ingredient"]),
        ]

    def __str__(self):
        return f"{self.recipe_id}:{self.position}:{self.ingredient.name}"


class RecipeStep(models.Model):
    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    step_number = models.PositiveIntegerField()
    instruction = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipe", "step_number"],
                name="uniq_recipe_step_number",
            ),
        ]
        indexes = [
            models.Index(fields=["recipe", "step_number"]),
        ]
        ordering = ["step_number"]

    def __str__(self):
        return f"{self.recipe_id}:{self.step_number}"


class RecipeTag(models.Model):
    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="recipe_tags",
    )
    tag = models.ForeignKey(
        Tag,
        on_delete=models.CASCADE,
        related_name="recipe_tags",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipe", "tag"],
                name="uniq_recipe_tag",
            ),
        ]
        indexes = [
            models.Index(fields=["tag"]),
            models.Index(fields=["recipe", "tag"]),
        ]

    def __str__(self):
        return f"{self.recipe_id}:{self.tag.name}"
