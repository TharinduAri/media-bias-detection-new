import ast
import logging
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def format_explainability_data(input_csv="data/explainability_data.csv", output_csv="data/ui_explain_data.csv"):
    """
    Prepares data specifically for the UI explainability view.
    Filters out rows with empty example sentences and sorts by absolute sentiment score 
    to show the most polarizing examples first.
    """
    logging.info(f"Loading explainability data from {input_csv}")
    try:
        df = pd.read_csv(input_csv)
    except FileNotFoundError:
        logging.error(f"Input file {input_csv} not found.")
        return

    if df.empty:
        logging.warning("Explainability dataset is empty.")
        return
        
    logging.info("Formatting data for UI...")
    
    # Filter rows that actually have an example sentence
    df = df[df['example_sentence'].notna() & (df['example_sentence'] != '')]
    
    # Calculate absolute sentiment for sorting (most polarized first)
    df['abs_sentiment'] = df['sentiment'].abs()
    
    # Sort by entity, then by absolute sentiment descending to get the most opinionated statements
    # when exploring a specific entity in the UI
    df_sorted = df.sort_values(by=['entity', 'abs_sentiment'], ascending=[True, False])
    
    # For UI performance and clarity, keep only top N most polarizing sentences per entity per outlet
    # For MVP, maybe keep top 5
    top_examples = df_sorted.groupby(['outlet', 'entity']).head(5)
    
    top_examples.to_csv(output_csv, index=False)
    logging.info(f"Saved formatted explainability data to {output_csv}")
    logging.info("Done.")

if __name__ == "__main__":
    format_explainability_data()
