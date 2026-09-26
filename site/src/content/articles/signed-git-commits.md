---
title: "Signed Git commits with GPG"
description: "Git does not verify who made a commit. GPG signing does, and setup takes 5 minutes."
pubDate: 2026-06-11
category: setup
tags: [git, security]
---

Every commit I push is GPG-signed. GitHub shows a green "Verified" badge next to them, which proves the commit actually came from me and wasn't spoofed. Setup takes 5 minutes.

## Why Bother

Git doesn't verify identity. Anyone can set `user.name` and `user.email` to whatever they want:

```bash
git config user.email "linus@kernel.org"
git commit -m "totally legit"
```

GPG signing adds cryptographic proof that a commit came from the key holder. GitHub and GitLab both verify signatures and show it in the UI.

## Setup

### 1. Install GPG

On macOS, the easiest option is [GPG Suite](https://gpgtools.org/):

```bash
brew install --cask gpg-suite
```

Or just the CLI tools:

```bash
brew install gnupg
```

### 2. Generate a Key

```bash
gpg --full-generate-key
```

When prompted:
- Key type: **RSA and RSA** (default)
- Key size: **4096** bits
- Expiration: your choice (I use no expiration for personal keys, 1 year for work)
- Name and email: use the **same email** as your GitHub account

### 3. Find Your Key ID

```bash
gpg --list-secret-keys --keyid-format=long
```

Output looks like:

```
sec   rsa4096/AABBCCDD11223344 2024-01-15 [SC]
      1234567890ABCDEF1234567890AABBCCDD11223344
uid                 [ultimate] Your Name <your.email@example.com>
ssb   rsa4096/5566778899AABBCC 2024-01-15 [E]
```

The key ID is the part after `rsa4096/` on the `sec` line — `AABBCCDD11223344` in this example.

### 4. Add the Key to GitHub

Export the public key:

```bash
gpg --armor --export AABBCCDD11223344
```

Copy the entire output (including `-----BEGIN PGP PUBLIC KEY BLOCK-----` and `-----END PGP PUBLIC KEY BLOCK-----`) and paste it in:

**GitHub** → Settings → SSH and GPG keys → New GPG key

### 5. Configure Git

Tell git to sign all commits with your key:

```bash
git config --global user.signingkey AABBCCDD11223344
git config --global commit.gpgsign true
git config --global tag.gpgSign true
```

With `commit.gpgsign = true`, every commit is signed automatically — no need to pass `-S` each time.

### 6. Fix the TTY

GPG needs to know which terminal to use for the passphrase prompt. Add to `~/.zshrc`:

```bash
export GPG_TTY=$(tty)
```

Without this, you'll get `error: gpg failed to sign the data` when committing from the terminal.

## Verifying It Works

Make a test commit and check:

```bash
git commit --allow-empty -m "test signed commit"
git log --show-signature -1
```

You should see `Good signature from "Your Name <your.email@example.com>"` in the output. On GitHub, the commit will show a green "Verified" badge.

## Troubleshooting

**"gpg failed to sign the data"** — usually means `GPG_TTY` is not set, or the GPG agent lost the passphrase cache. Run `export GPG_TTY=$(tty)` and try again.

**"secret key not available"** — the signing key ID in your git config doesn't match any key in your keyring. Double-check with `gpg --list-secret-keys`.

**GitHub shows "Unverified"** — the email on the GPG key must match a verified email on your GitHub account. Check under Settings → Emails.

## Config Reference

The relevant section in [git/.gitconfig](https://github.com/andriykislitsyn/dotfiles/blob/main/git/.gitconfig):

```ini
[commit]
    gpgsign = true

[tag]
    gpgSign = true

[user]
    signingkey = YOUR_KEY_ID
```
