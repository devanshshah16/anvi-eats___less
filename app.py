import streamlit as st
import pandas as pd
import sqlite3
import requests
import os, re, math
from pathlib import Path
from datetime import date, datetime, timedelta

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "funvi_diet.db"
MEALS_PATH = APP_DIR / "meals.csv"
FATSECRET_TOKEN_URL = "https://oauth.fatsecret.com/connect/token"
FATSECRET_API_URL = "https://platform.fatsecret.com/rest/server.api"

st.set_page_config(page_title="AnviEats (...less)", page_icon="🥑", layout="wide", initial_sidebar_state="expanded")

# ---------- Persistence ----------
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS profile (
            id INTEGER PRIMARY KEY CHECK(id=1), age INTEGER, height_cm REAL,
            goal_weight REAL, activity TEXT, sex TEXT DEFAULT 'female',
            goal_rate TEXT DEFAULT 'moderate', created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT, log_date TEXT NOT NULL, weight REAL NOT NULL,
            note TEXT DEFAULT '', created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS food_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, log_date TEXT NOT NULL, log_time TEXT,
            meal_type TEXT, food_name TEXT NOT NULL, servings REAL NOT NULL DEFAULT 1,
            calories REAL NOT NULL, protein REAL DEFAULT 0, carbs REAL DEFAULT 0,
            fat REAL DEFAULT 0, notes TEXT DEFAULT '', created_at TEXT
        );
        """)
        if not c.execute("SELECT id FROM profile WHERE id=1").fetchone():
            c.execute("INSERT INTO profile(id, age, height_cm, goal_weight, activity, sex, goal_rate, created_at) VALUES(1, NULL, NULL, NULL, 'light', 'female', 'moderate', ?)", (datetime.now().isoformat(),))

def get_profile():
    with db() as c:
        return dict(c.execute("SELECT * FROM profile WHERE id=1").fetchone())

def save_profile(age, height, goal, activity, rate):
    with db() as c:
        c.execute("UPDATE profile SET age=?, height_cm=?, goal_weight=?, activity=?, goal_rate=? WHERE id=1",
                  (age, height, goal, activity, rate))

def calories_target(profile, current_weight):
    if not profile.get("age") or not profile.get("height_cm") or not current_weight:
        return None, None, None
    bmr = 10 * float(current_weight) + 6.25 * float(profile["height_cm"]) - 5 * int(profile["age"]) - 161
    factors = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "very active": 1.725}
    tdee = bmr * factors.get(profile["activity"], 1.375)
    deficits = {"gentle": 250, "moderate": 350, "faster": 500, "maintenance": 0}
    target = max(1200, round(tdee - deficits.get(profile["goal_rate"], 350)))
    return round(bmr), round(tdee), target

def get_fatsecret_credentials():
    try:
        client_id = st.secrets.get("FATSECRET_CLIENT_ID", os.getenv("FATSECRET_CLIENT_ID", ""))
        client_secret = st.secrets.get("FATSECRET_CLIENT_SECRET", os.getenv("FATSECRET_CLIENT_SECRET", ""))
        return client_id, client_secret
    except Exception:
        return os.getenv("FATSECRET_CLIENT_ID", ""), os.getenv("FATSECRET_CLIENT_SECRET", "")

@st.cache_data(ttl=82800, show_spinner=False)
def fatsecret_access_token(client_id, client_secret):
    """Get a FatSecret OAuth2 client-credentials token; credentials remain in secrets."""
    response = requests.post(
        FATSECRET_TOKEN_URL,
        data={"grant_type": "client_credentials", "scope": "basic"},
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    if "access_token" not in payload:
        raise RuntimeError("FatSecret did not return an access token. Check the credentials and API account settings.")
    return payload["access_token"]

def fatsecret_call(token, method, **params):
    data = {"method": method, "format": "json", **params}
    response = requests.post(
        FATSECRET_API_URL,
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
        timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(str(payload["error"]))
    return payload

def nutrition_for_query(query, token):
    """Search FatSecret and fetch serving-level nutrition for the best initial match."""
    payload = fatsecret_call(token, "foods.search", search_expression=query, max_results=5)
    foods_block = payload.get("foods", {})
    foods = foods_block.get("food", []) if isinstance(foods_block, dict) else []
    if isinstance(foods, dict):
        foods = [foods]
    if not foods:
        raise LookupError(f"No FatSecret match found for “{query}”. Try a simpler food name.")
    selected = foods[0]
    food_id = selected.get("food_id")
    details_payload = fatsecret_call(token, "food.get.v5", food_id=food_id)
    detail = details_payload.get("food", {})
    servings_block = detail.get("servings", {})
    servings = servings_block.get("serving", []) if isinstance(servings_block, dict) else []
    if isinstance(servings, dict):
        servings = [servings]
    # Prefer serving records with metric grams so arbitrary gram quantities can be estimated.
    usable = []
    for serving in servings:
        try:
            amount = float(serving.get("metric_serving_amount", 0) or 0)
            kcal = float(serving.get("calories", 0) or 0)
            if amount > 0 and kcal >= 0:
                usable.append(serving)
        except (TypeError, ValueError):
            pass
    if not usable:
        raise LookupError(f"FatSecret returned no usable serving nutrition for “{query}”.")
    # Prefer 100 g records when available; otherwise normalize the first metric serving to 100 g.
    serving = min(usable, key=lambda x: abs(float(x.get("metric_serving_amount", 0) or 0)-100))
    grams = float(serving.get("metric_serving_amount", 100) or 100)
    factor = 100.0 / grams
    nutrients_100g = {
        "calories": float(serving.get("calories", 0) or 0) * factor,
        "protein": float(serving.get("protein", 0) or 0) * factor,
        "carbs": float(serving.get("carbohydrate", 0) or 0) * factor,
        "fat": float(serving.get("fat", 0) or 0) * factor,
    }
    return {
        "food_id": food_id,
        "description": selected.get("food_name", query),
        "brand": selected.get("brand_name", ""),
        "nutrients_100g": nutrients_100g,
        "servings": usable,
        "alternatives": foods[:5],
        "source_serving": serving,
    }, foods



@st.cache_data(ttl=300, show_spinner=False)
def search_fatsecret_matches(query, token):
    """Cached live search results for the food selector."""
    payload = fatsecret_call(token, "foods.search", search_expression=query, max_results=8)
    block = payload.get("foods", {})
    foods = block.get("food", []) if isinstance(block, dict) else []
    if isinstance(foods, dict):
        foods = [foods]
    matches = []
    for item in foods:
        if item.get("food_id") and item.get("food_name"):
            label = item.get("food_name", "")
            brand = item.get("brand_name", "")
            if brand:
                label += f" ({brand})"
            matches.append({"food_id": str(item["food_id"]), "label": label, "food_name": item.get("food_name", ""), "brand": brand})
    return matches


def nutrition_for_food_id(food_id, token):
    """Fetch detailed nutrition for the exact food selected by the user."""
    payload = fatsecret_call(token, "food.get.v5", food_id=str(food_id))
    detail = payload.get("food", {})
    servings_block = detail.get("servings", {})
    servings = servings_block.get("serving", []) if isinstance(servings_block, dict) else []
    if isinstance(servings, dict):
        servings = [servings]
    usable = []
    for serving in servings:
        try:
            amount = float(serving.get("metric_serving_amount", 0) or 0)
            kcal = float(serving.get("calories", 0) or 0)
            if amount > 0 and kcal >= 0:
                usable.append(serving)
        except (TypeError, ValueError):
            continue
    if not usable:
        raise LookupError("FatSecret did not return usable serving nutrition for this match.")
    serving = min(usable, key=lambda x: abs(float(x.get("metric_serving_amount", 0) or 0) - 100))
    base_grams = float(serving.get("metric_serving_amount", 100) or 100)
    factor = 100.0 / base_grams
    return {
        "food_id": str(food_id),
        "description": detail.get("food_name", "Selected food"),
        "brand": detail.get("brand_name", ""),
        "nutrients_100g": {
            "calories": float(serving.get("calories", 0) or 0) * factor,
            "protein": float(serving.get("protein", 0) or 0) * factor,
            "carbs": float(serving.get("carbohydrate", 0) or 0) * factor,
            "fat": float(serving.get("fat", 0) or 0) * factor,
        },
        "source_serving": serving,
    }

def nutrient_value(food, key):
    return float(food["nutrients_100g"].get(key, 0) or 0)

def parse_quantity_line(line):
    """Parse simple quantity + unit + food phrase; conversions are approximate household weights."""
    s = line.strip().lower()
    if not s:
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?|\d+\s*/\s*\d+|½|¼|¾)\s*(.*?)\s+(.+?)\s*$", s)
    if not m:
        # Allow food only; assume one standard serving, but visibly mark it as an assumption.
        return {"qty": 1.0, "unit": "serving", "food": s, "grams": None, "assumed": True}
    qraw, unitraw, food = m.groups()
    if "/" in qraw:
        a,b = qraw.split("/"); qty = float(a)/float(b)
    else:
        qty = {"½":0.5,"¼":0.25,"¾":0.75}.get(qraw, float(qraw) if qraw not in {"½","¼","¾"} else 1)
    unitraw = unitraw.strip()
    unit_aliases = {"g":"g","gram":"g","grams":"g","kg":"kg","ml":"ml","milliliter":"ml","milliliters":"ml",
                    "l":"l","oz":"oz","ounce":"oz","ounces":"oz","lb":"lb","pound":"lb","pounds":"lb",
                    "cup":"cup","cups":"cup","tbsp":"tbsp","tablespoon":"tbsp","tablespoons":"tbsp",
                    "tsp":"tsp","teaspoon":"tsp","teaspoons":"tsp","piece":"piece","pieces":"piece",
                    "pc":"piece","pcs":"piece","slice":"slice","slices":"slice","banana":"piece","chapati":"piece",
                    "chapatis":"piece","roti":"piece","rotis":"piece","egg":"piece","eggs":"piece","apple":"piece"}
    unit = unit_aliases.get(unitraw, unitraw)
    grams = None
    if unit == "g": grams = qty
    elif unit == "kg": grams = qty * 1000
    elif unit == "oz": grams = qty * 28.3495
    elif unit == "lb": grams = qty * 453.592
    elif unit == "ml": grams = qty # water-density approximation only
    elif unit == "l": grams = qty * 1000
    else:
        # Generic household conversions; recipe/food-specific portions differ considerably.
        generic = {"cup":240, "tbsp":15, "tsp":5, "piece":100, "slice":30, "serving":150}
        grams = qty * generic.get(unit, 150)
    return {"qty":qty, "unit":unit, "food":food, "grams":grams, "assumed":unit not in {"g","kg","oz","lb"}}

def calculate_text_food(text, token):
    results, errors = [], []
    for raw_line in re.split(r"[\n,;]+", text):
        parsed = parse_quantity_line(raw_line)
        if not parsed:
            continue
        try:
            food, choices = nutrition_for_query(parsed["food"], token)
            grams = parsed["grams"] if parsed["grams"] is not None else 150
            nutrients = food["nutrients_100g"]
            results.append({
                "input": raw_line.strip(), "quantity": parsed["qty"], "unit": parsed["unit"], "grams_est": grams,
                "food": food["description"], "fdc_id": food["food_id"],
                "calories": nutrients["calories"]*grams/100, "protein": nutrients["protein"]*grams/100,
                "carbs": nutrients["carbs"]*grams/100, "fat": nutrients["fat"]*grams/100,
                "assumed": parsed["assumed"], "basis": f"{food['description']} · approx. {grams:.0f} g",
                "alternatives": [x.get("food_name","") + (f" ({x.get('brand_name')})" if x.get("brand_name") else "") for x in choices[:5]],
                "source_serving": food["source_serving"]
            })
        except Exception as e:
            errors.append(f"{raw_line.strip()}: {e}")
    return results, errors

def load_meals():
    if MEALS_PATH.exists():
        return pd.read_csv(MEALS_PATH).fillna("")
    return pd.DataFrame(columns=["name","category","meal_type","calories","protein","carbs","fat","ingredients","method","source","tags"])

init_db()
profile = get_profile()
meals = load_meals()
fatsecret_client_id, fatsecret_client_secret = get_fatsecret_credentials()
fatsecret_token = ""
fatsecret_error = ""
if fatsecret_client_id and fatsecret_client_secret:
    try:
        fatsecret_token = fatsecret_access_token(fatsecret_client_id, fatsecret_client_secret)
    except Exception as exc:
        fatsecret_error = str(exc)

# ---------- Visual style ----------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Nunito+Sans:wght@400;600;700;800;900&display=swap');
.block-container {padding-top:2rem !important; max-width:1400px;}
[data-testid="stAppViewContainer"] {background:#fbfaf7;}
[data-testid="stSidebar"] {background:#f0f3eb;}
.brand-wrap {width:100%; box-sizing:border-box; padding:0.25rem 0 0.15rem; margin:0 0 0.25rem; overflow:visible;}
.brand {font-family:'Nunito Sans',sans-serif;font-weight:900;letter-spacing:-1.8px;color:#087f45;font-size:clamp(2.1rem, 5vw, 3.5rem);line-height:1.12; white-space:normal; overflow-wrap:anywhere; margin:0;}
.brand span {display:inline-block; color:#202820;font-weight:800;font-size:clamp(1.2rem, 2.8vw, 1.7rem);letter-spacing:-.5px; white-space:nowrap; vertical-align:baseline; margin-left:.12em;}
.tagline {color:#647064;font-size:1rem;line-height:1.4;margin-top:.45rem;margin-bottom:1.2rem;}
div[data-testid="stMetric"] {background:#fff;border:1px solid #e7e9e2;padding:14px 16px;border-radius:14px;}
.stTabs [data-baseweb="tab-list"] {gap:8px;}
.stTabs [data-baseweb="tab"] {border-radius:10px 10px 0 0;padding:10px 14px;background:#f0f3eb;}
div.stButton > button {border-radius:12px;}
@media (max-width: 600px) {
  .block-container {padding-top:1.4rem !important;}
  .brand {letter-spacing:-1px; font-size:2.1rem;}
  .brand span {font-size:1.15rem; display:block; margin-left:0; margin-top:.1rem;}
}
</style>
""", unsafe_allow_html=True)
st.markdown('<div class="brand-wrap"><div class="brand">AnviEats <span>(...less)</span></div></div><div class="tagline">Eat well. Log less. Feel good.</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Your plan")
    with st.form("profile_form"):
        age = st.number_input("Age", min_value=18, max_value=100, value=int(profile["age"] or 26))
        height = st.number_input("Height (cm)", min_value=120.0, max_value=220.0, value=float(profile["height_cm"] or 165), step=0.5)
        goal_weight = st.number_input("Goal weight (kg)", min_value=30.0, max_value=250.0, value=float(profile["goal_weight"] or 60), step=0.5)
        activity = st.selectbox("Usual activity", ["sedentary","light","moderate","very active"], index=["sedentary","light","moderate","very active"].index(profile["activity"]))
        rate = st.selectbox("Goal approach", ["gentle","moderate","faster","maintenance"], index=["gentle","moderate","faster","maintenance"].index(profile["goal_rate"]))
        saved = st.form_submit_button("Save plan", use_container_width=True)
        if saved:
            save_profile(age, height, goal_weight, activity, rate)
            st.success("Plan saved.")
            st.rerun()
    st.caption("Calorie and timeline figures are estimates, not medical advice.")
    with st.expander("Food database setup"):
        st.write("Nutrition lookups use FatSecret Platform API. Add your Client ID and Client Secret to `.streamlit/secrets.toml` (instructions in README).")
        st.markdown("Documentation: [FatSecret OAuth 2.0](https://platform.fatsecret.com/docs/guides/authentication/oauth2)")
        if fatsecret_token:
            st.success("FatSecret credentials accepted and access token retrieved.")
        elif fatsecret_error:
            st.error("FatSecret authentication failed. Check your credentials and IP restrictions.")
        else:
            st.warning("FatSecret credentials not detected.")

with db() as c:
    weight_df = pd.read_sql_query("SELECT * FROM weights ORDER BY log_date, id", c)
    food_df = pd.read_sql_query("SELECT * FROM food_logs ORDER BY log_date DESC, id DESC", c)

today = date.today().isoformat()
today_food = food_df[food_df["log_date"] == today] if not food_df.empty else pd.DataFrame()
today_cal = float(today_food["calories"].sum()) if not today_food.empty else 0
today_pro = float(today_food["protein"].sum()) if not today_food.empty else 0
current_weight = float(weight_df.iloc[-1]["weight"]) if not weight_df.empty else None
bmr, tdee, target = calories_target(profile, current_weight)

def goal_eta_days(current, goal, profile, tdee, target):
    if current is None or not goal or abs(current-goal) < 0.05:
        return 0 if current is not None and goal and abs(current-goal) < 0.05 else None
    if profile["goal_rate"] == "maintenance" or not tdee or not target:
        return None
    # Estimate weekly change using the intended deficit, capped at 0.5 kg/week for a conservative projection.
    deficit = max(0, tdee-target)
    kg_week = min(0.5, deficit*7/7700)
    if kg_week <= 0: return None
    return math.ceil(abs(current-float(goal))/kg_week*7)

tabs = st.tabs(["🏠 Dashboard", "🍽️ Quick log", "⚖️ Weight", "🍲 Meal library", "📈 History", "⚙️ Settings"])

# ---------- Dashboard ----------
with tabs[0]:
    st.subheader("Today's overview")
    st.caption(date.today().strftime("%A, %d %B %Y"))
    if target:
        remaining = target-today_cal
        a,b,c,d = st.columns(4)
        a.metric("Daily calorie target", f"{target:,} kcal")
        b.metric("Calories eaten", f"{today_cal:,.0f} kcal")
        c.metric("Calories left", f"{max(0,remaining):,.0f} kcal")
        d.metric("Protein logged", f"{today_pro:.1f} g")
        st.progress(min(1.0,today_cal/target))
        st.caption(f"{today_cal/target*100:.0f}% of daily target logged")
    else:
        st.info("Log a weight and complete your profile to calculate a starting calorie estimate.")
        st.metric("Calories eaten today", f"{today_cal:,.0f} kcal")

    if current_weight is not None and profile["goal_weight"]:
        goal = float(profile["goal_weight"])
        delta = current_weight-goal
        eta = goal_eta_days(current_weight, goal, profile, tdee, target)
        st.markdown("### Your weight goal")
        x,y,z = st.columns(3)
        x.metric("Latest weight", f"{current_weight:.1f} kg")
        y.metric("Goal weight", f"{goal:.1f} kg")
        z.metric("Difference", f"{abs(delta):.1f} kg", delta="to lose" if delta>0 else ("to gain" if delta<0 else "goal reached"))
        if eta == 0:
            st.success("You're at your entered goal weight. Weight naturally fluctuates.")
        elif eta is not None:
            st.metric("Estimated time to goal", f"~{eta} days", help="A rough projection from the selected calorie deficit, not a promise. Real weight change is nonlinear.")
            if not weight_df.empty:
                start_weight = float(weight_df.iloc[0]["weight"])
                total_distance = abs(start_weight - goal)
                remaining_distance = abs(current_weight - goal)
                if total_distance > 0:
                    progress = min(1.0, max(0.0, 1 - remaining_distance / total_distance))
                    st.progress(progress)
                    st.caption(f"{progress*100:.0f}% of the distance from your first logged weight to your goal has been covered. This can move up or down with normal fluctuations.")
            st.caption("Timeline updates when your weight or plan changes. Focus on the trend, not a deadline.")
        else:
            st.info("Choose a weight-loss approach (rather than maintenance) and record a weight to estimate a timeline.")
    st.markdown("### Weight trend")
    periods = {"3 days":3, "1 week":7, "2 weeks":14, "1 month":30, "1 year":365}
    period_choice = st.radio("Show", list(periods.keys()), horizontal=True, index=1, key="dashboard_weight_period")
    cutoff = pd.Timestamp(date.today() - timedelta(days=periods[period_choice]-1))
    if not weight_df.empty:
        chart_df = weight_df.copy()
        chart_df["log_date"] = pd.to_datetime(chart_df["log_date"], errors="coerce")
        chart_df = chart_df[chart_df["log_date"] >= cutoff].sort_values(["log_date","id"])
        if not chart_df.empty:
            chart_df = chart_df.groupby("log_date", as_index=False)["weight"].last().set_index("log_date")
            st.line_chart(chart_df["weight"], y_label="Weight (kg)")
        else:
            st.info(f"No weigh-ins in the last {period_choice}. Log a weight to start the chart.")
    else:
        st.info("Your weight chart will appear here after your first weigh-in.")
    st.markdown("### Today's food")
    if today_food.empty:
        st.caption("Nothing logged yet. Use Quick log and just type what you ate.")
    else:
        st.dataframe(today_food[["log_time","meal_type","food_name","calories","protein","carbs","fat"]].rename(columns={"log_time":"Time","meal_type":"Meal","food_name":"Food","calories":"kcal","protein":"Protein (g)","carbs":"Carbs (g)","fat":"Fat (g)"}), hide_index=True, use_container_width=True)

# ---------- Quick log ----------
with tabs[1]:
    st.subheader("Quick log")
    st.write("Search each food, choose the exact FatSecret match from the dropdown, and enter the amount in grams. Search results update as you type.")
    if not fatsecret_token:
        st.warning("Nutrition lookup is not configured yet. Add your FatSecret Client ID and Client Secret in `.streamlit/secrets.toml`; setup instructions are in README.md.")
        if fatsecret_error:
            st.error(f"FatSecret authentication error: {fatsecret_error}")

    log_date = st.date_input("When did you eat it?", value=date.today(), key="quick_log_date")
    log_time = st.time_input("Time", value=datetime.now().time().replace(second=0, microsecond=0), key="quick_log_time")
    meal_type = st.selectbox("Meal", ["Breakfast", "Mid-morning snack", "Lunch", "Afternoon snack", "Dinner", "Drink", "Other"], key="quick_meal_type")

    # Voice input remains optional: transcript can be used to seed food search terms.
    try:
        from streamlit_mic_recorder import speech_to_text
        spoken = speech_to_text(language="en", start_prompt="🎙️ Speak your meal", stop_prompt="⏹️ Stop", just_once=True, use_container_width=True, key="anvi_speech")
        if spoken:
            st.session_state["voice_food_text"] = spoken
            st.info("Voice captured. You can copy individual food names into the rows below and choose the correct database match.")
    except Exception:
        st.caption("Voice input is optional. You can type food names directly below.")

    if "food_row_count" not in st.session_state:
        st.session_state["food_row_count"] = 3
    if "food_rows_data" not in st.session_state:
        st.session_state["food_rows_data"] = {}

    st.markdown("#### Food items")
    st.caption("Enter a food name, select the closest match from FatSecret, then enter the amount. Grams give the most consistent estimates.")
    rows = []
    for i in range(st.session_state["food_row_count"]):
        st.markdown(f"**Food {i + 1}**")
        c_food, c_amount = st.columns([3, 1])
        state = st.session_state["food_rows_data"].get(i, {})
        query = c_food.text_input(
            "Food item",
            value=state.get("query", ""),
            placeholder="e.g., cooked green peas",
            key=f"food_query_{i}",
        )
        amount = c_amount.number_input(
            "Amount (g)",
            min_value=0.0,
            max_value=10000.0,
            value=float(state.get("amount", 100.0)),
            step=10.0,
            key=f"food_amount_{i}",
        )
        selected_id = None
        selected_label = ""
        matches = []
        if fatsecret_token and query.strip() and len(query.strip()) >= 2:
            try:
                matches = search_fatsecret_matches(query.strip(), fatsecret_token)
                if matches:
                    options = [m["food_id"] for m in matches]
                    labels = {m["food_id"]: m["label"] for m in matches}
                    previous = state.get("selected_id")
                    default_index = options.index(previous) if previous in options else 0
                    selected_id = c_food.selectbox(
                        "Choose FatSecret match",
                        options=options,
                        index=default_index,
                        format_func=lambda x, labels=labels: labels.get(x, x),
                        key=f"food_match_{i}",
                    )
                    selected_label = labels.get(selected_id, "")
                else:
                    c_food.caption("No matches found. Try a shorter or more specific food name.")
            except Exception as exc:
                c_food.warning(f"Food search failed: {exc}")
        elif query.strip():
            c_food.caption("Enter at least 2 characters to search." if len(query.strip()) < 2 else "Add FatSecret credentials to search.")
        st.session_state["food_rows_data"][i] = {
            "query": query, "amount": amount, "selected_id": selected_id, "selected_label": selected_label
        }
        rows.append({"index": i, "query": query.strip(), "amount": amount, "food_id": selected_id, "label": selected_label})
        st.divider()

    add_col, remove_col = st.columns(2)
    if add_col.button("＋ Add another food", use_container_width=True):
        st.session_state["food_row_count"] = min(20, st.session_state["food_row_count"] + 1)
        st.rerun()
    if remove_col.button("− Remove last row", use_container_width=True, disabled=st.session_state["food_row_count"] <= 1):
        last = st.session_state["food_row_count"] - 1
        st.session_state["food_row_count"] = max(1, last)
        st.session_state["food_rows_data"].pop(last, None)
        st.rerun()

    calculate = st.button(
        "Calculate calories",
        type="primary",
        use_container_width=True,
        disabled=not bool(fatsecret_token) or not any(r["food_id"] and r["amount"] > 0 for r in rows),
    )
    if calculate:
        results, errors = [], []
        with st.spinner("Retrieving nutrition for selected foods…"):
            for row in rows:
                if not row["query"].strip():
                    continue
                if not row["food_id"]:
                    errors.append(f"{row['query']}: choose a food from the FatSecret match dropdown.")
                    continue
                if row["amount"] <= 0:
                    errors.append(f"{row['query']}: enter an amount greater than zero.")
                    continue
                try:
                    food = nutrition_for_food_id(row["food_id"], fatsecret_token)
                    nutrients = food["nutrients_100g"]
                    grams = float(row["amount"])
                    results.append({
                        "input": f"{grams:g} g {row['query']}",
                        "quantity": grams,
                        "unit": "g",
                        "grams_est": grams,
                        "food": food["description"],
                        "fdc_id": food["food_id"],
                        "calories": nutrients["calories"] * grams / 100,
                        "protein": nutrients["protein"] * grams / 100,
                        "carbs": nutrients["carbs"] * grams / 100,
                        "fat": nutrients["fat"] * grams / 100,
                        "assumed": False,
                        "basis": f"{food['description']} · {grams:.0f} g",
                        "alternatives": [m["label"] for m in search_fatsecret_matches(row["query"], fatsecret_token)[:8]],
                        "source_serving": food["source_serving"],
                    })
                except Exception as exc:
                    errors.append(f"{row['query']}: {exc}")
        st.session_state["nutrition_results"] = results
        st.session_state["nutrition_errors"] = errors

    results = st.session_state.get("nutrition_results", [])
    errors = st.session_state.get("nutrition_errors", [])
    if results:
        st.markdown("#### Nutrition estimate")
        result_df = pd.DataFrame(results)
        view = result_df[["input", "food", "grams_est", "calories", "protein", "carbs", "fat"]].copy()
        view.columns = ["Amount entered", "Selected food match", "Amount (g)", "kcal", "Protein (g)", "Carbs (g)", "Fat (g)"]
        for col in ["kcal", "Protein (g)", "Carbs (g)", "Fat (g)"]:
            view[col] = view[col].astype(float).round(1)
        st.dataframe(view, hide_index=True, use_container_width=True)
        total_kcal = sum(r["calories"] for r in results)
        total_pro = sum(r["protein"] for r in results)
        total_carb = sum(r["carbs"] for r in results)
        total_fat = sum(r["fat"] for r in results)
        a, b, c, d = st.columns(4)
        a.metric("Meal calories", f"{total_kcal:.0f} kcal")
        b.metric("Protein", f"{total_pro:.1f} g")
        c.metric("Carbs", f"{total_carb:.1f} g")
        d.metric("Fat", f"{total_fat:.1f} g")
        for r in results:
            with st.expander(f"Nutrition details: {r['input']}"):
                st.write(f"Selected database item: **{r['food']}** (FatSecret food ID: {r['fdc_id']})")
                serving = r.get("source_serving", {})
                st.caption(f"Nutrition normalized from FatSecret serving: {serving.get('serving_description', '')} ({serving.get('metric_serving_amount', '?')} {serving.get('metric_serving_unit', '')}).")
        if st.button("Save this meal to today's log", type="primary", use_container_width=True):
            name = " + ".join(f"{r['grams_est']:g} g {r['food']}" for r in results)
            with db() as conn:
                conn.execute(
                    """INSERT INTO food_logs(log_date,log_time,meal_type,food_name,servings,calories,protein,carbs,fat,notes,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (log_date.isoformat(), log_time.strftime("%H:%M"), meal_type, name, 1, total_kcal, total_pro, total_carb, total_fat, "FatSecret nutrition estimate; amounts entered in grams.", datetime.now().isoformat()),
                )
            st.session_state["nutrition_results"] = []
            st.session_state["nutrition_errors"] = []
            st.success("Meal saved.")
            st.rerun()
    if errors:
        st.warning("Some items could not be calculated:")
        for error in errors:
            st.write("• " + error)
    st.caption("Nutrition is an estimate. Review the selected food match before saving; database entries can differ by preparation and brand.")

# ---------- Weight ----------
with tabs[2]:
    st.subheader("Weight tracker")
    with st.form("weight_form", clear_on_submit=True):
        wd = st.date_input("Weigh-in date", value=date.today())
        ww = st.number_input("Weight (kg)", min_value=25.0, max_value=300.0, value=float(current_weight or 60), step=0.1)
        wn = st.text_input("Note (optional)", placeholder="e.g., morning, before breakfast")
        add_weight = st.form_submit_button("Save weight", use_container_width=True)
        if add_weight:
            with db() as conn:
                conn.execute("INSERT INTO weights(log_date,weight,note,created_at) VALUES(?,?,?,?)",(wd.isoformat(),ww,wn,datetime.now().isoformat()))
            st.success("Weight saved."); st.rerun()
    if not weight_df.empty:
        plot = weight_df.copy()
        plot["log_date"] = pd.to_datetime(plot["log_date"])
        plot = plot.groupby("log_date", as_index=False)["weight"].last().set_index("log_date")
        st.line_chart(plot["weight"], y_label="Weight (kg)")
        st.dataframe(weight_df.sort_values(["log_date","id"],ascending=False)[["log_date","weight","note"]],hide_index=True,use_container_width=True)
        st.download_button("Export weight CSV",weight_df.to_csv(index=False).encode(),file_name="weight_log.csv",mime="text/csv")
    else: st.info("Your weigh-ins will appear here.")

# ---------- Meal library ----------
with tabs[3]:
    st.subheader("Meal inspiration")
    st.write("Browse saved meal ideas. Values from older plans are historical; added recipes have estimated nutrition.")
    if not meals.empty:
        c1,c2 = st.columns([2,1])
        search = c1.text_input("Search meals or ingredients")
        categories = ["All"] + sorted([str(x) for x in meals["category"].unique() if str(x)])
        category = c2.selectbox("Category",categories)
        view = meals.copy()
        if category != "All": view = view[view["category"]==category]
        if search:
            mask = view.astype(str).apply(lambda col: col.str.contains(search,case=False,na=False)).any(axis=1)
            view=view[mask]
        for _,r in view.iterrows():
            with st.expander(f"{r['name']} · {r['calories']} kcal / serving"):
                st.markdown(f"**Macros (estimate):** Protein {r['protein']} g · Carbs {r['carbs']} g · Fat {r['fat']} g")
                st.markdown(f"**Ingredients:** {r['ingredients']}")
                st.markdown(f"**Method:** {r['method']}")
                st.caption(f"Source: {r['source']} | Tags: {r['tags']}")
                if st.button("Log this meal",key=f"library_{r['name']}"):
                    with db() as conn:
                        conn.execute("""INSERT INTO food_logs(log_date,log_time,meal_type,food_name,servings,calories,protein,carbs,fat,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (today,datetime.now().strftime("%H:%M"),str(r["meal_type"]),str(r["name"]),1,float(r["calories"] or 0),float(r["protein"] or 0),float(r["carbs"] or 0),float(r["fat"] or 0),"Meal library estimate.",datetime.now().isoformat()))
                    st.rerun()
        st.download_button("Download meal library CSV",data=meals.to_csv(index=False).encode(),file_name="meals.csv",mime="text/csv")

# ---------- History ----------
with tabs[4]:
    st.subheader("History")
    if not food_df.empty:
        ff=food_df.copy(); ff["log_date"]=pd.to_datetime(ff["log_date"])
        daily=ff.groupby("log_date",as_index=False).agg(calories=("calories","sum"),protein=("protein","sum"),carbs=("carbs","sum"),fat=("fat","sum"),meals=("id","count"))
        st.markdown("### Daily nutrition")
        st.line_chart(daily.set_index("log_date")[["calories"]],y_label="kcal")
        st.dataframe(daily.sort_values("log_date",ascending=False).round(1),hide_index=True,use_container_width=True)
        st.download_button("Export food CSV",food_df.to_csv(index=False).encode(),file_name="food_log.csv",mime="text/csv")
    else: st.info("Meal history will appear as you log food.")
    if not weight_df.empty:
        st.markdown("### Weight history")
        st.dataframe(weight_df.sort_values(["log_date","id"],ascending=False),hide_index=True,use_container_width=True)
    st.caption("Use trends over weeks, not a single weigh-in, to understand progress.")

# ---------- Settings ----------
with tabs[5]:
    st.subheader("Settings & how it works")
    st.markdown("""
### Calorie target
BMR is estimated using the Mifflin–St Jeor equation for women, multiplied by an activity factor to estimate daily energy expenditure. The selected goal approach subtracts 250, 350 or 500 kcal/day, or zero for maintenance. The app has a 1,200 kcal/day lower guardrail, but that is not a guarantee this intake is appropriate for any individual.

### Estimated days to goal
The app uses the current weight, goal weight and selected calorie deficit to provide a rough timeline. It assumes a simplified rate of change and caps the projection at 0.5 kg/week. Actual weight change is nonlinear and can differ significantly; the date is a planning estimate, not a deadline.

### Food estimates
Food lookups use the **FatSecret Platform API**. It supports food search and food-detail endpoints with serving-level nutrition. It does not contain every food in the world or every regional/home-cooked recipe. Nutrition values are estimates, and household measures are approximate. Grams and specific product labels are more reliable.

### Data & privacy
Meals and weight entries are stored in `funvi_diet.db` beside `app.py`. This local version does not sync across devices and has no login. Before deploying publicly, add authentication, secure secrets, and persistent storage.
""")
    st.markdown("**API reference:** [FatSecret OAuth 2.0 guide](https://platform.fatsecret.com/docs/guides/authentication/oauth2) · [FatSecret platform resources](https://platform.fatsecret.com/docs/guides)")
    if st.button("Delete ALL meal and weight logs"):
        st.session_state["confirm_wipe"] = True
    if st.session_state.get("confirm_wipe"):
        st.error("This permanently deletes all food and weight history.")
        if st.button("Confirm permanent deletion"):
            with db() as conn:
                conn.execute("DELETE FROM food_logs"); conn.execute("DELETE FROM weights")
            st.session_state["confirm_wipe"] = False; st.rerun()
