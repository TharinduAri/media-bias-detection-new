import ast
import logging
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def format_explainability_data():
    from prisma import Prisma
    import json
    import pandas as pd
    
    logging.info("Connecting to DB...")
    db = Prisma()
    db.connect()
    
    try:
        all_articles = db.article.find_many()
        articles = [a for a in all_articles if a.entity_sentiments is not None]
        
        if not articles:
            logging.warning("No data to explain.")
            return

        flattened_data = []
        for article in articles:
            if not article.entity_sentiments:
                continue
                
            ent_sents = article.entity_sentiments
            if isinstance(ent_sents, str):
                ent_sents = json.loads(ent_sents)
                
            year_month = article.date.strftime('%Y-%m')
            
            for ent in ent_sents:
                example_sentence = ent.get('example_sentence', '')
                if not example_sentence:
                    continue
                    
                sentiment = ent.get('sentiment', 0.0)
                
                flattened_data.append({
                    'outlet': article.outlet,
                    'year_month': year_month,
                    'date': article.date,
                    'entity': ent['entity'],
                    'label': ent['label'],
                    'sentiment': float(sentiment),
                    'mention_count': int(ent['mention_count']),
                    'article_url': article.url,
                    'example_sentence': example_sentence,
                    'example_sentence_score': float(ent.get('example_sentence_score', 0.0)),
                    'abs_sentiment': abs(float(sentiment))
                })

        if not flattened_data:
            logging.warning("No valid explainability instances found.")
            return

        df = pd.DataFrame(flattened_data)
        
        # Sort by entity, then by absolute sentiment descending to get the most opinionated statements
        df_sorted = df.sort_values(by=['entity', 'abs_sentiment'], ascending=[True, False])
        
        # Kept top 5 per entity per outlet
        top_examples = df_sorted.groupby(['outlet', 'entity']).head(5)
        
        db.uiexplaindata.delete_many()
        records = top_examples.to_dict('records')
        
        for r in records:
            if isinstance(r['date'], pd.Timestamp):
                r['date'] = r['date'].to_pydatetime()
                
        if records:
            db.uiexplaindata.create_many(data=records)
            
        logging.info("Saved formatted explainability data to DB")
    except Exception as e:
        logging.error(f"DB Error compiling explainability data: {e}")
    finally:
        db.disconnect()
        logging.info("Done.")

if __name__ == "__main__":
    format_explainability_data()
