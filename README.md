# Final-Year-Project
### Welcome to my Panion Project
## Jake Walsh : C22493266

# Panion Prototype

prototype for the Panion smart meal planner.

Tech stack:
- Django (backend API)
- PostgreSQL (database) - 17-alpine (lighter version)
- React (frontend)
- Docker + docker compose for local development

Enter you own OpenAI API key into the .env file
currently the docker compose doesnt compile properly due to an issue with the node_modules, fixing

## System Overview (brief)
- React frontend: collects user inputs, calls the Django REST API, and renders meal plans/recipes returned from the server.
- Django + REST + OpenAI: parses user prompts, enforces auth/business rules, queries the database via Django ORM, and optionally calls OpenAI for AI-assisted parsing; returns structured JSON to the frontend.
- PostgreSQL: stores users, recipes, and related domain data; accessed only through the Django ORM to keep schema and constraints centralized.