---
title: "Shell startup: from 5s to 140ms"
description: "Lazy-loading NVM and virtualenvwrapper, and deduplicating compinit, took zsh startup from over 5 seconds to about 140ms."
pubDate: 2026-06-11
category: setup
tags: [zsh, performance]
---

My zsh shell took over 5 seconds to start. I timed it, found the bottlenecks, and got it down to ~140ms. Here's what worked.

## Measuring

Before changing anything, measure:

```bash
time zsh -i -c exit
```

Run it 3-5 times and take the median. On my machine this was consistently over 5 seconds.

## The Bottlenecks

### NVM (~300ms)

NVM sources a full shell script on every shell startup, even if you never use `node` in that session. The fix is lazy-loading — wrap the commands in functions that load the real NVM on first use:

```zsh
nvm() { unset -f nvm node npm npx; [[ -s "$HOME/.nvm/nvm.sh" ]] && . "$HOME/.nvm/nvm.sh"; nvm "$@"; }
node() { unset -f nvm node npm npx; [[ -s "$HOME/.nvm/nvm.sh" ]] && . "$HOME/.nvm/nvm.sh"; node "$@"; }
npm() { unset -f nvm node npm npx; [[ -s "$HOME/.nvm/nvm.sh" ]] && . "$HOME/.nvm/nvm.sh"; npm "$@"; }
npx() { unset -f nvm node npm npx; [[ -s "$HOME/.nvm/nvm.sh" ]] && . "$HOME/.nvm/nvm.sh"; npx "$@"; }
```

The first call to any of these unsets all four functions, loads NVM for real, then forwards the call. Every subsequent call goes through the real NVM at native speed.

### virtualenvwrapper (~200ms)

Same problem, same fix:

```zsh
_load_venvwrapper() { unset -f workon mkvirtualenv rmvirtualenv; source /opt/homebrew/bin/virtualenvwrapper.sh; }
workon() { _load_venvwrapper; workon "$@"; }
mkvirtualenv() { _load_venvwrapper; mkvirtualenv "$@"; }
rmvirtualenv() { _load_venvwrapper; rmvirtualenv "$@"; }
```

### compinit deduplication

Oh My Zsh calls `compinit` once, but some plugins and custom configurations trigger it again. Each `compinit` call scans the entire fpath for completion functions. Making sure it only runs once saved another noticeable chunk.

## The Tools That Didn't Slow Things Down

These are instant and worth keeping:

- **zoxide** (`eval "$(zoxide init zsh)"`) — negligible
- **Powerlevel10k instant prompt** — actually *improves* perceived startup by rendering the prompt before the rest of .zshrc finishes
- **fzf** — plugin is lightweight

## Result

```
Before:  5.2s average
After:   ~140ms average
```

The shell now opens faster than my fingers can move to start typing. The key insight: most startup cost comes from tools eagerly initializing "just in case." Lazy-loading defers that cost to the moment you actually need it — and for many sessions, that moment never comes.
