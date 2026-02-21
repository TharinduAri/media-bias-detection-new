import ast
import logging
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def process_entity_sentiments(row):
    """Parses the stringified list of dictionaries back into a Python list."""
    try:
        val = row['entity_sentiments']
        if pd.isna(val) or val == '[]':
            return []
        return ast.literal_eval(val) if isinstance(val, str) else val
    except Exception as e:
        logging.error(f"Error parsing entity_sentiments for row: {e}")
        return []

def aggregate_data(input_csv="data/article_signals.csv",
                  sentiment_out="data/agg_sentiment.csv",
                  coverage_out="data/agg_coverage.csv"):
                      
    logging.info(f"Loading article signals from {input_csv}")
    try:
        df = pd.read_csv(input_csv)
    except FileNotFoundError:
        logging.error(f"Input file {input_csv} not found.")
        return

    if df.empty:
        logging.warning("Dataset is empty.")
        return

    # Convert date strings to datetime objects
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    
    # Create a Year-Month column for longitudinal grouping
    df['year_month'] = df['date'].dt.to_period('M').astype(str)

    # Parse entity sentiments
    df['parsed_sentiments'] = df.apply(process_entity_sentiments, axis=1)

    # Flatten the data: Create a row for every entity mention in every article
    flattened_data = []
    for _, row in df.iterrows():
        for ent in row['parsed_sentiments']:
            flattened_data.append({
                'outlet': row['outlet'],
                'year_month': row['year_month'],
                'date': row['date'],
                'entity': ent['entity'],
                'label': ent['label'],
                'sentiment': ent['sentiment'],
                'mention_count': ent['mention_count'],
                'article_url': row['url'],
                'example_sentence': ent.get('example_sentence', ''),
                'example_sentence_score': ent.get('example_sentence_score', 0.0)
            })

    if not flattened_data:
        logging.warning("No entity sentiment data found to aggregate.")
        return

    flat_df = pd.DataFrame(flattened_data)

    # --- 1. Aggregate Sentiment ---
    # Group by Outlet, Time (Month), and Entity
    logging.info("Aggregating sentiment data...")
    agg_sentiment = flat_df.groupby(['outlet', 'year_month', 'entity', 'label']).agg(
        avg_sentiment=('sentiment', 'mean'),
        total_mentions=('mention_count', 'sum'),
        article_count=('article_url', 'nunique')
    ).reset_index()

    # Save mapping for explainability (top sentences per entity per outlet)
    # We'll just save the flattened data for the UI to query
    flat_df.to_csv("data/explainability_data.csv", index=False)
    
    # Filter to show only relatively prominent entities to reduce noise (e.g., mentioned in >1 article)
    # For MVP with limited data, we might not want to filter too much
    agg_sentiment = agg_sentiment[agg_sentiment['total_mentions'] > 1]
    
    agg_sentiment.to_csv(sentiment_out, index=False)
    logging.info(f"Saved aggregated sentiment to {sentiment_out}")


    # --- 2. Aggregate Coverage & Identify Omissions ---
    logging.info("Aggregating coverage data...")
    # Coverage frequency: total mentions of an entity across all time for an outlet
    agg_coverage = flat_df.groupby(['outlet', 'entity', 'label']).agg(
        total_mentions=('mention_count', 'sum'),
        article_count=('article_url', 'nunique')
    ).reset_index()

    # Omission logic: Find entities covered by at least one outlet but entirely missing in another
    # Create a pivot table: Entities as rows, Outlets as columns, values are mention counts
    # Use pivot_table with an aggregation function to handle potential duplicate entities per outlet across months
    pivot_coverage = agg_coverage.pivot_table(index='entity', columns='outlet', values='total_mentions', aggfunc='sum').fillna(0)
    
    # Find entities that are highly covered by one, but 0 by another
    omissions = []
    outlets = pivot_coverage.columns
    
    # Simple logic for MVP: if max mentions > 5 and min mentions == 0
    for entity, row in pivot_coverage.iterrows():
        max_val = row.max()
        min_val = row.min()
        if max_val > 2 and min_val == 0:  # Using low threshold for the MVP's tiny dataset
            omitting_outlets = row[row == 0].index.tolist()
            covering_outlets = row[row == max_val].index.tolist()
            omissions.append({
                'entity': entity,
                'covered_mostly_by': covering_outlets[0] if covering_outlets else "Unknown",
                'max_mentions': max_val,
                'omitted_by': ", ".join(omitting_outlets)
            })

    omissions_df = pd.DataFrame(omissions)
    if not omissions_df.empty:
         omissions_df.to_csv("data/potential_omissions.csv", index=False)
         logging.info("Saved potential omissions to data/potential_omissions.csv")
    
    agg_coverage.to_csv(coverage_out, index=False)
    logging.info(f"Saved aggregated coverage to {coverage_out}")
    logging.info("Done.")

if __name__ == "__main__":
    aggregate_data()
