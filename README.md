# pebkac: The AI-Powered Web Automaton Without The Automation

Update: I've written a more detailed guide on setting up the pebkac environment. It's on [Medium.](https://medium.com/ai-in-plain-english/building-your-own-secure-local-ai-web-co-browser-in-linux-mint-7bd2144fd64e)

## **What This Is**

pebkac browses the web for you. It is a web nonautomation framework powered by SmolAgents and Zendriver. Synchronous communication becomes asynchronous communication in an elegant double-helix of English language-powered Python interpretation driven by you, the user. There is no MCP, no n8n, no LangChain or LangGraph. pebkac employs the LLM's native ability to control a web browser by writing Python directly into it.

- Zendriver is described as "A blazing fast, async-first, undetectable webscraping/web automation framework based on ultrafunkamsterdam/nodriver."
- SmolAgents is "a barebones library for agents that think in code."

Together, they fit to give your localised, secure, rambunctiously stupid LLM a manual and a set of tools to operate a web browser.

## ✨ Features

### Core Capabilities

**Autonomous Intelligence**
- 🧠 **Code-Writing LLM** - Writes Python with loops, conditions, error handling (not limited to sequential tool calls like LangChain)
- 🎯 **Multi-Step Reasoning** - Works through complex tasks independently over 10 configurable steps
- 🔄 **Self-Correction** - Tries alternative strategies when approaches fail

**Stealth & Persistence**
- 👻 **Undetectable Automation** - Bypasses anti-bot detection (Cloudflare, etc.) using real Chrome instead of WebDriver
- 🔐 **Persistent Sessions** - Remembers logins and cookies across restarts (sign in once, done)
- 🛡️ **Anti-Bot Bypass** - Automatically handles challenges and verification pages

**Smart Data Extraction**
- 📊 **Intelligent Content Extraction** - Trafilatura parses web pages like a human reader (ignores ads, navigation, footers)
- 🎯 **API Response Capture** - Extracts structured JSON from modern websites instead of scraping messy HTML
- ⚡ **Extreme Caching** - 500-2000x faster on repeat visits (Redis + DuckDB two-tier cache)
- 📑 **Tab Management** - Opens relevant pages in background for you to explore later

**User Experience**
- 💬 **Chat Interface** - Type natural language commands at localhost:8888
- 👁️ **Live Browser View** - Watch what it's doing via noVNC (1280x720)
- 📝 **Detailed Logging** - See every decision and action in real-time
- 🔍 **Web Search Integration** - Searches DuckDuckGo and filters out junk results

**Performance Features**
- 🚀 **Parallel Operations** - Extracts multiple page elements simultaneously
- 🎨 **Form Automation** - Types with human-like delays, handles keyboard navigation
- 📸 **Screenshot Capture** - Visual verification of page state
- 📊 **Selector Learning** - Remembers which CSS selectors work per site and reuses them automatically (survives restarts)

### 🚀 Why pebkac Outperforms Traditional Solutions
**The Game-Changer: LLMs Write Python, Not JSON**

Unlike LangChain's rigid JSON tool-calling or MCP's predefined functions, pebkac's LLM writes actual Python code that executes browser actions. This means your AI will look at its own tools and write Python code to utilise them. This is impossible with LangChain/MCP's approach. They can only call predefined tools sequentially. pebkac's LLM can write loops, conditions, error handling, and complex logic.

This also means that pebkac is only as capable as the LLM that runs it, and the prompts you give it! It is fundamentally of no-mind. It has no real understanding of what it is asked to do. All it has is Google Chrome dev tools, a couple libraries, and an API.

Frankly, no LLM has been made that **is supposed to** fully operate Google Chrome.

The browser runs with noVNC and loads about:blank on startup. You are warned. pebkac is not C-3P0. pebkac is a garden path. pebkac will click the wrong buttons. It will go off on tangents. It works independently through ten (adjustable) steps using its own logic and processes, providing entirely self-directed browsing. While pebkac is active you can check the highly detailed log output below the browser window to see what your LLM is up to.

Or just give it a job and go do something else. Eat an apple. [Read a book.](https://www.amazon.com/Wells-Rest-Mitch-Davis/dp/0646826778?ref_=ast_author_mpb)

You operate it simply by opening the pebkac Control Panel in your browser (localhost:8888) and typing into the chat window. The control panel displays the browser via noVNC and shows live logs from both the browser automation service and the LLM. pebkac will perform its duties and return nicely-formatted results in the chat window.

### 🚀 How does pebkac know what to do?
By reading the page, of course, same as you. State of the art extraction technologies are built in to Zendriver's existing framework, giving it an enormous capability boost. I used Trafilatura to achieve this.

- Trafilatura is "a cutting-edge Python package and command-line tool designed to gather text on the Web and simplify the process of turning raw HTML into structured, meaningful data."

Basically, pebkac's vision is augmented. Not only is it excellent at text/data extraction (check it out on github: https://github.com/adbar/trafilatura) it utilises its extraction (along with native Zendriver CSS detection) to figure out what to do! This makes things like handling Cloudflare and popups a lot easier.

YOU CAN ALSO interact with the Chrome browser pebkac uses. You can manually sign into websites and ask pebkac to perform actions on the page. Think of it like a co-browser. It can go off on its own, collect the day's news, find out about things, and (maybe) handle little jobs while you do other things, or you can drop in, hang-ten over the keyboard, and surf collaboratively. Remember, pebkac and its browser are fully contained, so there's no way the LLM can access your host PC.

This whole project is both an entirely useful web co-browsing service and a stark artistic reminder of the realities of our modular, chronically-online based existences. We all exist in our little boxes with internet connections to view the outside world, and now more than ever our little boxes are subject to oversight and control by forces far more intelligent than us. I view this project as a black mirror (lol) to our modern life.

It's also never been done before.

It's also incredibly capable.

## ✨ Technicals

With a powerful enough LLM behind it, this setup is capable of:
- Thinking (via LLM)
- Seeing (via CSS selection/Trafilatura)
- Acting (via SmolAgents and Zendriver)
- Remembering (via elaborate, lightweight caching)
- Learning (via CSS selector tracking)

Here's what it does:
- Avoids the need to pay for API calls. The LLM now works like you do.
- Remembers your logins across Podman/Docker sessions.
- Interprets your commands with versatility. If you ask it to "search amazon", it'll go to Amazon and search. If you ask it to "wait 1min and reload", it will figure it out.
- Coordinates its own tool use so it doesn't get confused. It won't extract before navigating, and knows what page it's already on.
- Combines its usage of tools mid-step (with async). Remember how I said it has ten steps to complete a task? Inside each of those steps the LLM makes its own decisions about how to work.
- Decides its own workflows. Aside from operating a browser search, its methods are decided on-the-fly.
- Navigates, types, searches, clicks, visits, extracts, takes screenshots, exports markdown, bypasses cloudflare, fills forms.
- Tries, fails, and LEARNS. If one strategy fails, another might work.
- Parses text intelligently. Trafilatura is excellent and its responses are formatted cleanly.
- Logs each action extensively. All logfiles are available in the control panel.
- Validates inputs! I've done much to ensure there is little to no risk from Javascript or SQL injection. Please be careful. I made sure to do this based on an XKCD comic strip I saw in high school: https://m.xkcd.com/327/
- A lot more. It is designed to turn your natural language input into results, and does its humble best.

## What Needs Work
- Voice assist
- Advanced selector prediction (ML-based selector generation)

This version of pebkac is designed to be mindful of context length and run on inexpensive GPUs. I built this whole project on a very budget MiniPC, and tested it with a specific fine-tuned model. For operating pebkac, I would HIGHLY recommend using David_AU's models, particularly the Brainstorm variants. Not only do they know to operate pebkac nearly 100% of the time, but they seem to have been trained on the SmolAgents library, making much of the 'thinking' already integrated.

Search for and download them here: https://hf.tst.eu/model

I did most testing using DavidAU/Qwen3-Jan-Nano-128k-6B-Brainstorm20x which was fast for my testing cases, but I would VERY MUCH RECOMMEND looking at the MoE models, like Qwen3-30b-whatever. His MoE models are excellent. Between non-thinking and thinking models, I like the results I get from non-thinking models.

It is reasonably important to find a model with an extremely long context length, like 64k or higher. That's fundamental. Basic models will not cut it.

I would also highly recommend adjusting the extraction method to extract more text, and altering llama.cpp's GPU usage in the .env file. That will truly allow pebkac to work its magic.

#### And so, I introduce to you pebkac, the web automation service without the automation. It's just a mathematical word-generator with a set of word-tools, let free on the internet.

## **AUTHOR'S NOTE**
For full disclosure, I am a writer, not a developer. I barely know print hello world. I began this project using Claude as a way to automate my own web research and social media activities. What came out of it was a much larger project that took many months to complete and taught me a lot about AI, programming, and computer science. It's not that I assumed it wouldn't be hard, but that I assumed it wouldn't be so complex. I can confidently say that I understand most of this project, but of course, I don't know what I don't know. Use pebkac at your own risk. It's as secure as a VIBE CODING AUTHOR knows how to make it.

What I have learned more than anything is that my very basic hardware cannot handle LLMs very well. I have made sure every part of this project is as lightweight and fast as possible. If you choose to support me by donating, that money would first and foremost go towards making this project harder, better, faster, and stronger. I'd also like to direct you to my Amazon page, because on God, writing books doesn't make money. My novel **[Well's Rest](https://www.amazon.com/Wells-Rest-Mitch-Davis/dp/0646826778?ref_=ast_author_mpb)** is on **[Amazon](https://www.amazon.com/Wells-Rest-Mitch-Davis/dp/0646826778?ref_=ast_author_mpb)**.

pebkac might even be able to buy it for you.

It will definitely be able to find me on Royal Road:
https://www.royalroad.com/fiction/126900/wells-rest-grimdark-pirate-action-watch-book-trailer

I am of the opinion that pebkac demonstrates how mainstream approaches to LLMs are changing. Small, tailored models are the future for operating untold new and old technologies. I do not know if they should be writing words that mean things to humans. Check out my website at www.akickintheteeth.com. That is where I've been documenting my other experiments with AI. It's a brave new world!

## **Getting Started**
### **Requirements:**
- **Podman or Docker** I used Podman. I use a custom storage directory for my Podman setup. You'll have to adapt a little.
- **Podman/Docker Compose** Runs stuff.
- **Linux** I use Mint.
- **AMD or NVIDIA GPU** for llama.cpp acceleration

### **Initial Setup**
For total beginners, start [here.](https://medium.com/ai-in-plain-english/building-your-own-secure-local-ai-web-co-browser-in-linux-mint-7bd2144fd64e)

1. Clone this repository into your podman directory
2. Rename the ROOT files to `.env` and `docker-compose.yml`
3. Configure `docker-compose.yml`:
   - Set `group_add` entries to your actual render group GID (find with `getent group render`)
   - Adjust GPU settings for your hardware
   - Just thoroughly check through the docker-compose files to suit your hardware. Same with the .env files. Be thorough.
4. Configure `.env` file:
   - Set `LLAMACPP_MODEL` to your GGUF model filename (must exist in `/podman/models/gguf/`) unless setting yourself. This is the trickiest part that I can't help with.
   - Set `LLAMACPP_GPU_LAYERS` based on your VRAM
   - Set `HF_TOKEN` if downloading models from HuggingFace
5. Open the pebkac Yaml Runner.
6. Access the Control Panel at http://localhost:8888
   - Chat interface for interacting with the LLM
   - Live browser view via noVNC (1280x720)
   - Real-time logs from zendriver and llama-cpp-server
7. Start chatting! Type commands like "search for cheese" or "go to amazon and find shoes"

### **Monitoring**
You can monitor logs externally via:
```bash
podman logs -f zendriver        # Browser automation and agent execution
podman logs -f llama-cpp-server # LLM inference logs
```

Below is some stuff Claude put together. It's mostly accurate. Just more detail.

### **Core Architecture**

#### **1. Browser Automation Layer (Zendriver)**
- **Undetectable Chrome automation** using CDP (Chrome DevTools Protocol) via zendriver
- Runs in a **virtual Wayland/Sway display** with full GPU acceleration (1280x720 default)
- **VNC debugging** on port 5910 for visual monitoring
- **Browser profiles** persist across sessions at `/tmp/pebkac_profiles/`
- **Clean architectural separation**:
  - Routes handle high-level business logic
  - BrowserManager service layer encapsulates CDP operations
  - Only protocol-level routes (network.py) use CDP directly
- Full API with endpoints for:
  - Navigation with wait conditions
  - Element finding by selector or text
  - Clicking, typing (with human-like delays)
  - Scrolling (directional and to elements)
  - Tab management (create, list, close)
  - API response capture
  - Element discovery
  - Content extraction with fallbacks
  - Parallel operations

#### **2. AI Agent Layer (SmolAgents + LLM)**
- **SmolAgents framework** integration allowing LLMs to use browser tools autonomously
- **SafeCodeAgent** handles multiple final_answer calls and retries on missing final_answer
- **Local LLM inference** via llama.cpp with Vulkan GPU acceleration
- **Integrated AgentManager** runs inside zendriver container (no separate service)

**Tool suite for agents (18 tools in zendriver-docker/app/tools/)**:

### Browser Control
- `NavigateBrowserTool` - Navigate to URLs
- `ClickElementTool` - Click elements
- `TypeTextTool` - Type text into inputs
- `KeyboardNavigationTool` - Press keyboard keys
- `GetCurrentURLTool` - Get current page URL

### Content Extraction
- `ExtractContentTool` - Extract page content with intelligent link extraction
- `ParallelExtractionTool` - Extract from multiple selectors simultaneously
- `CapturePageMarkdownTool` - Export page as Markdown

### Search & Navigation
- `WebSearchTool` - Search DuckDuckGo with result filtering (LLM decides which tabs to open)
- `VisitWebpageTool` - Visit and extract page content in one call
- `SearchHistoryTool` - Access cached search results

### Tab Management (NEW)
- `OpenBackgroundTabTool` - Open URLs in background while keeping main tab active
- `ListTabsTool` - List all tabs with indices and status
- `CloseTabTool` - Close background tabs (tab 0 protected)

### API & Network
- `CaptureAPIResponseTool` - Capture JSON API responses during navigate/click (structured data extraction)

### Advanced Tools
- `ScreenshotTool` - Capture screenshots
- `CloudflareBypassTool` - Handle anti-bot challenges automatically
- `GetElementPositionTool` - Get element coordinates for verification

#### **3. Caching Infrastructure**
**Two-tier cache system providing 500-2000x speedup on cached content:**

- **L1 Cache (Redis)**: Ultra-fast in-memory caching (10ms lookups)
  - 512MB with LRU eviction
  - Complete response storage with formatted output
  - 90-day selector performance memory
  - Automatic cleanup every 30 minutes

- **L2 Cache (DuckDB SQL Database)**: Persistent disk-based analytical database
  - Embedded SQL database optimized for analytics (similar to SQLite)
  - Survives container restarts
  - HTTP service with 5-connection pool
  - SQL tables: `cached_pages`, `cached_elements`, `cached_workflows`, `cache_metrics`
  - Permanent selector analytics with success/fail tracking
  - Transaction management with `conn.commit()` for data persistence
  - Database file: `/mnt/ssd/podman/duckdb-data/cache.db`

- **Tiered Lookup Flow**:
  1. Check L1 (Redis) → Return if hit (~10ms)
  2. Check L2 (DuckDB) → Promote to L1 if hit (~95ms)
  3. Extract from browser if both miss (5-20 seconds)

- **Smart Caching Strategies**:
  - **Selective L2 persistence**: Universal extractions, large content (>10KB), or long-lived (≥1 hour TTL)
  - **Content-based TTL**: Structural elements (24h), text selectors (30min), dynamic content (no cache)
  - **Cache key normalization**: Maximizes hits by removing query params and normalizing URLs
  - **Auto-promotion**: L2 hits automatically promoted to L1 for future fast access

#### **4. Control Panel**
- **Web UI at localhost:8888** for chat and system monitoring
- **Chat interface** with localStorage persistence
- **Tabbed interface**: Chat | VNC Browser | Logs
- **Live logs** from zendriver and llama-cpp-server containers
- **Container controls**: Start, stop, reset services

### **Key Technical Achievements**
1. **Robust extraction system**:
   - Multiple strategies for text extraction
   - Metadata extraction capabilities
   - Support for both visible and hidden text

2. **Workflows**:
   - Publication analysis with structure detection
   - Parallel operations with proper error handling
   - Retry strategies with exponential backoff
   - Performance tracking for selectors

3. **Human-like interactions**:
   - Typing with configurable delays between keystrokes
   - Smooth scrolling options
   - Tab navigation for accessibility

### **Production Features**

#### **Reliability**
- Health checks on all services
- Automatic restart policies
- Error tracking and logging
- Cache fallbacks if extraction fails

#### **Performance**
- GPU-accelerated browser rendering
- Parallel extraction capabilities
- Intelligent caching to reduce re-scraping
- Optimised LLM inference with batching

#### **Security & Stealth**
- Undetectable by anti-bot systems (Cloudflare, etc.)
- Persistent browser profiles
- No automation markers
- Real browser behavior simulation

#### **Scalability**
- Docker/Podman-based deployment
- Network isolation with custom subnet
- Volume management for persistent data
- Profile-based configuration

### **Use Cases Enabled**

1. **Autonomous Web Research**: LLM can browse, search, and compile information
2. **Data Extraction**: Scrape any website, even those with anti-bot protection
3. **Form Automation**: Fill out complex forms with AI decision-making
4. **Content Monitoring**: Track changes on websites over time
5. **Testing Automation**: AI-driven testing of web applications
6. **Information Synthesis**: Combine data from multiple sources automatically

## CREDITS:

Big thanks to everyone at HuggingFace
https://github.com/huggingface/smolagents /
https://huggingface.co

cdpdriver for Zendriver:
https://github.com/cdpdriver/zendriver /
https://zendriver.dev/

adbar for Trafilatura:
https://github.com/adbar/trafilatura / https://trafilatura.readthedocs.io/en/latest/

This project is licensed with GNU Public V3

Support me at:
https://ko-fi.com/dredgesta
www.akickintheteeth.com
