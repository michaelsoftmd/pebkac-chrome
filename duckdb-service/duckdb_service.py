"""
DuckDB Cache Service for structured data storage and analytics
"""

from fastapi import FastAPI, HTTPException, Query, Body
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import duckdb
import os
import logging
from datetime import datetime, timedelta
import json
import asyncio
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_PATH = os.getenv("DUCKDB_DATABASE", "/data/cache.db")
MEMORY_LIMIT = os.getenv("DUCKDB_MEMORY_LIMIT", "1GB")

# Global connection pool
class DuckDBPool:
    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = db_path
        self.pool_size = pool_size
        self.connections = []
        self.available = asyncio.Queue()
        self.initialized = False
    
    async def init(self):
        """Initialize connection pool and create tables"""
        if not self.initialized:
            try:
                # Ensure directory exists
                os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
                
                # Create initial connection for setup
                conn = duckdb.connect(self.db_path)
                conn.execute(f"SET memory_limit='{MEMORY_LIMIT}'")
                
                # Create sequence FIRST (before tables that use it)
                conn.execute("""
                    CREATE SEQUENCE IF NOT EXISTS seq_cached_elements START 1
                """)
                
                # Create tables
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cached_pages (
                        cache_key VARCHAR PRIMARY KEY,
                        url VARCHAR NOT NULL,
                        title VARCHAR,
                        content TEXT,
                        extracted_at TIMESTAMP,
                        ttl_expires TIMESTAMP,
                        content_hash VARCHAR(32),
                        word_count INTEGER,
                        summary TEXT,
                        key_points JSON,
                        entities JSON,
                        selector_used VARCHAR,
                        extraction_method VARCHAR,
                        success_rate DOUBLE
                    )
                """)
                
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cached_elements (
                        id INTEGER PRIMARY KEY DEFAULT nextval('seq_cached_elements'),
                        domain VARCHAR NOT NULL,
                        element_type VARCHAR NOT NULL,
                        selector VARCHAR NOT NULL,
                        success_count INTEGER DEFAULT 1,
                        fail_count INTEGER DEFAULT 0,
                        last_used TIMESTAMP,
                        avg_find_time_ms DOUBLE
                    )
                """)
                
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_domain_type 
                    ON cached_elements(domain, element_type)
                """)
                
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cached_workflows (
                        workflow_id VARCHAR PRIMARY KEY,
                        workflow_type VARCHAR,
                        input_hash VARCHAR(32),
                        result JSON,
                        created_at TIMESTAMP,
                        accessed_count INTEGER DEFAULT 1,
                        total_tokens_saved INTEGER
                    )
                """)
                
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cache_metrics (
                        timestamp TIMESTAMP,
                        metric_type VARCHAR,
                        metric_value DOUBLE,
                        metadata JSON
                    )
                """)
                
                conn.close()
                
                # Create connection pool
                for _ in range(self.pool_size):
                    conn = duckdb.connect(self.db_path)
                    conn.execute(f"SET memory_limit='{MEMORY_LIMIT}'")
                    self.connections.append(conn)
                    await self.available.put(conn)
                
                self.initialized = True
                logger.info(f"DuckDB pool initialized with {self.pool_size} connections")
            except Exception as e:
                logger.error(f"Failed to initialize DuckDB pool: {e}")
                raise
    
    async def acquire(self):
        """Get a connection from the pool"""
        if not self.initialized:
            await self.init()
        return await self.available.get()
    
    async def release(self, conn):
        """Return a connection to the pool"""
        await self.available.put(conn)
    
    async def close(self):
        """Close all connections"""
        for conn in self.connections:
            try:
                conn.close()
            except:
                pass
        self.connections.clear()
        self.initialized = False

# Initialize pool
db_pool = DuckDBPool(DB_PATH)

# Pydantic models
class CachedPage(BaseModel):
    cache_key: str
    url: str
    title: Optional[str] = None
    content: str
    content_hash: str
    word_count: int
    summary: Optional[str] = None
    key_points: Optional[List[str]] = None
    entities: Optional[List[str]] = None
    selector_used: Optional[str] = None
    extraction_method: Optional[str] = None
    ttl_seconds: int = 3600

class CachedElement(BaseModel):
    domain: str
    element_type: str
    selector: str
    success: bool = True
    find_time_ms: Optional[float] = None

class WorkflowCache(BaseModel):
    workflow_id: str
    workflow_type: str
    input_hash: str
    result: Dict[str, Any]
    tokens_saved: Optional[int] = None

class CacheStats(BaseModel):
    total_pages: int
    total_elements: int
    total_workflows: int
    avg_tokens_saved: float
    cache_size_mb: float
    oldest_entry: Optional[datetime]
    newest_entry: Optional[datetime]

# Application lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting DuckDB Cache Service...")
    try:
        await db_pool.init()
        logger.info("DuckDB pool initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize DuckDB pool: {e}")
        # Don't fail startup completely, but log the error
    yield
    # Shutdown
    logger.info("Shutting down DuckDB Cache Service...")
    await db_pool.close()

# Create FastAPI app - MUST BE BEFORE ANY DECORATORS
app = FastAPI(
    title="DuckDB Cache Service",
    description="Structured cache storage for browser automation",
    version="1.0.0",
    lifespan=lifespan
)

# NOW we can use decorators - Endpoints
@app.get("/")
async def root():
    """Service information"""
    return {
        "service": "DuckDB Cache Service",
        "version": "1.0.0",
        "database": DB_PATH,
        "memory_limit": MEMORY_LIMIT
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        conn = await db_pool.acquire()
        try:
            # Simple query that always works
            conn.execute("SELECT 1").fetchone()
            
            # Try to get table count, but handle if table doesn't exist
            try:
                result = conn.execute("SELECT COUNT(*) FROM cached_pages").fetchone()
                cached_pages = result[0] if result else 0
            except:
                cached_pages = 0  # Table doesn't exist yet
                
            await db_pool.release(conn)
            return {
                "status": "healthy",
                "cached_pages": cached_pages,
                "database": DB_PATH
            }
        except Exception as e:
            await db_pool.release(conn)
            raise e
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "database": DB_PATH
        }

@app.post("/store")
async def store_data(request: dict):
    """Generic data storage endpoint"""
    table = request.get("table")
    data = request.get("data")
    timestamp = request.get("timestamp", datetime.utcnow().isoformat())
    
    if not table or not data:
        raise HTTPException(status_code=400, detail="Missing table or data")
    
    conn = await db_pool.acquire()
    try:
        # Create table if it doesn't exist
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id INTEGER PRIMARY KEY,
            timestamp TIMESTAMP,
            data JSON
        )
        """
        conn.execute(create_table_sql)
        
        # Insert data
        insert_sql = f"""
        INSERT INTO {table} (timestamp, data) 
        VALUES (?, ?)
        """
        conn.execute(insert_sql, [timestamp, json.dumps(data)])
        
        return {"status": "stored", "table": table}
    finally:
        await db_pool.release(conn)

@app.post("/query")
async def query_data(request: dict):
    """Execute query and return results - READ ONLY"""
    query = request.get("query")
    
    if not query:
        raise HTTPException(status_code=400, detail="Missing query")
    
    # Only allow SELECT queries
    query_upper = query.strip().upper()
    if not query_upper.startswith(('SELECT', 'WITH', 'EXPLAIN')):
        raise HTTPException(status_code=403, detail="Only SELECT queries allowed")
    
    # Block dangerous keywords
    dangerous = ['DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'CREATE', 'TRUNCATE']
    if any(word in query_upper for word in dangerous):
        raise HTTPException(status_code=403, detail="Modification queries not allowed")
    
    conn = await db_pool.acquire()
    try:
        result = conn.execute(query)
        rows = result.fetchall()
        
        columns = [desc[0] for desc in result.description] if result.description else []
        results = [dict(zip(columns, row)) for row in rows]
        
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query error: {str(e)}")
    finally:
        await db_pool.release(conn)

@app.post("/cache/page")
async def cache_page(page: CachedPage):
    """Store a cached page"""
    conn = await db_pool.acquire()
    try:
        now = datetime.now()
        expires = now + timedelta(seconds=page.ttl_seconds)
        
        conn.execute("""
            INSERT OR REPLACE INTO cached_pages
            (cache_key, url, title, content, extracted_at, ttl_expires, 
             content_hash, word_count, summary, key_points, entities,
             selector_used, extraction_method, success_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            page.cache_key, page.url, page.title, page.content,
            now, expires, page.content_hash, page.word_count,
            page.summary, json.dumps(page.key_points) if page.key_points else None,
            json.dumps(page.entities) if page.entities else None,
            page.selector_used, page.extraction_method, 1.0
        ))
        
        return {"status": "cached", "expires": expires.isoformat()}
    finally:
        await db_pool.release(conn)

@app.get("/cache/page/{cache_key}")
async def get_cached_page(
    cache_key: str,
    summary_only: bool = Query(False, description="Return only summary to save context")
):
    """Retrieve a cached page"""
    conn = await db_pool.acquire()
    try:
        result = conn.execute("""
            SELECT url, title, content, summary, word_count, content_hash,
                   key_points, entities, extracted_at, ttl_expires
            FROM cached_pages
            WHERE cache_key = ? AND ttl_expires > ?
        """, (cache_key, datetime.now())).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Cache entry not found or expired")
        
        (url, title, content, summary, word_count, content_hash,
         key_points, entities, extracted_at, ttl_expires) = result
        
        if summary_only and summary:
            return {
                "url": url,
                "title": title,
                "content": summary,
                "is_summary": True,
                "word_count_original": word_count,
                "word_count_saved": word_count - len(summary.split()) if summary else 0,
                "key_points": json.loads(key_points) if key_points else None,
                "entities": json.loads(entities) if entities else None
            }
        
        return {
            "url": url,
            "title": title,
            "content": content,
            "word_count": word_count,
            "content_hash": content_hash,
            "summary": summary,
            "key_points": json.loads(key_points) if key_points else None,
            "entities": json.loads(entities) if entities else None,
            "cached_at": extracted_at.isoformat() if extracted_at else None,
            "expires_at": ttl_expires.isoformat() if ttl_expires else None
        }
    finally:
        await db_pool.release(conn)

@app.post("/cache/element")
async def cache_element(element: CachedElement):
    """Store element selector success/failure"""
    conn = await db_pool.acquire()
    try:
        # Check if selector exists
        existing = conn.execute("""
            SELECT id, success_count, fail_count, avg_find_time_ms
            FROM cached_elements
            WHERE domain = ? AND element_type = ? AND selector = ?
        """, (element.domain, element.element_type, element.selector)).fetchone()
        
        if existing:
            id_val, success_count, fail_count, avg_time = existing
            if element.success:
                new_success = success_count + 1
                new_fail = fail_count
            else:
                new_success = success_count
                new_fail = fail_count + 1
            
            # Update average time
            new_avg_time = avg_time
            if element.find_time_ms and element.success:
                new_avg_time = ((avg_time * success_count) + element.find_time_ms) / new_success if new_success > 0 else element.find_time_ms
            
            conn.execute("""
                UPDATE cached_elements
                SET success_count = ?, fail_count = ?, 
                    last_used = ?, avg_find_time_ms = ?
                WHERE id = ?
            """, (new_success, new_fail, datetime.now(), new_avg_time, id_val))
        else:
            # Insert new selector
            conn.execute("""
                INSERT INTO cached_elements
                (domain, element_type, selector, success_count, fail_count,
                 last_used, avg_find_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                element.domain, element.element_type, element.selector,
                1 if element.success else 0,
                0 if element.success else 1,
                datetime.now(),
                element.find_time_ms or 0
            ))
        
        return {"status": "recorded"}
    finally:
        await db_pool.release(conn)

@app.get("/cache/element/{domain}/{element_type}")
async def get_best_selector(domain: str, element_type: str):
    """Get best performing selector for domain and element type"""
    conn = await db_pool.acquire()
    try:
        result = conn.execute("""
            SELECT selector, success_count, fail_count, avg_find_time_ms
            FROM cached_elements
            WHERE domain = ? AND element_type = ?
                  AND success_count > fail_count
            ORDER BY (success_count - fail_count) DESC, avg_find_time_ms ASC
            LIMIT 5
        """, (domain, element_type)).fetchall()
        
        if not result:
            raise HTTPException(status_code=404, detail="No selectors found")
        
        selectors = []
        for selector, success, fail, avg_time in result:
            success_rate = success / (success + fail) if (success + fail) > 0 else 0
            selectors.append({
                "selector": selector,
                "success_rate": success_rate,
                "success_count": success,
                "fail_count": fail,
                "avg_time_ms": avg_time
            })
        
        return {"domain": domain, "element_type": element_type, "selectors": selectors}
    finally:
        await db_pool.release(conn)

@app.post("/cache/workflow")
async def cache_workflow(workflow: WorkflowCache):
    """Store workflow results"""
    conn = await db_pool.acquire()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO cached_workflows
            (workflow_id, workflow_type, input_hash, result, 
             created_at, accessed_count, total_tokens_saved)
            VALUES (?, ?, ?, ?, ?, 1, ?)
        """, (
            workflow.workflow_id, workflow.workflow_type,
            workflow.input_hash, json.dumps(workflow.result),
            datetime.now(), workflow.tokens_saved or 0
        ))
        
        return {"status": "cached", "workflow_id": workflow.workflow_id}
    finally:
        await db_pool.release(conn)

@app.get("/cache/workflow/{workflow_id}")
async def get_workflow_cache(workflow_id: str):
    """Retrieve cached workflow results"""
    conn = await db_pool.acquire()
    try:
        # Increment access count
        conn.execute("""
            UPDATE cached_workflows
            SET accessed_count = accessed_count + 1
            WHERE workflow_id = ?
        """, (workflow_id,))
        
        result = conn.execute("""
            SELECT workflow_type, result, created_at, accessed_count, total_tokens_saved
            FROM cached_workflows
            WHERE workflow_id = ?
        """, (workflow_id,)).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        workflow_type, result_json, created_at, accessed_count, tokens_saved = result
        
        return {
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "result": json.loads(result_json),
            "created_at": created_at.isoformat() if created_at else None,
            "accessed_count": accessed_count,
            "tokens_saved": tokens_saved
        }
    finally:
        await db_pool.release(conn)

@app.get("/cache/stats")
async def get_cache_stats() -> CacheStats:
    """Get cache statistics"""
    conn = await db_pool.acquire()
    try:
        # Get counts
        pages_count = conn.execute("SELECT COUNT(*) FROM cached_pages").fetchone()[0]
        elements_count = conn.execute("SELECT COUNT(*) FROM cached_elements").fetchone()[0]
        workflows_count = conn.execute("SELECT COUNT(*) FROM cached_workflows").fetchone()[0]
        
        # Get average tokens saved
        avg_tokens = conn.execute("""
            SELECT AVG(total_tokens_saved) FROM cached_workflows
        """).fetchone()[0] or 0
        
        # Get date range
        oldest = conn.execute("""
            SELECT MIN(extracted_at) FROM cached_pages
        """).fetchone()[0]
        
        newest = conn.execute("""
            SELECT MAX(extracted_at) FROM cached_pages
        """).fetchone()[0]
        
        # Estimate cache size
        db_size = os.path.getsize(DB_PATH) / (1024 * 1024) if os.path.exists(DB_PATH) else 0
        
        return CacheStats(
            total_pages=pages_count,
            total_elements=elements_count,
            total_workflows=workflows_count,
            avg_tokens_saved=avg_tokens,
            cache_size_mb=db_size,
            oldest_entry=oldest,
            newest_entry=newest
        )
    finally:
        await db_pool.release(conn)

@app.delete("/cache/expired")
async def clear_expired():
    """Remove expired cache entries"""
    conn = await db_pool.acquire()
    try:
        now = datetime.now()
        
        # Delete expired pages
        pages_deleted = conn.execute("""
            DELETE FROM cached_pages WHERE ttl_expires < ?
        """, (now,)).rowcount
        
        # Delete old workflows (>7 days)
        workflows_deleted = conn.execute("""
            DELETE FROM cached_workflows 
            WHERE created_at < ? AND accessed_count < 3
        """, (now - timedelta(days=7),)).rowcount
        
        # Delete unused selectors (>30 days)
        selectors_deleted = conn.execute("""
            DELETE FROM cached_elements
            WHERE last_used < ? AND success_count < 2
        """, (now - timedelta(days=30),)).rowcount
        
        return {
            "pages_deleted": pages_deleted,
            "workflows_deleted": workflows_deleted,
            "selectors_deleted": selectors_deleted
        }
    finally:
        await db_pool.release(conn)

@app.post("/cache/analyze")
async def analyze_content(
    content: str = Body(...),
    generate_summary: bool = Query(True)
):
    """Analyze content for caching optimization"""
    word_count = len(content.split())
    char_count = len(content)
    
    # Simple heuristics for now (would use LLM in production)
    summary = None
    key_points = []
    entities = []
    
    if generate_summary and word_count > 100:
        # Create a basic summary (placeholder for LLM call)
        sentences = content.split('.')[:3]
        summary = '. '.join(sentences) + '.'
        
        # Extract potential key points (lines starting with -, *, or numbers)
        import re
        key_point_pattern = r'^[\s]*[-*•\d]+[\s).](.+)$'
        for line in content.split('\n'):
            match = re.match(key_point_pattern, line)
            if match:
                key_points.append(match.group(1).strip())
        
        # Extract potential entities (capitalized words)
        entity_pattern = r'\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b'
        potential_entities = re.findall(entity_pattern, content)
        entities = list(set(potential_entities))[:10]  # Top 10 unique
    
    return {
        "word_count": word_count,
        "char_count": char_count,
        "summary": summary,
        "summary_reduction": len(summary.split()) / word_count if summary else 0,
        "key_points": key_points[:5],  # Limit to 5
        "entities": entities,
        "recommended_cache": word_count > 50,
        "recommended_ttl": 3600 if word_count < 500 else 7200
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9001, log_level="info")