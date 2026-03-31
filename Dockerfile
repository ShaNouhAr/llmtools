# LLMTools - Plateforme multi-modules avec LLM (LM Studio)
FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive

# Python + pip + build essentials
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Pentest tools - Reconnaissance
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap masscan whatweb dnsutils whois wafw00f amass \
    && rm -rf /var/lib/apt/lists/*

# Pentest tools - Web
RUN apt-get update && apt-get install -y --no-install-recommends \
    nikto sqlmap gobuster dirb wfuzz wpscan \
    && rm -rf /var/lib/apt/lists/*

# Pentest tools - Network
RUN apt-get update && apt-get install -y --no-install-recommends \
    netcat-traditional hydra enum4linux smbclient crackmapexec nbtscan \
    && rm -rf /var/lib/apt/lists/*

# Pentest tools - Exploitation
RUN apt-get update && apt-get install -y --no-install-recommends \
    metasploit-framework exploitdb \
    && rm -rf /var/lib/apt/lists/*

# Pentest tools - Passwords
RUN apt-get update && apt-get install -y --no-install-recommends \
    john hashcat wordlists \
    && rm -rf /var/lib/apt/lists/*

# Utilities + networking + SSH client
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget jq tcpdump tshark \
    openssh-client iputils-ping net-tools iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Install ffuf and nuclei (Go binaries, not in Kali repos by default on all arches)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffuf nuclei 2>/dev/null \
    || true \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --ignore-installed --break-system-packages -r requirements.txt

COPY src/ ./src/
COPY templates/ ./templates/
COPY static/ ./static/
COPY .env* ./

# Workspace for agent output files
RUN mkdir -p /workspace /data/reports /data/chats

ENV LLMTOOLS_REPORTS_DIR=/data/reports
ENV LLMTOOLS_CHATS_DIR=/data/chats
ENV LM_STUDIO_MODEL=local-model
ENV TOOL_TIMEOUT=120
ENV AGENT_MAX_ITERATIONS=50

EXPOSE 8000
ENTRYPOINT ["uvicorn", "src.web:app", "--host", "0.0.0.0", "--port", "8000"]
