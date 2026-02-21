import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Sri Lanka Media Bias MVP", layout="wide")

st.title("Media Bias Detection MVP")
st.markdown("""
This dashboard demonstrates media bias as a longitudinal, outlet-level phenomenon.
It uses proxy signals (entity sentiment and coverage frequency) rather than binary classification.
""")

# --- Load Data ---
@st.cache_data
def load_data():
    try:
        agg_sentiment = pd.read_csv("data/agg_sentiment.csv")
        agg_coverage = pd.read_csv("data/agg_coverage.csv")
        explain_data = pd.read_csv("data/ui_explain_data.csv")
        omissions = pd.read_csv("data/potential_omissions.csv")
        return agg_sentiment, agg_coverage, explain_data, omissions
    except FileNotFoundError:
        return None, None, None, None

agg_sentiment, agg_coverage, explain_data, omissions = load_data()

if agg_sentiment is None:
    st.error("Data files not found. Please run the pipeline scripts first.")
    st.stop()

# --- Dashboard Layout ---
tab1, tab2, tab3 = st.tabs(["Longitudinal Sentiment", "Topic Coverage & Omissions", "Explainability"])

with tab1:
    st.header("Outlet Sentiment Trends")
    st.markdown("Tracks the average sentiment expressed toward specific entities over time by different outlets.")
    
    entities = agg_sentiment['entity'].unique()
    selected_entity = st.selectbox("Select Entity to track:", entities)
    
    entity_data = agg_sentiment[agg_sentiment['entity'] == selected_entity]
    
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
    top_entities = agg_coverage.groupby('entity')['total_mentions'].sum().nlargest(15).index
    coverage_filtered = agg_coverage[agg_coverage['entity'].isin(top_entities)]
    
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
