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

def preprocess_data(input_csv="data/raw_articles.csv", output_csv="data/processed_articles.csv"):
    logging.info(f"Loading data from {input_csv}")
    try:
        df = pd.read_csv(input_csv)
    except FileNotFoundError:
        logging.error(f"Input file {input_csv} not found.")
        return
    
    if df.empty:
        logging.warning("Input dataset is empty.")
        return
        
    logging.info("Starting text preprocessing...")
    
    # Clean full text
    df['clean_text'] = df['text'].apply(clean_text)
    
    # Segment into sentences (useful for explainability and sentence-level sentiment later)
    df['sentences'] = df['clean_text'].apply(segment_sentences)
    
    # Extract entities from the clean text
    df['entities'] = df['clean_text'].apply(extract_entities)
    
    logging.info(f"Preprocessing complete. Saving to {output_csv}")
    df.to_csv(output_csv, index=False)
    logging.info("Done.")

if __name__ == "__main__":
    preprocess_data()
