"""Portas abertas pelos terminais: o servidor que o agente subiu (npm run dev, uvicorn...)."""

from __future__ import annotations

import subprocess


def children_map() -> dict[int, list[int]]:
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=5).stdout
    tree: dict[int, list[int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            tree.setdefault(int(parts[1]), []).append(int(parts[0]))
    return tree


def descendants(root: int, tree: dict[int, list[int]]) -> set[int]:
    seen, stack = {root}, [root]
    while stack:
        for child in tree.get(stack.pop(), []):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def parse_lsof(output: str) -> dict[int, set[int]]:
    """Saída de `lsof -F pn`: linhas `p<pid>` seguidas de `n<endereço>:<porta>`."""
    result: dict[int, set[int]] = {}
    pid = None
    for line in output.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            port = line.rsplit(":", 1)[-1]
            if port.isdigit():
                result.setdefault(pid, set()).add(int(port))
    return result


def listening_ports(pids: set[int]) -> dict[int, set[int]]:
    if not pids:
        return {}
    out = subprocess.run(
        ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-a", "-p", ",".join(str(p) for p in sorted(pids)), "-F", "pn"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return parse_lsof(out.stdout)


def ports_by_session(roots: dict[str, int]) -> dict[str, list[int]]:
    """id da sessão → portas em escuta do processo dela e dos filhos."""
    if not roots:
        return {}
    tree = children_map()
    owner: dict[int, str] = {}
    for session_id, pid in roots.items():
        for p in descendants(pid, tree):
            owner.setdefault(p, session_id)
    found: dict[str, set[int]] = {}
    for pid, ports in listening_ports(set(owner)).items():
        found.setdefault(owner[pid], set()).update(ports)
    return {session_id: sorted(found.get(session_id, set())) for session_id in roots}
