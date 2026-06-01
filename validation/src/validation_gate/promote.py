from rdflib import Graph


def promote_if_valid(conforms: bool, source_graph: Graph, target_graph: Graph) -> bool:
    """Promote triples from source to target graph only if validation passed."""
    if not conforms:
        return False

    for triple in source_graph:
        target_graph.add(triple)
    return True
