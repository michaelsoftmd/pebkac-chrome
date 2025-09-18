# Zenbot - Containerized AI Browser Automation Platform

Zenbot is a sophisticated multi-service platform that combines LLM capabilities with browser automation, providing a complete environment for AI-driven web interactions and data extraction.

## Core Architecture

The system consists of several integrated services:

- **Browser Automation**: Zendriver with Chrome/Chromium in containerized environment
- **AI Integration**: SmolAgents with tool-based web interaction capabilities
- **LLM Services**: Ollama and llama.cpp with GPU acceleration support
- **Caching Layer**: Redis (L1) and DuckDB (L2) for performance optimization
- **Web Interface**: Control panel with VNC access to browser sessions
- **Session Persistence**: Hybrid profile system maintaining login state across restarts

## Quick Start

### Prerequisites
- Docker/Podman with container runtime
- GPU drivers (AMD/NVIDIA) for hardware acceleration
- Minimum 4GB RAM, 6-8GB recommended

### Boot System
```bash
# Start all services
docker compose --profile full up --build

# For AMD GPUs
docker compose -f "ROOT docker-compose.yml" -f zendriver-docker/docker-compose.amd.yml up --build

# For NVIDIA GPUs
docker compose -f "ROOT docker-compose.yml" -f zendriver-docker/docker-compose.nvidia.yml up --build
```

### Access Points
- **Control Panel**: http://localhost:3000 (web interface)
- **Browser API**: http://localhost:8090 (zendriver endpoints)
- **SmolAgents API**: http://localhost:9000 (tool integration)
- **VNC Access**: Integrated in control panel for direct browser interaction

## Key Features

### Browser Session Persistence
- Sessions survive container restarts
- Cookies, login data, and preferences maintained
- Hybrid storage: tmpfs for performance, persistent volumes for data
- Automatic session restore on startup

### Multi-Browser Pool Support
- Pre-spawned browser instances for zero-latency operations
- Session-based browser assignment for stateful workflows
- Configurable pool size (2-5 browsers)
- Automatic cleanup and resource management

### Security & Validation
- Input sanitization with Pydantic models
- XSS prevention in CSS selectors and XPath expressions
- Path traversal protection for file operations
- Safe command execution without shell injection

### Performance Optimization
- Multi-layer caching strategy (Redis + DuckDB)
- Browser pool management for high-throughput scenarios
- GPU acceleration for LLM inference
- Optimized container networking

## Development

### Zendriver Development
```bash
cd zendriver-docker
uv sync
./scripts/format.sh    # Code formatting
./scripts/lint.sh      # Linting and type checks
uv run pytest          # Run tests
```

### API Development
```bash
cd openapi-server
uv sync
uv run uvicorn main:main --host 0.0.0.0 --port 9000 --reload
```

### Configuration

#### Environment Variables (ROOT env.txt)
- `LLAMACPP_MODEL`: GGUF model filename for llama.cpp
- `LLAMACPP_GPU_LAYERS`: Number of layers for GPU acceleration
- `HF_TOKEN`: Hugging Face token for model downloads
- `BROWSER_HEADLESS`: Browser display mode (true/false)
- `SWAY_RESOLUTION`: VNC window resolution (default: 640x480)

#### Timeout Configuration
Timeout values are configurable in ROOT env.txt:
- `TIMEOUT_ELEMENT_FIND`: Element location timeout
- `TIMEOUT_HTTP_REQUEST`: HTTP request timeout
- `TIMEOUT_HTTP_EXTRACTION`: Content extraction timeout
- `TIMEOUT_PAGE_LOAD`: Page load timeout

### Adding Browser Tools
1. Extend request models in `zendriver-docker/app/models/requests.py`
2. Add endpoint to `zendriver-docker/app/main.py`
3. Create SmolAgents tool in `openapi-server/main.py`
4. Test via API before integration

## System Requirements

### Memory Requirements
- Minimum: 4GB RAM for basic operation
- Recommended: 6-8GB RAM for full multi-browser setup
- Each browser instance: ~1GB memory

### GPU Support
- **AMD**: Uses radeonsi drivers with Vulkan acceleration
- **NVIDIA**: Requires Container Toolkit installation
- Hardware acceleration configured per docker-compose file

### Storage
- Base system: ~2GB
- Model storage: Variable based on LLM models
- Session data: Minimal (cookies, preferences)
- Persistent volumes mounted to `/mnt/ssd/podman/`

## Network Architecture

Services communicate via bridge network with these endpoints:
- zendriver: port 8090 (browser automation)
- openapi-tools: port 9000 (SmolAgents bridge)
- redis-cache: port 6379 (L1 caching)
- duckdb-cache: port 9001 (L2 storage)
- ollama/llama-cpp: ports 11434/8080 (LLM inference)
- open-webui: port 3000 (user interface)

## Troubleshooting

### Common Issues
- **Session loss**: Check volume mounts for `/app/session-data`
- **GPU not detected**: Verify drivers and container runtime support
- **Browser crashes**: Check memory limits and tmpfs permissions
- **Network errors**: Ensure bridge network creation before service start

### Health Checks
- `/health` endpoints available on all services
- Browser pool stats at `/browsers/stats`
- Monitor container resources via `docker stats`

### Logs
Access service logs through the control panel or directly:
```bash
docker logs <container_name>
```

## API Documentation

### Browser Automation (zendriver)
- `POST /navigate` - Navigate to URL
- `POST /click` - Click elements
- `POST /extraction/extract` - Extract page content
- `POST /interaction/type` - Type text
- `GET /health` - Service health check

### SmolAgents Integration (openapi-tools)
- `POST /tools/navigate` - Navigate with AI context
- `POST /tools/extract` - AI-powered content extraction
- Automatic tool discovery and integration

## License & Support

This platform integrates multiple open-source projects. Check individual component licenses for specific terms. For issues and contributions, see the project repository.