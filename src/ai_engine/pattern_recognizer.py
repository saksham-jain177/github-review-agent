import logging
import numpy as np
import torch
import ast
from sklearn.cluster import DBSCAN
from typing import List, Dict
from .exceptions import PatternAnalysisError
from .logging_config import get_logger
from transformers import AutoModel, AutoTokenizer

logger = get_logger(__name__)

class PatternRecognizer:
    def __init__(self, model=None):
        self.logger = get_logger(__name__)
        if model:
            self.embedding_model = model
            # Initialize tokenizer separately when model is provided
            self.tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base")
        else:
            self._initialize_embedding_model()
    
    def _initialize_embedding_model(self):
        """Initialize both model and tokenizer"""
        try:
            model_name = "microsoft/codebert-base"
            self.embedding_model = AutoModel.from_pretrained(model_name)
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        except Exception as e:
            self.logger.error(f"Failed to initialize embedding model: {str(e)}")
            raise PatternAnalysisError(f"Model initialization failed: {str(e)}")
    
    def _get_embeddings(self, code_blocks: List[str]) -> np.ndarray:
        """Generates embeddings for code blocks."""
        try:
            embeddings = []
            for code in code_blocks:
                # Use self.tokenizer instead of self.embedding_model.tokenizer
                inputs = self.tokenizer(
                    code,
                    padding=True,
                    truncation=True,
                    return_tensors="pt",
                    max_length=512
                )
                
                # Generate embeddings
                with torch.no_grad():
                    outputs = self.embedding_model(**inputs)
                    embedding = outputs.last_hidden_state[:, 0, :].numpy()
                    embeddings.append(embedding[0])
                    
            return np.array(embeddings)
        except Exception as e:
            self.logger.error(f"Embedding generation failed: {str(e)}")
            raise PatternAnalysisError(f"Failed to generate embeddings: {str(e)}")
    
    def _cluster_patterns(self, embeddings: np.ndarray) -> np.ndarray:
        """Clusters similar code patterns."""
        try:
            clustering = DBSCAN(eps=0.3, min_samples=2)
            clusters = clustering.fit_predict(embeddings)
            self.logger.info(f"Identified {len(set(clusters))} pattern clusters")
            return clusters
        except Exception as e:
            self.logger.error(f"Pattern clustering failed: {str(e)}")
            raise PatternAnalysisError(f"Failed to cluster patterns: {str(e)}")

    def analyze(self, ast_trees: Dict) -> List[Dict]:
        """Analyzes AST trees to identify code patterns."""
        patterns = []
        for file_path, tree_info in ast_trees.items():
            tree = tree_info['ast']
            class_scope = None  # Track if we're inside a class
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_scope = node
                    patterns.append({
                        'type': 'class_definition',
                        'name': node.name,
                        'file': file_path,
                        'pattern_type': 'class',
                        'data': {'name': node.name},
                        'frequency': 1
                    })
                    # Add methods within the class
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            patterns.append({
                                'type': 'method_definition',
                                'name': item.name,
                                'file': file_path,
                                'pattern_type': 'method',
                                'data': {
                                    'name': item.name,
                                    'class': node.name
                                },
                                'frequency': 1
                            })
                elif isinstance(node, ast.FunctionDef) and not class_scope:
                    pattern = {
                        'type': 'function_definition',
                        'name': node.name,
                        'file': file_path,
                        'pattern_type': 'function',
                        'data': {'name': node.name},
                        'frequency': 1
                    }
                    if node.decorator_list:
                        pattern['type'] = 'decorator'
                        pattern['pattern_type'] = 'decorator'
                    patterns.append(pattern)
                if isinstance(node, ast.ClassDef):
                    class_scope = None  # Reset class scope when exiting class
        return patterns
    
    def _analyze_clusters(self, clusters: np.ndarray, code_blocks: List[str]) -> List[Dict]:
        """Analyzes and categorizes identified patterns."""
        pattern_groups = {}
        
        # Group code blocks by cluster
        for idx, cluster_id in enumerate(clusters):
            if cluster_id == -1:  # Noise points
                continue
                
            if cluster_id not in pattern_groups:
                pattern_groups[cluster_id] = []
            pattern_groups[cluster_id].append(code_blocks[idx])
        
        # Analyze each cluster
        patterns = []
        for cluster_id, group in pattern_groups.items():
            patterns.append({
                'cluster_id': cluster_id,
                'frequency': len(group),
                'examples': group[:3],  # First 3 examples
                'pattern_type': self._identify_pattern_type(group)
            })
            
        return patterns
    
    def _identify_pattern_type(self, code_group: List[str]) -> str:
        """Identifies the type of pattern in a group of similar code blocks."""
        # Simple pattern type identification based on keywords
        combined_code = ' '.join(code_group).lower()
        
        if 'class' in combined_code:
            return 'class_definition'
        elif 'def' in combined_code:
            return 'function_definition'
        elif 'import' in combined_code:
            return 'import_pattern'
        elif 'try' in combined_code and 'except' in combined_code:
            return 'error_handling'
        elif 'for' in combined_code or 'while' in combined_code:
            return 'loop_pattern'
        else:
            return 'general_code_pattern'
