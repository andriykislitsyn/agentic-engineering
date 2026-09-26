---
title: "Zsh setup with Oh My Zsh"
description: "A fresh macOS terminal in 15 minutes: Oh My Zsh, Powerlevel10k, plugins, and modern CLI replacements."
pubDate: 2026-06-11
category: setup
tags: [zsh, terminal]
---

My terminal setup from scratch on a fresh macOS machine. It takes about 15 minutes and makes the shell a pleasure to use.

## The stack

- **Zsh**: default shell on macOS since Catalina
- **Oh My Zsh**: plugin framework (manages plugins, themes, updates)
- **Powerlevel10k**: fast, configurable prompt theme with instant prompt
- **Modern CLI replacements**: `bat`, `lsd`, `ripgrep`, `delta`, `zoxide`, `fzf`

## Step 1: Oh My Zsh

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
```

This creates `~/.zshrc` with sensible defaults. Everything below goes into that file.

## Step 2: Powerlevel10k

```bash
git clone --depth=1 https://github.com/romkatv/powerlevel10k.git \
  ${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/themes/powerlevel10k
```

Set the theme in `~/.zshrc`:

```zsh
ZSH_THEME="powerlevel10k/powerlevel10k"
```

On next shell start, P10k runs its configuration wizard. Pick what you like. You can re-run it anytime with `p10k configure`.

The instant prompt is what makes the shell feel fast. It renders the prompt immediately while the rest of `.zshrc` is still loading:

```zsh
# This goes at the very top of .zshrc
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi
```

## Step 3: Plugins

Install the external plugins first (not bundled with Oh My Zsh):

```bash
git clone https://github.com/zsh-users/zsh-autosuggestions \
  ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-autosuggestions

git clone https://github.com/zsh-users/zsh-syntax-highlighting \
  ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-syntax-highlighting

git clone https://github.com/zsh-users/zsh-completions \
  ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-completions
```

Then add everything to `~/.zshrc`:

```zsh
plugins=(
    # External (installed above)
    zsh-autosuggestions          # Fish-like suggestions from history
    zsh-syntax-highlighting      # Colors valid/invalid commands as you type
    zsh-completions              # Additional completion definitions
    zsh-interactive-cd           # Tab completion for cd with fzf

    # Bundled with Oh My Zsh
    aliases                      # `als` to search aliases
    aws                          # AWS CLI completions
    brew                         # Homebrew completions
    docker                       # Docker completions
    fzf                          # Fuzzy finder integration
    git                          # Git aliases (gst, gco, gp, etc.)
    helm                         # Helm completions
    kubectl                      # kubectl completions + aliases
    kubectx                      # kubectx/kubens completions
    macos                        # macOS utilities (ofd, pfd, etc.)
    pip                          # pip completions
    python                       # Python aliases
    urltools                     # urlencode/urldecode
    web-search                   # `google "search term"` from terminal
)
```

Pick what's relevant to your stack, and skip plugins for tools you don't use. Each plugin adds to startup time.

## Step 4: Modern CLI replacements

```bash
brew install bat lsd ripgrep git-delta zoxide fzf
```

Add aliases to `~/.zshrc`:

```zsh
alias cat=bat       # Syntax-highlighted file viewer
alias ls=lsd        # Colorful ls with icons and tree view
alias grep=rg       # Faster grep with sane defaults
```

Initialize zoxide (at the end of `.zshrc`):

```zsh
eval "$(zoxide init zsh)"
```

Now `z` replaces `cd`. It learns your most-used directories and fuzzy-matches:

```bash
z work        # jumps to ~/workspace (or wherever you go most)
z dot         # jumps to ~/dotfiles
```

## Step 5: Quality of life

A few settings I find essential:

```zsh
ENABLE_CORRECTION="true"           # Suggest corrections for typos
COMPLETION_WAITING_DOTS="true"     # Show dots while waiting for completion

bindkey -e                         # Emacs key bindings
bindkey '\e\e[C' forward-word      # Option+Right to jump words
bindkey '\e\e[D' backward-word     # Option+Left to jump words
```

## The result

A shell that:
- Opens in ~140ms (see [Shell startup: from 5s to 140ms](/agentic-engineering/articles/zshrc-from-5s-to-140ms/) for how)
- Suggests commands as you type (from history)
- Colors valid/invalid commands in real-time
- Shows a rich prompt with git status, Python venv, and cloud context
- Fuzzy-finds files, directories, and history with `fzf`
- Remembers where you go and jumps there with `z`

The full config is in [zsh/.zshrc](https://github.com/andriykislitsyn/dotfiles/blob/main/zsh/.zshrc).
