"""
Control Panel for LLM Browser System
Simple FastAPI server for monitoring and controlling the podman stack
"""

import asyncio
import json
import subprocess
import logging
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from contextlib import asynccontextmanager
import uvicorn

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global process tracking
log_processes = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Cleanup on shutdown"""
    yield
    # Kill any remaining log processes
    for proc in log_processes.values():
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(asyncio.create_task(proc.wait()), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
    logger.info("Control panel shutdown complete")

# Create FastAPI app
app = FastAPI(
    title="Zenbot-Chrome Remote Control",
    version="1.0.0",
    lifespan=lifespan
)

# Serve static files (our HTML UI)
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)

@app.get("/")
async def root():
    """Serve the main UI"""
    html_path = static_dir / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return {"error": "UI not found. Please ensure index.html is in the static directory"}

@app.get("/api/logs/{container}")
async def stream_logs(container: str):
    """Stream container logs via Server-Sent Events"""
    
    # Validate container name (basic security)
    if container not in ['openapi-tools', 'zendriver', 'llama-cpp-server', 'open-webui']:
        return JSONResponse({"error": "Invalid container name"}, status_code=400)
    
    async def log_generator():
        """Generate SSE stream from podman logs"""
        global log_processes
        
        # Kill existing process for this container if any
        if container in log_processes:
            old_proc = log_processes[container]
            if old_proc and old_proc.returncode is None:
                old_proc.terminate()
                try:
                    await old_proc.wait()
                except:
                    pass
        
        try:
            # Start podman logs process
            proc = await asyncio.create_subprocess_exec(
                'podman', 'logs', '-f', '--tail', '100', container,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            
            log_processes[container] = proc
            
            # Send initial connection message
            yield f"data: {json.dumps({'message': f'Connected to {container} logs', 'level': 'info'})}\n\n"
            
            # Stream logs line by line
            while True:
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
                    if line:
                        # Decode and clean the line
                        text = line.decode('utf-8', errors='replace').rstrip()
                        
                        # Detect log level from content
                        level = 'info'
                        lower_text = text.lower()
                        if 'error' in lower_text or 'exception' in lower_text:
                            level = 'error'
                        elif 'warning' in lower_text or 'warn' in lower_text:
                            level = 'warning'
                        
                        # Send as SSE
                        yield f"data: {json.dumps({'message': text, 'level': level})}\n\n"
                    else:
                        # Process ended
                        if proc.returncode is not None:
                            yield f"data: {json.dumps({'message': f'Log stream ended (exit code: {proc.returncode})', 'level': 'warning'})}\n\n"
                            break
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"
                except Exception as e:
                    logger.error(f"Error reading log stream: {e}")
                    yield f"data: {json.dumps({'message': f'Error: {str(e)}', 'level': 'error'})}\n\n"
                    break
            
        except Exception as e:
            logger.error(f"Failed to start log stream: {e}")
            yield f"data: {json.dumps({'message': f'Failed to connect: {str(e)}', 'level': 'error'})}\n\n"
        finally:
            # Clean up process reference
            if container in log_processes:
                del log_processes[container]
    
    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )

@app.post("/api/control/stop-all")
async def stop_all_containers():
    """Stop all containers, remove them, and remove the network"""
    try:
        results = []
        
        # Stop all containers
        logger.info("Stopping all containers...")
        result = subprocess.run(
            ['podman', 'stop', '-a'],
            capture_output=True,
            text=True,
            timeout=30
        )
        results.append(f"Stop: {result.stdout}")
        
        # Remove all containers
        logger.info("Removing all containers...")
        result = subprocess.run(
            ['podman', 'rm', '-a'],
            capture_output=True,
            text=True,
            timeout=10
        )
        results.append(f"Remove: {result.stdout}")
        
        # Remove the network
        logger.info("Removing network...")
        result = subprocess.run(
            ['podman', 'network', 'rm', 'podman_llm-network'],
            capture_output=True,
            text=True,
            timeout=5
        )
        results.append(f"Network: {result.stdout or 'Removed'}")
        
        return {
            "status": "success",
            "message": "All containers stopped and network removed",
            "details": results
        }
        
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": "Command timed out"
        }
    except Exception as e:
        logger.error(f"Error stopping containers: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@app.post("/api/control/compose-up")
async def compose_up():
    """Start the full stack with docker-compose"""
    try:
        logger.info("Starting podman-compose with full profile...")
        
        # Run in background
        proc = await asyncio.create_subprocess_exec(
            'podman', 'compose', '--profile', 'full', 'up', '-d',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        
        if proc.returncode == 0:
            return {
                "status": "success",
                "message": "Stack started successfully",
                "output": stdout.decode('utf-8', errors='replace')
            }
        else:
            return {
                "status": "error",
                "message": "Compose failed",
                "error": stderr.decode('utf-8', errors='replace')
            }
            
    except asyncio.TimeoutError:
        return {
            "status": "error",
            "message": "Command timed out (60s)"
        }
    except Exception as e:
        logger.error(f"Error starting compose: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@app.post("/api/export/copy-tmp")
async def copy_tmp_to_exports():
    """Copy all files from zendriver container's /tmp to mounted /exports"""
    import shutil
    
    try:
        # Paths for zendriver container's tmp directories
        tmp_screenshots = Path('/mnt/ssd/podman/zendriver_tmp/screenshots')
        tmp_exports = Path('/mnt/ssd/podman/zendriver_tmp/exports')
        
        # Destination exports directory
        exports_dir = Path('/mnt/ssd/podman/exports')
        exports_dir.mkdir(exist_ok=True)
        
        copied_files = []
        
        # Copy screenshots if they exist
        if tmp_screenshots.exists():
            for file_path in tmp_screenshots.glob('*'):
                if file_path.is_file():
                    dest_path = exports_dir / file_path.name
                    shutil.copy2(file_path, dest_path)
                    copied_files.append(f"screenshots/{file_path.name}")
        
        # Copy markdown exports if they exist
        if tmp_exports.exists():
            for file_path in tmp_exports.glob('*'):
                if file_path.is_file():
                    dest_path = exports_dir / file_path.name
                    shutil.copy2(file_path, dest_path)
                    copied_files.append(f"exports/{file_path.name}")
        
        return {
            "status": "success",
            "message": f"Copied {len(copied_files)} files to exports directory",
            "files": copied_files,
            "destination": str(exports_dir)
        }
        
    except Exception as e:
        logger.error(f"Export copy error: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "control-panel"}

if __name__ == "__main__":
    # Create static directory if it doesn't exist
    static_dir.mkdir(exist_ok=True)
    
    # Save the HTML file if running standalone
    html_content = Path(__file__).parent / "index.html"
    if html_content.exists():
        import shutil
        shutil.copy(html_content, static_dir / "index.html")
    
    # Run the server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8888,
        log_level="info"
    )