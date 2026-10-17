# Contributing to MdGraph

Thank you for your interest in contributing to **MdGraph**! 

MdGraph is an open-source storage engine implementing Google's Open Knowledge Format (OKF) to build deterministic, traversable, and version-controlled context for autonomous AI agents.

Whether you're fixing a bug, adding a parser for new file formats, improving graph traversal algorithms, or extending MCP tools, we welcome your contributions.

---

## Code of Conduct

This project adheres to the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

---

## Development Setup

### Prerequisites

- **Python**: 3.10, 3.11, 3.12, 3.13, or 3.14
- **Git**: Installed and configured on your system

### 1. Clone the Repository

```bash
git clone https://github.com/firecodex/mdgraph.git
cd mdgraph
```

### 2. Create and Activate a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install in Editable Mode with Dev Dependencies

```bash
pip install -e ".[dev]"
```

---

## Development Workflow

### Running Tests

We maintain strict test coverage. Run the test suite using `pytest`:

```bash
pytest
```

Run tests with verbose output:

```bash
pytest -v
```

### Code Formatting and Linting

We adhere to standard Python PEP 8 styling, formatted with `ruff`:

```bash
# Check linting
ruff check .

# Fix auto-fixable lint issues
ruff check --fix .

# Check formatting
ruff format --check .
```

---

## Submitting Pull Requests

1. **Fork the Repository**: Create your own fork and create a feature branch:
   ```bash
   git checkout -b feature/my-new-feature
   ```
2. **Make Your Changes**: Write clean, readable code with descriptive comments and type annotations where appropriate.
3. **Add Tests**: Every bug fix or new feature must include corresponding unit or integration tests in `tests/`.
4. **Run the Full Test Suite**: Ensure all existing and new tests pass before submitting.
5. **Commit Your Changes**: Follow conventional commits:
   - `feat: add support for docx document ingestion`
   - `fix: resolve cycle prevention edge case in recursive CTE`
   - `docs: update FastMCP tool signatures in README`
6. **Open a Pull Request**: Open a PR targeting the `main` branch with a clear description of the problem solved and changes made.

---

## Architecture Guidelines

- **Compiler vs. Cache Separation**: Keep the Compiler Layer (heavy, LLM-driven, state-mutating) strictly decoupled from the Query Cache (lightweight, read-optimized, vectorless index).
- **Strict OKF Conformance**: Ensure all generated Markdown files adhere strictly to Google's Open Knowledge Format (non-empty `type`, YAML frontmatter, explicit links `[Title](./target.md)`).
- **Git-Backed Truth**: The Markdown filesystem in Git is always the single source of truth. The database cache must be disposable and completely rebuildable from Git at any time.

Thank you for helping make context engines better for autonomous AI!
