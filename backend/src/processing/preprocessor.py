import logging
import re
import pandas as pd
import spacy

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load the spaCy English model for NER and sentence segmentation
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    logging.error("SpaCy model 'en_core_web_sm' not found. Please run 'python -m spacy download en_core_web_sm'")
    raise

def clean_text(text):
    """Removes boilerplate, extra whitespace, and basic HTML artifacts."""
    if not isinstance(text, str):
        return ""
    
    # Remove excessive newlines and tabs
    text = re.sub(r'[\n\t\r]+', ' ', text)
    # Remove common boilerplate phrases (simple example)
    text = re.sub(r'(?i)click here to read more\b', '', text)
    text = re.sub(r'(?i)subscribe to our newsletter\b', '', text)
    # Condense multiple spaces into one
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def segment_sentences(text):
    """Uses spaCy to split text into sentences."""
    if not text:
        return []
    
    doc = nlp(text)
    return [sent.text.strip() for sent in doc.sents if len(sent.text.strip()) > 5]

def extract_entities(text):
    """Extracts Named Entities (PERSON, ORG, GPE, NORP) using spaCy."""
    if not text:
        return []
    
    doc = nlp(text)
    entities = []
    
    # Focus on people, organizations, geopolitical entities, and groups
    target_labels = {"PERSON", "ORG", "GPE", "NORP"}
    
    for ent in doc.ents:
        if ent.label_ in target_labels:
            entities.append({
                "text": ent.text.strip(),
                "label": ent.label_
            })
            
    # Remove exact duplicates for the same article to avoid over-counting in simple metrics
    unique_entities = []
    seen = set()
    for ent in entities:
        key = (ent['text'], ent['label'])
        if key not in seen:
            seen.add(key)
            unique_entities.append(ent)
            
    return unique_entities

def preprocess_data():
    from prisma import Prisma
    import json
    
    logging.info("Connecting to DB...")
    db = Prisma()
    db.connect()
    
    try:
        # Fetch articles that require processing
        articles = db.article.find_many(where={'clean_text': None})
        
        if not articles:
            logging.warning("No new articles to preprocess.")
            return

        logging.info(f"Starting text preprocessing for {len(articles)} articles...")
        
        for article in articles:
            text = article.text
            if not text:
                continue
                
            clean_t = clean_text(text)
            sentences = segment_sentences(clean_t)
            entities = extract_entities(clean_t)
            
            # Update article
            # Prisma python accepts string for Json fields.
            db.article.update(
                where={'id': article.id},
                data={
                    'clean_text': clean_t,
                    'sentences': json.dumps(sentences),
                    'entities': json.dumps(entities)
                }
            )
            
        logging.info("Preprocessing complete.")
    except Exception as e:
        logging.error(f"DB Error during preprocessing: {e}")
    finally:
        db.disconnect()
        logging.info("Done.")

if __name__ == "__main__":
    preprocess_data()
