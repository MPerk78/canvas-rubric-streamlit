import streamlit as st
import pandas as pd
import requests
import re           # <-- add this line
from canvasapi import Canvas
from datetime import datetime
import plotly.express as px
from openai import OpenAI

# --- PAGE CONFIG ---
st.set_page_config(page_title="Canvas Tools", layout="wide")

# --- HEADER ---
st.image("COED.png", width=300)
st.title("Canvas Rubric Scraper & Comments Exporter")
st.markdown(
    "<h5 style='color: gray;'>This Program is the Property of Mark A. Perkins, Ph.D.</h5>",
    unsafe_allow_html=True
)

# --- LOGIN ---
VALID_USERNAME = st.secrets["username"]
VALID_PASSWORD = st.secrets["password"]

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

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

# --- UPLOAD TOKENS CSV ---
token_file = st.file_uploader("Upload CSV with Token, URL, Institution", type=["csv"])
tokens_list = []

if token_file:
    try:
        tokens_df = pd.read_csv(token_file).dropna(subset=['Token', 'URL']).drop_duplicates(subset=['Token', 'URL'])
        tokens_list = tokens_df.to_dict('records')
        st.success(f"{len(tokens_list)} token(s) loaded.")
    except Exception as e:
        st.error(f"Could not read tokens: {e}")

# --- TABS ---
tab_rubric, tab_comments = st.tabs(["📋 Rubric Scraper", "💬 Comments Exporter"])

# =========================
# TAB 1: RUBRIC SCRAPER
# =========================
with tab_rubric:
    st.subheader("Rubric Analyzer")

    if tokens_list:

        @st.cache_data(show_spinner=False)
        def fetch_rubric_data(tokens_with_urls):
            all_data = []

            def term_year(course):
                try:
                    if course.start_at:
                        start_date = datetime.fromisoformat(course.start_at.rstrip("Z"))
                        month = start_date.month
                        year = start_date.year
                        term = "Spring" if 1 <= month <= 4 else "Summer" if 5 <= month <= 7 else "Fall"
                        academic_year = f"{year}-{year+1}" if term=="Fall" else f"{year-1}-{year}"
                        return term, academic_year
                    else:
                        return "Unknown", "Unknown"
                except:
                    return "Unknown", "Unknown"

            for record in tokens_with_urls:
                token = record['Token']
                canvas_url = record['URL']
                institution = record.get('Institution', 'Unknown')
                try:
                    canvas = Canvas(canvas_url, token)
                    courses = list(canvas.get_courses(enrollment_type='teacher', state=['available', 'completed']))
                    for course in courses:
                        instructor_list = course.get_users(enrollment_type='teacher')
                        instructors = ", ".join([i.short_name for i in instructor_list])
                        term, year = term_year(course)
                        assignments = course.get_assignments(include=['rubric'])
                        for assignment in assignments:
                            if not getattr(assignment, 'rubric', None):
                                continue
                            submissions = assignment.get_submissions(include=['rubric_assessment'])
                            for sub in submissions:
                                if getattr(sub, 'rubric_assessment', None):
                                    for setting in assignment.rubric:
                                        rid = setting['id']
                                        desc = setting['description']
                                        score = sub.rubric_assessment.get(rid, {}).get('points', None)
                                        all_data.append({
                                            "Institution": institution,
                                            "Term": term,
                                            "Year": year,
                                            "Course": course.name,
                                            "Instructor": instructors,
                                            "Assignment": assignment.name,
                                            "Rubric Item": desc,
                                            "Score": score,
                                            "Points Possible": setting.get('points', None),
                                            "Student ID": sub.user_id
                                        })
                except Exception as e:
                    st.warning(f"Error fetching data for token {token[:6]}: {e}")
            return pd.DataFrame(all_data)

        # --- FETCH BUTTON ---
        if st.button("Fetch Rubric Data"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            df_rubric_all = pd.DataFrame()
            total_tokens = len(tokens_list)

            for i, record in enumerate(tokens_list):
                status_text.text(f"Processing token {i+1}/{total_tokens} ({record.get('Institution', 'Unknown')})...")
                df_part = fetch_rubric_data([record])
                df_rubric_all = pd.concat([df_rubric_all, df_part], ignore_index=True)
                progress_bar.progress(int((i+1)/total_tokens*100))

            progress_bar.empty()
            status_text.empty()

            if df_rubric_all.empty:
                st.info("No rubric data found.")
            else:
                st.session_state['df_rubric'] = df_rubric_all
                st.success("✅ Rubric data fetched successfully!")

    # --- FILTERS AND VISUALIZATION ---
    if 'df_rubric' in st.session_state:
        df_rubric = st.session_state['df_rubric'].copy()

        # Filters
        filtered_df = df_rubric.copy()
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

        # --- TABS FOR VISUALS ---
        tab1_r, tab2_r, tab3_r = st.tabs([
            "📋 Data Table", 
            "📊 Average Scores", 
            "🧮 Score Frequency"
        ])

        with tab1_r:
            st.dataframe(filtered_df, use_container_width=True)
            st.download_button(
                "📥 Download Filtered Data as CSV",
                data=filtered_df.to_csv(index=False).encode('utf-8'),
                file_name='filtered_rubric_data.csv',
                mime='text/csv'
            )

        with tab2_r:
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

                fig1 = px.bar(
                    avg_scores, x=group_by, y='Avg_Score',
                    title=f"Average Scores by {group_by}",
                    labels={group_by: group_by, 'Avg_Score': 'Average Score'},
                    text='Avg_Score'
                )
                fig1.update_traces(texttemplate='%{text:.2f}', textposition='outside')
                fig1.update_layout(xaxis_tickangle=45, margin=dict(l=40, r=40, t=80, b=100), height=450)
                st.plotly_chart(fig1, use_container_width=True)

                fig2 = px.box(aggregated_df, x='Avg_Score', y=group_by, points="all", title=f"Score Distribution by {group_by}")
                fig2.update_layout(margin=dict(l=40, r=40, t=50, b=100), height=450)
                st.plotly_chart(fig2, use_container_width=True)

        with tab3_r:
            long_agg_df = (
                filtered_df.groupby(['Rubric Item', 'Score'])
                .agg(Count=('Student ID', 'nunique'))
                .reset_index()
            )
            total_per_criterion = long_agg_df.groupby("Rubric Item")["Count"].transform("sum")
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
                        file_name='frequency_rubric_data.csv',
                        mime='text/csv'
                    )
                except ValueError as e:
                    st.warning(f"⚠️ {e}")
                except Exception as e:
                    st.error(f"🚨 Error rendering score frequency chart: {e}")

# =========================
# TAB 2: COMMENTS EXPORTER
# =========================
with tab_comments:
    st.subheader("Comments Exporter")
    st.image("COED.png", width=300)
    st.markdown("### Download comments from your courses and export to a CSV")

    if tokens_list:
        institution = st.selectbox("Select Institution", [r.get('Institution','Unknown') for r in tokens_list])
        inst_row = next(r for r in tokens_list if r.get('Institution')==institution)
        base_url = inst_row['URL'].rstrip("/") + "/api/v1"
        token = inst_row['Token']

        # Helper functions
        def paginate_request(url, token):
            headers = {"Authorization": f"Bearer {token}"}
            all_results = []
            while url:
                r = requests.get(url, headers=headers)
                r.raise_for_status()
                all_results.extend(r.json())
                url = r.links["next"]["url"] if "next" in r.links else None
            return all_results

        def get_courses(base_url, token):
            url = f"{base_url}/courses?per_page=100"
            return paginate_request(url, token)

        def get_assignments(base_url, token, course_id):
            url = f"{base_url}/courses/{course_id}/assignments?per_page=100"
            return paginate_request(url, token)

        def get_student_names(base_url, token, course_id):
            url = f"{base_url}/courses/{course_id}/enrollments?type[]=StudentEnrollment&per_page=100"
            enrollments = paginate_request(url, token)
            return [e["user"]["name"] for e in enrollments]

        def get_instructor_ids(base_url, token, course_id):
            url = f"{base_url}/courses/{course_id}/enrollments?type[]=TeacherEnrollment&per_page=100"
            enrollments = paginate_request(url, token)
            return [e["user"]["id"] for e in enrollments]

        def get_comments(base_url, token, course_id, assignment_id):
            url = f"{base_url}/courses/{course_id}/assignments/{assignment_id}/submissions?include[]=submission_comments&per_page=100"
            return paginate_request(url, token)

        def clean_comment(text, student_names):
            cleaned = text
            for name in student_names:
                cleaned = re.sub(re.escape(name), "STUDENT", cleaned, flags=re.IGNORECASE)
                for part in name.split():
                    cleaned = re.sub(rf"\b{re.escape(part)}\b", "STUDENT", cleaned, flags=re.IGNORECASE)
            return cleaned

        # Course + Assignment selection
        courses = get_courses(base_url, token)
        course_dict = {c["name"]: c["id"] for c in courses if c.get("name") and c.get("id")}
        course_name = st.selectbox("Select Course", list(course_dict.keys()))
        course_id = course_dict[course_name]

        assignments = get_assignments(base_url, token, course_id)
        assignment_dict = {a["name"]: a["id"] for a in assignments if a.get("name") and a.get("id")}
        assignment_name = st.selectbox("Select Assignment", list(assignment_dict.keys()))
        assignment_id = assignment_dict[assignment_name]

        if st.button("Pull Comments"):
            student_names = get_student_names(base_url, token, course_id)
            instructor_ids = get_instructor_ids(base_url, token, course_id)
            submissions = get_comments(base_url, token, course_id, assignment_id)

            rows = []
            for sub in submissions:
                for c in sub.get("submission_comments", []):
                    raw = c["comment"]
                    cleaned = clean_comment(raw, student_names)
                    author_id = c.get("author_id")
                    role = "Instructor" if author_id in instructor_ids else "Student"
                    rows.append({
                        "student_id": sub.get("user_id"),
                        "author_id": author_id,
                        "role": role,
                        "raw_comment": raw,
                        "cleaned_comment": cleaned
                    })

            df_comments = pd.DataFrame(rows)
            st.dataframe(df_comments)

            st.download_button(
                "Download Comments CSV",
                df_comments.to_csv(index=False),
                file_name=f"{course_name}_{assignment_name}_comments.csv",
                mime="text/csv"
            )

