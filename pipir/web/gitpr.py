"""Fetch GitHub PR contents with plain system git — no gh CLI, no API.

GitHub (incl. Enterprise) exposes each PR as a server-side ref
`refs/pull/<N>/head` that any authenticated `git fetch` can retrieve using
git's existing credentials (SSH key / credential helper).

Two modes:
- local clone: fetch the PR ref into an existing checkout;
- pasted PR URL: maintain a bare, blob-less cache clone under
  ~/.cache/pipir/repos/ and fetch the PR refs into that. Auth is git's own
  (public repos need nothing; private ones need whatever `git clone` needs).
"""

import os
import re
import subprocess

_PR_URL = re.compile(
    r"^https?://([^/]+)/([^/]+)/([^/]+?)(?:\.git)?/pull/(\d+)")


class GitError(RuntimeError):
    pass


def _cred_flags():
    """One-shot credential helper when PIPIR_GIT_PASSWORD is set.

    Supplies PIPIR_GIT_USER / PIPIR_GIT_PASSWORD from the environment for
    git-over-https auth (a plain account password, or a PAT used as one).
    The values are read inside the helper at call time, so they never
    appear in process arguments or on disk. Empty helper first resets any
    configured helpers so these credentials win (and nothing prompts).
    """
    if not os.environ.get("PIPIR_GIT_PASSWORD"):
        return []
    helper = ("!f() { echo \"username=${PIPIR_GIT_USER:-git}\"; "
              "echo \"password=$PIPIR_GIT_PASSWORD\"; }; f")
    return ["-c", "credential.helper=", "-c", "credential.helper=" + helper]


def _git(repo, *args, timeout=120, auth=False):
    cmd = ["git"] + (["-C", repo] if repo else []) \
        + (_cred_flags() if auth else []) + list(args)
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise GitError((proc.stderr or proc.stdout)
                       .decode("utf-8", "replace").strip()
                       or "git %s failed" % " ".join(args))
    return proc.stdout


def _text(repo, *args):
    return _git(repo, *args).decode("utf-8", "replace").strip()


def pr_slp_files(repo, number, remote="origin"):
    """Fetch PR #number; return (base_sha, head_sha, [changed .slp paths])."""
    _git(repo, "fetch", "--quiet", remote, "pull/%d/head" % int(number))
    head = _text(repo, "rev-parse", "FETCH_HEAD")

    # Base: merge-base of the PR head and the remote default branch.
    try:
        default = _text(repo, "symbolic-ref", "--short",
                        "refs/remotes/%s/HEAD" % remote)
    except GitError:
        default = None
        for cand in ("%s/main" % remote, "%s/master" % remote):
            try:
                _text(repo, "rev-parse", "--verify", cand)
                default = cand
                break
            except GitError:
                continue
        if default is None:
            raise GitError("cannot determine the default branch of %s; "
                           "run: git remote set-head %s -a" % (remote, remote))
    base = _text(repo, "merge-base", default, head)

    changed = _text(repo, "diff", "--name-only", "--diff-filter=ACMR",
                    base, head).splitlines()
    slps = [p for p in changed if p.endswith(".slp")]
    return base, head, slps


def blob(repo, rev, path):
    """File content at rev, or None if it does not exist there."""
    try:
        return _git(repo, "show", "%s:%s" % (rev, path)).decode("utf-8")
    except GitError:
        return None


def parse_pr_url(url):
    m = _PR_URL.match(url.strip())
    if not m:
        raise GitError("not a PR URL (expected "
                       "https://<host>/<owner>/<repo>/pull/<N>): %s" % url)
    host, owner, repo, number = m.groups()
    return host, owner, repo, int(number)


def _cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") \
        or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "pipir", "repos")


def _cache_repo(host, owner, repo):
    """Bare, blob-less cache clone for a remote repo; cloned on first use."""
    path = os.path.join(_cache_dir(),
                        "%s_%s_%s.git" % (host, owner, repo))
    if not os.path.isdir(path):
        os.makedirs(_cache_dir(), exist_ok=True)
        url = "https://%s/%s/%s.git" % (host, owner, repo)
        try:
            _git(None, "clone", "--bare", "--filter=blob:none",
                 url, path, timeout=600, auth=True)
        except GitError as exc:
            raise GitError(
                "cannot clone %s: %s\n(private repo? either make plain "
                "`git clone %s` work, set PIPIR_GIT_USER/PIPIR_GIT_PASSWORD "
                "in .env, or use local-clone mode)" % (url, exc, url))
    return path


def pr_url_slp_files(url):
    """Resolve a pasted PR URL via the cache clone.

    Returns (repo_path, base_sha, head_sha, [changed .slp paths]).
    """
    host, owner, repo, number = parse_pr_url(url)
    path = _cache_repo(host, owner, repo)
    # Default branch of the remote (target of the PR's merge-base).
    sym = _git(path, "ls-remote", "--symref", "origin", "HEAD",
               auth=True).decode("utf-8", "replace")
    m = re.search(r"^ref:\s+refs/heads/(\S+)\s+HEAD", sym, re.M)
    default = m.group(1) if m else "main"
    _git(path, "fetch", "--force", "--quiet", "origin",
         "refs/pull/%d/head:refs/pipir/head" % number,
         "refs/heads/%s:refs/pipir/base" % default,
         timeout=600, auth=True)
    head = _text(path, "rev-parse", "refs/pipir/head")
    base = _text(path, "merge-base", "refs/pipir/base", head)
    changed = _text(path, "diff", "--name-only", "--diff-filter=ACMR",
                    base, head).splitlines()
    return path, base, head, [p for p in changed if p.endswith(".slp")]
