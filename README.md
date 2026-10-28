# AnviEats (...less)

Streamlit nutrition and weight tracker with FatSecret food search, per-ingredient quantity and measure selectors, pink light theme, meal logging, saved custom meals, and weight tracking.

## Files
- `app.py` — Streamlit application.
- `meals.csv` — starter meal ideas.
- `requirements.txt` — dependencies.
- `funvi_diet.db` — created automatically to store food logs, weight logs, and custom saved meals.

## Run locally
1. Use Python 3.11 or 3.12.
2. In this folder, create/activate a virtual environment.
3. Run `pip install -r requirements.txt`.
4. Create `.streamlit/secrets.toml` with:
   ```toml
   FATSECRET_CLIENT_ID = "your-client-id"
   FATSECRET_CLIENT_SECRET = "your-client-secret"
   ```
5. Run `streamlit run app.py`.

For Streamlit Community Cloud, put credentials in app **Settings → Secrets**. Never commit secrets or put them in `app.py`. If a secret was exposed, rotate it in FatSecret first.

## Food logging
The Quick log starts with one ingredient row. Add more using **Add ingredient**. Each row has a food search/dropdown, amount, and unit. Supported units are g, oz, lb, ml, cup, tbsp, tsp, piece, and serving. Grams are the most reliable. Household conversions use generic approximations (cup 150 g, tablespoon 15 g, teaspoon 5 g, piece/serving 100/150 g) and can be inaccurate for a specific food. Review the chosen FatSecret match and nutrition before saving.

After calculating a meal, choose **Log meal** to add it to the daily log or **Add to saved meals** to name it and save its ingredient-level breakdown in the Meals tab. Saved meals can later be logged or deleted.

## Data and privacy
The SQLite database is stored beside `app.py` on the machine/server running the app. Streamlit Community Cloud's local filesystem may not be durable across app restarts/redeploys; use persistent storage for important logs. This prototype has no login, so do not deploy sensitive personal data publicly without authentication and access controls.

## Nutrition note
Calories and macros are estimates, not medical advice. Database matches and household measures can be inaccurate.
