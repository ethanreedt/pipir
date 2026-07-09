"""Fetch GitHub PR contents with plain system git — no gh CLI, no API.

GitHub (incl. Enterprise) exposes each PR as a server-side ref
`refs/pull/<N>/head` that any authenticated `git fetch` can retrieve using
the clone's existing credentials (SSH key / credential helper).
"""

import subprocess


class GitError(RuntimeError):
    pass


def _git(repo, *args):
    proc = subprocess.run(
        ["git", "-C", repo] + list(args),
        capture_output=True, timeout=120)
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
