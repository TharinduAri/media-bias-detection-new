import ast
import logging
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def aggregate_data():
    from prisma import Prisma
    import json
    
    logging.info("Connecting to DB...")
    db = Prisma()
    db.connect()
    
    try:
        all_articles = db.article.find_many()
        articles = [a for a in all_articles if a.entity_sentiments is not None]
        
        if not articles:
            logging.warning("No articles with entity sentiments found.")
            return

        # Flatten the data: Create a row for every entity mention in every article
        flattened_data = []
        for article in articles:
            if not article.entity_sentiments:
                continue
            
            ent_sents = article.entity_sentiments
            if isinstance(ent_sents, str):
                ent_sents = json.loads(ent_sents)
                
            year_month = article.date.strftime('%Y-%m')
            
            for ent in ent_sents:
                flattened_data.append({
                    'outlet': article.outlet,
                    'year_month': year_month,
                    'date': article.date,
                    'entity': ent['entity'],
                    'label': ent['label'],
                    'sentiment': ent['sentiment'],
                    'mention_count': ent['mention_count'],
                    'article_url': article.url,
                    'example_sentence': ent.get('example_sentence', ''),
                    'example_sentence_score': ent.get('example_sentence_score', 0.0)
                })

        if not flattened_data:
            logging.warning("No entity sentiment data found to aggregate.")
            return

        flat_df = pd.DataFrame(flattened_data)

        # --- 1. Aggregate Sentiment ---
        logging.info("Aggregating sentiment data...")
        agg_sentiment = flat_df.groupby(['outlet', 'year_month', 'entity', 'label']).agg(
            avg_sentiment=('sentiment', 'mean'),
            total_mentions=('mention_count', 'sum'),
            article_count=('article_url', 'nunique')
        ).reset_index()

        # Filter to show only relatively prominent entities
        agg_sentiment = agg_sentiment[agg_sentiment['total_mentions'] > 1]
        
        # Clear existing & Insert
        db.aggregatedsentiment.delete_many()
        sent_records = []
        for _, row in agg_sentiment.iterrows():
            sent_records.append({
                'outlet': row['outlet'],
                'year_month': row['year_month'],
                'entity': row['entity'],
                'label': row['label'],
                'avg_sentiment': float(row['avg_sentiment']),
                'total_mentions': int(row['total_mentions']),
                'article_count': int(row['article_count'])
            })
        if sent_records:
            db.aggregatedsentiment.create_many(data=sent_records)
        logging.info("Saved aggregated sentiment to DB.")

        # --- 2. Aggregate Coverage & Identify Omissions ---
        logging.info("Aggregating coverage data...")
        agg_coverage = flat_df.groupby(['outlet', 'entity', 'label']).agg(
            total_mentions=('mention_count', 'sum'),
            article_count=('article_url', 'nunique')
        ).reset_index()

        db.aggregatedcoverage.delete_many()
        cov_records = []
        for _, row in agg_coverage.iterrows():
            cov_records.append({
                'outlet': row['outlet'],
                'entity': row['entity'],
                'label': row['label'],
                'total_mentions': int(row['total_mentions']),
                'article_count': int(row['article_count'])
            })
        if cov_records:
            db.aggregatedcoverage.create_many(data=cov_records)
        logging.info("Saved aggregated coverage to DB.")

        # Omissions logic
        pivot_coverage = agg_coverage.pivot_table(index='entity', columns='outlet', values='total_mentions', aggfunc='sum').fillna(0)
        
        omissions = []
        for entity, row in pivot_coverage.iterrows():
            max_val = row.max()
            min_val = row.min()
            if max_val > 2 and min_val == 0:
                omitting_outlets = row[row == 0].index.tolist()
                covering_outlets = row[row == max_val].index.tolist()
                omissions.append({
                    'entity': entity,
                    'covered_mostly_by': covering_outlets[0] if covering_outlets else "Unknown",
                    'max_mentions': int(max_val),
                    'omitted_by': ", ".join(omitting_outlets)
                })

        db.potentialomission.delete_many()
        if omissions:
             db.potentialomission.create_many(data=omissions)
             logging.info("Saved potential omissions to DB.")

        logging.info("Done.")
    except Exception as e:
        logging.error(f"DB Error during aggregation: {e}")
    finally:
        db.disconnect()

if __name__ == "__main__":
    aggregate_data()
