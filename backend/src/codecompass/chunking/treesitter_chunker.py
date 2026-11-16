"""Structure-aware chunking for Python, JavaScript, TypeScript and TSX (NFR-002, R4, T049).

Rules:
- one chunk per top-level function/class (decorators and directly preceding comments included);
- a class longer than MAX_CHUNK_LINES is split: one chunk per method (embedded with the class
  signature as a header) plus "class" chunks for the remaining class-body code;
- other top-level code (imports, constants, statements) is merged into "module" chunks;
- any single piece still longer than MAX_CHUNK_LINES is split into line windows with
  OVERLAP_LINES of overlap.
Line numbers come straight from the syntax tree, so citations are exact (FR-011).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from codecompass.chunking.documents import ChunkDraft, line_slice
from codecompass.chunking.generic_chunker import windows

MAX_CHUNK_LINES = 120
OVERLAP_LINES = 15
CODE_LANGUAGES = {"python", "javascript", "typescript", "tsx"}

PY_DEFS = {"function_definition": "function", "class_definition": "class"}
JS_DEFS = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "class",
    "type_alias_declaration": "class",
    "enum_declaration": "class",
}
JS_FUNCTION_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}


@cache
def _parser(language: str) -> Parser:
    grammar = {
        "python": tree_sitter_python.language,
        "javascript": tree_sitter_javascript.language,
        "typescript": tree_sitter_typescript.language_typescript,
        "tsx": tree_sitter_typescript.language_tsx,
    }[language]
    return Parser(Language(grammar()))


@dataclass
class Definition:
    node: Node  # the node whose lines form the chunk (includes decorators / export)
    inner: Node  # the actual function/class node
    kind: str
    name: str


def _text(node: Node | None) -> str | None:
    return node.text.decode() if node is not None and node.text is not None else None


def _start(node: Node) -> int:
    return node.start_point[0] + 1


def _end(node: Node) -> int:
    # A node ending at column 0 of a line really ended on the previous line.
    row, col = node.end_point
    return row if col == 0 and row > node.start_point[0] else row + 1


def _definition(node: Node, language: str) -> Definition | None:
    if language == "python":
        inner = node
        if node.type == "decorated_definition":
            found = node.child_by_field_name("definition")
            if found is None:
                return None
            inner = found
        kind = PY_DEFS.get(inner.type)
        name = _text(inner.child_by_field_name("name"))
        return Definition(node, inner, kind, name) if kind and name else None

    inner = node
    if node.type == "export_statement":
        found = node.child_by_field_name("declaration")
        if found is None:
            return None
        inner = found
    if inner.type in JS_DEFS:
        name = _text(inner.child_by_field_name("name"))
        return Definition(node, inner, JS_DEFS[inner.type], name) if name else None
    if inner.type in {"lexical_declaration", "variable_declaration"}:
        declarators = [c for c in inner.named_children if c.type == "variable_declarator"]
        if len(declarators) == 1:
            value = declarators[0].child_by_field_name("value")
            name = _text(declarators[0].child_by_field_name("name"))
            if value is not None and value.type in JS_FUNCTION_VALUES and name:
                return Definition(node, inner, "function", name)
    return None


def _methods(class_node: Node, language: str) -> tuple[Node, list[tuple[Node, str]]]:
    """(class body node, [(method chunk node, method name)])."""
    body = class_node.child_by_field_name("body")
    if body is None:
        return class_node, []
    found: list[tuple[Node, str]] = []
    for child in body.named_children:
        if language == "python":
            inner = (
                child.child_by_field_name("definition")
                if child.type == "decorated_definition"
                else child
            )
            if inner is not None and inner.type == "function_definition":
                name = _text(inner.child_by_field_name("name"))
                if name:
                    found.append((child, name))
        elif child.type in {"method_definition", "abstract_method_signature"}:
            name = _text(child.child_by_field_name("name"))
            if name:
                found.append((child, name))
    return body, found


class _Builder:
    def __init__(self, path: str, text: str, language: str) -> None:
        self.path = path
        self.language = language
        self.lines = text.splitlines(keepends=True)
        self.chunks: list[ChunkDraft] = []

    def add(
        self, start: int, end: int, kind: str, symbol: str | None = None, parent: str | None = None
    ) -> None:
        for s, e in windows(start, end, MAX_CHUNK_LINES, OVERLAP_LINES):
            body = line_slice(self.lines, s, e)
            if body.strip():
                self.chunks.append(
                    ChunkDraft(
                        self.path, s, e, self.language, kind, body, symbol=symbol, parent=parent
                    )
                )

    def add_class(self, definition: Definition, start: int) -> None:
        end = _end(definition.node)
        if end - start + 1 <= MAX_CHUNK_LINES:
            self.add(start, end, "class", definition.name)
            return
        signature = self.lines[_start(definition.inner) - 1].strip()
        _, methods = _methods(definition.inner, self.language)
        cursor = start  # first line not yet assigned to a chunk
        for method_node, name in methods:
            m_start = _leading_comment_start(method_node, self.language) or _start(method_node)
            if m_start > cursor:
                self.add(cursor, m_start - 1, "class", definition.name)
            self.add(m_start, _end(method_node), "method", f"{definition.name}.{name}", signature)
            cursor = _end(method_node) + 1
        if cursor <= end:
            self.add(cursor, end, "class", definition.name)


def _leading_comment_start(node: Node, language: str) -> int | None:
    """First line of the comment block directly above `node` (no blank line in between)."""
    start: int | None = None
    expected = _start(node) - 1
    sibling = node.prev_named_sibling
    while sibling is not None and sibling.type == "comment" and _end(sibling) == expected:
        start = _start(sibling)
        expected = start - 1
        sibling = sibling.prev_named_sibling
    return start


def chunk_code(path: str, text: str, language: str) -> list[ChunkDraft]:
    if not text.strip():
        return []
    tree = _parser(language).parse(text.encode())
    builder = _Builder(path, text, language)
    children = tree.root_node.named_children
    attached: set[int] = set()  # ids of comment nodes attached to a following definition

    definitions: dict[int, tuple[Definition, int]] = {}
    for node in children:
        definition = _definition(node, language)
        if definition is None:
            continue
        start = _start(node)
        sibling = node.prev_named_sibling
        expected = start - 1
        while sibling is not None and sibling.type == "comment" and _end(sibling) == expected:
            attached.add(sibling.id)
            start = _start(sibling)
            expected = start - 1
            sibling = sibling.prev_named_sibling
        definitions[node.id] = (definition, start)

    run: list[Node] = []  # consecutive module-level nodes

    def flush() -> None:
        if run:
            builder.add(_start(run[0]), _end(run[-1]), "module")
            run.clear()

    for node in children:
        if node.id in attached:
            continue
        if node.id in definitions:
            flush()
            definition, start = definitions[node.id]
            if definition.kind == "class":
                builder.add_class(definition, start)
            else:
                builder.add(start, _end(node), definition.kind, definition.name)
        else:
            run.append(node)
    flush()
    return builder.chunks
