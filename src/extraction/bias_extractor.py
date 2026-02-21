import ast
import logging
import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

analyzer = SentimentIntensityAnalyzer()

def get_sentence_sentiment(sentence):
    """Returns the compound sentiment score for a sentence."""
    return analyzer.polarity_scores(sentence)['compound']

def extract_entity_sentiment(row):
    """
    Calculates sentiment for each entity in an article.
    We approximate this by finding the sentiment of the sentences mentioning the entity.
    """
    try:
        # String representations of lists need to be evaluated if read from CSV
        entities = ast.literal_eval(row['entities']) if isinstance(row['entities'], str) else row['entities']
        sentences = ast.literal_eval(row['sentences']) if isinstance(row['sentences'], str) else row['sentences']
    except Exception as e:
        logging.error(f"Error parsing entities/sentences for article {row.get('url', 'Unknown')}: {e}")
        return []

    entity_sentiments = []
    
    # Very basic approach: if entity is in a sentence, that sentence's sentiment contributes to the entity's sentiment
    for ent in entities:
        ent_text = ent['text']
        m_sentences = [s for s in sentences if ent_text in s]
        
        if not m_sentences:
            continue
            
        # Calculate average sentiment of mentioning sentences
        scores = [get_sentence_sentiment(s) for s in m_sentences]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        # Keep track of the most strongly opinionated sentence for explainability
        max_impact_sentence = max(m_sentences, key=lambda s: abs(get_sentence_sentiment(s))) if m_sentences else ""
        
        entity_sentiments.append({
            "entity": ent_text,
            "label": ent['label'],
            "sentiment": avg_score,
            "mention_count": len(m_sentences),
            "example_sentence": max_impact_sentence,
            "example_sentence_score": get_sentence_sentiment(max_impact_sentence) if max_impact_sentence else 0
        })
        
    return entity_sentiments

def extract_signals(input_csv="data/processed_articles.csv", output_csv="data/article_signals.csv"):
    logging.info(f"Loading preprocessed data from {input_csv}")
    try:
        df = pd.read_csv(input_csv)
    except FileNotFoundError:
        logging.error(f"Input file {input_csv} not found.")
        return
        
    if df.empty:
        logging.warning("Dataset is empty.")
        return

    logging.info("Extracting entity-level sentiment and mentions...")
    
    # Extract entity sentiments
    df['entity_sentiments'] = df.apply(extract_entity_sentiment, axis=1)
    
    # We will compute omission proxy later during the aggregation phase across outlets.
    # At the article level, we just need the sentiments and mention counts.
    
    logging.info(f"Extraction complete. Saving to {output_csv}")
    df.to_csv(output_csv, index=False)
    logging.info("Done.")

if __name__ == "__main__":
    extract_signals()
