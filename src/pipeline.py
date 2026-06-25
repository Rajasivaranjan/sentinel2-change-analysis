"""Run the full Sentinel-2 change-analysis pipeline end to end.

    python src/pipeline.py

Stages:
  1. Data preparation     (data_preparation.prepare)
  2. Change detection     (change_detection.detect_change)
  3. Feature extraction   (feature_extraction.extract_features)
  4. Visualisation        (visualize.visualize)
"""
from __future__ import annotations

from data_preparation import prepare
from change_detection import detect_change
from feature_extraction import extract_features
from visualize import visualize


def main() -> None:
    print("=" * 64)
    print("Sentinel-2 Change Analysis pipeline")
    print("=" * 64 + "\n")

    prepare()
    detect_change()
    extract_features()
    visualize()

    print("=" * 64)
    print("Done. See data/processed/ and outputs/.")
    print("=" * 64)


if __name__ == "__main__":
    main()
