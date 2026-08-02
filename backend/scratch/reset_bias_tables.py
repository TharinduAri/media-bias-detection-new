from api.database import db_manager, Base
from api import models

def reset_bias_tables():
    target_tables = [
        models.ArticleBiasScore.__table__,
        models.ArticleBiasEvidence.__table__,
        models.ArticleEmbedding.__table__,
        models.OutletBiasProfile.__table__,
        models.BiasRunLog.__table__,
    ]
    print("Dropping bias tables...")
    Base.metadata.drop_all(bind=db_manager.engine, tables=target_tables)
    print("Recreating bias tables...")
    Base.metadata.create_all(bind=db_manager.engine, tables=target_tables)
    print("Done.")

if __name__ == "__main__":
    reset_bias_tables()
