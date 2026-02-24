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
    from prisma import Prisma
    import pandas as pd
    
    db = Prisma()
    try:
        db.connect()
    except Exception as e:
        logging.error(f"Could not connect to database: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    try:
        def to_dict(record):
            return record.model_dump() if hasattr(record, 'model_dump') else dict(record)

        agg_sentiment_records = db.aggregatedsentiment.find_many()
        agg_sentiment = pd.DataFrame([to_dict(r) for r in agg_sentiment_records]) if agg_sentiment_records else pd.DataFrame()

        agg_coverage_records = db.aggregatedcoverage.find_many()
        agg_coverage = pd.DataFrame([to_dict(r) for r in agg_coverage_records]) if agg_coverage_records else pd.DataFrame()

        explain_records = db.uiexplaindata.find_many()
        explain_data = pd.DataFrame([to_dict(r) for r in explain_records]) if explain_records else pd.DataFrame()

        omissions_records = db.potentialomission.find_many()
        omissions = pd.DataFrame([to_dict(r) for r in omissions_records]) if omissions_records else pd.DataFrame()

        logging.info(f"Loaded from DB: sentiment={len(agg_sentiment)}, coverage={len(agg_coverage)}, explain={len(explain_data)}, omissions={len(omissions)}")
    except Exception as e:
        logging.exception(f"Error loading data from DB: {e}")
        agg_sentiment = pd.DataFrame()
        agg_coverage = pd.DataFrame()
        explain_data = pd.DataFrame()
        omissions = pd.DataFrame()
    finally:
        db.disconnect()

    return agg_sentiment, agg_coverage, explain_data, omissions

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

    selected_entity = st.selectbox("Select Entity to track:", list(entities) if len(entities) > 0 else ["No entities available"]) 

    if len(entities) > 0 and selected_entity != "No entities available":
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
