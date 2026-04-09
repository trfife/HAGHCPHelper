ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TERM=xterm-256color

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    git \
    jq \
    openssh-client \
    tmux \
    coreutils \
    findutils \
    grep \
    sed \
    ca-certificates \
    openssl \
    ripgrep \
    procps \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Pre-install Memory MCP server globally (persistent knowledge graph)
RUN npm install -g @modelcontextprotocol/server-memory 2>/dev/null || true

# Install GitHub Copilot CLI (standalone binary — no Node.js needed)
ARG BUILD_ARCH
RUN case "${BUILD_ARCH}" in \
        amd64)  COPILOT_ARCH="x64"   ;; \
        aarch64) COPILOT_ARCH="arm64" ;; \
        *) COPILOT_ARCH="x64"        ;; \
    esac && \
    curl -fsSL \
      "https://github.com/github/copilot-cli/releases/latest/download/copilot-linux-${COPILOT_ARCH}.tar.gz" \
      -o /tmp/copilot.tar.gz && \
    tar -xzf /tmp/copilot.tar.gz -C /usr/local/bin && \
    chmod +x /usr/local/bin/copilot && \
    rm -f /tmp/copilot.tar.gz && \
    copilot --version

# Install ttyd (web terminal server)
RUN case "${BUILD_ARCH}" in \
        amd64)   TTYD_ARCH="x86_64"  ;; \
        aarch64) TTYD_ARCH="aarch64" ;; \
        *) TTYD_ARCH="x86_64"        ;; \
    esac && \
    curl -fsSL \
      "https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.${TTYD_ARCH}" \
      -o /usr/bin/ttyd && \
    chmod +x /usr/bin/ttyd

# Configure tmux
RUN cat > /root/.tmux.conf << 'EOF'
set-option -g history-limit 50000
set-option -g mouse on
set-option -g default-terminal "screen-256color"
set-option -ga terminal-overrides ',xterm*:smcup@:rmcup@'
set-option -g status on
set-option -g status-position bottom
set-option -g status-style "bg=#0d1117,fg=#8b949e"
set-option -g status-left " #[fg=#58a6ff,bold]Copilot CLI #[fg=#484f58]| "
set-option -g status-right "#[fg=#484f58]Session: #[fg=#3fb950]#{session_name} "
set-option -g allow-rename off
set-option -sg escape-time 10
bind -n WheelUpPane if-shell -F -t = "#{mouse_any_flag}" "send-keys -M" "if -Ft= '#{pane_in_mode}' 'send-keys -M' 'select-pane -t=; copy-mode -e; send-keys -M'"
bind -n WheelDownPane select-pane -t= \; send-keys -M
EOF

# Configure bash with aliases and prompt
RUN cat > /root/.bashrc << 'EOF'
export TERM=xterm-256color
export LANG=C.UTF-8
PS1='\[\033[1;36m\]copilot-cli\[\033[0m\]:\[\033[1;34m\]\w\[\033[0m\]\$ '

# Source environment if available
[ -f /data/copilot-env.sh ] && source /data/copilot-env.sh

# Aliases
alias c="copilot"
alias ll="ls -la"
alias ha-config="cd /homeassistant"
alias ha-logs="cat /homeassistant/home-assistant.log 2>/dev/null || echo 'Log not found'"
EOF

RUN echo 'source ~/.bashrc' > /root/.profile

# Copy rootfs overlay (s6 service scripts)
COPY rootfs /

# Copy conversation agent integration into the image for auto-install
COPY ghcp_conversation /opt/ghcp_conversation/

# Ensure s6 service scripts are executable (Windows builds may strip the bit)
RUN chmod +x /etc/services.d/ttyd/run \
    && chmod +x /etc/services.d/copilot-acp/run \
    && chmod +x /etc/services.d/copilot-acp/finish

# Set working directory to HA config
WORKDIR /homeassistant

# Health check — verify ttyd process is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD pgrep -x ttyd > /dev/null || exit 1
