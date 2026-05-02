import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io

# --- CONFIGURATION ---
st.set_page_config(page_title="Fish Family Budget", layout="centered")


def check_password():
    if st.session_state.get("password_correct", False):
        return True
    st.title("🔐 Secure Budget Access")
    pwd = st.text_input("Enter Access Key", type="password")
    if st.button("Login"):
        if pwd == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


@st.cache_data(ttl=3600)
def fetch_raw_data(url):
    """
    Downloads the Excel binary stream using a session and
    enhanced headers to bypass 403 Forbidden blocks.
    """
    try:
        # A Session preserves cookies and handles redirects better than a single call
        session = requests.Session()

        # We spoof a real browser's 'User-Agent' and 'Accept' patterns
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://onedrive.live.com/',
            'Connection': 'keep-alive'
        }

        response = session.get(url, headers=headers, timeout=30, allow_redirects=True)

        # This will trigger the Error if the status code is 403, 404, etc.
        response.raise_for_status()

        return response.content
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            st.error(
                "🔒 403 Forbidden: Microsoft is blocking the script. Please try the 'Embed Link' method to get a fresh URL.")
        else:
            st.error(f"HTTP Error: {e}")
        return None
    except Exception as e:
        st.error(f"Network Error: {e}")
        return None

@st.cache_data
def parse_excel_data(raw_data):
    """
    Parses the raw Excel binary into DataFrames.
    Cached so we don't rebuild the DataFrames on every UI interaction.
    """
    xl_initial = pd.ExcelFile(io.BytesIO(raw_data), engine='openpyxl')
    df_trans = pd.read_excel(xl_initial, sheet_name="Transactions")
    df_cats = pd.read_excel(xl_initial, sheet_name="Categories")

    # --- VALIDATE TRANSACTIONS ---
    required_trans_cols = ['Date', 'Category', 'Amount']
    missing_trans = [col for col in required_trans_cols if col not in df_trans.columns]
    if missing_trans:
        return None, None, f"Transactions tab is missing required columns: {', '.join(missing_trans)}"

    # --- VALIDATE CATEGORIES ---
    required_cats_cols = ['Category', 'Group', 'Type']
    missing_cats = [col for col in required_cats_cols if col not in df_cats.columns]
    if missing_cats:
        return None, None, f"Categories tab is missing required columns: {', '.join(missing_cats)}"

    # If everything is good, return the DataFrames and no error
    return df_trans, df_cats, None

def standardize_dates(df, date_column):
    """Converts the date column to datetime objects."""
    df[date_column] = pd.to_datetime(df[date_column], errors='coerce')
    df = df.dropna(subset=[date_column])

    if df.empty:
        return None
    return df


def get_available_years(df_trans):
    """
    Scans the Transactions table and returns a sorted list
    of unique years found in the data.
    """
    # Standardize first to ensure we are pulling from valid dates
    years = df_trans['Date'].dt.year.unique().tolist()

    # Sort descending so the most recent year is the first option
    years.sort(reverse=True)
    return years


def process_budget_logic(df_trans, df_cats, selected_month_name, selected_year):
    month_map = {
        "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
        "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12
    }
    sel_month_num = month_map[selected_month_name]

    # Filter Transactions
    df_trans_filtered = df_trans[
        (df_trans['Date'].dt.month == sel_month_num) &
        (df_trans['Date'].dt.year == int(selected_year))
        ].copy()

    budget_col = f"{selected_month_name[:3]} {selected_year}"
    if budget_col not in df_cats.columns:
        return None, f"Budget column '{budget_col}' not found."

    # Group and Merge
    spending = df_trans_filtered.groupby('Category')['Amount'].sum().reset_index()
    final_df = pd.merge(df_cats, spending, on='Category', how='left').fillna({'Amount': 0})

    result = final_df[['Category', 'Group', 'Type', budget_col, 'Amount']].copy()
    result.rename(columns={budget_col: 'Budgeted', 'Amount': 'Actual'}, inplace=True)

    return result, None


# --- MAIN APP ---
if check_password():
    data_blob = fetch_raw_data(st.secrets["EXCEL_URL"])

    if data_blob:
        trans_df, cats_df, parse_error = parse_excel_data(data_blob)

        # Halt the app immediately if the data structure is broken
        if parse_error:
            st.error(f"🚨 Data Error: {parse_error}")
            st.stop()
        trans_df = standardize_dates(trans_df, 'Date')
        if trans_df is None:
            st.error("📅 Date Error: No valid dates found in the Transactions tab. "
                     "Please check your Excel file formatting.")
            st.stop()
        dynamic_years = get_available_years(trans_df)

        st.sidebar.header("🗓️ Select Period")
        months = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]
        sel_month = st.sidebar.selectbox("Month", months)
        # Use the dynamically generated list here
        sel_year = st.sidebar.selectbox("Year", dynamic_years)

        if st.sidebar.button("🔄 Sync Latest Data"):
            st.cache_data.clear()
            st.rerun()

        budget_df, error_msg = process_budget_logic(trans_df, cats_df, sel_month, sel_year)

        if error_msg:
            st.warning(f"⚠️ {error_msg}")
        elif budget_df is not None:
            st.title(f"💰 {sel_month} {sel_year}")

            # --- METRICS SECTION ---
            st.subheader("📍 Major Groups")
            major_groups = ["Primary Income", "Bills", "Discretionary", "Giving", "Living", "Work"]
            m_cols = st.columns(3)
            group_totals = budget_df.groupby('Group')[['Budgeted', 'Actual']].sum(min_count=1).reset_index()

            for i, g_name in enumerate(major_groups):
                if g_name in group_totals['Group'].values:
                    row = group_totals[group_totals['Group'] == g_name].iloc[0]
                    actual, b_val = row['Actual'], row['Budgeted']

                    # Logic for Income vs Expense Labels
                    if g_name == "Primary Income":
                        delta_raw = b_val - actual
                        label_main = "Earned"
                        if pd.isna(b_val):
                            label_delta = None
                            d_color = "normal"
                        elif delta_raw >= 0:
                            label_delta = "Remaining to Earn"
                            d_color = 'inverse'
                        else:
                            label_delta = "Over Expected Earnings"
                            d_color = "normal"
                    else:
                        delta_raw = b_val + actual
                        label_main = "Spent"
                        if pd.isna(b_val):
                            label_delta = None
                            d_color = "normal"
                        elif delta_raw >= 0:
                            label_delta = "Left to Spend"
                            d_color = 'normal'
                        else:
                            label_delta = "Over Budget"
                            d_color = "inverse"

                    if pd.isna(b_val):
                        val_display, delta_val = "No set budget", None
                    else:
                        val_display = f"${abs(actual):,.0f}"
                        # For income, a positive delta is "good" (green), for spending its "bad"
                        delta_val = f"${abs(delta_raw):,.0f} {label_delta}"

                    with m_cols[i % 3]:
                        st.metric(label=g_name, value=val_display, delta=delta_val, delta_color=d_color)

            st.divider()

            # --- DETAILED VIEW ---
            st.subheader("🔍 Category Breakdown")
            selected_cat = st.selectbox("Detailed Analysis:", budget_df['Category'].unique())
            cat_row = budget_df[budget_df['Category'] == selected_cat].iloc[0]

            # Context-Aware Labels
            is_income = cat_row['Group'] == "Primary Income"

            if cat_row['Actual'] <=0:
                verb_actual = 'Spent'
            else:
                verb_actual = 'Earned'

            target = cat_row['Budgeted']

            if is_income:
                delta_cat = target - cat_row['Actual']
                if delta_cat <=0:
                    verb_remain = 'Over Plan'
                else:
                    verb_remain = 'to Earn'
            else:
                delta_cat = target + cat_row['Actual']
                if delta_cat <=0:
                    verb_remain = 'Over Budget'
                else:
                    verb_remain = 'Left'

            c1, c2 = st.columns(2)
            with c1:
                st.write(f"### {selected_cat}")

                if pd.isna(target):
                    st.info("Budget: **No set budget**")
                    rem_text = "N/A"
                else:
                    st.write(f"Budget: **${target:,.2f}**")
                    rem_text = f"${abs(delta_cat):,.2f} {verb_remain}"
                st.write(f"{verb_actual}: **${abs(cat_row['Actual']):,.2f}**")
                st.write(f"Status: **{rem_text}**")

            with c2:
                if delta_cat <0:
                    st.write('')
                    st.write('')
                    st.write('# Over Budget')
                elif target == 0:
                    st.write('')
                    st.write('')
                    st.write('# No Budget')
                if not pd.isna(target) and target > 0:
                    if delta_cat >0:
                        fig = go.Figure(data=[go.Pie(
                            labels=[verb_actual, 'Remaining'],
                            values=[abs(cat_row['Actual']), max(0, abs(delta_cat))],
                            hole=.6, marker_colors=['#00c853' if is_income else '#ff4b4b', '#4b8bff' if is_income else '#00c853']
                        )])
                        fig.update_layout(showlegend=False, height=250, margin=dict(t=0, b=0, l=0, r=0))
                        st.plotly_chart(fig, use_container_width=True)
