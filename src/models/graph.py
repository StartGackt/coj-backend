"""Graph document classes for knowledge graph construction"""

from typing import List


class SimpleNode:
    """Represents a node in the knowledge graph"""
    
    def __init__(self, id: str, type: str):
        self.id = id
        self.type = type


class SimpleRel:
    """Represents a relationship between nodes in the knowledge graph"""
    
    def __init__(self, source: SimpleNode, target: SimpleNode, type: str):
        self.source = source
        self.target = target
        self.type = type


class SimpleGraphDocument:
    """Represents a graph document containing nodes and relationships"""
    
    def __init__(self, nodes: List[SimpleNode], relationships: List[SimpleRel]):
        self.nodes = nodes
        self.relationships = relationships
