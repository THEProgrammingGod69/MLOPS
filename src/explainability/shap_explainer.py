import numpy as np
import pandas as pd
import joblib
import shap
import os
import yaml
from typing import Dict, List, Any, Tuple
from src.models.train_baselines import PREDICTIVE_FEATURES
from src.intervention.intervention_engine import InterventionEngine

class SHAPExplainer:
    def __init__(self, model_path: str = 'models/baseline/xgb_pipeline.pkl'):
        """Initializes the explainer using the trained pipeline."""
        self.pipeline = joblib.load(model_path)
        self.preprocessor = self.pipeline.named_steps['preprocessor']
        self.model = self.pipeline.named_steps['classifier']
        
        # Use TreeExplainer for XGBoost - pass Booster directly to avoid parsing issues
        # with SHAP on some XGBoost sklearn versions
        booster = self.model.get_booster()
        self.explainer = shap.TreeExplainer(booster)
        self.intervention_engine = InterventionEngine()
        
    def _get_feature_names(self) -> List[str]:
        """Extracts transformed feature names from the preprocessor."""
        # Note: Depending on scikit-learn version and how preprocessor is built,
        # get_feature_names_out might exist or we might need to construct manually.
        try:
            return list(self.preprocessor.get_feature_names_out())
        except AttributeError:
            # Fallback if get_feature_names_out is not available
            features = []
            for name, trans, cols in self.preprocessor.transformers_:
                if name == 'remainder':
                    continue
                if hasattr(trans, 'get_feature_names_out'):
                    features.extend(trans.get_feature_names_out(cols))
                else:
                    features.extend(cols)
            return features

    def explain_instances(self, X_raw: pd.DataFrame) -> Tuple[np.ndarray, List[str]]:
        """
        Calculates SHAP values for a set of raw instances.
        
        Args:
            X_raw: Raw validation features (DataFrame).
            
        Returns:
            Tuple of (shap_values, transformed_feature_names)
        """
        X_processed = self.preprocessor.transform(X_raw)
        if isinstance(X_processed, pd.DataFrame):
            X_matrix = X_processed.values
        else:
            X_matrix = X_processed
            
        shap_values = self.explainer.shap_values(X_matrix)
        feature_names = self._get_feature_names()
        return shap_values, feature_names

    def get_local_explanation(self, x_raw_row: pd.DataFrame, num_features: int = 5) -> Dict[str, Any]:
        """
        Generates a human-readable local explanation for a single instance.
        
        Args:
            x_raw_row: Single row DataFrame of raw features.
            
        Returns:
            Dictionary with risk_probability, risk_tier, top_positive_contributors, top_negative_contributors.
        """
        # Get risk probability and tier
        prob = self.pipeline.predict_proba(x_raw_row)[0, 1]
        rec = self.intervention_engine.generate_recommendation(prob)
        
        shap_vals, feature_names = self.explain_instances(x_raw_row)
        shap_vals = shap_vals[0] # Single instance
        
        # Create mapping of feature name to SHAP value
        feature_contributions = list(zip(feature_names, shap_vals))
        
        # Positive contributors push risk UP
        positive_contributors = sorted(
            [(f, v) for f, v in feature_contributions if v > 0], 
            key=lambda x: x[1], 
            reverse=True
        )[:num_features]
        
        # Negative contributors push risk DOWN
        negative_contributors = sorted(
            [(f, v) for f, v in feature_contributions if v < 0], 
            key=lambda x: x[1]
        )[:num_features]
        
        return {
            'risk_probability': prob,
            'risk_tier': rec['risk_tier'],
            'top_positive_contributors': [f for f, v in positive_contributors],
            'top_negative_contributors': [f for f, v in negative_contributors]
        }
