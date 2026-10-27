# AnviEats (...less)

Streamlit diet and weight tracker with natural-language food logging, optional microphone dictation, FatSecret Platform API nutrition search, a meal library, weight charts, and an estimated time-to-goal projection.

## Files
- `app.py` — application and SQLite persistence.
- `meals.csv` — starter meal/recipe library.
- `requirements.txt` — Python dependencies.
- `funvi_diet.db` — created automatically when the app first runs; stores logs locally.

## Important credential security note
The FatSecret Client Secret was shown in a screenshot in a chat. Treat it as exposed and **regenerate/rotate the Client Secret in your FatSecret developer dashboard before using it**. Do not put API credentials directly in `app.py`, commit them to GitHub, or share them in screenshots. The app code intentionally does not contain your actual credentials.

## Setup locally
1. Use Python 3.11 or 3.12.
2. Open a terminal in this folder.
3. Create and activate a virtual environment (recommended):
   - macOS/Linux: `python3 -m venv .venv` then `source .venv/bin/activate`
   - Windows: `py -m venv .venv` then `.venv\\Scripts\\activate`
4. Install packages: `pip install -r requirements.txt`
5. Create a folder named `.streamlit` in this project folder.
6. Inside it, create `.streamlit/secrets.toml` containing:
   ```toml
   FATSECRET_CLIENT_ID = "your-new-client-id"
   FATSECRET_CLIENT_SECRET = "your-new-client-secret"
   ```
7. In FatSecret developer settings, check whether your account requires IP allowlisting and add the public IP address from which the app will call the API. Their OAuth 2.0 docs state that API token requests are restricted to configured IPs.
8. Run: `streamlit run app.py`

For Streamlit Community Cloud, add `FATSECRET_CLIENT_ID` and `FATSECRET_CLIENT_SECRET` in the app's **Settings → Secrets** rather than uploading a local secrets file. Depending on FatSecret key restrictions, the cloud app's outbound IP may be a deployment issue; test it and check the FatSecret developer console.

## Food logging
Enter one food item per line, for example:
- `100 g paneer`
- `2 chapatis`
- `1 cup cooked rice`
- `1 tsp ghee`

The app searches FatSecret, retrieves serving-level nutrition, normalizes the selected record to a per-100-g estimate, and calculates calories/macros for the entered quantity. It currently uses the first search match automatically and shows alternatives for review. Please check the match before saving. Grams are more accurate than household measures; generic conversions for cups, pieces, spoons, chapatis and other units can be wrong for a specific food.

Voice dictation uses `streamlit-mic-recorder` and browser microphone support. Review the transcript before calculating. If no quantity is spoken, the app assumes a generic serving and flags the portion as estimated.

## API
FatSecret uses OAuth 2.0 client-credentials authentication. The app requests an access token from `https://oauth.fatsecret.com/connect/token` and calls the platform REST endpoint for `foods.search` and `food.get.v5`.
- Official guide: https://platform.fatsecret.com/docs/guides/authentication/oauth2
- API overview: https://platform.fatsecret.com/docs/guides

Whether particular food fields/methods are available depends on the FatSecret account plan and API permissions. Some errors may indicate scope/plan access or IP restriction problems.

## Goal estimate and medical caution
The app estimates BMR with Mifflin–St Jeor, multiplies by an activity factor, and applies the selected calorie adjustment. The time-to-goal is a rough projection capped at 0.5 kg/week; actual weight change is nonlinear. It is not a medical recommendation or deadline. Historical reports are not automatically treated as current instructions. Confirm targets with a qualified clinician/dietitian, especially if following a medically supervised plan.

## Data and privacy
Logs persist in `funvi_diet.db` on the computer/server running Streamlit but do not automatically sync across devices. This prototype has no login or encryption. Before public deployment, add authentication, access controls, secure hosting, persistent storage and backups. Keep the database private.
