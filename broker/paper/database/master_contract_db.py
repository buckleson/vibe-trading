"""Master contract of the paper broker, built locally with no download.

``master_contract_download()`` replaces the symtoken table with the bundled
universe of ``broker.paper.database.instruments``: NSE and BSE equities, NSE
and BSE indices, near-month index futures, and NIFTY / BANKNIFTY option chains
whose expiries are computed from today's date and whose strikes are centred on
the underlying's current price (Yahoo Finance or simulated).
"""

import os

import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from broker.paper.database.instruments import build_instruments
from database.engine_factory import create_db_engine
from extensions import socketio
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_db_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class SymToken(Base):
    __tablename__ = "symtoken"
    id = Column(Integer, Sequence("symtoken_id_seq"), primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    brsymbol = Column(String, nullable=False, index=True)
    name = Column(String)
    exchange = Column(String, index=True)
    brexchange = Column(String, index=True)
    token = Column(String, index=True)
    expiry = Column(String)
    strike = Column(Float)
    lotsize = Column(Integer)
    instrumenttype = Column(String)
    tick_size = Column(Float)
    contract_value = Column(Float)

    __table_args__ = (Index("idx_symbol_exchange", "symbol", "exchange"),)


def init_db():
    logger.info("Initializing Master Contract DB")
    Base.metadata.create_all(bind=engine)


def delete_symtoken_table():
    logger.info("Deleting Symtoken Table")
    SymToken.query.delete()
    db_session.commit()


def copy_from_dataframe(df):
    logger.info("Performing Bulk Insert")
    records = df.to_dict(orient="records")
    try:
        if records:
            db_session.bulk_insert_mappings(SymToken, records)
            db_session.commit()
            logger.info(f"Bulk insert completed successfully with {len(records)} new records.")
        else:
            logger.info("No new records to insert.")
    except Exception:
        logger.exception("Error during bulk insert")
        db_session.rollback()
        raise


def build_master_contract_df() -> pd.DataFrame:
    """The paper universe as a symtoken-shaped DataFrame, strikes centred on the current spot."""

    def spot_of(underlying):
        from broker.paper.api.market_data import underlying_spot

        price, _source = underlying_spot(underlying)
        return price

    return pd.DataFrame(build_instruments(spot_of=spot_of))


def master_contract_download():
    logger.info("Building the paper broker master contract")
    try:
        token_df = build_master_contract_df()
        init_db()
        delete_symtoken_table()
        copy_from_dataframe(token_df)
        logger.info(f"Paper master contract ready: {len(token_df)} symbols")
        return socketio.emit(
            "master_contract_download", {"status": "success", "message": "Successfully Downloaded"}
        )
    except Exception as e:
        logger.exception("Paper master contract build failed")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})
    finally:
        db_session.remove()


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
