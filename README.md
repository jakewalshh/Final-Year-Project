# Panion

Final Year Project by Jake Walsh (`C22493266`).

Panion is a meal planning web app that lets users generate recipe plans from either a natural language prompt or manual filters, then save and manage those plans through their account.

## What Panion Does

- User signup and login with account-based data
- Meal plan generation from:
  - Prompt mode (chat-style request)
  - Manual mode (structured filters)
- Recipe filtering by ingredient, tags, time, nutrition, and budget cap
- Saved plans with swap meal and delete actions
- Meal completion and per-meal rating (1 to 5)
- Shopping list generation from a saved plan
- Rough budget estimation with clear warning metadata when constraints are too strict

## Main Stack

- Frontend: React
- Backend API: Django + Django REST Framework
- Database: PostgreSQL
- AI support: OpenAI (with rules-based fallback where needed)
- Deployment: Docker, Azure Web App + Azure PostgreSQL

## Project Structure

- `frontend/` React UI
- `backend/` Django API, planner logic, models, tests
- `scripts/` helper scripts
- `docker-compose.yml` local container orchestration

## Notes

Panion is designed as a practical planner, not a perfect nutrition or supermarket pricing engine. Cost and optimization outputs are intentionally rough planning guidance.
