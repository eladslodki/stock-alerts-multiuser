import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

class Database:
    def init_schema(self):
        """Initialize database schema"""
        try:
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
            
            -- Indexes for performance
            CREATE INDEX IF NOT EXISTS idx_alerts_user_active 
                ON alerts(user_id, active);
            CREATE INDEX IF NOT EXISTS idx_alerts_active 
                ON alerts(active) WHERE active = TRUE;
            CREATE INDEX IF NOT EXISTS idx_users_email 
                ON users(email);
            """
            
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(schema)
            
            logger.info("Database schema initialized")
        except Exception as e:
            logger.error(f"Schema init error (may be normal if tables exist): {e}")
    
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
    
    def init_schema(self):
        """Initialize database schema"""
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
        
        -- Indexes for performance
        CREATE INDEX IF NOT EXISTS idx_alerts_user_active 
            ON alerts(user_id, active);
        CREATE INDEX IF NOT EXISTS idx_alerts_active 
            ON alerts(active) WHERE active = TRUE;
        CREATE INDEX IF NOT EXISTS idx_users_email 
            ON users(email);
        """
        
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(schema)
        
        logger.info("Database schema initialized")

db = Database()