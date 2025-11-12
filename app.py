import streamlit as st
from canvasapi import Canvas
import pandas as pd
from datetime import datetime
import plotly.express as px
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="Canvas Rubric Scraper", layout="wide")

# --- SESSION STATE FOR LOGIN ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

# --- CREDENTIALS ---
# --- CREDENTIALS ---
VALID_USERNAME = "mark"
VALID_PASSWORD = "password123"


# --- LOGIN SIDEBAR ---
st.sidebar.title("🔒 Login")
username_input = st.sidebar.text_input("Username")
password_input = st.sidebar.text_input("Password", type="password")
login_button = st.sidebar.button("Login")

if login_button:
    if username_input == VALID_USERNAME and password_input == VALID_PASSWORD:
        st.session_state["logged_in"] = True
    else:
        st.error("❌ Invalid username or password.")

if not st.session_state["logged_in"]:
    st.warning("Please log in to access the app.")
    st.stop()

# --- HEADER ---
st.image(
    "https://marksresearch.shinyapps.io/PictureSite/_w_237fc4faadbc4c7e844fdb756bcd9876/COED2.png",
    width=240
)
st.title("Canvas Rubric Report Generator")
st.markdown(
    "<h5 style='color: gray;'>This Program is the Property of Mark A. Perkins, Ph.D. for demonstration at UCCS</h5>",
    unsafe_allow_html=True
)

# --- CSV UPLOAD ---
token_file = st.file_uploader("Upload a CSV API Token and Canvas Web Address", type=["csv"])

tokens_list = []
if token_file:
    try:
        tokens_df = pd.read_csv(token_file).dropna(subset=['Token', 'URL']).drop_duplicates(subset=['Token', 'URL'])
        tokens_list = tokens_df.to_dict('records')
        st.success(f"{len(tokens_list)} token(s) loaded.")
    except Exception as e:
        st.error(f"Could not read tokens: {e}")
        tokens_list = []

# --- FETCH DATA FUNCTION ---
@st.cache_data(show_spinner=False)
def fetch_data(tokens_with_urls):
    all_data = []

    # Term helpers
    def extract_term_info(start_date_str):
        try:
            start_date = datetime.fromisoformat(start_date_str.rstrip("Z"))
            month = start_date.month
            year = start_date.year

            if 1 <= month <= 4:
                term = "Spring"
            elif 5 <= month <= 7:
                term = "Summer"
            else:
                term = "Fall"

            academic_year = f"{year}-{year+1}" if term == "Fall" else f"{year-1}-{year}"
            return term, academic_year
        except Exception:
            return "Unknown", "Unknown"

    def extract_term_and_year_from_name(course_name):
        match = re.search(r'\((Spring|Summer|Fall) (\d{4})\)', course_name)
        if match:
            term = match.group(1)
            year = int(match.group(2))
            academic_year = f"{year}-{year+1}" if term == "Fall" else f"{year-1}-{year}"
            return term, academic_year
        return "Unknown", "Unknown"

    # Fetch data from Canvas
    for record in tokens_with_urls:
        token = record['Token']
        canvas_url = record['URL']
        institution = record.get('Institution', 'Unknown')
        try:
            canvas = Canvas(canvas_url, token)
            courses = list(canvas.get_courses(enrollment_type='teacher', state=['available', 'completed']))
            st.write(f"🧾 Token {token[:6]}... found {len(courses)} courses")

            for course in courses:
                try:
                    instructor = course.get_users(enrollment_type='teacher')
                    instructor_names = ", ".join([i.short_name for i in instructor])
                    term, year = extract_term_info(course.start_at) if course.start_at else extract_term_and_year_from_name(course.name)
                    course_name = course.name
                    course_start_date = course.start_at if course.start_at else "Unknown"

                    assignments = course.get_assignments(include=['rubric'])
                    for assignment in assignments:
                        if not hasattr(assignment, 'rubric') or not assignment.rubric:
                            continue
                        rubric = assignment.rubric
                        submissions = assignment.get_submissions(include=['rubric_assessment'])

                        for submission in submissions:
                            if hasattr(submission, 'rubric_assessment') and submission.rubric_assessment:
                                for setting in rubric:
                                    rid = setting['id']
                                    desc = setting['description']
                                    score = submission.rubric_assessment.get(rid, {}).get('points', None)
                                    points_possible = setting.get('points', None)
                                    all_data.append({
                                        "Institution": institution,
                                        "Term": term,
                                        "Year": year,
                                        "Course": course_name,
                                        "Instructor": instructor_names,
                                        "Assignment": assignment.name,
                                        "Rubric Item": desc,
                                        "Score": score,
                                        "Points Possible": points_possible,
                                        "Student ID": submission.user_id,
                                        "Course Start Date": course_start_date
                                    })
                except Exception as course_error:
                    st.warning(f"⚠️ Error in course {course_name}: {course_error}")
        except Exception as token_error:
            st.error(f"🚫 Error using token {token[:6]}...: {token_error}")

    return pd.DataFrame(all_data)

# --- FETCH DATA ---
if tokens_list:
    with st.spinner("⏳ Fetching rubric data..."):
        df = fetch_data(tokens_list)

    if df.empty:
        st.info("No rubric data found for the uploaded tokens.")
    else:
        st.success(f"✅ Found {len(df)} rubric scores across {df['Course'].nunique()} course(s).")

        # --- FILTERS ---
        filtered_df = df.copy()
        for col, label in [('Institution', "Select Institution(s)"),
                           ('Year', "Select Academic Year(s)"),
                           ('Term', "Select Term(s)"),
                           ('Course', "Select Course(s)"),
                           ('Assignment', "Select Assignment(s)"),
                           ('Instructor', "Select Instructor(s)")]:
            options = st.multiselect(label, sorted(filtered_df[col].unique()))
            if options:
                filtered_df = filtered_df[filtered_df[col].isin(options)]

        # --- AGGREGATED DATA ---
        aggregated_df = (
            filtered_df.groupby(['Institution', 'Year', 'Term', 'Course', 'Instructor', 'Assignment', 'Rubric Item'])
            .agg(
                Avg_Score=('Score', 'mean'),
                Max_Score=('Score', 'max'),
                Min_Score=('Score', 'min'),
                Count=('Student ID', 'nunique')
            ).reset_index()
        )

        # --- TABS ---
        tab1, tab2, tab3 = st.tabs([
            "📋 Data Table", 
            "📊 Average Scores", 
            "🧮 Score Frequency"
        ])

        # --- TAB 1: RAW DATA ---
        with tab1:
            st.dataframe(filtered_df, use_container_width=True)
            st.download_button(
                "📥 Download Filtered Data as CSV",
                data=filtered_df.to_csv(index=False).encode('utf-8'),
                file_name='filtered_rubric_data.csv',
                mime='text/csv'
            )

        # --- TAB 2: AVERAGE SCORES ---
        with tab2:
            st.subheader("🎯 Average Scores Visualization")
            st.download_button(
                "📥 Download Aggregated Data as CSV",
                data=aggregated_df.to_csv(index=False).encode('utf-8'),
                file_name='aggregated_rubric_data.csv',
                mime='text/csv'
            )

            group_by = st.selectbox("Group by", ['Institution', 'Rubric Item', 'Course', 'Instructor'])
            if not aggregated_df.empty:
                avg_scores = aggregated_df.groupby(group_by)['Avg_Score'].mean().sort_values().reset_index()

                # Bar chart
                fig1 = px.bar(
                    avg_scores, x=group_by, y='Avg_Score',
                    title=f"Average Scores by {group_by}",
                    labels={group_by: group_by, 'Avg_Score': 'Average Score'},
                    text='Avg_Score'
                )
                fig1.update_traces(texttemplate='%{text:.2f}', textposition='outside')
                fig1.update_layout(xaxis_tickangle=45, margin=dict(l=40, r=40, t=80, b=100), height=450)
                st.plotly_chart(fig1, use_container_width=True)

                # Box plot
                fig2 = px.box(aggregated_df, x='Avg_Score', y=group_by, points="all", title=f"Score Distribution by {group_by}")
                fig2.update_layout(margin=dict(l=40, r=40, t=50, b=100), height=450)
                st.plotly_chart(fig2, use_container_width=True)

        # --- TAB 3: SCORE FREQUENCY ---
        with tab3:
            long_agg_df = (
                filtered_df.groupby(['Rubric Item', 'Score'])
                .agg(Count=('Student ID', 'nunique'))
                .reset_index()
            )
            total_per_criterion = long_agg_df.groupby('Rubric Item')['Count'].transform('sum')
            long_agg_df['Percentage'] = (long_agg_df['Count'] / total_per_criterion * 100).round(1)
            long_agg_df['Label'] = long_agg_df.apply(lambda row: f"{row['Count']} ({row['Percentage']}%)", axis=1)

            MAX_FACETS = 12
            num_rubric_items = long_agg_df['Rubric Item'].nunique()

            if long_agg_df.empty:
                st.info("No data matches the selected filters for visualization.")
            elif num_rubric_items > MAX_FACETS:
                st.warning(f"⚠️ {num_rubric_items} rubric items selected — too many to display. Filter further to <12.")
            else:
                facet_by = st.selectbox("Facet by", ["Rubric Item", "Institution"])

                try:
                    if facet_by == "Rubric Item":
                        ranges = long_agg_df.groupby("Rubric Item")["Score"].agg(['min', 'max']).reset_index()
                        ranges["Facet Title"] = ranges.apply(lambda row: f"{row['Rubric Item']} ({row['min']}-{row['max']})", axis=1)
                        long_df_labeled = long_agg_df.merge(ranges[['Rubric Item', 'Facet Title']], on='Rubric Item')
                        facet_col = "Facet Title"
                    else:
                        long_df_labeled = (
                            filtered_df.groupby(["Institution", "Score"])["Student ID"]
                            .nunique()
                            .reset_index(name="Count")
                        )
                        total_per_inst = long_df_labeled.groupby("Institution")["Count"].transform("sum")
                        long_df_labeled["Percentage"] = (long_df_labeled["Count"] / total_per_inst * 100).round(1)
                        long_df_labeled["Label"] = long_df_labeled.apply(lambda row: f"{row['Count']} ({row['Percentage']}%)", axis=1)
                        facet_col = "Institution"

                    fig3 = px.bar(
                        long_df_labeled, x="Score", y="Count",
                        facet_col=facet_col, facet_col_wrap=3,
                        text="Label", hover_data=["Label"],
                        title=f"🎓 Distinct Student Scores by {facet_by}",
                        labels={"Score": "Score Value", "Count": "Number of Students"},
                        height=600
                    )
                    fig3.update_xaxes(matches=None)
                    fig3.update_traces(texttemplate="%{text}", textposition='auto')
                    fig3.update_layout(margin=dict(l=40, r=40, t=80, b=100), showlegend=False)
                    st.plotly_chart(fig3, use_container_width=True)

                    st.download_button(
                        "📥 Download Aggregated Data as CSV",
                        data=long_agg_df.to_csv(index=False).encode('utf-8'),
                        file_name='aggregated_rubric_data.csv',
                        mime='text/csv'
                    )

                except ValueError as e:
                    if "Horizontal spacing cannot be greater than" in str(e):
                        st.warning("⚠️ Too many items to display. Apply filters to reduce the number.")
                    else:
                        st.error(f"Unexpected error: {e}")
                except Exception as e:
                    st.error(f"🚨 Error rendering score frequency chart: {e}")
