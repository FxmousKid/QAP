"""House style for QA pass diagrams: nodes and edges, drawn as an SVG with no dependency. The twin of chart_style.py.

    import sys; sys.path.insert(0, "<skill>/scripts")
    from diagram import Diagram
    d = Diagram(860, 360)
    d.node("app", 20, 20, 220, 96, "iOS app", ["MeetingFormViewModel", "keeps the draft"], "component")
    d.node("rpc", 320, 20, 220, 96, "save_session RPC", ["writes the form"], "changed")
    d.edge([d.side("app", "r"), d.side("rpc", "l")], "on « Valider »", broken=True)
    d.save("img/save-before.svg")        # then {{IMG:save-before.svg}} in the pass

Three views, as the skill asks for each topic (python3 my_diagram.py, nothing to install):
- tech, as it works today: every topic that touches two components or more. Nodes are components, edges are
  calls or data. The edge that breaks is broken=True (red).
- tech, after the fix: the same layout, the nodes the fix changes are kind "changed", a new edge is new=True.
  Keep the coordinates of the "today" view, so the pair reads at a glance.
- product, the path to reproduce it: when it takes more than three steps or depends on timing. Nodes are what
  the rep or the manager does and sees (kind "step", "you" for the person's own action), and the step where it
  breaks is kind "breaks".

Kinds: component, changed, data, tool, page, step, you, breaks, session, engine, file.
Coordinates are in px of a viewBox of the given width and height; side(key, "l|r|t|b", t) is the point on a
node's side (t from 0 to 1 along it) an edge starts or ends at. Every node and label is real text, so it stays
sharp at any size and in both themes (the page draws the figure on white).
"""
from __future__ import annotations

from html import escape

STYLES = {  # kind: (fill, stroke)
    "component": ("#eef3fa", "#2e5a86"), "engine": ("#eef3fa", "#2e5a86"),
    "changed": ("#fff4e5", "#b4700e"), "data": ("#f3eefa", "#6a3fb5"), "file": ("#fff7e6", "#b4700e"),
    "tool": ("#f6f6f6", "#666666"), "page": ("#f3eefa", "#6a3fb5"), "session": ("#eef7ef", "#2e7d32"),
    "step": ("#f6f6f6", "#555555"), "you": ("#fdecec", "#c62828"), "breaks": ("#fdecec", "#c62828"),
}
EDGE = "#444444"
BROKEN = "#c62828"
NEW = "#2e7d32"


class Diagram:
    def __init__(self, w: int, h: int):
        self.w, self.h, self.out, self.nodes = w, h, [], {}

    def node(self, key: str, x: float, y: float, w: float, h: float, title: str, lines=(), kind: str = "component"):
        fill, stroke = STYLES[kind]
        self.nodes[key] = (x, y, w, h)
        width = 2.6 if kind in ("changed", "breaks") else 1.5
        self.out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{fill}" stroke="{stroke}" '
                        f'stroke-width="{width}"/>')
        self.out.append(f'<text x="{x + 12}" y="{y + 23}" font-size="15" font-weight="700" fill="#111">'
                        f'{escape(title)}</text>')
        for i, line in enumerate(lines):
            self.out.append(f'<text x="{x + 12}" y="{y + 44 + 19 * i}" font-size="13" fill="#333">{escape(line)}</text>')

    def side(self, key: str, where: str, t: float = 0.5) -> tuple[float, float]:
        x, y, w, h = self.nodes[key]
        return {"l": (x, y + h * t), "r": (x + w, y + h * t), "t": (x + w * t, y), "b": (x + w * t, y + h)}[where]

    def edge(self, pts, label: str = "", at=None, broken: bool = False, new: bool = False, dash: bool = False,
             anchor: str = "middle"):
        colour = BROKEN if broken else NEW if new else EDGE
        marker = "b" if broken else "n" if new else "a"
        extra = ' stroke-dasharray="6 4"' if dash else ""
        points = " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)
        self.out.append(f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="{2.4 if broken else 1.7}" '
                        f'marker-end="url(#{marker})"{extra}/>')
        if label:
            lx, ly = at or ((pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2 - 7)
            for i, part in enumerate(label.split("\n")):
                self.out.append(f'<text x="{lx:.0f}" y="{ly + 15 * i:.0f}" font-size="12.5" fill="{colour}" '
                                f'text-anchor="{anchor}">{escape(part)}</text>')

    def text(self, x: float, y: float, s: str, size: float = 12.5, colour: str = "#555", anchor: str = "start",
             bold: bool = False):
        weight = ' font-weight="700"' if bold else ""
        self.out.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{colour}" text-anchor="{anchor}"{weight}>'
                        f'{escape(s)}</text>')

    def svg(self) -> str:
        markers = "".join(
            f'<marker id="{key}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{colour}"/></marker>'
            for key, colour in (("a", EDGE), ("b", BROKEN), ("n", NEW)))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" '
                f'height="{self.h}" font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif">'
                f'<defs>{markers}</defs><rect width="{self.w}" height="{self.h}" fill="white"/>'
                + "".join(self.out) + "</svg>")

    def save(self, path: str) -> str:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.svg())
        print(path)
        return path
