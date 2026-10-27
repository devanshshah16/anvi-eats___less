# Anvi Diet & Weight Tracker

A Streamlit starter app for food logging, weight tracking, a recipe library, and historical exports.

## Files
- `app.py` — Streamlit app and SQLite persistence.
- `meals.csv` — editable starter meal/recipe library. Includes some meals and macro values transcribed from Anvi's 25-Apr-2024 diet guide and the pattice recipe PDF, plus clearly labelled rough-estimate recipe ideas.
- `requirements.txt` — Python dependencies.
- `funvi_diet.db` — created automatically on first run; stores profile, weight logs and food logs. Back it up regularly.

## Run locally
1. Install Python 3.10+.
2. Unzip this folder to a location you can find.
3. Open Terminal (Mac) or Command Prompt/PowerShell (Windows) and change directory into this folder.
4. Create and activate a virtual environment (recommended):
   - Mac/Linux: `python3 -m venv .venv` then `source .venv/bin/activate`
   - Windows: `py -m venv .venv` then `.venv\\Scripts\\activate`
5. Install dependencies: `pip install -r requirements.txt`
6. Start the app: `streamlit run app.py`
7. A browser tab should open. The app runs locally; keep the terminal window open while using it.

## How the calorie estimate works
The app estimates BMR with the Mifflin–St Jeor equation for women, multiplies by an activity factor to estimate TDEE, then subtracts a selected 250, 350 or 500 kcal/day deficit (or zero for maintenance). The app has a 1,200 kcal/day lower guardrail, but this is not a medical recommendation and 1,200 kcal is not necessarily appropriate for an individual. Current weight comes from the most recently recorded weigh-in. It is an estimate, not a prescription.

**Important:** the older PDFs contain historical clinician/dietitian plans with different dates and targets. The app does not automatically treat their old target weights or calorie totals as current instructions. One historical report shows a very low daily calorie figure; do not reuse that figure as a new target without confirmation from a qualified clinician/dietitian. For PCOS, high cholesterol, medication, pregnancy/breastfeeding, symptoms, or any medically supervised plan, have the target and nutrition approach reviewed by her clinician/dietitian.

## Logging and data
- Data is stored in `funvi_diet.db` on the machine running Streamlit.
- Logs persist when the app is restarted on that machine.
- It does not sync between devices automatically. To use on a phone and laptop, deploy with a durable database/storage layer and authentication. Do not assume the local filesystem on a free cloud host is permanent.
- Use the History tab to export food and weight logs as CSV. Keep backups of the database and CSV exports.
- `meals.csv` can be edited in Excel/Google Sheets. Nutrition values are estimates and depend on ingredients, brands, preparation, and portions.

## Suggested next improvements
- Add password/login and per-user data isolation before sharing online.
- Add a weekly average weight chart, fibre and micronutrient tracking, recipe serving-size calculator, meal planner, reminders, and database backups.
- For more accurate nutrition, calculate recipes from weighed ingredients using a trusted nutrition database or package labels, then update `meals.csv`.

## Privacy
This app is a prototype and has no login or encryption layer. Do not deploy it publicly with identifiable health information until authentication, access controls, secure hosting and backup are added.
