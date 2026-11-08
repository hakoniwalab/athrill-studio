"""A flattened Devicetree (DTB) reader for Athrill Studio.

Reads a .dtb as Athrill does (the board comes only from it) and gives the
nodes, their properties and the references between them: the bus tree
(parent and child) and the phandle edges (interrupt parent, DMA, clocks,
resets, GPIOs, pin control, value sources). No dependency besides Python.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9

# Properties whose value starts with a phandle per entry, and what the edge means.
REFERENCE_PROPERTIES = {
    "interrupt-parent": "interrupt",
    "interrupts-extended": "interrupt",
    "dmas": "dma",
    "clocks": "clock",
    "resets": "reset",
    "pinctrl-0": "pinctrl",
    "value-source": "value",
    "io-channels": "adc",
    "pwms": "pwm",
}


@dataclass
class Node:
    path: str
    name: str
    parent: str | None
    properties: dict[str, bytes] = field(default_factory=dict)

    def string_list(self, name: str) -> list[str]:
        value = self.properties.get(name)
        if not value:
            return []
        return [s.decode("utf-8", "replace") for s in value.rstrip(b"\0").split(b"\0")]

    def cells(self, name: str) -> list[int]:
        value = self.properties.get(name, b"")
        return list(struct.unpack(f">{len(value) // 4}I", value[: len(value) // 4 * 4]))

    @property
    def compatible(self) -> list[str]:
        return self.string_list("compatible")

    @property
    def status(self) -> str:
        values = self.string_list("status")
        return values[0] if values else "okay"

    @property
    def phandle(self) -> int | None:
        cells = self.cells("phandle") or self.cells("linux,phandle")
        return cells[0] if cells else None


def parse(data: bytes) -> dict[str, Node]:
    """Nodes by path, in file order."""
    (magic, _total, off_struct, off_strings, _off_rsv, _version, _last, _boot,
     size_strings, size_struct) = struct.unpack(">10I", data[:40])
    if magic != FDT_MAGIC:
        raise ValueError("not a flattened Devicetree (bad magic)")
    strings = data[off_strings:off_strings + size_strings]
    nodes: dict[str, Node] = {}
    stack: list[str] = []
    pos = off_struct
    end = off_struct + size_struct

    def align(p: int) -> int:
        return (p + 3) & ~3

    while pos < end:
        (token,) = struct.unpack(">I", data[pos:pos + 4])
        pos += 4
        if token == FDT_BEGIN_NODE:
            zero = data.index(b"\0", pos)
            name = data[pos:zero].decode("utf-8", "replace")
            pos = align(zero + 1)
            parent = stack[-1] if stack else None
            if parent is None:
                path = "/"
            elif parent == "/":
                path = "/" + name
            else:
                path = parent + "/" + name
            nodes[path] = Node(path=path, name=name or "/", parent=parent)
            stack.append(path)
        elif token == FDT_END_NODE:
            stack.pop()
        elif token == FDT_PROP:
            length, nameoff = struct.unpack(">II", data[pos:pos + 8])
            pos += 8
            value = data[pos:pos + length]
            pos = align(pos + length)
            pname = strings[nameoff:strings.index(b"\0", nameoff)].decode()
            nodes[stack[-1]].properties[pname] = value
        elif token == FDT_NOP:
            continue
        elif token == FDT_END:
            break
        else:
            raise ValueError(f"bad token {token} at {pos - 4}")
    return nodes


def enabled(nodes: dict[str, Node], path: str) -> bool:
    """A node is enabled when it and every parent are (status absent or okay)."""
    while path is not None:
        node = nodes[path]
        if node.status not in ("okay", "ok"):
            return False
        path = node.parent
    return True


def references(nodes: dict[str, Node]) -> list[tuple[str, str, str]]:
    """(from path, to path, kind) for the phandle references of every node.

    A reference property is a list of entries, each a phandle and the target's
    cells (#dma-cells, #clock-cells, ...). Only the phandles are needed, so an
    entry is decoded with the cell count of its target when the target has one
    and the remaining length otherwise.
    """
    by_phandle = {n.phandle: n.path for n in nodes.values() if n.phandle is not None}
    count_names = {
        "dma": "#dma-cells", "clock": "#clock-cells", "reset": "#reset-cells",
        "interrupt": "#interrupt-cells", "pwm": "#pwm-cells", "adc": "#io-channel-cells",
    }
    edges: list[tuple[str, str, str]] = []

    def interrupt_parent(path: str) -> str | None:
        while path is not None:
            cells = nodes[path].cells("interrupt-parent")
            if cells:
                return by_phandle.get(cells[0])
            path = nodes[path].parent
        return None

    for node in nodes.values():
        # "interrupts" goes to the inherited interrupt parent (the NVIC, the PLIC)
        if "interrupts" in node.properties and "interrupt-parent" not in node.properties:
            target = interrupt_parent(node.parent)
            if target is not None:
                edges.append((node.path, target, "interrupt"))
        for prop, kind in REFERENCE_PROPERTIES.items():
            if prop not in node.properties:
                continue
            cells = node.cells(prop)
            i = 0
            while i < len(cells):
                target = by_phandle.get(cells[i])
                if target is None:
                    break
                edges.append((node.path, target, kind))
                if prop in ("interrupt-parent", "pinctrl-0", "value-source"):
                    i += 1
                    continue
                extra = nodes[target].cells(count_names.get(kind, ""))
                i += 1 + (extra[0] if extra else 0)
        for prop, value in node.properties.items():
            if prop.endswith("-gpios") or prop == "gpios":
                cells = node.cells(prop)
                i = 0
                while i < len(cells):
                    target = by_phandle.get(cells[i])
                    if target is None:
                        break
                    edges.append((node.path, target, "gpio"))
                    extra = nodes[target].cells("#gpio-cells")
                    i += 1 + (extra[0] if extra else 2)
    return edges


def describe(data: bytes) -> dict:
    """The board as Studio shows it: the enabled nodes with a compatible, their
    bus parents, and the references between them."""
    nodes = parse(data)
    shown = {
        path for path, node in nodes.items()
        if path == "/" or (node.compatible and enabled(nodes, path))
    }
    out_nodes = []
    for path in nodes:
        if path not in shown:
            continue
        node = nodes[path]
        parent = node.parent
        while parent is not None and parent not in shown:
            parent = nodes[parent].parent
        reg = node.cells("reg")
        out_nodes.append({
            "path": path,
            "name": node.name,
            "parent": parent,
            "compatible": node.compatible,
            "reg": reg[:2],
            "model": node.string_list("model")[0] if node.string_list("model") else None,
        })
    edges = [
        {"from": a, "to": b, "kind": kind}
        for a, b, kind in references(nodes) if a in shown and b in shown
    ]
    root = nodes["/"]
    return {
        "model": root.string_list("model")[0] if root.string_list("model") else "",
        "compatible": root.compatible,
        "nodes": out_nodes,
        "edges": edges,
    }
