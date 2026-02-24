import ast
import logging
import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

analyzer = SentimentIntensityAnalyzer()

def get_sentence_sentiment(sentence):
    """Returns the compound sentiment score for a sentence."""
    return analyzer.polarity_scores(sentence)['compound']

def extract_entity_sentiment(article):
    """
    Calculates sentiment for each entity in an article.
    We approximate this by finding the sentiment of the sentences mentioning the entity.
    """
    import json
    try:
        entities = article.entities
        if isinstance(entities, str):
            entities = json.loads(entities)
        
        sentences = article.sentences
        if isinstance(sentences, str):
            sentences = json.loads(sentences)
            
        if not entities or not sentences:
            return []
    except Exception as e:
        logging.error(f"Error parsing entities/sentences for article {article.url}: {e}")
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

def extract_signals():
    from prisma import Prisma
    import json
    
    logging.info("Connecting to DB...")
    db = Prisma()
    db.connect()
    
    try:
        # Fetch articles and filter in Python to avoid Prisma JSON null query issues
        all_articles = db.article.find_many()
        articles = [a for a in all_articles if a.entities is not None and a.entity_sentiments is None]
        
        if not articles:
            logging.warning("No new articles require bias extraction.")
            return

        logging.info("Extracting entity-level sentiment and mentions...")
        
        for article in articles:
            sentiments = extract_entity_sentiment(article)
            
            db.article.update(
                where={'id': article.id},
                data={'entity_sentiments': json.dumps(sentiments)}
            )
            
        logging.info("Extraction complete.")
    except Exception as e:
        logging.error(f"DB Error during sentiment extraction: {e}")
    finally:
        db.disconnect()
        logging.info("Done.")

if __name__ == "__main__":
    extract_signals()
