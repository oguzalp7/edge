"""
Deterministic Image Parity Diff Tool
Compares baseline and refactored UI screenshots pixel-by-pixel with antialiasing tolerance.
Generates an optional visual diff highlight and computes mismatch ratio.
Runs via: uv run --with pillow python -m tools.ui_audit.diff_image <baseline.png> <refactored.png>
"""

import argparse
import sys
from pathlib import Path
from PIL import Image, ImageChops


def compare_images(
    baseline_path: Path,
    refactored_path: Path,
    tolerance: int = 15,
    max_mismatch_pct: float = 0.15,
    diff_out_path: Path = None,
) -> bool:
    """
    Compare two images with subpixel/antialiasing tolerance.
    Returns True if images have visual parity within max_mismatch_pct.
    """
    if not baseline_path.exists():
        print(f"Error: Baseline image not found: {baseline_path}", file=sys.stderr)
        return False
    if not refactored_path.exists():
        print(f"Error: Refactored image not found: {refactored_path}", file=sys.stderr)
        return False

    img1 = Image.open(baseline_path).convert("RGB")
    img2 = Image.open(refactored_path).convert("RGB")

    if img1.size != img2.size:
        print(f"FAIL: Dimension mismatch! Baseline: {img1.size}, Refactored: {img2.size}")
        return False

    width, height = img1.size
    total_pixels = width * height

    # Fast check: ImageChops difference
    diff = ImageChops.difference(img1, img2)
    bbox = diff.getbbox()

    if not bbox:
        print(f"PASS: 100.0% exact byte-for-byte pixel match ({total_pixels:,} pixels).")
        return True

    # Detailed pixel-level scan within bounding box with antialiasing tolerance
    pixels1 = img1.load()
    pixels2 = img2.load()

    diff_count = 0
    min_x, min_y, max_x, max_y = width, height, 0, 0
    
    # Create diff image with dimmed baseline and bright magenta highlights for changes
    diff_img = Image.new("RGB", (width, height), (30, 30, 30))
    diff_pixels = diff_img.load()

    for y in range(height):
        for x in range(width):
            r1, g1, b1 = pixels1[x, y]
            r2, g2, b2 = pixels2[x, y]

            dist = abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)

            if dist > tolerance:
                diff_count += 1
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
                # Highlight in bright red/magenta
                diff_pixels[x, y] = (255, 0, 128)
            else:
                # Dim background for context
                diff_pixels[x, y] = (r1 // 3, g1 // 3, b1 // 3)

    mismatch_pct = (diff_count / total_pixels) * 100.0

    if diff_out_path and diff_count > 0:
        diff_out_path.parent.mkdir(parents=True, exist_ok=True)
        diff_img.save(diff_out_path)
        print(f"Diff visualization saved to: {diff_out_path}")

    if mismatch_pct <= max_mismatch_pct:
        print(
            f"PASS: Visual Parity Confirmed! Mismatch: {mismatch_pct:.3f}% "
            f"({diff_count:,} / {total_pixels:,} px within antialiasing tolerance <= {max_mismatch_pct}%)."
        )
        return True
    else:
        print(
            f"FAIL: Visual Discrepancy Detected! Mismatch: {mismatch_pct:.3f}% "
            f"({diff_count:,} / {total_pixels:,} px > {max_mismatch_pct}% threshold).\n"
            f"Affected Bounding Box: [x: {min_x}..{max_x}, y: {min_y}..{max_y}, w: {max_x - min_x}, h: {max_y - min_y}]"
        )
        return False


def main():
    parser = argparse.ArgumentParser(description="Deterministic Visual Parity Diff Tool")
    parser.add_argument("baseline", help="Path to baseline screenshot")
    parser.add_argument("refactored", help="Path to refactored screenshot")
    parser.add_argument(
        "--tolerance",
        type=int,
        default=15,
        help="RGB distance tolerance for font antialiasing/subpixel rendering (default: 15)",
    )
    parser.add_argument(
        "--max-mismatch",
        type=float,
        default=0.15,
        help="Maximum allowed mismatch percentage to consider parity a pass (default: 0.15%%)",
    )
    parser.add_argument(
        "--diff-out",
        type=str,
        default=None,
        help="Optional path to save highlighted diff image",
    )

    args = parser.parse_args()
    diff_out = Path(args.diff_out) if args.diff_out else None

    success = compare_images(
        Path(args.baseline),
        Path(args.refactored),
        tolerance=args.tolerance,
        max_mismatch_pct=args.max_mismatch,
        diff_out_path=diff_out,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
