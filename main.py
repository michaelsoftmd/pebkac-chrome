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
from fastapi import FastAPI, Response, Request
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

# Mount static files directory
app.mount("/static", StaticFiles(directory=static_dir), name="static")

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
    if container not in ['zendriver', 'llama-cpp-server']:
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
            # First check if container exists and is running
            check_proc = await asyncio.create_subprocess_exec(
                'podman', 'ps', '--format', 'json', '--filter', f'name={container}',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await check_proc.communicate()

            if check_proc.returncode != 0:
                yield f"data: {json.dumps({'message': f'Container {container} not found or not running', 'level': 'error'})}\n\n"
                return

            containers = json.loads(stdout.decode()) if stdout.strip() else []
            if not containers:
                yield f"data: {json.dumps({'message': f'Container {container} is not running', 'level': 'error'})}\n\n"
                return

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

@app.post("/api/control/stop")
async def stop_containers():
    """Stop containers WITHOUT removing them"""
    try:
        results = []

        # Just stop, don't remove
        logger.info("Stopping all containers...")
        result = subprocess.run(
            ['podman', 'stop', '-a'],
            capture_output=True,
            text=True,
            timeout=30
        )
        results.append(f"Stop: {result.stdout}")

        return {
            "status": "success",
            "message": "All containers stopped (preserved for restart)",
            "details": results
        }

    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Command timed out"}

@app.post("/api/control/start")
async def start_containers():
    """Start existing containers"""
    try:
        # Start existing containers
        logger.info("Starting existing containers...")
        result = subprocess.run(
            ['podman', 'compose', '--profile', 'full', 'start'],
            capture_output=True,
            text=True,
            timeout=30
        )

        return {
            "status": "success",
            "message": "Containers restarted",
            "output": result.stdout
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/control/reset")
async def reset_containers():
    """Full reset - remove and recreate containers (data loss warning)"""
    try:
        # This is the destructive option - should require confirmation
        results = []

        # Stop all
        subprocess.run(['podman', 'stop', '-a'], capture_output=True)
        results.append("Stopped all containers")

        # Remove all
        subprocess.run(['podman', 'rm', '-a'], capture_output=True)
        results.append("Removed all containers")

        # Remove the network
        logger.info("Removing network...")
        result = subprocess.run(
            ['podman', 'network', 'rm', 'podman_llm-network'],
            capture_output=True,
            text=True,
            timeout=5
        )
        results.append(f"Network: {result.stdout or 'Removed'}")

        # Recreate with compose
        subprocess.run(['podman', 'compose', '--profile', 'full', 'up', '-d'],
                      capture_output=True)
        results.append("Recreated containers")

        return {
            "status": "success",
            "message": "Full reset completed - ALL DATA LOST",
            "details": results
        }

    except Exception as e:
        logger.error(f"Error resetting containers: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/control/create-network")
async def create_network():
    """Create the podman network for containers"""
    try:
        logger.info("Creating podman network...")

        result = subprocess.run(
            ['podman', 'network', 'create',
             '--driver', 'bridge',
             '--subnet', '172.20.0.0/16',
             'podman_llm-network'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            return {
                "status": "success",
                "message": "Network created successfully",
                "output": result.stdout
            }
        else:
            # Network might already exist
            if "already exists" in result.stderr.lower():
                return {
                    "status": "success",
                    "message": "Network already exists",
                    "output": result.stderr
                }
            else:
                return {
                    "status": "error",
                    "message": "Failed to create network",
                    "error": result.stderr
                }

    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": "Network creation timed out"
        }
    except Exception as e:
        logger.error(f"Error creating network: {e}")
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
    """Copy files from container /tmp to host using podman cp"""
    from datetime import datetime

    try:
        # Create host export directory with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        host_export_dir = Path(f'/mnt/ssd/podman/exports_{timestamp}')
        host_export_dir.mkdir(parents=True, exist_ok=True)

        # Copy screenshots from container
        result_screenshots = await asyncio.create_subprocess_exec(
            'podman', 'cp', 'zendriver:/tmp/screenshots', str(host_export_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout_s, stderr_s = await result_screenshots.communicate()

        # Copy markdown exports from container
        result_markdown = await asyncio.create_subprocess_exec(
            'podman', 'cp', 'zendriver:/tmp/exports', str(host_export_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout_m, stderr_m = await result_markdown.communicate()

        # Count files copied
        files_copied = []
        if host_export_dir.exists():
            for ext in ['*.png', '*.jpg', '*.md']:
                files_copied.extend(host_export_dir.rglob(ext))

        return {
            "status": "success",
            "message": f"Exported {len(files_copied)} files",
            "destination": str(host_export_dir),
            "screenshots": result_screenshots.returncode == 0,
            "markdown": result_markdown.returncode == 0,
            "files": [str(f.relative_to(host_export_dir)) for f in files_copied]
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