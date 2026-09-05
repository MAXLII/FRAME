def matches_parameter_search(name: str, query: str) -> bool:
    """Match case-insensitive characters in order, allowing gaps and query spaces."""
    characters = iter(name.casefold())
    return all(character in characters for character in query.casefold() if not character.isspace())
