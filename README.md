# Zenbot: The AI-Powered Web Automaton Without The Automation

## **What This Is**

UNRELATED TO THE OTHER ZENBOT PROJECT! This project shares NO RELATION WHATSOEVER to any other Zenbot-named repository that can be found online. This project was named after its originally forked project, Zendriver.

Zenbot browses the web for you. It is a web nonautomation framework powered by Smolagents and Zendriver. Synchronous communication becomes asynchronous communication in an elegant double-helix of English language-powered Python interpretation driven by you, the user. There is no MCP, no n8n, no LangChain or LangGraph. Zenbot employs the LLM's native ability to control a web browser by writing Python directly into it.

- Zendriver is described as "A blazing fast, async-first, undetectable webscraping/web automation framework based on ultrafunkamsterdam/nodriver."
- Smolagents is "a barebones library for agents that think in code."

Together, they fit to give your localised, secure, rambunctiously stupid LLM a manual and a set of tools to operate a web browser. The massive advantage to this is that everything is contained - the LLM, the web browser, and everything it uses is (almost) entirely kept inside a local, isolated network of little boxes that never get root access, but enjoy the full benefits of working in your system.



## ✨ Features

### Core Capabilities

- 🌐 **Undetectable Browser Automation** - Uses Chrome DevTools Protocol (CDP) instead of Selenium/WebDriver
- 🤖 **LLM-Powered Control** - Natural language commands translated to browser actions
- 🔒 **Persistent Sessions** - Maintains cookies and authentication across restarts
- 📊 **Intelligent Caching** - Multi-tier cache system (Memory → Redis → DuckDB)
- 🎯 **Selector Learning** - Optimizes element selection strategies over time
- 🛡️ **Cloudflare Bypass** - Handles anti-bot challenges including reCAPTCHA
- 👁️ **Visual Debugging** - Live browser view through noVNC
- 📝 **Content Extraction** - Advanced text extraction using Trafilatura

<br>
</br>

Important! Zenbot is only as capable as the LLM that runs it, and the prompts you give it! It is fundamentally of no-mind. It has no rigid workflows, no LangGraphs, no LangChains, and no real understanding of what it is asked to do. All it has is Google Chrome dev tools, a couple libraries, and a few APIs.

The browser runs with noVNC and loads about:blank on startup. You are warned. Zenbot is not C-3P0. Zenbot is a garden path. Zenbot will click the wrong buttons. It will go off on tangents. It has ten (adjustable) steps to accomplish any task you give it, providing entirely self-directed browsing. While Zenbot is active you can check the highly detailed log output below the browser window to see what your LLM is up to.

Or just give it a job and go do something else. Eat an apple. Read a book.

You operate it simply by sending messages through Open WebUI and watching its progress in the Zenbot Control Panel, which operates as a separate browser tab on your host machine. You can watch the LLM handling everything live. Zenbot will perform its duties and return some nicely-formatted results for you back in the chat window.

How does Zenbot know what to do? By reading the page, of course, same as you. State of the art extraction technologies are built in to Zendriver's existing framework, giving it an enormous capability boost. I used Trafilatura to achieve this. 

- Trafilatura is “a cutting-edge Python package and command-line tool designed to gather text on the Web and simplify the process of turning raw HTML into structured, meaningful data.”

Basically, Zenbot’s vision is augmented. Not only is it excellent at text/data extraction (check it out on github: https://github.com/adbar/trafilatura) it utilises its extraction (along with native Zendriver CSS detection) to figure out what to do! This makes things like handling Cloudflare and popups a lot easier.

YOU CAN ALSO interact with the Chrome browser Zenbot uses. You can manually sign into websites and ask Zenbot to perform actions on the page. Think of it like a co-browser. It can go off on its own, collect the day’s news, find out about things, and (maybe) handle little jobs while you do other things, or you can drop in, hang-ten over the keyboard, and surf collaboratively. Remember, Zenbot and its browser are fully contained, so there’s no way the LLM can access your host PC.

This whole project is both an entirely useful web co-browsing service and a stark artistic reminder of the realities of our modular, chronically-online based existences. We all exist in our little boxes with internet connections to view the outside world, and now more than ever our little boxes are subject to oversight and control by forces far more intelligent than us. I view this project as a black mirror (lol) to our modern life. It’s also never been done before. It’s also incredibly capable.

<br>
</br>

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
- Interprets your commands with versatility. If you ask it to “search amazon”, it’ll go to Amazon and search. If you ask it to “wait 1min and reload”, it will figure it out.
- Coordinates its own tool use so it doesn’t get confused. It won’t extract before navigating, and knows what page it’s already on.
- Combines its usage of tools mid-step (with async). Remember how I said it has ten steps to complete a task? Inside each of those steps the LLM makes its own decisions about how to work.
- Decides its own workflows. Aside from operating a browser search, its methods are decided on-the-fly.
- Navigates, types, searches, clicks, visits, extracts, takes screenshots, exports markdown, bypasses cloudflare, fills forms.
- Tries, fails, and LEARNS. If one strategy fails, another might work.
- Parses text intelligently. Trafilatura is excellent and its responses are formatted cleanly.
- Logs each action extensively. All logfiles are available below the browser window.
- Validates inputs! I’ve done much to ensure there is little to no risk from Javascript or SQL injection. Please be careful. I made sure to do this based on an XKCD comic strip I saw in high school: https://m.xkcd.com/327/
- A lot more. It is designed to turn your natural language input into results, and does its humble best.

Here’s what needs work:
- Caching, memory, more functionality.
- Version control
- Managing volume mounts in regards to browser profiles/databases. They can be kept inside the container, I just need to adjust the containers/ports for conflicts.
- This section

This version of Zenbot is designed to be mindful of context length and run on inexpensive GPUs. I built this whole project on a very budget MiniPC, and tested it with a specific fine-tuned model. For operating Zenbot, I would HIGHLY recommend using David_AU’s models, particularly the Brainstorm variants. Not only do they know to operate Zenbot nearly 100% of the time, but they seem to have been trained on the Smolagents library, making much of the ‘thinking’ already integrated.

Search for and download them here: https://hf.tst.eu/model

I did most testing using DavidAU/Qwen3-Jan-Nano-128k-6B-Brainstorm20x which was fast for my testing cases, but I would VERY MUCH RECOMMEND looking at the MoE models, like Qwen3-30b-whatever. His MoE models are excellent. Between non-thinking and thinking models, I like the results I get from non-thinking models.

I would also highly recommend adjusting the extraction method to extract more text, and altering llama.cpp’s GPU usage in the .env file. That will truly allow Zenbot to work its magic.

<br>
</br>

#### And so, I introduce to you Zenbot, the web automation service without the automation. It's just a mathematical word-generator with a set of word-tools, let free on the internet.

<br>
</br>

## **AUTHOR'S NOTE**
For full disclosure, I am a writer, not a developer. I barely know print hello world. I began this project using Claude as a way to automate my own web research and social media activities. What came out of it was a much larger project that took many months to complete and taught me a lot about AI, programming, and computer science. It’s not that I assumed it wouldn’t be hard, but that I assumed it wouldn’t be so complex. I can confidently say that I understand most of this project, but of course, I don’t know what I don’t know. Use Zenbot at your own risk. It’s as secure as a VIBE CODING AUTHOR knows how to make it.

What I have learned more than anything is that my very basic hardware cannot handle LLMs very well. I have made sure every part of this project is as lightweight and fast as possible. If you choose to support me by donating, that money would first and foremost go towards making this project harder, better, faster, and stronger. I’d also like to direct you to my Amazon page, because on God, writing books doesn't make money. My novel **[Well's Rest](https://www.amazon.com/Wells-Rest-Mitch-Davis/dp/0646826778?ref_=ast_author_mpb)** is on **[Amazon](https://www.amazon.com/Wells-Rest-Mitch-Davis/dp/0646826778?ref_=ast_author_mpb)**.

Zenbot might even be able to buy it for you.

It will definitely be able to find me on Royal Road:
https://www.royalroad.com/fiction/126900/wells-rest-grimdark-pirate-action-watch-book-trailer

<br>
</br>

I am of the opinion that Zenbot demonstrates how mainstream approaches to LLMs are changing. Small, tailored models are the future for operating untold new and old technologies. I do not know if they should be writing words that mean things to humans. Check out my website at www.akickintheteeth.com. That is where I've been documenting my other experiments with AI. It's a brave new world!

<br>
</br>

## **Getting Started**
### **Requirements:**
- **Podman or Docker** I used Podman. I use a custom storage directory for my Podman setup. You'll have to adapt a little.
- **Podman/Docker Compose** Runs stuff.
- **Linux** I use Mint.
- **Open WebUI** or equivalent. (podman pull ghcr.io/open-webui/open-webui:main) ;)

### **Initial Setup**
- Open the Zenbot Yaml Runner.
- Rename the ROOT files to .env and docker-compose.yml
- Configure the docker-compose file to suit your setup.
- Configure the .env file to suit your setup. My hardware is extremely basic, so you will definitely need to adjust. ALSO HIGHLY IMPORTANT is configuring your Podman LLM model directory.

- Go to localhost:3000 and configure the tool server:
  -  Navigate to http://localhost:3000
  -  Go to Settings → Connections → OpenAPI
  -  Add URL: http://openapi-tools:9000 
  -  openapi.json
  -  Click "Add" and verify tools appear
  -  Go to Open WebUI's model settings and enable tool use for that model specifically (you will have to do this each time, but only once for each model)
- Run the code to start the Zenbot virtual environment.
- Got to localhost:8888

- You can externally monitor the logfiles at:
  - podman logs -f openapi-tools (this one gives a live readout of Zenbot's progress, with error handling)
  - podman logs -f zendriver (more information about what's going on)


Below is some stuff Claude put together. It’s mostly accurate. Just more detail.

<br>
</br>

### **Core Architecture**

#### **1. Browser Automation Layer (Zendriver)**
- **Undetectable Chrome automation** using CDP (Chrome DevTools Protocol) via zendriver
- Runs in a **virtual Wayland/Sway display** with full GPU acceleration
- **VNC debugging** on port 5910 for visual monitoring
- **Fresh profiles** by default for each session (avoiding detection)
- Full API with endpoints for:
  - Navigation with wait conditions (working)
  - Element finding by selector or text (working)
  - Clicking, typing (with human-like delays) (working)
  - Scrolling (directional and to elements)
  - Tab navigation
  - Element discovery (working)
  - Content extraction with fallbacks
  - Parallel operations

#### **2. AI Agent Layer (SmolAgents + LLM)**
- **SmolAgents framework** integration allowing LLMs to use browser tools autonomously
- **Local LLM inference** via llama.cpp with Vulkan GPU acceleration (or your own drop-in LLM setup, its entirely workable)

- **Tool suite for agents**:

### Browser Control
- `NavigateBrowserTool` - Navigate to URLs
- `ClickElementTool` - Click elements
- `TypeTextTool` - Type text into inputs
- `ScrollPageTool` - Scroll pages
- `KeyboardNavigationTool` - Press keyboard keys

### Content Extraction
- `ExtractContentTool` - Extract page content
- `ParallelExtractionTool` - Extract from multiple selectors
- `GarboPageMarkdownTool` - Export page as Markdown

### Utility Tools
- `WebSearchTool` - Search various search engines
- `ScreenshotTool` - Capture screenshots
- `CloudflareBypassTool` - Handle anti-bot challenges
- `GetCurrentURLTool` - Get current page URL
- `SearchHistoryTool` - Access cached searches



#### **3. Caching Infrastructure**
- **L1 Cache (Redis)**: Fast in-memory caching with LRU eviction
- **L2 Cache (DuckDB)**: Structured data storage for:
  - Extracted page content
  - Element selector performance tracking
  - Workflow results
  - Search history
  - Failed selector tracking
- **Intelligent caching strategies**:
  - Domain-specific selector tracking
  - Extraction result caching with TTL
  - Navigation result caching
  - Workflow state persistence

#### **4. Service Integration**
- **OpenAPI Tools Server**: Bridge between SmolAgents and Zendriver
- **Open WebUI**: Chat interface for interacting with the LLM

### **Key Technical Achievements**
1. **Robust extraction system**:
   - Multiple strategies for text extraction
   - Metadata extraction capabilities
   - Support for both visible and hidden text

2. **Enhanced workflows**:
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
- Health checks on all services (working)
- Automatic restart policies (working)
- Error tracking and logging (working)
- Cache fallbacks if extraction fails

#### **Performance**
- GPU-accelerated browser rendering (working, see my other repos)
- Parallel extraction capabilities
- Intelligent caching to reduce re-scraping
- Optimized LLM inference with batching

#### **Security & Stealth**
- Undetectable by anti-bot systems (Cloudflare, etc.)
- Persistent browser profiles (working)
- No automation markers
- Real browser behavior simulation (working)

#### **Scalability**
- Docker-based deployment
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


CREDITS:

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
