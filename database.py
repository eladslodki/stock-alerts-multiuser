import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable not set")
        
        # Railway uses postgres:// but psycopg2 needs postgresql://
        if self.database_url.startswith('postgres://'):
            self.database_url = self.database_url.replace('postgres://', 'postgresql://', 1)
    
    @contextmanager
    def get_connection(self):
        conn = psycopg2.connect(self.database_url)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()
    
    def execute(self, query, params=None, fetchone=False, fetchall=False):
        """Execute query and return results"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params or ())
                
                if fetchone:
                    return cur.fetchone()
                elif fetchall:
                    return cur.fetchall()
                elif query.strip().upper().startswith('INSERT') and 'RETURNING' in query.upper():
                    return cur.fetchone()
                return None
    
    def run_migrations(self):
        """Run database migrations automatically"""
        logger.info("=" * 60)
        logger.info("🔄 Running database migrations...")
        logger.info("=" * 60)
        
        migrations = [
            # Migration 1: Add new columns to trades table
            """
            ALTER TABLE trades ADD COLUMN IF NOT EXISTS stop_loss DECIMAL(10, 2);
            """,
            """
            ALTER TABLE trades ADD COLUMN IF NOT EXISTS take_profit DECIMAL(10, 2);
            """,
            """
            ALTER TABLE trades ADD COLUMN IF NOT EXISTS is_closed BOOLEAN DEFAULT FALSE;
            """,
            """
            ALTER TABLE alerts ADD COLUMN IF NOT EXISTS last_price DECIMAL(10, 2);
            """,
            """
            ALTER TABLE alerts ADD COLUMN IF NOT EXISTS crossed BOOLEAN DEFAULT FALSE;
            """,
            """
            ALTER TABLE trades ADD COLUMN IF NOT EXISTS close_price DECIMAL(10, 2);
            """,
            """
            ALTER TABLE trades ADD COLUMN IF NOT EXISTS close_date DATE;
            """,
            """
            ALTER TABLE trades ADD COLUMN IF NOT EXISTS notes TEXT;
            """,
            """
            ALTER TABLE alerts ADD COLUMN IF NOT EXISTS alert_type VARCHAR(10) DEFAULT 'price' CHECK (alert_type IN ('price', 'ma'));
            """,
            """
            ALTER TABLE alerts ADD COLUMN IF NOT EXISTS ma_period INTEGER;
            """,
            """
            ALTER TABLE alerts ADD COLUMN IF NOT EXISTS ma_value DECIMAL(10, 2);
            """,
            # Migration 2: Add indexes
            """
            CREATE INDEX IF NOT EXISTS idx_trades_closed ON trades(user_id, is_closed);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_trades_close_date ON trades(close_date DESC) WHERE close_date IS NOT NULL;
            """,
            """
            CREATE TABLE IF NOT EXISTS alert_triggers (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            ticker VARCHAR(10) NOT NULL,
            alert_type VARCHAR(10) NOT NULL,
            alert_params_json JSONB NOT NULL,
            triggered_at TIMESTAMP DEFAULT NOW(),
            price_at_trigger DECIMAL(10, 2) NOT NULL,
            explanation_text TEXT,
            metrics_json JSONB
            );
            CREATE INDEX IF NOT EXISTS idx_triggers_user_time ON alert_triggers(user_id, triggered_at DESC);
            """,
            """
            CREATE TABLE IF NOT EXISTS market_anomalies (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            ticker VARCHAR(10) NOT NULL,
            anomaly_type VARCHAR(20) NOT NULL,
            metrics_json JSONB NOT NULL,
            detected_at TIMESTAMP DEFAULT NOW(),
            severity VARCHAR(10) DEFAULT 'medium',
            is_read BOOLEAN DEFAULT FALSE
            );
            CREATE INDEX IF NOT EXISTS idx_anomalies_user_time ON market_anomalies(user_id, detected_at DESC);
            """,
            """
            CREATE TABLE IF NOT EXISTS forex_amd_alerts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                symbol VARCHAR(20) NOT NULL,
                direction VARCHAR(10) NOT NULL,
                session VARCHAR(20) NOT NULL,
                accumulation_start TIMESTAMP NOT NULL,
                accumulation_end TIMESTAMP NOT NULL,
                accumulation_range DECIMAL(10, 5) NOT NULL,
                sweep_time TIMESTAMP NOT NULL,
                sweep_level DECIMAL(10, 5) NOT NULL,
                sweep_strength DECIMAL(5, 2) NOT NULL,
                displacement_time TIMESTAMP NOT NULL,
                displacement_candle_body DECIMAL(10, 5) NOT NULL,
                displacement_vs_avg DECIMAL(5, 2) NOT NULL,
                ifvg_time TIMESTAMP NOT NULL,
                ifvg_high DECIMAL(10, 5) NOT NULL,
                ifvg_low DECIMAL(10, 5) NOT NULL,
                atr_at_setup DECIMAL(10, 5) NOT NULL,
                volatility_score DECIMAL(5, 2) NOT NULL,
                setup_quality INTEGER NOT NULL,
                detected_at TIMESTAMP DEFAULT NOW(),
                is_read BOOLEAN DEFAULT FALSE
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_forex_amd_user_symbol ON forex_amd_alerts(user_id, symbol);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_forex_amd_detected ON forex_amd_alerts(detected_at);
            """,
            """
            CREATE TABLE IF NOT EXISTS forex_watchlist (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                symbol VARCHAR(20) NOT NULL,
                added_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, symbol)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS forex_amd_state (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                symbol VARCHAR(20) NOT NULL,
                current_state INTEGER DEFAULT 0,
                accumulation_data TEXT,
                sweep_data TEXT,
                displacement_data TEXT,
                last_update TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, symbol)
            );
            """,
        ]
        
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    for i, migration in enumerate(migrations, 1):
                        try:
                            cur.execute(migration)
                            logger.info(f"✅ Migration {i}/{len(migrations)} completed")
                        except Exception as e:
                            logger.warning(f"⚠️  Migration {i} skipped (may already exist): {e}")
            
            logger.info("=" * 60)
            logger.info("✅ All migrations completed successfully!")
            logger.info("=" * 60)
            return True
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            logger.error("=" * 60)
            return False
    
    def init_schema(self):
        """Initialize database schema"""
        try:
            # First run migrations to add new columns
            self.run_migrations()
            
            # Then create tables if they don't exist
            schema = """
            -- Users table
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );
            
            -- Alerts table
            CREATE TABLE IF NOT EXISTS alerts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                ticker VARCHAR(10) NOT NULL,
                target_price DECIMAL(10, 2) NOT NULL,
                current_price DECIMAL(10, 2),
                direction VARCHAR(4) NOT NULL CHECK (direction IN ('up', 'down')),
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW(),
                triggered_at TIMESTAMP,
                triggered_price DECIMAL(10, 2)
            );
            
            -- Portfolio table
            CREATE TABLE IF NOT EXISTS portfolios (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                cash DECIMAL(15, 2) NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id)
            );

            -- Trades table (base structure - new columns added via migrations)
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                ticker VARCHAR(10) NOT NULL,
                buy_price DECIMAL(10, 2) NOT NULL,
                quantity DECIMAL(10, 4) NOT NULL,
                position_size DECIMAL(15, 2) NOT NULL,
                risk_amount DECIMAL(15, 2) NOT NULL,
                timeframe VARCHAR(10) NOT NULL CHECK (timeframe IN ('Long', 'Swing')),
                trade_date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
            
            -- Indexes for performance
            CREATE INDEX IF NOT EXISTS idx_alerts_user_active 
                ON alerts(user_id, active);
            CREATE INDEX IF NOT EXISTS idx_alerts_active 
                ON alerts(active) WHERE active = TRUE;
            CREATE INDEX IF NOT EXISTS idx_users_email 
                ON users(email);
            CREATE INDEX IF NOT EXISTS idx_portfolios_user ON portfolios(user_id);
            CREATE INDEX IF NOT EXISTS idx_trades_user ON trades(user_id);
            CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(trade_date DESC);
            """
            
            
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(schema)
            
            logger.info("✅ Database schema initialized")
        except Exception as e:
            logger.error(f"Schema init error (may be normal if tables exist): {e}")

db = Database()
