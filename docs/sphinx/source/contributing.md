# Contributing

## Development Setup

1. Fork the repository
2. Clone your fork
3. Create a feature branch
4. Make changes
5. Run tests
6. Submit a pull request

## Code Style

### Python

- Use type hints for all function signatures
- Use Pydantic models for data validation
- Prefer `async/await` for I/O operations
- Use `loguru` for logging, not `print()`
- Follow PEP 8, max line length 100 chars
- Use Google-style docstrings

Example:

```python
def process_document(
    document_id: str,
    options: ProcessOptions | None = None,
) -> ProcessResult:
    """Process a document through the RAG pipeline.
    
    Args:
        document_id: Unique identifier for the document.
        options: Optional processing configuration.
        
    Returns:
        ProcessResult containing extracted chunks and metadata.
        
    Raises:
        DocumentNotFoundError: If document doesn't exist.
        ProcessingError: If processing fails.
    """
    ...
```

### TypeScript/React

- Use functional components with hooks
- Prefer `interface` over `type` for object shapes
- Use shadcn/ui components when available
- Handle loading/error states explicitly
- Use `fetch` with proper error handling

## Documentation

When adding new modules:

1. Add docstrings to all public functions/classes
2. Update the appropriate `.md` file in `docs/sphinx/source/api/`
3. Rebuild docs: `cd docs/sphinx && make html`

## Gotchas

### Supabase caps a response at 1,000 rows

A `select` through the Supabase client returns at most 1,000 rows and does not warn, so any query that can match
more must page or it silently truncates. Use `fetch_all_rows` from `src.auth` for reads and `update_by_ids` for
id-filtered writes. When only a count is needed, aggregate in Postgres instead of reading rows; see
`supabase/migrations/20261117000200_admin_count_functions.sql`. This under-reported the admin dashboards and the
Processing tab once a project passed 1,000 documents.

## Testing

```bash
# Python tests
pytest tests/ -v

# Frontend tests
cd frontend && npm test

# Linting
ruff check .
cd frontend && npm run lint
```

## Commit Messages

Use conventional commits:

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation only
- `refactor:` Code change that doesn't fix/add
- `test:` Adding tests
- `chore:` Maintenance tasks

Example: `feat: Add binary quantization support`
