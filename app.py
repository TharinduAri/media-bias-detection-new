import logging
import streamlit as st
import pandas as pd
import plotly.express as px

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

st.set_page_config(page_title="Sri Lanka Media Bias MVP", layout="wide")

st.title("Media Bias Detection MVP")
st.markdown("""
This dashboard demonstrates media bias as a longitudinal, outlet-level phenomenon.
It uses proxy signals (entity sentiment and coverage frequency) rather than binary classification.
""")

# --- Load Data ---
@st.cache_data
def load_data():
    files = {
        'agg_sentiment': 'data/agg_sentiment.csv',
        'agg_coverage': 'data/agg_coverage.csv',
        'explain_data': 'data/ui_explain_data.csv',
        'omissions': 'data/potential_omissions.csv'
    }

    results = {}
    for key, path in files.items():
        try:
            df = pd.read_csv(path)
            logging.info(f"Loaded {path}: shape={df.shape}, cols={list(df.columns)}")
            if not df.empty:
                try:
                    logging.info(f"{path} first row: {df.head(1).to_dict(orient='records')}")
                except Exception:
                    logging.info(f"{path} loaded but couldn't show head() (non-standard types)")
        except FileNotFoundError:
            logging.warning(f"File not found: {path}")
            df = pd.DataFrame()
        except Exception as e:
            logging.exception(f"Error loading {path}: {e}")
            df = pd.DataFrame()

        results[key] = df

    logging.info("Finished attempting to load all data files.")
    return results['agg_sentiment'], results['agg_coverage'], results['explain_data'], results['omissions']

agg_sentiment, agg_coverage, explain_data, omissions = load_data()

# Ensure we always have DataFrame objects and guard missing columns
if not isinstance(agg_sentiment, pd.DataFrame):
    agg_sentiment = pd.DataFrame()
if not isinstance(agg_coverage, pd.DataFrame):
    agg_coverage = pd.DataFrame()
if not isinstance(explain_data, pd.DataFrame):
    explain_data = pd.DataFrame()
if not isinstance(omissions, pd.DataFrame):
    omissions = pd.DataFrame()

# --- Dashboard Layout ---
tab1, tab2, tab3 = st.tabs(["Longitudinal Sentiment", "Topic Coverage & Omissions", "Explainability"])

with tab1:
    st.header("Outlet Sentiment Trends")
    st.markdown("Tracks the average sentiment expressed toward specific entities over time by different outlets.")
    
    # Safely get entities list
    if not agg_sentiment.empty and 'entity' in agg_sentiment.columns:
        entities = agg_sentiment['entity'].unique()
    else:
        entities = []

    selected_entity = st.selectbox("Select Entity to track:", entities if len(entities) > 0 else ["No entities available"]) 

    if entities and selected_entity != "No entities available":
        entity_data = agg_sentiment[agg_sentiment['entity'] == selected_entity]
    else:
        entity_data = pd.DataFrame()
    
    if not entity_data.empty:
        fig_sentiment = px.line(
            entity_data, 
            x='year_month', 
            y='avg_sentiment', 
            color='outlet',
            markers=True,
            title=f"Trend for '{selected_entity}'",
            labels={'year_month': 'Time Period', 'avg_sentiment': 'Average Sentiment Score'}
        )
        st.plotly_chart(fig_sentiment, use_container_width=True)
    else:
        st.info("No timeline data for this entity.")

with tab2:
    st.header("Coverage Comparison")
    st.markdown("Compares how frequently different outlets cover specific entities/topics.")
    
    # Simple bar chart of total mentions
    # For a cleaner chart, take top 15 most mentioned entities overall
    # Guard coverage DataFrame
    if not agg_coverage.empty and 'entity' in agg_coverage.columns and 'total_mentions' in agg_coverage.columns:
        top_entities = agg_coverage.groupby('entity')['total_mentions'].sum().nlargest(15).index
        coverage_filtered = agg_coverage[agg_coverage['entity'].isin(top_entities)]
    else:
        top_entities = []
        coverage_filtered = pd.DataFrame()
    
    if not coverage_filtered.empty:
        fig_coverage = px.bar(
            coverage_filtered,
            x='entity',
            y='total_mentions',
            color='outlet',
            barmode='group',
            title="Top 15 Entities: Coverage Frequency by Outlet",
            labels={'total_mentions': 'Total Mentions (Sentences)'}
        )
        st.plotly_chart(fig_coverage, use_container_width=True)
    else:
        st.info("No coverage data available.")

    st.subheader("Potential Omissions")
    st.markdown("Entities heavily covered by one outlet but ignored by another:")
    if omissions is not None and not omissions.empty:
        st.dataframe(omissions, use_container_width=True)
    else:
        st.info("No significant omissions detected in this timeframe.")

with tab3:
    st.header("Explainability Layer")
    st.markdown("Shows the specific sentences driving the sentiment scores for an entity.")
    
    if explain_data is not None and not explain_data.empty:
        explain_entities = explain_data['entity'].unique()
        explain_entity = st.selectbox("Select Entity to explain:", explain_entities, key='explain_select')
        
        filtered_explain = explain_data[explain_data['entity'] == explain_entity]
        
        for outlet in filtered_explain['outlet'].unique():
            st.subheader(f"Sentences from {outlet}")
            outlet_sentences = filtered_explain[filtered_explain['outlet'] == outlet]
            
            for _, row in outlet_sentences.iterrows():
                sentiment_color = "green" if row['sentiment'] > 0 else "red" if row['sentiment'] < 0 else "gray"
                st.markdown(f"> *\"{row['example_sentence']}\"*")
                st.markdown(f"**Score:** :{sentiment_color}[{row['sentiment']:.2f}] | **Date:** {row['date']}")
                st.divider()
    else:
        st.info("No explainability data available.")
