"""Enforce the docstring and comment rules on the Python code of every package.

Rules for ``packages/*/src``: every module, class, function and method has a numpy-style
docstring, private names, nested functions and dunder methods included. A function with
parameters and four or more of them, or a body of more than ``MAX_PLAIN_STATEMENTS``
statements, documents them in a ``Parameters`` section. Rules for ``packages/*/tests``:
every class, test, fixture and helper has a docstring. Everywhere, ``#`` comments are
rejected except shebang, encoding, ``noqa``, ``type:`` and ``pragma`` markers.

Exemptions: ``__init__`` when the class docstring has a ``Parameters`` section,
``typing.overload`` stubs, bodies of ``typing.Protocol`` classes, and property setters
and deleters (the getter carries the text).

Usage: ``check_docstrings.py`` checks the whole tree and exits non-zero on any finding.
"""

import ast
import io
import re
import sys
import tokenize
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_PLAIN_PARAMETERS = 3
MAX_PLAIN_STATEMENTS = 15
SKIP: frozenset[str] = frozenset()
SECTIONS = frozenset(
    {
        "Parameters",
        "Other Parameters",
        "Returns",
        "Yields",
        "Receives",
        "Raises",
        "Warns",
        "Warnings",
        "See Also",
        "Notes",
        "References",
        "Examples",
        "Attributes",
        "Methods",
    }
)
ALLOWED_COMMENT = re.compile(r"#\s*(!|.*coding[:=]|noqa|type:|pragma)")
GOOGLE_SECTION = re.compile(
    r"^\s*(Args|Arguments|Returns|Raises|Yields|Example|Examples|Note|Notes):\s*$"
)
Function = ast.FunctionDef | ast.AsyncFunctionDef


def decorator_names(node: ast.AST) -> set[str]:
    """Return the last dotted component of every decorator of a function or class."""
    names: set[str] = set()
    for decorator in getattr(node, "decorator_list", []):
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute):
            names.add(target.attr)
        elif isinstance(target, ast.Name):
            names.add(target.id)
    return names


def is_protocol(node: ast.ClassDef) -> bool:
    """Return whether the class lists ``Protocol`` among its bases."""
    for base in node.bases:
        target = base.value if isinstance(base, ast.Subscript) else base
        if isinstance(target, ast.Name) and target.id == "Protocol":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "Protocol":
            return True
    return False


def parameter_count(node: Function) -> int:
    """Count the parameters of a function without ``self`` and ``cls``."""
    args = node.args
    names = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return len([name for name in names if name not in ("self", "cls")])


def statement_count(node: Function) -> int:
    """Count the statements of a function body, nested ones included, docstring excluded."""
    count = 0
    stack: list[ast.AST] = list(node.body)
    while stack:
        current = stack.pop()
        if isinstance(current, ast.stmt):
            count += 1
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        stack.extend(ast.iter_child_nodes(current))
    return count - (1 if ast.get_docstring(node, clean=False) is not None else 0)


def section_titles(doc: str) -> list[str]:
    """Return the numpy section titles found in a docstring, malformed ones flagged with ``!``."""
    lines = doc.expandtabs().splitlines()
    titles: list[str] = []
    for index, line in enumerate(lines[:-1]):
        underline = lines[index + 1].strip()
        if underline and set(underline) == {"-"} and line.strip():
            title = line.strip()
            well_formed = title in SECTIONS and len(underline) == len(title)
            titles.append(title if well_formed else "!" + title)
    return titles


def docstring_problems(doc: str) -> list[str]:
    """Return the style problems of one docstring."""
    problems = []
    if not doc.strip():
        problems.append("empty docstring")
    for title in section_titles(doc):
        if title.startswith("!"):
            problems.append(f"malformed numpy section {title[1:]!r}")
    for line in doc.splitlines():
        if GOOGLE_SECTION.match(line):
            problems.append(f"non-numpy section {line.strip()!r}")
    return problems


def is_trivial_stub(node: Function) -> bool:
    """Return whether the body is only ``...``, ``pass`` or a docstring."""
    return all(
        isinstance(s, ast.Pass) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
        for s in node.body
    )


class Checker(ast.NodeVisitor):
    """Collect docstring findings of one parsed module."""

    def __init__(self, path: str, is_test: bool) -> None:
        """Create a checker for one file; ``is_test`` relaxes the module and parameter rules."""
        self.path = path
        self.is_test = is_test
        self.findings: list[str] = []
        self.class_stack: list[ast.ClassDef] = []

    def report(self, node: ast.AST, message: str) -> None:
        """Record a finding at the line of ``node``."""
        self.findings.append(f"{self.path}:{getattr(node, 'lineno', 1)}: {message}")

    def check_module(self, tree: ast.Module) -> None:
        """Require a module docstring in source files and check its style."""
        doc = ast.get_docstring(tree, clean=False)
        if doc is None:
            if not self.is_test:
                self.report(tree, "module without docstring")
            return
        for problem in docstring_problems(doc):
            self.report(tree, f"module: {problem}")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Require a class docstring and visit the members."""
        doc = ast.get_docstring(node, clean=False)
        if doc is None:
            self.report(node, f"class {node.name} without docstring")
        else:
            for problem in docstring_problems(doc):
                self.report(node, f"class {node.name}: {problem}")
        self.class_stack.append(node)
        self.generic_visit(node)
        self.class_stack.pop()

    def exempt(self, node: Function) -> bool:
        """Return whether a function is on the short exemption list."""
        decorators = decorator_names(node)
        if decorators & {"overload", "setter", "deleter"}:
            return True
        owner = self.class_stack[-1] if self.class_stack else None
        if owner is None:
            return False
        if is_protocol(owner) and is_trivial_stub(node):
            return True
        if node.name == "__init__":
            owner_doc = ast.get_docstring(owner, clean=False) or ""
            return "Parameters" in section_titles(owner_doc)
        return False

    def visit_function(self, node: Function) -> None:
        """Check one function or method, then visit nested definitions."""
        doc = ast.get_docstring(node, clean=False)
        if doc is None:
            if not self.exempt(node):
                self.report(node, f"function {node.name} without docstring")
        else:
            for problem in docstring_problems(doc):
                self.report(node, f"function {node.name}: {problem}")
            self.check_parameters_section(node, doc)
        outer = self.class_stack
        self.class_stack = []
        self.generic_visit(node)
        self.class_stack = outer

    def check_parameters_section(self, node: Function, doc: str) -> None:
        """Require ``Parameters`` for functions with many parameters or a long body."""
        if self.is_test or "overload" in decorator_names(node):
            return
        count = parameter_count(node)
        if not count or "Parameters" in section_titles(doc):
            return
        if count > MAX_PLAIN_PARAMETERS or statement_count(node) > MAX_PLAIN_STATEMENTS:
            self.report(node, f"function {node.name}: {count} parameters, no Parameters section")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check a synchronous function definition."""
        self.visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check an asynchronous function definition."""
        self.visit_function(node)


def comment_findings(path: str, text: str) -> Iterator[str]:
    """Yield a finding for every disallowed ``#`` comment in ``text``."""
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT and not ALLOWED_COMMENT.match(token.string):
            yield f"{path}:{token.start[0]}: inline comment {token.string[:40]!r}"


def source_files() -> Iterator[tuple[Path, bool]]:
    """Yield every package Python file with a flag telling whether it is a test."""
    for kind, is_test in (("src", False), ("tests", True)):
        for path in sorted(ROOT.glob(f"packages/*/{kind}/**/*.py")):
            if path.relative_to(ROOT).as_posix() not in SKIP:
                yield path, is_test


def check_file(path: Path, is_test: bool) -> list[str]:
    """Return every finding for one file."""
    relative = path.relative_to(ROOT).as_posix()
    text = path.read_text(encoding="utf-8")
    checker = Checker(relative, is_test)
    tree = ast.parse(text)
    checker.check_module(tree)
    checker.visit(tree)
    return [*checker.findings, *comment_findings(relative, text)]


def main() -> None:
    """Check all files and exit non-zero when anything is found."""
    findings = [f for path, is_test in source_files() for f in check_file(path, is_test)]
    if findings:
        print("\n".join(findings))
        sys.exit(f"{len(findings)} docstring or comment findings")
    print("docstrings and comments ok")


if __name__ == "__main__":
    main()
