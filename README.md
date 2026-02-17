# Final-Year-Project
### Welcome to my Panion Project
## Jake Walsh : C22493266

# Panion Prototype

Prototype for the Panion smart meal planner.

## Tech Stack
- Django backend API
- PostgreSQL (`postgres:17-alpine`)
- React frontend
- Docker Compose for local development

## What Is Implemented
- Normalized recipe database schema:
  - `Recipe`
  - `Ingredient`
  - `RecipeIngredient` (ordered list)
  - `RecipeStep` (ordered list)
  - `Tag`
  - `RecipeTag`
- CSV importer command for Kaggle `RAW_recipes.csv`
- Query API endpoints:
  - `GET /api/recipes/search/`
  - `GET /api/recipes/<id>/`
  - `POST /api/plan-meals/`

## Environment
Create `.env` in repo root:

```env
OPENAI_API_KEY=sk-yourkey
USE_OPENAI_PARSER=0
```

`USE_OPENAI_PARSER=0` keeps parsing local/offline. Set to `1` to enable OpenAI parsing in `plan-meals`.

## Database Setup
Run migrations:

```bash
docker compose run --rm backend python manage.py migrate
```

## Import Kaggle Dataset
Your dataset is outside the project folder, so mount it when running import:

```bash
docker compose run --rm \
  -v /Users/jake/College/Yr4S1/FinalYearProject/Dataset/KaggleDataset/RecipesAndInteractions/RAW_recipes.csv:/tmp/RAW_recipes.csv:ro \
  backend python manage.py import_raw_recipes --csv-path /tmp/RAW_recipes.csv --truncate --batch-size 1000
```

Quick smoke import (first 2000 rows only):

```bash
docker compose run --rm \
  -v /Users/jake/College/Yr4S1/FinalYearProject/Dataset/KaggleDataset/RecipesAndInteractions/RAW_recipes.csv:/tmp/RAW_recipes.csv:ro \
  backend python manage.py import_raw_recipes --csv-path /tmp/RAW_recipes.csv --limit 2000 --truncate
```

## Query API Examples
Search by ingredient:

```bash
curl "http://localhost:8000/api/recipes/search/?ingredient=chicken&limit=5"
```

Search by ingredient + tag + max minutes:

```bash
curl "http://localhost:8000/api/recipes/search/?ingredient=beef&tag=30-minutes-or-less&max_minutes=45&limit=10"
```

Get recipe detail:

```bash
curl "http://localhost:8000/api/recipes/1/"
```

Plan meals:

```bash
curl -X POST "http://localhost:8000/api/plan-meals/" \
  -H "Content-Type: application/json" \
  -d '{"user_prompt":"Create 3 chicken meals for 2 people"}'
```

## Testing
Backend tests:

```bash
docker compose run --rm backend python manage.py test recipes
```
