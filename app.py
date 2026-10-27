import streamlit as st
import pandas as pd
import sqlite3
from pathlib import Path
from datetime import date, datetime
import math

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "funvi_diet.db"
MEALS_PATH = APP_DIR / "meals.csv"

st.set_page_config(page_title="Funvi | Food & Fitness", page_icon="🥑", layout="wide", initial_sidebar_state="expanded")

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
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, start_date TEXT, calorie_override INTEGER,
            notes TEXT DEFAULT ''
        );
        """)
        if not c.execute("SELECT id FROM profile WHERE id=1").fetchone():
            c.execute("INSERT INTO profile(id, age, height_cm, goal_weight, activity, sex, goal_rate, created_at) VALUES(1, NULL, NULL, NULL, 'light', 'female', 'moderate', ?)", (datetime.now().isoformat(),))

def get_profile():
    with db() as c:
        return dict(c.execute("SELECT * FROM profile WHERE id=1").fetchone())

def save_profile(age, height, goal, activity, rate):
    with db() as c:
        c.execute("""UPDATE profile SET age=?, height_cm=?, goal_weight=?, activity=?, goal_rate=? WHERE id=1""",
                  (age, height, goal, activity, rate))

def get_logs(table, start=None, end=None):
    with db() as c:
        q = f"SELECT * FROM {table}"
        args = []
        if start and end:
            q += " WHERE log_date BETWEEN ? AND ?"
            args = [str(start), str(end)]
        q += " ORDER BY log_date DESC, id DESC"
        return pd.read_sql_query(q, c, params=args)

def calories_target(profile, current_weight):
    """Mifflin-St Jeor estimate + activity multiplier + optional modest deficit."""
    if not profile.get("age") or not profile.get("height_cm") or not current_weight:
        return None, None, None
    # Female equation; profile is intentionally designed for Anvi's use.
    bmr = 10 * float(current_weight) + 6.25 * float(profile["height_cm"]) - 5 * int(profile["age"]) - 161
    factors = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "very active": 1.725}
    tdee = bmr * factors.get(profile["activity"], 1.375)
    deficits = {"gentle": 250, "moderate": 350, "faster": 500, "maintenance": 0}
    # Safety guardrail: never automatically prescribe below 1,200 kcal/day.
    target = max(1200, round(tdee - deficits.get(profile["goal_rate"], 350)))
    return round(bmr), round(tdee), target

def load_meals():
    if MEALS_PATH.exists():
        return pd.read_csv(MEALS_PATH).fillna("")
    return pd.DataFrame(columns=["name","category","meal_type","calories","protein","carbs","fat","ingredients","method","source","tags"])

init_db()
profile = get_profile()
meals = load_meals()

# ---------- Style ----------
st.markdown("""
<style>
:root { color-scheme: light; }
.block-container {padding-top: 1.4rem; max-width: 1400px;}
[data-testid="stAppViewContainer"] {background: #fbfaf7;}
[data-testid="stSidebar"] {background: #f0f3eb;}
.hero {padding: 1.2rem 1.5rem; border-radius: 18px; background: linear-gradient(120deg,#e8f0df,#f7eee4); margin-bottom:1rem;}
.hero h1 {margin:0; color:#243b2c; font-size:2rem;}
.hero p {margin:.35rem 0 0; color:#526455;}
.small-muted {color:#65736a; font-size:.88rem;}
div[data-testid="stMetric"] {background:#fff; border:1px solid #e7e9e2; padding:14px 16px; border-radius:14px;}
.stTabs [data-baseweb="tab-list"] {gap:8px;}
.stTabs [data-baseweb="tab"] {border-radius:10px 10px 0 0; padding:10px 16px; background:#f0f3eb;}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="hero"><h1>🥑 Funvi</h1><p>A calm, simple space to log meals, understand nutrition, and follow progress — one day at a time.</p></div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Your plan")
    st.caption("Set up or update your estimates.")
    with st.form("profile_form"):
        age = st.number_input("Age", min_value=18, max_value=100, value=int(profile["age"] or 26))
        height = st.number_input("Height (cm)", min_value=120.0, max_value=220.0, value=float(profile["height_cm"] or 165), step=0.5)
        goal_weight = st.number_input("Goal weight (kg)", min_value=30.0, max_value=250.0, value=float(profile["goal_weight"] or 60), step=0.5)
        activity = st.selectbox("Usual activity", ["sedentary","light","moderate","very active"],
                                index=["sedentary","light","moderate","very active"].index(profile["activity"]))
        rate = st.selectbox("Goal approach", ["gentle","moderate","faster","maintenance"],
                            index=["gentle","moderate","faster","maintenance"].index(profile["goal_rate"]))
        saved = st.form_submit_button("Save plan", use_container_width=True)
        if saved:
            save_profile(age, height, goal_weight, activity, rate)
            st.success("Plan saved.")
            st.rerun()
    st.caption("Estimates are not medical advice. If pregnant, breastfeeding, under medical care, or managing a condition, confirm targets with a qualified clinician/dietitian.")

# Get data
with db() as c:
    weight_df = pd.read_sql_query("SELECT * FROM weights ORDER BY log_date, id", c)
    food_df = pd.read_sql_query("SELECT * FROM food_logs ORDER BY log_date DESC, id DESC", c)

today = date.today().isoformat()
today_food = food_df[food_df["log_date"] == today] if not food_df.empty else pd.DataFrame()
today_cal = float(today_food["calories"].sum()) if not today_food.empty else 0
today_pro = float(today_food["protein"].sum()) if not today_food.empty else 0
today_carbs = float(today_food["carbs"].sum()) if not today_food.empty else 0
today_fat = float(today_food["fat"].sum()) if not today_food.empty else 0
current_weight = float(weight_df.iloc[-1]["weight"]) if not weight_df.empty else None
bmr, tdee, target = calories_target(profile, current_weight)

tabs = st.tabs(["🏠 Dashboard", "➕ Log a meal", "⚖️ Weight", "🍲 Meal library", "📈 History & insights", "⚙️ Settings"])

# ---------- Dashboard ----------
with tabs[0]:
    st.subheader("Today's overview")
    st.caption(date.today().strftime("%A, %d %B %Y"))
    if not profile["age"] or not profile["height_cm"] or not profile["goal_weight"]:
        st.info("Add your age, height and goal weight in the sidebar to calculate a starting calorie estimate.")
    if current_weight is None:
        st.info("Log your first weight in the Weight tab to personalise your calorie estimate.")
    if target:
        remaining = target - today_cal
        a,b,c,d = st.columns(4)
        a.metric("Daily calorie target", f"{target:,} kcal")
        b.metric("Calories eaten", f"{today_cal:,.0f} kcal")
        c.metric("Calories remaining", f"{max(0, remaining):,.0f} kcal", delta=f"{remaining:,.0f} kcal to target" if remaining < 0 else None)
        d.metric("Protein so far", f"{today_pro:.1f} g")
        st.progress(min(1.0, today_cal / target) if target else 0)
        st.caption(f"{today_cal/target*100:.0f}% of estimated calorie target logged" if target else "")
        if today_cal > target:
            st.warning("You're above today's estimate. This is just information, not a reason to skip meals or compensate tomorrow.")
        elif remaining <= 200:
            st.success("You're close to today's estimated target. Check hunger, energy and your clinician's guidance too.")
    else:
        a,b,c = st.columns(3)
        a.metric("Calories eaten", f"{today_cal:,.0f} kcal")
        b.metric("Protein so far", f"{today_pro:.1f} g")
        c.metric("Meals logged", len(today_food))
    if current_weight is not None and profile["goal_weight"]:
        diff = current_weight - float(profile["goal_weight"])
        st.markdown("### Weight goal")
        x,y,z = st.columns(3)
        x.metric("Latest weight", f"{current_weight:.1f} kg")
        y.metric("Goal weight", f"{float(profile['goal_weight']):.1f} kg")
        y2 = abs(diff)
        z.metric("Difference to goal", f"{y2:.1f} kg", delta="to lose" if diff > 0 else ("to gain" if diff < 0 else "goal reached"))
        if not weight_df.empty:
            start_w = float(weight_df.iloc[0]["weight"])
            st.caption(f"Change since first log: {current_weight-start_w:+.1f} kg. Day-to-day changes often reflect water, digestion and menstrual cycle; focus on trends over several weeks.")
    st.markdown("### Today's food log")
    if today_food.empty:
        st.write("Nothing logged yet. Add a meal whenever you eat.")
    else:
        show = today_food[["log_time","meal_type","food_name","servings","calories","protein","carbs","fat"]].copy()
        show.columns = ["Time","Meal","Food","Servings","kcal","Protein (g)","Carbs (g)","Fat (g)"]
        st.dataframe(show, hide_index=True, use_container_width=True)

# ---------- Meal log ----------
with tabs[1]:
    st.subheader("Log food")
    st.write("Log packaged foods, homemade meals, snacks, or a recipe from the library. Use nutrition labels or a trusted food database when possible.")
    meal_date = st.date_input("Date", value=date.today(), key="log_date")
    meal_time = st.time_input("Time", value=datetime.now().time().replace(second=0, microsecond=0))
    meal_type = st.selectbox("Meal type", ["Breakfast","Mid-morning","Lunch","Afternoon snack","Dinner","Drink","Other"])
    options = ["Enter food manually"] + (meals["name"].astype(str).tolist() if not meals.empty else [])
    selected = st.selectbox("Food / recipe", options)
    selected_row = None
    if selected != "Enter food manually" and not meals.empty:
        rows = meals[meals["name"] == selected]
        if not rows.empty: selected_row = rows.iloc[0]
    if selected_row is not None:
        st.info(f"Library estimate: {selected_row['calories']} kcal · Protein {selected_row['protein']} g · Carbs {selected_row['carbs']} g · Fat {selected_row['fat']} g per serving. Recipe values vary with ingredients and portions.")
    with st.form("food_form", clear_on_submit=True):
        food_name = st.text_input("Food name", value="" if selected_row is None else str(selected_row["name"]))
        servings = st.number_input("Servings / portions", min_value=0.1, max_value=20.0, value=1.0, step=0.5)
        default_cal = float(selected_row["calories"]) if selected_row is not None and str(selected_row["calories"]) else 0.0
        default_pro = float(selected_row["protein"]) if selected_row is not None and str(selected_row["protein"]) else 0.0
        default_carb = float(selected_row["carbs"]) if selected_row is not None and str(selected_row["carbs"]) else 0.0
        default_fat = float(selected_row["fat"]) if selected_row is not None and str(selected_row["fat"]) else 0.0
        c1,c2 = st.columns(2)
        cal = c1.number_input("Calories per serving (kcal)", min_value=0.0, max_value=5000.0, value=default_cal, step=5.0)
        protein = c2.number_input("Protein per serving (g)", min_value=0.0, max_value=300.0, value=default_pro, step=1.0)
        c3,c4 = st.columns(2)
        carbs = c3.number_input("Carbs per serving (g)", min_value=0.0, max_value=500.0, value=default_carb, step=1.0)
        fat = c4.number_input("Fat per serving (g)", min_value=0.0, max_value=300.0, value=default_fat, step=1.0)
        notes = st.text_input("Notes (optional)", placeholder="e.g., homemade, less oil, half portion")
        submit = st.form_submit_button("Save meal", use_container_width=True)
        if submit:
            if not food_name.strip():
                st.error("Please enter a food name.")
            else:
                with db() as conn:
                    conn.execute("""INSERT INTO food_logs(log_date,log_time,meal_type,food_name,servings,calories,protein,carbs,fat,notes,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (meal_date.isoformat(), meal_time.strftime("%H:%M"), meal_type, food_name.strip(), servings,
                     cal*servings, protein*servings, carbs*servings, fat*servings, notes, datetime.now().isoformat()))
                st.success("Meal saved to your local history.")
                st.rerun()
    st.caption("Nutrition values entered above are per serving; the app multiplies them by the number of servings.")

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
                conn.execute("INSERT INTO weights(log_date,weight,note,created_at) VALUES(?,?,?,?)",
                             (wd.isoformat(), ww, wn, datetime.now().isoformat()))
            st.success("Weight saved.")
            st.rerun()
    if not weight_df.empty:
        st.markdown("### Weight trend")
        plot = weight_df.copy()
        plot["log_date"] = pd.to_datetime(plot["log_date"])
        plot = plot.groupby("log_date", as_index=False)["weight"].last().set_index("log_date")
        st.line_chart(plot["weight"], y_label="Weight (kg)")
        st.dataframe(weight_df.sort_values(["log_date","id"], ascending=False)[["log_date","weight","note"]], hide_index=True, use_container_width=True)
        if st.button("Delete selected weight entry…"):
            st.session_state["show_delete_weight"] = True
        if st.session_state.get("show_delete_weight"):
            ids = weight_df.sort_values(["log_date","id"], ascending=False)
            labels = {f"{r['log_date']} · {r['weight']} kg · ID {r['id']}": int(r["id"]) for _,r in ids.iterrows()}
            chosen = st.selectbox("Choose entry", list(labels.keys()), key="delete_weight_choice")
            if st.button("Confirm delete weight"):
                with db() as conn: conn.execute("DELETE FROM weights WHERE id=?", (labels[chosen],))
                st.session_state["show_delete_weight"] = False
                st.rerun()
    else:
        st.info("Your weigh-ins will appear here as a trend over time.")

# ---------- Meal library ----------
with tabs[3]:
    st.subheader("Meal inspiration")
    st.write("A searchable starting library based on foods and combinations appearing in the supplied diet guides, plus vegetarian recipe ideas. The older reports contain different plans; these are not assumed to be current medical instructions.")
    if meals.empty:
        st.warning("meals.csv is missing or empty. Restore it from the app folder.")
    else:
        c1,c2 = st.columns([2,1])
        search = c1.text_input("Search meals or ingredients")
        cats = ["All"] + sorted([str(x) for x in meals["category"].unique() if str(x)])
        category = c2.selectbox("Category", cats)
        view = meals.copy()
        if category != "All": view = view[view["category"] == category]
        if search:
            mask = view.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
            view = view[mask]
        st.caption(f"{len(view)} meal ideas")
        for _,r in view.iterrows():
            with st.expander(f"{r['name']} · {r['calories']} kcal / serving"):
                st.markdown(f"**Macros (estimate):** Protein {r['protein']} g · Carbs {r['carbs']} g · Fat {r['fat']} g")
                st.markdown(f"**Ingredients:** {r['ingredients']}")
                st.markdown(f"**Method:** {r['method']}")
                st.caption(f"Source: {r['source']} | Tags: {r['tags']}")
                if st.button("Log this meal", key=f"log_{r['name']}"):
                    with db() as conn:
                        conn.execute("""INSERT INTO food_logs(log_date,log_time,meal_type,food_name,servings,calories,protein,carbs,fat,notes,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (today, datetime.now().strftime("%H:%M"), str(r["meal_type"]), str(r["name"]), 1,
                         float(r["calories"] or 0), float(r["protein"] or 0), float(r["carbs"] or 0), float(r["fat"] or 0),
                         "Logged from meal library; nutrition is an estimate.", datetime.now().isoformat()))
                    st.success("Added to today's food log.")
                    st.rerun()
        st.download_button("Download meal library CSV", data=meals.to_csv(index=False).encode("utf-8"), file_name="meals.csv", mime="text/csv")

# ---------- History ----------
with tabs[4]:
    st.subheader("History & insights")
    if not food_df.empty:
        ff = food_df.copy()
        ff["log_date"] = pd.to_datetime(ff["log_date"])
        daily = ff.groupby("log_date", as_index=False).agg(calories=("calories","sum"), protein=("protein","sum"), carbs=("carbs","sum"), fat=("fat","sum"), meals=("id","count"))
        st.markdown("### Daily nutrition")
        st.line_chart(daily.set_index("log_date")[["calories"]], y_label="kcal")
        st.dataframe(daily.sort_values("log_date", ascending=False).round(1), hide_index=True, use_container_width=True)
        st.download_button("Export food log CSV", data=food_df.to_csv(index=False).encode("utf-8"), file_name="food_log.csv", mime="text/csv")
    else:
        st.info("Meal history will build as food is logged.")
    if not weight_df.empty:
        st.markdown("### Weight history")
        st.dataframe(weight_df.sort_values(["log_date","id"], ascending=False), hide_index=True, use_container_width=True)
        st.download_button("Export weight log CSV", data=weight_df.to_csv(index=False).encode("utf-8"), file_name="weight_log.csv", mime="text/csv")
    st.warning("Use weekly averages and multi-week trends rather than judging progress from one weigh-in. The app does not diagnose conditions or prescribe treatment.")

# ---------- Settings ----------
with tabs[5]:
    st.subheader("How estimates work")
    st.markdown("""
**1. Basal metabolic rate (BMR)** is estimated with the Mifflin–St Jeor equation for women:

`BMR = 10 × weight(kg) + 6.25 × height(cm) − 5 × age − 161`

**2. Total daily energy expenditure (TDEE)** = BMR × activity multiplier:
- Sedentary 1.20
- Light 1.375
- Moderate 1.55
- Very active 1.725

**3. Starting calorie target** = estimated TDEE minus a selected modest deficit (250 / 350 / 500 kcal), or TDEE for maintenance. The app applies a 1,200 kcal/day lower guardrail so it does not automatically generate an even lower target; this is not a guarantee that 1,200 is appropriate for any individual.

The estimate is a starting point, not a precise measurement. Weight trend, hunger, energy, training, menstrual health, medications and medical advice matter. Reassess after several weeks rather than changing the target in response to a single weigh-in.
""")
    st.markdown("### Data storage & privacy")
    st.write("Logs are stored in `funvi_diet.db` on the computer or server running Streamlit. They persist across app restarts on that same storage. They are not automatically synced between devices.")
    st.write("For cloud deployment, use persistent storage or a database service; Streamlit Community Cloud's local filesystem should not be treated as durable storage. Do not upload sensitive health data to a public repository.")
    if st.button("Delete ALL meal and weight logs", type="secondary"):
        st.session_state["confirm_wipe"] = True
    if st.session_state.get("confirm_wipe"):
        st.error("This permanently deletes all recorded food and weight history from this local database.")
        if st.button("Yes, permanently delete all logs"):
            with db() as conn:
                conn.execute("DELETE FROM food_logs")
                conn.execute("DELETE FROM weights")
            st.session_state["confirm_wipe"] = False
            st.rerun()
