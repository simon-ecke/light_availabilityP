"""
plotting.py
===========

Visualization functions for canopy height analysis.
"""

from typing import List, Optional
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


# Sequential blue ramp (light -> dark), ordinal-safe steps (skip below step 250)
# See dataviz skill reference palette: one hue, more-is-darker for ordered magnitude.
_ORDINAL_BLUE_STEPS = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab"]
_INK_PRIMARY = "#0b0b0b"
_INK_SECONDARY = "#52514e"
_INK_MUTED = "#898781"
_GRIDLINE = "#e1e0d9"
_BASELINE = "#c3c2b7"


def plot_height_histogram(
    class_labels: List[str],
    class_counts: List[int],
    threshold_height_m: float,
    output_path: Optional[str] = None,
    title: Optional[str] = None,
    figsize: tuple = (10, 6)
) -> plt.Figure:
    """
    Create bar chart of height distribution with threshold marker.

    Parameters
    ----------
    class_labels : list of str
        Class labels (e.g., ['0-15m', '15-25m', ...])
    class_counts : list of int
        Pixel counts per class
    threshold_height_m : float
        Height threshold for color coding
    output_path : str, optional
        Path to save figure
    title : str, optional
        Custom title
    figsize : tuple
        Figure size (width, height)

    Returns
    -------
    plt.Figure
        Matplotlib figure object
    """
    fig, ax = plt.subplots(figsize=figsize)

    # Calculate positions and proportions
    x_pos = np.arange(len(class_labels))
    total = sum(class_counts)
    proportions = [count / total * 100 for count in class_counts]

    # Determine colors based on threshold
    # Parse threshold from labels to determine which bars are above/below
    colors = []
    for label in class_labels:
        # Extract lower bound of class
        if label.startswith('>'):
            # Last class (e.g., ">35m")
            lower = float(label[1:-1])
        else:
            # Regular class (e.g., "15-25m")
            lower = float(label.split('-')[0])

        if lower >= threshold_height_m:
            colors.append('#2E7D32')  # Dark green for above threshold
        else:
            colors.append('#A5D6A7')  # Light green for below threshold

    # Create bars
    bars = ax.bar(x_pos, class_counts, color=colors, edgecolor='black', linewidth=1)

    # Add percentage labels on bars
    for i, (bar, count, prop) in enumerate(zip(bars, class_counts, proportions)):
        height = bar.get_height()
        if count > 0:  # Only label non-zero bars
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                height,
                f'{count:,}\n({prop:.1f}%)',
                ha='center',
                va='bottom',
                fontsize=9,
                fontweight='bold'
            )

    # Customize plot
    ax.set_xlabel('Height Class', fontsize=12, fontweight='bold')
    ax.set_ylabel('Number of Pixels', fontsize=12, fontweight='bold')

    if title:
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
    else:
        ax.set_title(
            f'Canopy Height Distribution (n={total:,} pixels)',
            fontsize=14,
            fontweight='bold',
            pad=20
        )

    ax.set_xticks(x_pos)
    ax.set_xticklabels(class_labels, fontsize=10)

    # Add grid for readability
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    # Add legend for threshold
    legend_patches = [
        mpatches.Patch(color='#A5D6A7', label=f'Below {threshold_height_m}m'),
        mpatches.Patch(color='#2E7D32', label=f'Above {threshold_height_m}m')
    ]
    ax.legend(handles=legend_patches, loc='upper right', fontsize=10)

    # Format y-axis with thousands separator
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))

    plt.tight_layout()

    # Save if path provided
    if output_path:
        fig.savefig(output_path, dpi=300, bbox_inches='tight')

    return fig


def plot_category_comparison(
    categories: List[str],
    values: List[float],
    category_order: List[str],
    output_path: Optional[str] = None,
    value_label: str = "Derived canopy closure index (0 = light, 1 = closed)",
    title: Optional[str] = None,
    figsize: tuple = (9.5, 5.5),
    seed: int = 0
) -> plt.Figure:
    """
    Compare a continuous DSM/DTM-derived metric (0-1) against an observer's
    ordered field categories (light -> closed): one jittered dot strip per
    category plus a median marker, arranged left-to-right in `category_order`.

    Parameters
    ----------
    categories : list of str
        Observer category label per point (same length as `values`).
    values : list of float
        Derived metric per point, expected in [0, 1].
    category_order : list of str
        Category labels in light -> closed order (defines x-axis order and
        the sequential shade assigned to each category).
    output_path : str, optional
        Path to save the figure.
    value_label : str
        Y-axis label.
    title : str, optional
        Custom title.
    figsize : tuple
        Figure size.
    seed : int
        RNG seed for horizontal jitter (deterministic output).

    Returns
    -------
    plt.Figure
    """
    rng = np.random.default_rng(seed)
    n_cat = len(category_order)
    if n_cat > len(_ORDINAL_BLUE_STEPS):
        raise ValueError(
            f"plot_category_comparison supports up to {len(_ORDINAL_BLUE_STEPS)} "
            f"ordered categories, got {n_cat}"
        )
    colors = _ORDINAL_BLUE_STEPS[:n_cat]

    fig, ax = plt.subplots(figsize=figsize)

    for i, cat in enumerate(category_order):
        cat_values = [v for c, v in zip(categories, values) if c == cat]
        n = len(cat_values)
        if n == 0:
            continue

        jitter = rng.uniform(-0.14, 0.14, size=n)
        ax.scatter(
            np.full(n, i) + jitter, cat_values,
            s=42, color=colors[i], edgecolor="white", linewidth=0.6,
            zorder=3, alpha=0.9
        )

        median = float(np.median(cat_values))
        ax.plot([i - 0.22, i + 0.22], [median, median],
                color=_INK_PRIMARY, linewidth=2, zorder=4, solid_capstyle="round")
        ax.text(
            i, 1.035, f"median {median:.2f}\n(n={n})",
            ha="center", va="bottom", fontsize=8.5, color=_INK_SECONDARY
        )

    ax.set_xlim(-0.6, n_cat - 0.4)
    ax.set_ylim(-0.05, 1.15)
    ax.set_xticks(range(n_cat))
    ax.set_xticklabels(category_order, fontsize=9.5, color=_INK_PRIMARY)
    ax.set_ylabel(value_label, fontsize=10.5, color=_INK_PRIMARY)

    ax.set_title(
        title or "Field-estimated canopy closure vs. DSM/DTM-derived index",
        fontsize=13, fontweight="bold", color=_INK_PRIMARY, pad=28
    )

    ax.grid(axis="y", color=_GRIDLINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine_name in ("top", "right"):
        ax.spines[spine_name].set_visible(False)
    for spine_name in ("left", "bottom"):
        ax.spines[spine_name].set_color(_BASELINE)
    ax.tick_params(colors=_INK_MUTED)

    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=300, bbox_inches="tight")

    return fig
