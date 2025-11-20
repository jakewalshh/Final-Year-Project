import React, { useState } from "react";

const PLAN_MEALS_URL = "http://localhost:8000/api/plan-meals/";

function App() {
  const [userPrompt, setUserPrompt] = useState(
    "Create 3 meals to feed two people. I want chicken to be in them, there are no alergies"
  );
  const [recipes, setRecipes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const handleSubmit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    setRecipes([]);

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
    } catch (err) {
      console.error(err);
      setError("Something went wrong generating the meal plan. Check the backend logs.");
    } finally {
      setLoading(false);
    }
  };


  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <h1 style={styles.title}>Panion Prototype</h1>
        <p style={styles.subtitle}>
          Enter a meal planning request below. For now, the app will always
          return 3 chicken recipes from the database.
        </p>

        <form onSubmit={handleSubmit} style={styles.form}>
          <label style={styles.label}>
            Meal plan request:
            <textarea
              style={styles.textarea}
              value={userPrompt}
              onChange={(e) => setUserPrompt(e.target.value)}
            />
          </label>

          <button type="submit" style={styles.button} disabled={loading}>
            {loading ? "Generating..." : "Generate Meal Plan"}
          </button>
        </form>

        {error && <p style={styles.error}>{error}</p>}

        <div style={styles.results}>
          <h2 style={styles.resultsTitle}>Recipes</h2>
          {recipes.length === 0 && !loading && (
            <p style={styles.noResults}>No recipes yet. Try generating a plan.</p>
          )}

          {recipes.map((recipe) => (
            <div key={recipe.id} style={styles.recipeCard}>
              <h3 style={styles.recipeTitle}>{recipe.name}</h3>
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

const styles = {
  page: {
    minHeight: "100vh",
    margin: 0,
    padding: "20px",
    backgroundColor: "#0f172a",
    color: "#e5e7eb",
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
    display: "flex",
    justifyContent: "center",
    alignItems: "flex-start",
  },
  card: {
    maxWidth: "800px",
    width: "100%",
    backgroundColor: "#020617",
    borderRadius: "16px",
    padding: "24px",
    boxShadow: "0 10px 40px rgba(15,23,42,0.8)",
    border: "1px solid #1f2937",
  },
  title: {
    margin: 0,
    marginBottom: "8px",
    fontSize: "28px",
  },
  subtitle: {
    marginTop: 0,
    marginBottom: "20px",
    color: "#9ca3af",
    fontSize: "14px",
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    marginBottom: "20px",
  },
  label: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    fontSize: "14px",
  },
  textarea: {
    minHeight: "80px",
    padding: "10px",
    borderRadius: "8px",
    border: "1px solid #4b5563",
    backgroundColor: "#020617",
    color: "#e5e7eb",
    resize: "vertical",
    fontFamily: "inherit",
    fontSize: "14px",
  },
  button: {
    marginTop: "4px",
    padding: "10px 16px",
    borderRadius: "9999px",
    border: "none",
    backgroundColor: "#22c55e",
    color: "#022c22",
    fontWeight: 600,
    cursor: "pointer",
    alignSelf: "flex-start",
  },
  error: {
    color: "#fca5a5",
    marginTop: "8px",
  },
  results: {
    marginTop: "16px",
  },
  resultsTitle: {
    fontSize: "20px",
    marginBottom: "8px",
  },
  noResults: {
    color: "#9ca3af",
    fontSize: "14px",
  },
  recipeCard: {
    marginTop: "12px",
    padding: "12px",
    borderRadius: "12px",
    backgroundColor: "#020617",
    border: "1px solid #1f2937",
  },
  recipeTitle: {
    margin: 0,
    marginBottom: "4px",
    fontSize: "18px",
  },
};

export default App;

