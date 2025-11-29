import React, { useState } from "react";
import "./App.css";

const PLAN_MEALS_URL = "http://localhost:8000/api/plan-meals/";

function App() {
  const [userPrompt, setUserPrompt] = useState(
    "Create 3 meals to feed two people. I want chicken as the meat, there are no alergies"
  );
  const [recipes, setRecipes] = useState([]);
  const [parsedQuery, setParsedQuery] = useState(null);
  const [noResults, setNoResults] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const handleSubmit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    setRecipes([]);
    setParsedQuery(null);
    setNoResults(false); 

    try {
      const response = await fetch(PLAN_MEALS_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          user_prompt: userPrompt,
        }),
      });

      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`);
      }

      const data = await response.json();

      // Expecting { query: {...}, recipes: [...] }
      setRecipes(data.recipes || []);
      setParsedQuery(data.query || null);
      setNoResults(Boolean(data.no_results));

    } catch (err) {
      console.error(err);
      setError("Something went wrong generating the meal plan. Check the backend logs.");
    } finally {
      setLoading(false);
    }
  };


  return (
    <div className="page">
      <div className="card">
        <h1 className="title">Panion Prototype</h1>
        <p className="subtitle">
          Enter a meal planning request below. For now, the app will always
          return 3 chicken recipes from the database.
        </p>

        <form onSubmit={handleSubmit} className="form">
          <label className="label">
            Meal plan request:
            <textarea
              className="textarea"
              value={userPrompt}
              onChange={(e) => setUserPrompt(e.target.value)}
            />
          </label>

          <button type="submit" className="button" disabled={loading}>
            {loading ? "Generating..." : "Generate Meal Plan"}
          </button>
        </form>

        {error && <p className="error">{error}</p>}

        {parsedQuery && (
          <div className="query-summary">
            <h2 className="results-title">Parsed Request</h2>
            <p className="query-text">
              <strong>Meals:</strong> {parsedQuery.num_meals} &nbsp;|&nbsp;
              <strong>Serves per meal:</strong> {parsedQuery.serves} &nbsp;|&nbsp;
              <strong>Main ingredient:</strong> {parsedQuery.ingredient_keyword}
            </p>
          </div>
        )}

        <div className="results">
          <h2 className="results-title">Recipes</h2>

          {recipes.length === 0 && !loading && !noResults && (
            <p className="no-results">No recipes yet. Try generating a plan.</p>
          )}

          {noResults && !loading && (
            <p className="no-results">
              No recipes found for this request. Try changing the main ingredient or serves.
            </p>
          )}


          {recipes.map((recipe) => (
            <div key={recipe.id} className="recipe-card">
              <h3 className="recipe-title">{recipe.name}</h3>
              <p>
                <strong>Serves:</strong> {recipe.serves}
              </p>
              <p>
                <strong>Ingredients:</strong> {recipe.ingredients}
              </p>
              <p>
                <strong>Instructions:</strong> {recipe.instructions}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default App;
