#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistent, validated qBittorrent alternative Web UI theme management."""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


class ThemeError(ValueError):
    pass


THEMES_ROOT = Path(os.environ.get("QBTOS_THEMES_ROOT", "/themes"))
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "/bin/false",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def validate_name(value):
    if not isinstance(value, str) or not NAME_RE.fullmatch(value) or value in {".", ".."}:
        raise ThemeError("Theme name must use 1-64 letters, numbers, dots, dashes, or underscores")
    return value


def validate_branch(value):
    if value in (None, ""):
        return ""
    if (not isinstance(value, str) or not BRANCH_RE.fullmatch(value)
            or ".." in value or "@{" in value or value.endswith((".", "/"))):
        raise ThemeError("Git branch name is invalid")
    return value


def validate_git_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(c in value for c in "\r\n\0"):
        raise ThemeError("Git repository URL is invalid")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ThemeError("Use an HTTPS Git URL without credentials, query parameters, or fragments")
    return value


def _run_git(argv, *, timeout=180):
    try:
        return subprocess.run(
            ["/usr/bin/git", "-c", "protocol.file.allow=never", *argv],
            check=True, text=True, timeout=timeout, env=GIT_ENV,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as error:
        raise ThemeError("Git is not installed in this image") from error
    except subprocess.TimeoutExpired as error:
        raise ThemeError("Git operation timed out") from error
    except subprocess.CalledProcessError as error:
        # Git may echo a remote URL in stderr. Do not return it to the browser.
        failure = error.stderr or ""
        if "remote-https' is not a git command" in failure:
            message = "This qbtOS image is missing Git HTTPS transport support"
        elif "Could not resolve host" in failure:
            message = "Git host name resolution failed"
        elif "SSL certificate problem" in failure:
            message = "Git could not validate the repository TLS certificate"
        elif "Remote branch" in failure and "not found" in failure:
            message = "The requested Git branch does not exist"
        else:
            message = "Git operation failed; verify the public repository and branch"
        raise ThemeError(message) from error


def _theme_path(name, root=THEMES_ROOT):
    name = validate_name(name)
    root = Path(root).resolve(strict=True)
    path = root / name
    if path.parent != root:
        raise ThemeError("Theme path escapes /themes")
    return path


def validate_theme(path):
    path = Path(path)
    index = path / "public/index.html"
    if not index.is_file() or index.is_symlink():
        raise ThemeError("Theme must contain a regular public/index.html file")
    for directory, names, filenames in os.walk(path, followlinks=False):
        for name in (*names, *filenames):
            if (Path(directory) / name).is_symlink():
                raise ThemeError("Theme trees may not contain symbolic links")
    return path


def _git_metadata(path):
    if not (path / ".git").is_dir():
        return None, None
    try:
        repository = _run_git(["-C", str(path), "config", "--get", "remote.origin.url"], timeout=10)
        url = validate_git_url(repository.stdout.strip())
        branch_result = _run_git(["-C", str(path), "branch", "--show-current"], timeout=10)
        branch = validate_branch(branch_result.stdout.strip())
        return url, branch
    except ThemeError:
        return None, None


def list_themes(root=THEMES_ROOT):
    root = Path(root)
    if not root.is_dir():
        return []
    themes = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        try:
            validate_name(path.name)
            if path.is_symlink() or not path.is_dir():
                continue
            validate_theme(path)
            url, branch = _git_metadata(path)
            themes.append({
                "name": path.name,
                "git_managed": url is not None,
                "repository": url or "",
                "branch": branch or "",
            })
        except (OSError, ThemeError):
            continue
    return themes


def _clone(url, destination, branch=""):
    arguments = ["clone", "--depth", "1", "--single-branch", "--no-tags"]
    if branch:
        arguments.extend(["--branch", branch])
    arguments.extend(["--", url, str(destination)])
    _run_git(arguments)
    validate_theme(destination)


def install_theme(name, url, branch="", root=THEMES_ROOT):
    name = validate_name(name)
    url = validate_git_url(url)
    branch = validate_branch(branch)
    root = Path(root)
    if not root.is_dir():
        raise ThemeError("Persistent /themes storage is unavailable")
    destination = _theme_path(name, root)
    if destination.exists():
        raise ThemeError("A theme with this name already exists")
    temporary_parent = Path(tempfile.mkdtemp(prefix=f".{name}.install-", dir=root))
    checkout = temporary_parent / "checkout"
    try:
        _clone(url, checkout, branch)
        os.replace(checkout, destination)
    finally:
        shutil.rmtree(temporary_parent, ignore_errors=True)
    return name


def update_theme(name, root=THEMES_ROOT):
    destination = _theme_path(name, root)
    validate_theme(destination)
    url, branch = _git_metadata(destination)
    if not url:
        raise ThemeError("Theme is not managed by a validated HTTPS Git repository")
    temporary_parent = Path(tempfile.mkdtemp(prefix=f".{name}.update-", dir=destination.parent))
    checkout = temporary_parent / "checkout"
    backup = temporary_parent / "previous"
    try:
        _clone(url, checkout, branch)
        os.replace(destination, backup)
        try:
            os.replace(checkout, destination)
        except OSError:
            os.replace(backup, destination)
            raise
    finally:
        shutil.rmtree(temporary_parent, ignore_errors=True)
    return name


def theme_preferences(config, name):
    name = validate_name(name) if name else ""
    replacements = {
        "WebUI\\AlternativeUIEnabled": "true" if name else "false",
        "WebUI\\RootFolder": f"/themes/{name}" if name else "",
    }
    prefixes = tuple(f"{key}=" for key in replacements)
    lines = [line for line in config.splitlines() if not line.startswith(prefixes)]
    try:
        preferences = lines.index("[Preferences]")
    except ValueError:
        if lines and lines[-1]:
            lines.append("")
        lines.append("[Preferences]")
        preferences = len(lines) - 1
    insertion = len(lines)
    for index in range(preferences + 1, len(lines)):
        if lines[index].startswith("[") and lines[index].endswith("]"):
            insertion = index
            break
    lines[insertion:insertion] = [f"{key}={value}" for key, value in replacements.items()]
    return "\n".join(lines).rstrip() + "\n"


def active_theme(config):
    enabled = False
    root = ""
    for line in config.splitlines():
        if line == "WebUI\\AlternativeUIEnabled=true":
            enabled = True
        elif line.startswith("WebUI\\RootFolder="):
            root = line.split("=", 1)[1]
    prefix = "/themes/"
    if not enabled or not root.startswith(prefix):
        return ""
    try:
        return validate_name(root[len(prefix):])
    except ThemeError:
        return ""
